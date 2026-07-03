#!/usr/bin/env python3
"""Merge official RMUL 3V3 award rankings and infer bracket stages."""

import json
import re
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup


DATA = Path("data/rmul_results.json")
ANNOUNCEMENTS = {
    "2026": "https://www.robomaster.com/zh-CN/resource/pages/announcement/1913",
    "2025": "https://www.robomaster.com/zh-CN/resource/pages/announcement/1830",
    "2024": "https://www.robomaster.com/zh-CN/resource/pages/announcement/1711",
    "2023": "https://www.robomaster.com/zh-CN/resource/pages/announcement/1596",
}
RESULT_ORDER = {"冠军": 1, "亚军": 2, "季军": 3, "殿军": 4, "八强": 5, "十六强": 9, "未出线": 17}


def download(year, url):
    cached = Path(f"/tmp/rmul_awards_{year}.html")
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Chrome/131 Safari/537.36"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_rankings(year, url, html):
    soup = BeautifulSoup(html, "html.parser")
    table = next(table for table in soup.find_all("table") if (lambda text: "站" in text and ("排名" in text or "名次" in text))(table.find("tr").get_text("|", strip=True)))
    rows = []
    for tr in table.find_all("tr")[1:]:
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 4 or not cells[0] or not cells[2] or not cells[3]:
            continue
        result = cells[1] if cells[1] in RESULT_ORDER else "未出线"
        zone = cells[0]
        if year == "2024" and zone == "西南站（0322-0325）":
            zone = "西南站"
        elif year == "2024" and zone == "西南站（0325-0327）":
            zone = "西南站二"
        rows.append({
            "season": year, "zone": zone, "result": result,
            "school": cells[2], "team": cells[3], "sortOrder": RESULT_ORDER[result],
            "source": url,
        })
    return rows


def plain(value):
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", str(value or "").lower())


def side_matches(side, ranking):
    text = plain(side)
    school, team = plain(ranking["school"]), plain(ranking["team"])
    return bool((school and school in text) or (team and len(team) >= 2 and team in text))


def annotate_brackets(matches, rankings):
    events = {}
    for item in matches:
        events.setdefault((item["season"], item["zone"]), []).append(item)
    rank_events = {}
    for item in rankings:
        rank_events.setdefault((item["season"], item["zone"]), []).append(item)

    for event, ranks in rank_events.items():
        rows = sorted(events.get(event, []), key=lambda item: int(item["order"]))
        if not rows:
            continue
        by_result = {}
        for rank in ranks:
            by_result.setdefault(rank["result"], []).append(rank)
        top16 = [rank for rank in ranks if rank["result"] in {"冠军", "亚军", "季军", "殿军", "八强", "十六强"}]
        top8 = [rank for rank in ranks if rank["result"] in {"冠军", "亚军", "季军", "殿军", "八强"}]
        top4 = [rank for rank in ranks if rank["result"] in {"冠军", "亚军", "季军", "殿军"}]

        def identities(item):
            return plain(item["redSchool"] + item["redTeam"]), plain(item["blueSchool"] + item["blueTeam"])

        def contains_pair(item, first, second):
            red, blue = identities(item)
            return ((side_matches(red, first) and side_matches(blue, second)) or
                    (side_matches(red, second) and side_matches(blue, first)))

        tagged = set()
        for result_a, result_b, stage in (("冠军", "亚军", "冠军争夺战"), ("季军", "殿军", "季军争夺战")):
            if by_result.get(result_a) and by_result.get(result_b):
                candidates = [item for item in rows if contains_pair(item, by_result[result_a][0], by_result[result_b][0])]
                if candidates:
                    item = candidates[-1]; item["stage"] = stage; tagged.add(item["id"])

        def candidates_for(pool, count, before_order=None):
            found = []
            for item in rows:
                if item["id"] in tagged or (before_order is not None and int(item["order"]) >= before_order):
                    continue
                red, blue = identities(item)
                if any(side_matches(red, rank) for rank in pool) and any(side_matches(blue, rank) for rank in pool):
                    found.append(item)
            return found[-count:]

        final_orders = [int(item["order"]) for item in rows if item["id"] in tagged]
        semis = candidates_for(top4, 2, min(final_orders) if final_orders else None)
        for item in semis: item["stage"] = "半决赛"; tagged.add(item["id"])
        semi_orders = [int(item["order"]) for item in semis]
        quarters = candidates_for(top8, 4, min(semi_orders) if semi_orders else None)
        for item in quarters: item["stage"] = "8进4淘汰赛"; tagged.add(item["id"])
        quarter_orders = [int(item["order"]) for item in quarters]
        round16 = candidates_for(top16, 8, min(quarter_orders) if quarter_orders else None)
        for item in round16: item["stage"] = "16进8淘汰赛"; tagged.add(item["id"])


def main():
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    official = []
    for year, url in ANNOUNCEMENTS.items():
        rows = parse_rankings(year, url, download(year, url))
        official.extend(rows)
        print(f"{year}: {len(rows)} official 3V3 ranking rows")
    payload["rankings"] = [item for item in payload.get("rankings", []) if item.get("season") not in ANNOUNCEMENTS] + official
    payload["rankingSources"] = ANNOUNCEMENTS
    annotate_brackets(payload["matches"], payload["rankings"])
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(payload['rankings'])} official ranking rows")


if __name__ == "__main__":
    main()
