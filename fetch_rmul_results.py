#!/usr/bin/env python3
"""Fetch official RMUL replay collections and normalize individual matches."""

import json
import re
import time
from collections import defaultdict
from pathlib import Path

import fetch_replay_links as bili
from data_store import save_rmul_results


OUTPUT = Path("data/rmul_results")
RAW_CACHE = Path("data/cache/rmul_raw_cache.json")
YEARS = {"2021", "2023", "2024", "2025", "2026"}
STATIONS = ("黑龙江站", "辽宁站", "华北站", "东北站", "山东站", "山西站", "西北站",
            "江苏站", "上海站", "浙江站", "安徽站", "福建站", "湖北站", "广东站",
            "华南站", "广西站", "四川站", "重庆站", "西南站", "北美站")

# Only include matches whose opponent pairing and order are uniquely recoverable
# from a complete round-robin group.  Red/blue assignment and score stay unknown.
INFERRED_MATCHES = (
    {
        "id": "RMUL-INFERRED-2026-东北站-32",
        "season": "2026", "zone": "东北站", "order": "32", "stage": "小组赛",
        "redSchool": "东北大学", "redTeam": "TDT",
        "blueSchool": "东北农业大学", "blueTeam": "TCP",
        "redScore": "-", "blueScore": "-", "title": "",
        "url": "", "uncertain": True, "inferred": True,
        "inferenceNote": "按同组单循环已知场次的唯一缺边推定；红蓝方、比分及官方回放未知",
    },
    {"season": "2026", "zone": "四川站", "order": "16", "redSchool": "青海大学", "redTeam": "河湟谷人", "blueSchool": "仲恺农业工程学院", "blueTeam": "奇点"},
    {"season": "2026", "zone": "四川站", "order": "32", "redSchool": "河南科技大学", "redTeam": "鼎行双创", "blueSchool": "青海大学", "blueTeam": "河湟谷人"},
    {"season": "2026", "zone": "山东站", "order": "6", "redSchool": "北京农学院", "redTeam": "银杏", "blueSchool": "北京化工大学", "blueTeam": "百花机甲"},
    {"season": "2026", "zone": "山东站", "order": "15", "redSchool": "济南大学", "redTeam": "TFT", "blueSchool": "枣庄学院", "blueTeam": "Summit"},
    {"season": "2026", "zone": "重庆站", "order": "11", "redSchool": "南华大学", "redTeam": "MA", "blueSchool": "联勤保障部队工程大学", "blueTeam": "陆擎"},
    {"season": "2026", "zone": "重庆站", "order": "19", "redSchool": "重庆大学", "redTeam": "千里", "blueSchool": "联勤保障部队工程大学", "blueTeam": "陆擎"},
    {"season": "2025", "zone": "福建站", "order": "23", "redSchool": "广东海洋大学", "redTeam": "浪潮", "blueSchool": "广州南方学院", "blueTeam": "南風"},
    {"season": "2025", "zone": "西南站", "order": "48", "redSchool": "重庆交通大学", "redTeam": "铺路石", "blueSchool": "西南石油大学", "blueTeam": "南充校区 泓龙"},
    {"season": "2026", "zone": "安徽站", "order": "3", "redSchool": "广东以色列理工学院", "redTeam": "工夫", "blueSchool": "南京航空航天大学（天目湖校区）", "blueTeam": "巡天御风"},
    {"season": "2023", "zone": "上海站", "order": "4", "redSchool": "中南大学", "redTeam": "FYT", "blueSchool": "常州大学", "blueTeam": "RPS"},
    {"season": "2023", "zone": "西南站", "order": "6", "redSchool": "电子科技大学成都学院", "redTeam": "微城市", "blueSchool": "贵阳人文科技学院", "blueTeam": "BIU"},
    {"season": "2024", "zone": "山东站", "order": "16", "redSchool": "山东理工大学", "redTeam": "齐奇", "blueSchool": "枣庄学院", "blueTeam": "Summit"},
    {"season": "2024", "zone": "广东站", "order": "39", "redSchool": "广州工商学院", "redTeam": "野草", "blueSchool": "电子科技大学中山学院", "blueTeam": "RoboBraver"},
    {"season": "2025", "zone": "广西站", "order": "2", "redSchool": "广东交通职业技术学院", "redTeam": "图灵", "blueSchool": "湖南大学", "blueTeam": "跃鹿"},
    {"season": "2026", "zone": "华北站", "order": "27", "redSchool": "山西工商学院", "redTeam": "TB Power", "blueSchool": "北京航空航天大学", "blueTeam": "Transistor"},
    {"season": "2026", "zone": "华北站", "order": "50", "stage": "16进8淘汰赛", "redSchool": "北京工业大学", "redTeam": "PIP", "blueSchool": "山西工商学院", "blueTeam": "TB Power"},
    {"season": "2025", "zone": "广西站", "order": "21", "redSchool": "深圳职业技术大学", "redTeam": "RCIA", "blueSchool": "广西师范大学", "blueTeam": "虎师"},
)

# Fill common fields after the compact declarations above.  The order/opponents
# are inferred; side assignment, score, title and replay are deliberately blank.
INFERRED_MATCHES = tuple({
    "id": f"RMUL-INFERRED-{item['season']}-{item['zone']}-{item['order']}",
    "stage": "小组赛", "redScore": "-", "blueScore": "-", "title": "", "url": "",
    "uncertain": True, "inferred": True,
    "inferenceNote": "按同组单循环缺边及相邻轮次排表唯一推定；红蓝方、比分及官方回放未知",
    **item,
} for item in INFERRED_MATCHES)

# Numbering holes left by reserved slots, cancelled/unused schedule positions or
# the gap before an exhibition match.  Their surrounding round-robin graph is
# already complete, so these must not be counted as missing match replays.
NON_MATCH_ORDERS = {
    ("2023", "西北站", "11"), ("2023", "西北站", "17"),
    ("2025", "山东站", "4"), ("2025", "山东站", "27"), ("2025", "山东站", "42"),
    ("2025", "浙江站", "54"), ("2025", "浙江站", "55"), ("2025", "浙江站", "56"),
    ("2025", "福建站", "24"),
    ("2025", "西南站", "1"), ("2025", "西南站", "8"), ("2025", "西南站", "32"),
    ("2025", "辽宁站", "5"),
    ("2026", "上海站", "8"), ("2026", "上海站", "32"), ("2026", "上海站", "48"),
    ("2026", "安徽站", "20"), ("2026", "安徽站", "30"),
}


def chinese_number(value):
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value.isdigit():
        return int(value)
    if "百" in value:
        left, right = value.split("百", 1)
        return digits.get(left, 1) * 100 + (chinese_number(right) if right else 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, 0)


def collection_info(meta):
    title = meta.get("title", "")
    year_match = re.search(r"20(?:2[1-6])", title)
    if not year_match or year_match.group(0) not in YEARS:
        return None
    if not re.search(r"RMUL|高校联盟赛", title, re.I):
        return None
    if re.search(r"高能|精彩", title) and year_match.group(0) != "2021":
        return None
    station_match = re.search(r"[（(]([^()（）]*站[一二]?)[）)]", title) or re.search(r"([^\s·（(]+站)(?:赛事|比赛|$)", title)
    station = station_match.group(1) if station_match else ("精选回放" if year_match.group(0) == "2021" else "多站合集")
    return year_match.group(0), station


def fetch_catalog(opener):
    metas = []
    for page in range(1, 8):
        data = bili.fetch_season_catalog(opener, page)
        items = data.get("items_lists") or {}
        metas.extend(item.get("meta", {}) for item in items.get("seasons_list", []))
        page_info = items.get("page") or {}
        if page * int(page_info.get("page_size") or 20) >= int(page_info.get("total") or 0):
            break
        time.sleep(2.0)
    selected = []
    for meta in metas:
        info = collection_info(meta)
        if info:
            selected.append({**meta, "year": info[0], "station": info[1]})
    return selected


def fetch_archives(opener, collections):
    cache = json.loads(RAW_CACHE.read_text(encoding="utf-8")) if RAW_CACHE.exists() else {"collections": {}, "archives": {}}
    for index, meta in enumerate(collections, 1):
        season_id = str(meta["season_id"])
        cache["collections"][season_id] = meta
        expected = int(meta.get("total") or 0)
        archives = cache["archives"].setdefault(season_id, [])
        page = len(archives) // 30 + 1
        while len(archives) < expected:
            data = None
            for attempt in range(6):
                try:
                    data = bili.fetch_season_archives(opener, season_id, page)
                    break
                except Exception as error:
                    if attempt == 5:
                        raise
                    wait = min(30, 4 * (attempt + 1))
                    print(f"network error on {season_id} page {page}: {error}; retry in {wait}s", flush=True)
                    time.sleep(wait)
            batch = data.get("archives") or []
            known = {item.get("bvid") for item in archives}
            archives.extend(item for item in batch if item.get("bvid") not in known)
            RAW_CACHE.parent.mkdir(parents=True, exist_ok=True)
            RAW_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{index}/{len(collections)}] {meta['year']} {meta['station']}: {len(archives)}/{expected}", flush=True)
            if not batch:
                break
            page += 1
            time.sleep(1.8)
    return cache


def fetch_2021_multipart(opener, cache):
    videos = {}
    for page in range(1, 4):
        for video in bili.fetch(opener, "2021机甲大师高校联盟赛", page):
            title = re.sub(r"<[^>]+>", "", video.get("title", ""))
            if video.get("mid") == bili.OFFICIAL_MID and "高校联盟赛" in title and "比赛视频合集" in title:
                videos[video["bvid"]] = title
        time.sleep(2)
    for bvid, title in videos.items():
        station = next((name for name in STATIONS if name in title), "高校联盟赛")
        parts = bili.fetch_pagelist(opener, bvid)
        key = f"video:{bvid}"
        cache["collections"][key] = {
            "season_id": key, "year": "2021", "station": station, "title": title,
            "total": len(parts), "url": f"https://www.bilibili.com/video/{bvid}/",
        }
        cache["archives"][key] = [
            {"bvid": bvid, "title": part.get("part", ""), "page": index,
             "url": f"https://www.bilibili.com/video/{bvid}/?p={index}"}
            for index, part in enumerate(parts, 1)
        ]
        print(f"2021 {station}: {len(parts)} multipart matches from {bvid}", flush=True)
    RAW_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache


def infer_stage(title):
    for pattern, label in (
        (r"季军|三四名", "季军争夺战"), (r"半决|4\s*进\s*2", "半决赛"),
        (r"冠军|总决赛|^决赛", "冠军争夺战"), (r"16\s*进\s*8|十六进八", "16进8淘汰赛"),
        (r"8\s*进\s*4|八进四", "8进4淘汰赛"), (r"小组", "小组赛"),
    ):
        if re.search(pattern, title, re.I):
            return label
    return "比赛回放"


def parse_archive(meta, archive, fallback_order):
    title = re.sub(r"\s+", " ", archive.get("title", "")).strip()
    versus = re.search(r"(?P<red>[^|｜丨【】]+?)\s*(?:VS|vs|Vs|vS)\s*(?P<blue>[^|｜丨【】]+)", title)
    if not versus:
        return None
    red = re.sub(r"^(?:.*?第[零一二两三四五六七八九十百\d]+场\s*)", "", versus.group("red")).strip(" -·：:")
    blue = re.split(r"\s+(?:RMUL|RoboMaster|机甲大师|比赛回放)", versus.group("blue"), maxsplit=1)[0].strip(" -·：:")
    order_match = re.search(r"第([零一二两三四五六七八九十百\d]+)(?:场|站)", title)
    order = chinese_number(order_match.group(1)) if order_match else fallback_order
    station = next((name for name in STATIONS if name in title), meta["station"])
    if station == "西南站" and "西南站二" in title:
        station = "西南站二"
    score = re.search(r"(?:比分)?\s*([0-3])\s*[-:：]\s*([0-3])", title)

    def competitor(value):
        value = re.sub(r"(?:战队|队伍)$", "", value).strip()
        school_match = re.match(r"^(.+(?:大学|学院|学校)(?:[（(][^）)]*校区[）)])?)\s*(.+)$", value)
        if school_match:
            return school_match.group(1).strip(), school_match.group(2).strip()
        return value, value

    red_school, red_team = competitor(red)
    blue_school, blue_team = competitor(blue)
    return {
        "id": f"RMUL-{meta['year']}-{station}-{order}-{archive.get('bvid')}",
        "season": meta["year"], "zone": station, "order": str(order),
        "stage": infer_stage(title),
        "redSchool": red_school, "redTeam": red_team, "blueSchool": blue_school, "blueTeam": blue_team,
        "redScore": score.group(1) if score else "-", "blueScore": score.group(2) if score else "-",
        "title": title, "url": archive.get("url") or f"https://www.bilibili.com/video/{archive.get('bvid')}/",
        "uncertain": not bool(score),
    }


def normalize(cache):
    rows = []
    collections = []
    for season_id, meta in cache.get("collections", {}).items():
        archives = cache.get("archives", {}).get(season_id, [])
        parsed = [row for index, item in enumerate(archives, 1) if (row := parse_archive(meta, item, index))]
        rows.extend(parsed)
        collections.append({
            "seasonId": season_id, "season": meta["year"], "zone": meta["station"],
            "title": meta["title"], "totalVideos": len(archives), "parsedMatches": len(parsed),
            "url": meta.get("url") or f"https://space.bilibili.com/{bili.OFFICIAL_MID}/lists/{season_id}?type=season",
        })
    rows.sort(key=lambda item: (item["season"], item["zone"], int(item["order"])))
    collections.sort(key=lambda item: (item["season"], item["zone"]), reverse=True)
    match_years = {item["season"] for item in rows}
    collection_years = {item["season"] for item in collections}
    coverage = []
    for year in sorted(YEARS, reverse=True):
        if year in match_years:
            coverage.append({"season": year, "status": "逐场回放", "matchCount": sum(item["season"] == year for item in rows)})
        elif year == "2021" and year in collection_years:
            coverage.append({"season": year, "status": "仅有官方高能合集，未作为逐场赛果", "matchCount": 0,
                             "url": "https://space.bilibili.com/20554233/lists/857450?type=season"})
        else:
            coverage.append({"season": year, "status": "官号合集目录暂无逐场回放", "matchCount": 0})
    return {"matches": rows, "collections": collections, "coverage": coverage, "rankings": []}


def supplement_missing(opener, payload, cache):
    searches = cache.setdefault("searches", {})
    events = defaultdict(list)
    for item in payload["matches"]:
        if item["season"] != "2021":
            events[(item["season"], item["zone"])].append(int(item["order"]))
    supplements = []
    unresolved = []
    for (year, station), numbers in sorted(events.items(), reverse=True):
        for order in sorted(set(range(1, max(numbers) + 1)) - set(numbers)):
            key = f"{year}|{station}|{order}"
            if key not in searches:
                query = f"{year} {station} 第{order}场 高校联盟赛"
                try:
                    results = bili.fetch(opener, query, 1)
                except Exception as error:
                    print(f"search failed for {key}: {error}", flush=True)
                    results = []
                searches[key] = [item for item in results if item.get("mid") == bili.OFFICIAL_MID]
                RAW_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                time.sleep(1.8)
            found = None
            for video in searches[key]:
                title = re.sub(r"<[^>]+>", "", video.get("title", ""))
                if station not in title or not re.search(rf"第\s*{order}\s*(?:场|站)", title):
                    continue
                found = parse_archive({"year": year, "station": station}, {"bvid": video.get("bvid"), "title": title}, order)
                if found:
                    break
            if found:
                supplements.append(found)
                print(f"supplemented {key}: {found['url']}", flush=True)
            else:
                unresolved.append({"season": year, "zone": station, "order": str(order)})
    known = {item["id"] for item in payload["matches"]}
    payload["matches"].extend(item for item in supplements if item["id"] not in known)
    occupied = {(item["season"], item["zone"], item["order"]) for item in payload["matches"]}
    inferred = [item.copy() for item in INFERRED_MATCHES
                if (item["season"], item["zone"], item["order"]) not in occupied]
    payload["matches"].extend(inferred)
    inferred_keys = {(item["season"], item["zone"], item["order"]) for item in inferred}
    unresolved = [item for item in unresolved
                  if (item["season"], item["zone"], item["order"]) not in inferred_keys]
    skipped = [item for item in unresolved
               if (item["season"], item["zone"], item["order"]) in NON_MATCH_ORDERS]
    unresolved = [item for item in unresolved
                  if (item["season"], item["zone"], item["order"]) not in NON_MATCH_ORDERS]
    payload["matches"].sort(key=lambda item: (item["season"], item["zone"], int(item["order"])))
    payload["missingReplays"] = unresolved
    payload["supplementedMatches"] = len(supplements)
    payload["inferredMatches"] = inferred
    payload["nonMatchOrderGaps"] = skipped
    return payload


def main():
    opener = bili.make_opener()
    collections = fetch_catalog(opener)
    print(f"found {len(collections)} official RMUL collections", flush=True)
    cache = fetch_archives(opener, collections)
    cache = fetch_2021_multipart(opener, cache)
    payload = normalize(cache)
    payload = supplement_missing(opener, payload, cache)
    save_rmul_results(payload)
    print(f"saved {len(payload['matches'])} parsed matches from {len(payload['collections'])} collections to {OUTPUT}")


if __name__ == "__main__":
    main()
