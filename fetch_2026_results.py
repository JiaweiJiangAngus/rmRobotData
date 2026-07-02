#!/usr/bin/env python3
"""Build normalized 2026 regional match rows from official Bilibili seasons."""

import json
import re
import time
import urllib.request
from pathlib import Path

import fetch_replay_links as replay
from build_results_dashboard import build_payload, read_workbook


SEASONS = {
    "8208439": "北部赛区",
    "8156146": "东部赛区",
    "8110609": "南部赛区",
}
SCHEDULE_URL = "https://rm-static.djicdn.com/live_json/schedule.json"
OUTPUT = Path("results_2026.json")
CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def chinese_number(value):
    if value.isdigit():
        return int(value)
    if "百" in value:
        left, right = value.split("百", 1)
        return CN_DIGITS.get(left, 1) * 100 + chinese_number(right) if right else CN_DIGITS.get(left, 1) * 100
    if "十" in value:
        left, right = value.split("十", 1)
        return CN_DIGITS.get(left, 1) * 10 + CN_DIGITS.get(right, 0)
    return CN_DIGITS.get(value, 0)


def split_competitor(text, schools):
    text = re.sub(r"\s+", " ", text).strip()
    for school in schools:
        if text.startswith(school):
            return school, text[len(school):].strip() or "-"
    parts = text.rsplit(" ", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (text, "-")


def stage_for(order, title):
    for label in ("冠军争夺赛", "季军争夺赛", "半决赛", "全国赛名额争夺赛",
                  "8进4淘汰赛", "16进8淘汰赛", "小组赛"):
        if label in title:
            return label
    return "区域赛"


def main():
    payload = build_payload(read_workbook(replay.XLSX))
    schools = {row[side] for row in payload["matches"] for side in ("redSchool", "blueSchool")}
    schools.update(row["school"] for row in payload["qualifiers"])
    schools = sorted((name for name in schools if name), key=len, reverse=True)
    opener = replay.make_opener()
    schedule_request = urllib.request.Request(SCHEDULE_URL, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    })
    with urllib.request.urlopen(schedule_request, timeout=30) as response:
        live_schedule = json.load(response)
    official_matches = {}
    for zone in live_schedule["data"]["event"]["zones"]["nodes"]:
        zone_name = zone["name"]
        for source, stage in (("groupMatches", "小组赛"), ("knockoutMatches", "淘汰赛")):
            for match in (zone.get(source) or {}).get("nodes", []):
                official_matches[(zone_name, int(match["orderNumber"]))] = {
                    "redScore": match.get("redSideWinGameCount"),
                    "blueScore": match.get("blueSideWinGameCount"),
                    "stage": stage,
                    "status": match.get("status"),
                }
    rows = []
    links = {}
    pattern = re.compile(
        r"^(?:RoboMaster\s*)?(?P<zone>[^ ]*赛区)\s+第(?P<number>[零一二两三四五六七八九十百\d]+)场\s+"
        r"(?P<red>.+?)\s*战队\s+[Vv][Ss]\s+(?P<blue>.+?)(?:\s*战队)?\s+(?:RoboMaster|RMUC|RM)\s"
    )
    for season_id, expected_zone in SEASONS.items():
        archives = []
        page = 1
        while True:
            data = replay.fetch_season_archives(opener, season_id, page)
            batch = data.get("archives") or []
            archives.extend(batch)
            total = int((data.get("page") or {}).get("total") or len(archives))
            if not batch or len(archives) >= total:
                break
            page += 1
            time.sleep(0.8)
        for archive in archives:
            title = archive.get("title", "")
            match = pattern.search(title)
            if not match:
                print(f"unparsed: {title}")
                continue
            order = chinese_number(match.group("number"))
            zone = match.group("zone") or expected_zone
            red_school, red_team = split_competitor(match.group("red"), schools)
            blue_school, blue_team = split_competitor(match.group("blue"), schools)
            official = official_matches.get((zone, order), {})
            red_score = official.get("redScore")
            blue_score = official.get("blueScore")
            completed = official.get("status") == "DONE" and red_score is not None and blue_score is not None
            item_id = f"2026-{zone}-{order}"
            rows.append({
                "id": item_id, "season": "2026", "zone": zone, "order": str(order),
                "stage": official.get("stage") or stage_for(order, title),
                "redSchool": red_school, "redTeam": red_team,
                "blueSchool": blue_school, "blueTeam": blue_team,
                "redScore": red_score if completed else "-",
                "blueScore": blue_score if completed else "-",
                "note": "比分与回放均来自官方数据" if completed else "官方回放已发布，比分待补",
                "uncertain": not completed,
            })
            links[f"2026|{zone}|{order}|{item_id}"] = {
                "title": title,
                "url": f'https://www.bilibili.com/video/{archive["bvid"]}/',
            }
        print(f"{expected_zone}: {len(archives)} videos")
    rows.sort(key=lambda item: (item["zone"], int(item["order"])))
    OUTPUT.write_text(json.dumps({"matches": rows, "replayLinks": links}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {len(rows)} matches and {len(links)} links to {OUTPUT}")


if __name__ == "__main__":
    main()
