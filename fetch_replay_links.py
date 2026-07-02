#!/usr/bin/env python3
"""Fetch and verify direct Bilibili replay links for normalized match rows."""

import argparse
import http.cookiejar
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from build_results_dashboard import build_payload, read_workbook


OFFICIAL_MID = 20554233
API = "https://api.bilibili.com/x/web-interface/search/type"
PAGELIST_API = "https://api.bilibili.com/x/player/pagelist"
SEASON_LIST_API = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
SEASON_CATALOG_API = "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
XLSX = Path("/home/jwj/Downloads/RoboMaster 2015-2026 赛果记录.xlsx")
OUTPUT = Path("data/replay_links.json")
CHECKED_OUTPUT = Path("data/replay_checked.json")
ZONE_NAMES = {
    "总决赛": "全国赛", "北区": "北部赛区", "南区": "南部赛区", "中区": "中部赛区",
    "北部": "北部赛区", "南部": "南部赛区", "中部": "中部赛区", "东部": "东部赛区",
}
COLLECTIONS = {
    ("2021", "北区"): ("BV1UB4y1T7v2", 71, lambda order: order),
    ("2021", "中区"): ("BV1M5411u7eV", 71, lambda order: order),
    ("2021", "南区"): ("BV1rh411B7oP", 62, lambda order: order if order <= 24 else order + 1),
    ("2021", "总决赛"): ("BV1vq4y1Z7C2", 68, lambda order: order),
    ("2019", "北部"): (
        "BV1jJ411M7A5", 82,
        lambda order: order + sum(order > duplicated for duplicated in (53, 57, 62, 64, 68, 75, 77)),
    ),
    # The middle collection contains one replay after match 57 and two extra
    # parts around matches 88/90.  Keep the offsets explicit so a rebuild does
    # not silently attach the wrong P number.
    ("2019", "中部"): (
        "BV1PJ411u7ZE", 90,
        lambda order: order if order <= 57 else order + 1 if order <= 88 else 91 if order == 89 else 93,
    ),
    ("2018", "总决赛"): (
        "BV1kE411f7Ds", 48,
        lambda order: order if order <= 39 else order - 1,
    ),
}

# Older finals were uploaded as several multipart videos instead of a space
# season.  Values map workbook match numbers to verified multipart pages.
MULTIPART_RANGES = {
    ("2019", "总决赛"): (
        (1, 48, "BV174411q7Ug", lambda order: order),
        (49, 56, "BV174411z75Y", lambda order: order - 48),
        (57, 70, "BV1N4411z7is", lambda order: order - 56),
    ),
    ("2019", "南部"): (
        (1, 33, "BV1KJ411T7o9", lambda order: order),
        (35, 49, "BV1KJ411T7o9", lambda order: order - 1),
        (53, 79, "BV1KJ411T7o9", lambda order: order - 4),
        (80, 80, "BV1KJ411T7o9", lambda order: 76),
    ),
}

INDIVIDUAL_MATCHES = {
    ("2019", "南部", 34): "BV154411s7EN",
    ("2019", "总决赛", 75): "BV1u4411r7V7",
    ("2019", "总决赛", 77): "BV1G4411r7tY",
    ("2019", "总决赛", 72): "BV1y441167P9",
    ("2019", "总决赛", 73): "BV1q441167bG",
    ("2019", "总决赛", 74): "BV1S441167Hu",
    ("2021", "总决赛", 69): "BV1GL4y1h7ix",
    ("2021", "总决赛", 70): "BV1Xf4y1F7R3",
    ("2021", "总决赛", 71): "BV1Q34y1D7gU",
    ("2021", "总决赛", 72): "BV1HL411s7on",
    ("2022", "南部赛区", 65): "BV19S4y1i7WU",
    ("2022", "南部赛区", 66): "BV1NA4y1d71u",
    ("2022", "南部赛区", 67): "BV1mA4y1R7Bx",
    ("2022", "中部赛区", 71): "BV1ea411s7ni",
    ("2022", "中部赛区", 72): "BV1jB4y147K2",
    ("2022", "东部赛区", 54): "BV1DN4y137UL",
}


def plain(value):
    value = re.sub(r"<[^>]+>", "", value or "")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", value.lower())


def make_opener():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"),
        ("Referer", "https://search.bilibili.com/"),
        ("Accept", "application/json, text/plain, */*"),
    ]
    try:
        opener.open("https://www.bilibili.com/", timeout=20).read(128)
    except Exception:
        pass
    return opener


def fetch(opener, query, page, retries=5):
    params = urllib.parse.urlencode({
        "search_type": "video", "keyword": query, "page": page, "page_size": 50,
    })
    request = urllib.request.Request(API + "?" + params)
    for attempt in range(retries):
        try:
            with opener.open(request, timeout=25) as response:
                payload = json.load(response)
            if payload.get("code") != 0:
                raise RuntimeError(f'API {payload.get("code")}: {payload.get("message")}')
            return payload.get("data", {}).get("result", [])
        except urllib.error.HTTPError as error:
            if error.code != 412 or attempt == retries - 1:
                raise
            wait = min(45, 5 * (2 ** attempt)) + random.uniform(0.5, 2.5)
            print(f"  412 temporary block; retry {attempt + 1}/{retries} in {wait:.1f}s", flush=True)
            time.sleep(wait)
    return []


def fetch_pagelist(opener, bvid):
    request = urllib.request.Request(PAGELIST_API + "?" + urllib.parse.urlencode({"bvid": bvid}))
    with opener.open(request, timeout=25) as response:
        payload = json.load(response)
    if payload.get("code") != 0:
        return []
    return payload.get("data") or []


def fetch_season_archives(opener, season_id, page, retries=5):
    params = urllib.parse.urlencode({
        "mid": OFFICIAL_MID, "season_id": season_id, "sort_reverse": "false",
        "page_num": page, "page_size": 30,
    })
    request = urllib.request.Request(SEASON_LIST_API + "?" + params)
    for attempt in range(retries):
        try:
            with opener.open(request, timeout=25) as response:
                payload = json.load(response)
            if payload.get("code") == 0:
                return payload.get("data") or {}
            if payload.get("code") not in {-352, -412, -503}:
                raise RuntimeError(f'API {payload.get("code")}: {payload.get("message")}')
        except urllib.error.HTTPError as error:
            if error.code != 412:
                raise
        if attempt == retries - 1:
            raise RuntimeError(f"official list {season_id} page {page} remained rate-limited")
        wait = min(35, 4 * (2 ** attempt)) + random.uniform(0.5, 1.5)
        print(f"official list temporary limit; retry page {page} in {wait:.1f}s", flush=True)
        time.sleep(wait)
    return {}


def fetch_season_catalog(opener, page):
    params = urllib.parse.urlencode({"mid": OFFICIAL_MID, "page_num": page, "page_size": 20})
    request = urllib.request.Request(SEASON_CATALOG_API + "?" + params)
    with opener.open(request, timeout=25) as response:
        payload = json.load(response)
    if payload.get("code") != 0:
        raise RuntimeError(f'catalog API {payload.get("code")}: {payload.get("message")}')
    return payload.get("data") or {}


def save_links(links):
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(links, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def seed_collection_links(matches, links):
    """Add verified multipart collections where part numbers follow match order."""
    for item in matches:
        collection = COLLECTIONS.get((item["season"], item["zone"]))
        if not collection:
            continue
        bvid, max_order, part_for_order = collection
        try:
            order = int(float(item["order"]))
        except (TypeError, ValueError):
            continue
        if order < 1 or order > max_order:
            continue
        if (item["season"], item["zone"], order) == ("2018", "总决赛", 40):
            continue
        key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
        links.setdefault(key, {
            "url": f"https://www.bilibili.com/video/{bvid}/?p={part_for_order(order)}",
            "title": f'{item["season"]} {item["zone"]} 第{order}场：{item["redTeam"]} vs {item["blueTeam"]}',
        })

        
    for item in matches:
        ranges = MULTIPART_RANGES.get((item["season"], item["zone"]), ())
        try:
            order = int(float(item["order"]))
        except (TypeError, ValueError):
            continue
        for first, last, bvid, page_for_order in ranges:
            if first <= order <= last:
                key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
                links.setdefault(key, {
                    "url": f"https://www.bilibili.com/video/{bvid}/?p={page_for_order(order)}",
                    "title": f'{item["season"]} {item["zone"]} 第{order}场：{item["redTeam"]} vs {item["blueTeam"]}',
                })
                break

    for item in matches:
        try:
            order = int(float(item["order"]))
        except (TypeError, ValueError):
            continue
        bvid = INDIVIDUAL_MATCHES.get((item["season"], item["zone"], order))
        if not bvid:
            continue
        key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
        links.setdefault(key, {
            "url": f"https://www.bilibili.com/video/{bvid}/",
            "title": f'{item["season"]} {item["zone"]} 第{order}场：{item["redTeam"]} vs {item["blueTeam"]}',
        })


def match_video(item, video):
    if video.get("mid") != OFFICIAL_MID or not video.get("bvid"):
        return None
    title = re.sub(r"<[^>]+>", "", video.get("title", ""))
    normalized_title = plain(title)
    red_names = [plain(item["redTeam"]), plain(item["redSchool"])]
    blue_names = [plain(item["blueTeam"]), plain(item["blueSchool"])]
    red_matches = any(name and name in normalized_title for name in red_names)
    blue_matches = any(name and name in normalized_title for name in blue_names)
    if not red_matches or not blue_matches:
        return None
    if str(item["season"]) not in title:
        return None
    number_match = re.search(r"第\s*(\d+)\s*场", title)
    if not number_match:
        number_match = re.search(r"(?:^|\s)(\d{1,3})(?:[.、\s]|$)", title)
    if not number_match:
        number_match = re.search(r"(?:^|\D)(\d{1,3})场", title)
    if item.get("order") and number_match and number_match.group(1) != str(item["order"]):
        return None
    page_suffix = f'?p={video["page"]}' if video.get("page") else ""
    return {
        "url": f'https://www.bilibili.com/video/{video["bvid"]}/{page_suffix}',
        "title": title,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", help="Fetch one or more comma-separated seasons, e.g. 2025,2024")
    parser.add_argument("--zone", help="Only fetch one source zone, e.g. 全国赛")
    parser.add_argument("--pages", type=int, default=4, help="Search result pages per group")
    parser.add_argument("--delay", type=float, default=3.0, help="Base delay between requests")
    parser.add_argument("--exhaustive", action="store_true", help="Query every unmatched match directly")
    parser.add_argument("--recheck", action="store_true", help="Ignore old checked-miss cache")
    parser.add_argument("--bili-season-id", help="Import one official Bilibili season/list id")
    parser.add_argument("--source-season", help="Season year for --bili-season-id")
    parser.add_argument("--source-zone", help="Source zone for --bili-season-id")
    parser.add_argument("--discover-official-lists", action="store_true", help="Discover and import all official replay seasons")
    args = parser.parse_args()
    matches = build_payload(read_workbook(XLSX))["matches"]
    target = {str(year) for year in range(2015, 2026)}
    groups = sorted({(item["season"], item["zone"]) for item in matches if item["season"] in target}, reverse=True)
    if args.season:
        requested_seasons = {value.strip() for value in args.season.split(",") if value.strip()}
        groups = [group for group in groups if group[0] in requested_seasons]
    if args.zone:
        groups = [group for group in groups if group[1] == args.zone]
    links = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    seed_collection_links(matches, links)
    save_links(links)
    opener = make_opener()
    expanded_collections = {}
    if args.discover_official_lists:
        catalog = []
        page = 1
        while True:
            data = fetch_season_catalog(opener, page)
            items = (data.get("items_lists") or {})
            seasons = items.get("seasons_list") or []
            catalog.extend(seasons)
            total = int((items.get("page") or {}).get("total") or len(catalog))
            print(f"catalog page {page}: {len(seasons)} / {total}", flush=True)
            if not seasons or len(catalog) >= total:
                break
            page += 1
            time.sleep(0.8)
        relevant = []
        for season in catalog:
            meta = season.get("meta") or {}
            name = f'{meta.get("name", "")} {meta.get("title", "")}'
            if re.search(r"20(?:18|19|21|22|23|24|25)", name) and re.search(r"回放|比赛视频合集|比赛回放", name):
                relevant.append((str(meta.get("season_id")), name.strip()))
        print(f"discovered {len(relevant)} relevant official lists", flush=True)
        for season_id, name in relevant:
            archives = []
            archive_page = 1
            while True:
                data = fetch_season_archives(opener, season_id, archive_page)
                rows = data.get("archives") or []
                archives.extend(rows)
                total = int((data.get("page") or {}).get("total") or len(archives))
                if not rows or len(archives) >= total:
                    break
                archive_page += 1
                time.sleep(0.8)
            before = len(links)
            for archive in archives:
                video = {"mid": OFFICIAL_MID, "bvid": archive.get("bvid"), "title": archive.get("title", "")}
                for item in matches:
                    replay = match_video(item, video)
                    if replay:
                        key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
                        links[key] = replay
                        break
            save_links(links)
            print(f"{season_id} {name}: +{len(links) - before} ({len(archives)} videos)", flush=True)
            time.sleep(1.2)
        print(f"official discovery complete: {len(links)} links")
        return
    if args.bili_season_id:
        if bool(args.source_season) != bool(args.source_zone):
            raise SystemExit("--source-season and --source-zone must be supplied together")
        source_matches = ([item for item in matches if item["season"] == args.source_season and item["zone"] == args.source_zone]
                          if args.source_season else matches)
        archives = []
        page = 1
        while True:
            data = fetch_season_archives(opener, args.bili_season_id, page)
            page_archives = data.get("archives") or []
            archives.extend(page_archives)
            total = int((data.get("page") or {}).get("total") or len(archives))
            meta_name = (data.get("meta") or {}).get("name") or (data.get("meta") or {}).get("title") or ""
            print(f"official list {args.bili_season_id} {meta_name} page {page}: {len(page_archives)} / {total}", flush=True)
            if not page_archives or len(archives) >= total:
                break
            page += 1
            time.sleep(0.8)
        before = len(links)
        for archive in archives:
            video = {"mid": OFFICIAL_MID, "bvid": archive.get("bvid"), "title": archive.get("title", "")}
            matched = False
            for item in source_matches:
                replay = match_video(item, video)
                if replay:
                    key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
                    links[key] = replay
                    matched = True
                    break
            if not matched and args.source_season:
                title = archive.get("title", "")
                number_match = re.search(r"第\s*(\d+)\s*场", title)
                if number_match:
                    order = number_match.group(1)
                    item = next((row for row in source_matches if str(row.get("order")) == order), None)
                    if item:
                        key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
                        links[key] = {
                            "url": f'https://www.bilibili.com/video/{archive["bvid"]}/',
                            "title": title,
                        }
        save_links(links)
        print(f"official list imported: +{len(links) - before}, total {len(links)}")
        return
    if args.exhaustive:
        checked = set(json.loads(CHECKED_OUTPUT.read_text(encoding="utf-8"))) if CHECKED_OUTPUT.exists() else set()
        requested_seasons = {value.strip() for value in args.season.split(",") if value.strip()} if args.season else set()
        selected = [item for item in matches if (not requested_seasons or item["season"] in requested_seasons)
                    and (not args.zone or item["zone"] == args.zone)]
        missing = [item for item in selected if f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}' not in links
                   and (args.recheck or f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}' not in checked)]
        print(f"exhaustive: {len(missing)} unmatched of {len(selected)} selected", flush=True)
        exhaustive_parts = {}
        for index, item in enumerate(missing, 1):
            normalized_zone = ZONE_NAMES.get(item["zone"], item["zone"])
            prefix = "RMUC" if item["season"] == "2025" else "RoboMaster"
            queries = [
                f'{prefix} {item["season"]} {normalized_zone} 第{item["order"]}场 {item["redTeam"]} {item["blueTeam"]}',
                f'{prefix} {item["season"]} {normalized_zone} 第{item["order"]}场 {item["redSchool"]} {item["blueSchool"]}',
            ]
            try:
                candidates = []
                seen_bvids = set()
                for query in dict.fromkeys(queries):
                    for candidate in fetch(opener, query, 1):
                        identity = candidate.get("bvid") or candidate.get("aid")
                        if identity not in seen_bvids:
                            candidates.append(candidate)
                            seen_bvids.add(identity)
            except Exception as error:
                print(f"[{index}/{len(missing)}] skip {item['season']} {item['zone']} #{item['order']}: {error}", flush=True)
                continue
            key = f'{item["season"]}|{item["zone"]}|{item["order"]}|{item["id"]}'
            for video in candidates:
                replay = match_video(item, video)
                if replay:
                    links[key] = replay
                    save_links(links)
                    break
                if video.get("mid") != OFFICIAL_MID or not video.get("bvid"):
                    continue
                bvid = video["bvid"]
                if bvid not in exhaustive_parts:
                    try:
                        parts = fetch_pagelist(opener, bvid)
                    except Exception:
                        parts = []
                    container_title = re.sub(r"<[^>]+>", "", video.get("title", ""))
                    exhaustive_parts[bvid] = [{
                        "mid": OFFICIAL_MID, "bvid": bvid, "page": part.get("page"),
                        "title": f'{item["season"]} {normalized_zone} {container_title} {part.get("part", "")}',
                    } for part in parts]
                for part_video in exhaustive_parts[bvid]:
                    replay = match_video(item, part_video)
                    if replay:
                        links[key] = replay
                        save_links(links)
                        break
                if key in links:
                    break
            checked.add(key)
            if index % 10 == 0 or key in links:
                CHECKED_OUTPUT.write_text(json.dumps(sorted(checked), ensure_ascii=False, indent=2), encoding="utf-8")
            if index % 10 == 0 or key in links:
                print(f"[{index}/{len(missing)}] verified total {len(links)}", flush=True)
            if args.delay:
                time.sleep(args.delay + random.uniform(0.2, 1.0))
        save_links(links)
        CHECKED_OUTPUT.write_text(json.dumps(sorted(checked), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved {len(links)} verified links to {OUTPUT}")
        return
    for season, zone in groups:
        normalized_zone = ZONE_NAMES.get(zone, zone)
        prefix = "RMUC" if season == "2025" else "RoboMaster"
        query = f"{prefix} {season} {normalized_zone} 第 场"
        candidates = []
        for page in range(1, args.pages + 1):
            try:
                page_rows = fetch(opener, query, page)
                candidates.extend(page_rows)
                if page == 1 or page % 5 == 0 or page == args.pages:
                    print(f"{season} {zone} page {page}: {len(page_rows)} candidates", flush=True)
            except Exception as error:
                print(f"skip {season} {zone} page {page}: {error}")
                break
            time.sleep(args.delay + random.uniform(0.3, 1.4))
        group_matches = [item for item in matches if item["season"] == season and item["zone"] == zone]
        collection_parts = []
        for video in candidates:
            title = re.sub(r"<[^>]+>", "", video.get("title", ""))
            bvid = video.get("bvid")
            if video.get("mid") != OFFICIAL_MID or not bvid:
                continue
            if "合集" not in title and int(video.get("duration", "0").split(":")[0] or 0) < 180:
                continue
            if bvid in expanded_collections:
                collection_parts.extend(expanded_collections[bvid])
                continue
            try:
                parts = fetch_pagelist(opener, bvid)
            except Exception:
                continue
            expanded = []
            for part in parts:
                expanded.append({
                    "mid": OFFICIAL_MID, "bvid": bvid, "page": part.get("page"),
                    "title": f'{title} {part.get("part", "")}',
                })
            expanded_collections[bvid] = expanded
            collection_parts.extend(expanded)
            if parts:
                print(f"  expanded {bvid}: {len(parts)} parts", flush=True)
            time.sleep(args.delay)
        candidates.extend(collection_parts)
        for video in candidates:
            for item in group_matches:
                replay = match_video(item, video)
                if replay:
                    key = f'{season}|{zone}|{item["order"]}|{item["id"]}'
                    links[key] = replay
                    break
        save_links(links)
        print(f"{season} {zone}: {sum(key.startswith(f'{season}|{zone}|') for key in links)} verified", flush=True)
        time.sleep(args.delay + random.uniform(1.0, 2.5))
    save_links(links)
    print(f"saved {len(links)} verified links to {OUTPUT}")


if __name__ == "__main__":
    main()
