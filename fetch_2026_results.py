#!/usr/bin/env python3
"""Build normalized 2026 match rows from official schedule and replay data."""

import json
import re
import time
import urllib.request
from pathlib import Path

import fetch_replay_links as replay
from data_store import load_rmuc_results, save_rmuc_results
SEASONS = {
    "8208439": "北部赛区",
    "8156146": "东部赛区",
    "8110609": "南部赛区",
    "8716384": "复活赛",
    "8746598": "全国赛",
}
SCHEDULE_URL = "https://rm-static.djicdn.com/live_json/schedule.json"
OUTPUT = Path("results_2026.json")
UNIFIED_OUTPUT = Path("data/rmuc_results")
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


def finals_stage(zone, order):
    """Return the published bracket phase for the 2026 revival/finals."""
    if zone == "复活赛":
        for start, end, stage in (
            (1, 4, "A组第1轮"), (5, 8, "B组第1轮"),
            (9, 12, "A组第2轮"), (13, 16, "B组第2轮"),
            (17, 19, "A组第3轮"), (20, 22, "B组第3轮"),
            (23, 26, "8进4淘汰赛"),
            (27, 28, "8进4败者组第一轮"),
            (29, 30, "8进4胜者组"),
            (31, 32, "8进4败者组第二轮"),
        ):
            if start <= order <= end:
                return stage
        return "复活赛"

    for start, end, stage in (
        (1, 8, "A组第1轮"), (9, 16, "B组第1轮"),
        (17, 24, "A组第2轮"), (25, 32, "B组第2轮"),
        (33, 40, "A组第3轮"), (41, 48, "B组第3轮"),
        (49, 54, "A组第4轮"), (55, 60, "B组第4轮"),
        (61, 63, "A组第5轮"), (64, 66, "B组第5轮"),
        (67, 74, "16进8淘汰赛"),
        (75, 78, "16进8败者组第一轮"),
        (79, 82, "16进8胜者组"),
        (83, 86, "16进8败者组第二轮"),
        (87, 88, "8进4胜者组"),
        (89, 90, "8进4败者组第一轮"),
        (91, 92, "8进4败者组第二轮"),
        (93, 94, "半决赛"),
    ):
        if start <= order <= end:
            return stage
    return {95: "季军争夺战", 96: "冠军争夺战", 97: "全明星赛", 98: "全明星赛"}.get(order, "全国赛")


def match_stage(zone, order):
    if zone in {"复活赛", "全国赛"}:
        return finals_stage(zone, order)
    return regional_stage(zone, order)


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
                    "redSchool": (((match.get("redSide") or {}).get("player") or {}).get("team") or {}).get("collegeName", "-"),
                    "redTeam": (((match.get("redSide") or {}).get("player") or {}).get("team") or {}).get("name", "-"),
                    "blueSchool": (((match.get("blueSide") or {}).get("player") or {}).get("team") or {}).get("collegeName", "-"),
                    "blueTeam": (((match.get("blueSide") or {}).get("player") or {}).get("team") or {}).get("name", "-"),
                }
    rows = []
    links = {}
    pattern = re.compile(r"(?P<zone>[^\s]*赛区|复活赛|全国赛)\s+第(?P<number>[零一二两三四五六七八九十百\d]+)场")
    all_star_pattern = re.compile(r"全明星赛\s+第(?P<number>[一二两\d]+)局")
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
                all_star_match = all_star_pattern.search(title) if expected_zone == "全国赛" else None
                if not all_star_match:
                    print(f"ignored non-match video: {title}")
                    continue
                order = 96 + chinese_number(all_star_match.group("number"))
            else:
                order = chinese_number(match.group("number"))
            zone = expected_zone
            official = official_matches.get((zone, order), {})
            if not official:
                print(f"missing official result: {zone} #{order}: {title}")
                continue
            normalized_title = replay.plain(title)
            for side in ("red", "blue"):
                school = replay.plain(official[f"{side}School"])
                team = replay.plain(official[f"{side}Team"])
                if school not in normalized_title and team not in normalized_title:
                    raise RuntimeError(f"{zone} #{order} {side} competitor does not match replay title: {title}")
            red_score = official.get("redScore")
            blue_score = official.get("blueScore")
            completed = official.get("status") == "DONE" and red_score is not None and blue_score is not None
            item_id = f"2026-{zone}-{order}"
            rows.append({
                "id": item_id, "season": "2026", "zone": zone, "order": str(order),
                "stage": match_stage(zone, order),
                "redSchool": official["redSchool"], "redTeam": official["redTeam"],
                "blueSchool": official["blueSchool"], "blueTeam": official["blueTeam"],
                "redScore": red_score if completed else "-",
                "blueScore": blue_score if completed else "-",
                "note": "比分与回放均来自官方数据" if completed else "官方回放已发布，比分待补",
                "uncertain": not completed,
                "matchId": official.get("matchId", ""),
                "redSourceMatch": official.get("redSourceMatch", ""),
                "blueSourceMatch": official.get("blueSourceMatch", ""),
            })
            links[f"2026|{zone}|{order}|{item_id}"] = {
                "title": title,
                "url": f'https://www.bilibili.com/video/{archive["bvid"]}/',
            }
        print(f"{expected_zone}: {len(archives)} videos")
    expected_keys = {
        key for key in official_matches
        if key[0] in set(SEASONS.values())
    }
    actual_keys = {(item["zone"], int(item["order"])) for item in rows}
    if len(actual_keys) != len(rows):
        raise RuntimeError("duplicate 2026 replay match rows detected")
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unexpected = sorted(actual_keys - expected_keys)
        raise RuntimeError(f"official/replay coverage mismatch; missing={missing}, unexpected={unexpected}")
    rows.sort(key=lambda item: (item["zone"], int(item["order"])))
    regional_zones = {"北部赛区", "东部赛区", "南部赛区"}
    rankings = derive_regional_results(
        [item for item in rows if item["zone"] in regional_zones],
        [item for item in rankings if item["zone"] in regional_zones],
    )
    OUTPUT.write_text(json.dumps({"matches": rows, "rankings": rankings, "replayLinks": links}, ensure_ascii=False, indent=2), encoding="utf-8")
    unified = load_rmuc_results() or {"matches": [], "qualifiers": [], "rankings": []}
    unified["matches"] = [item for item in unified.get("matches", []) if item.get("season") != "2026"] + rows
    save_rmuc_results(unified)
    existing_links = {}
    if replay.OUTPUT.exists():
        existing_links = json.loads(replay.OUTPUT.read_text(encoding="utf-8"))
    existing_links = {key: value for key, value in existing_links.items() if not key.startswith("2026|")}
    existing_links.update(links)
    replay.save_links(existing_links)
    if UNIFIED_OUTPUT.exists():
        print(f"updated unified schedule data in {UNIFIED_OUTPUT}")
    print(f"saved {len(rows)} matches, {len(rankings)} rankings and {len(links)} links to {OUTPUT}")


if __name__ == "__main__":
    main()
