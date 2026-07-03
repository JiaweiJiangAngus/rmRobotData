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
UNIFIED_OUTPUT = Path("data/schedule_results.json")
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


def regional_stage(zone, order):
    """Use the official 2026 regional bracket phases and repository naming."""
    group_ranges = (
        (1, 8, "A组第1轮"), (9, 16, "B组第1轮"),
        (17, 24, "A组第2轮"), (25, 32, "B组第2轮"),
        (33, 40, "A组第3轮"), (41, 48, "B组第3轮"),
        (49, 54, "A组第4轮"), (55, 60, "B组第4轮"),
        (61, 63, "A组第5轮"), (64, 66, "B组第5轮"),
    )
    for start, end, stage in group_ranges:
        if start <= order <= end:
            return stage
    if 67 <= order <= 74:
        return "16进8淘汰赛"
    if 75 <= order <= 78:
        return "8进4淘汰赛"
    if order in {83, 84}:
        return "半决赛"
    final_order = 90 if zone == "北部赛区" else 88
    if order == final_order - 1:
        return "季军争夺战"
    if order == final_order:
        return "冠军争夺战"
    if zone == "东部赛区" and order in {79, 80, 81, 82, 85, 86}:
        return "复活赛名额争夺"
    if zone == "北部赛区" and order in {87, 88}:
        return "复活赛名额争夺"
    if order in {79, 80, 81, 82, 85, 86}:
        return "全国赛名额争夺"
    return "淘汰赛"


def derive_regional_results(rows, group_rankings):
    """Derive final regional placements from the completed main knockout bracket."""
    placements = {}
    details = {}
    for item in group_rankings:
        key = (item.get("zone"), item.get("school"), item.get("team"))
        placements[key] = "未出线"
        details[key] = item
    for item in rows:
        for side in ("red", "blue"):
            key = (item.get("zone"), item.get(f"{side}School"), item.get(f"{side}Team"))
            placements.setdefault(key, "未出线")
            details.setdefault(key, {})

    def apply_stage(stage, default_result):
        for item in rows:
            if item.get("stage") != stage:
                continue
            for side in ("red", "blue"):
                key = (item.get("zone"), item.get(f"{side}School"), item.get(f"{side}Team"))
                placements[key] = default_result

    apply_stage("16进8淘汰赛", "十六强")
    apply_stage("8进4淘汰赛", "八强")
    for stage, winner_result, loser_result in (
        ("季军争夺战", "季军", "殿军"),
        ("冠军争夺战", "冠军", "亚军"),
    ):
        for item in rows:
            if item.get("stage") != stage:
                continue
            red_score, blue_score = int(item["redScore"]), int(item["blueScore"])
            winner, loser = ("red", "blue") if red_score > blue_score else ("blue", "red")
            placements[(item.get("zone"), item.get(f"{winner}School"), item.get(f"{winner}Team"))] = winner_result
            placements[(item.get("zone"), item.get(f"{loser}School"), item.get(f"{loser}Team"))] = loser_result

    result_order = {"冠军": 1, "亚军": 2, "季军": 3, "殿军": 4, "八强": 5, "十六强": 9, "未出线": 17}
    output = []
    for key, result in placements.items():
        zone, school, team = key
        if not school or not team:
            continue
        source = details.get(key, {})
        output.append({
            "season": "2026", "zone": zone, "school": school, "team": team,
            "result": result, "sortOrder": result_order[result],
            "group": source.get("group"), "groupRank": source.get("rank"),
        })
    return sorted(output, key=lambda item: (item["zone"], item["sortOrder"], item["school"], item["team"]))


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
    rankings = []
    for zone in live_schedule["data"]["event"]["zones"]["nodes"]:
        zone_name = zone["name"]
        group_rounds = []
        group_round_by_order = {}
        for match in sorted((zone.get("groupMatches") or {}).get("nodes", []), key=lambda item: int(item["orderNumber"])):
            team_ids = [str((((match.get(side) or {}).get("player") or {}).get("team") or {}).get("id") or "") for side in ("redSide", "blueSide")]
            round_index = next((index for index, used in enumerate(group_rounds) if not any(team_id in used for team_id in team_ids)), None)
            if round_index is None:
                group_rounds.append(set())
                round_index = len(group_rounds) - 1
            group_rounds[round_index].update(team_ids)
            group_round_by_order[int(match["orderNumber"])] = round_index + 1
        for group in (zone.get("groups") or {}).get("nodes", []):
            for player in (group.get("players") or {}).get("nodes", []):
                team = player.get("team") or {}
                rankings.append({
                    "season": "2026", "zone": zone_name, "group": group.get("name", "-"),
                    "rank": player.get("rank"), "school": team.get("collegeName", "-"),
                    "team": team.get("name", "-"), "score": player.get("score"),
                })
        for source, stage in (("groupMatches", "小组赛"), ("knockoutMatches", "淘汰赛")):
            for match in (zone.get(source) or {}).get("nodes", []):
                official_matches[(zone_name, int(match["orderNumber"]))] = {
                    "matchId": str(match.get("id") or ""),
                    "redSourceMatch": str((match.get("redSide") or {}).get("fillSourceId") or "") if (match.get("redSide") or {}).get("fillSourceType") == "Match" else "",
                    "blueSourceMatch": str((match.get("blueSide") or {}).get("fillSourceId") or "") if (match.get("blueSide") or {}).get("fillSourceType") == "Match" else "",
                    "redScore": match.get("redSideWinGameCount"),
                    "blueScore": match.get("blueSideWinGameCount"),
                    "stage": stage,
                    "groupRound": group_round_by_order.get(int(match["orderNumber"])),
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
                "stage": regional_stage(zone, order),
                "redSchool": red_school, "redTeam": red_team,
                "blueSchool": blue_school, "blueTeam": blue_team,
                "redScore": red_score if completed else "-",
                "blueScore": blue_score if completed else "-",
                "note": "比分与回放均来自官方数据" if completed else "官方回放已发布，比分待补",
                "uncertain": not completed,
                "matchId": official.get("matchId", ""),
                "redSourceMatch": official.get("redSourceMatch", ""),
                "blueSourceMatch": official.get("blueSourceMatch", ""),
                "groupRound": official.get("groupRound"),
            })
            links[f"2026|{zone}|{order}|{item_id}"] = {
                "title": title,
                "url": f'https://www.bilibili.com/video/{archive["bvid"]}/',
            }
        print(f"{expected_zone}: {len(archives)} videos")
    rows.sort(key=lambda item: (item["zone"], int(item["order"])))
    rankings = derive_regional_results(rows, rankings)
    OUTPUT.write_text(json.dumps({"matches": rows, "rankings": rankings, "replayLinks": links}, ensure_ascii=False, indent=2), encoding="utf-8")
    if UNIFIED_OUTPUT.exists():
        unified = json.loads(UNIFIED_OUTPUT.read_text(encoding="utf-8"))
        unified["matches"] = [item for item in unified.get("matches", []) if item.get("season") != "2026"] + rows
        UNIFIED_OUTPUT.write_text(json.dumps(unified, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"updated unified schedule data in {UNIFIED_OUTPUT}")
    print(f"saved {len(rows)} matches, {len(rankings)} rankings and {len(links)} links to {OUTPUT}")


if __name__ == "__main__":
    main()
