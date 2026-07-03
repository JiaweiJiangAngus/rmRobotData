#!/usr/bin/env python3
"""Read and normalize the historical RoboMaster xlsx for the main dashboard."""

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def column_number(reference):
    letters = re.match(r"[A-Z]+", reference).group(0)
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - 64
    return result - 1


def read_workbook(path):
    """Return all worksheets as rows using only Python's standard library."""
    with zipfile.ZipFile(path) as archive:
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t"))
            for item in shared_root.findall(f"{{{MAIN_NS}}}si")
        ]
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationships = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rel_root.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        result = {}
        for sheet in workbook.findall(f".//{{{MAIN_NS}}}sheet"):
            name = sheet.attrib["name"]
            target = relationships[sheet.attrib[f"{{{REL_NS}}}id"]]
            root = ET.fromstring(archive.read("xl/" + target))
            rows = []
            for row_node in root.findall(f".//{{{MAIN_NS}}}sheetData/{{{MAIN_NS}}}row"):
                cells = {}
                for cell in row_node.findall(f"{{{MAIN_NS}}}c"):
                    ref = cell.attrib.get("r", "A1")
                    value_node = cell.find(f"{{{MAIN_NS}}}v")
                    inline = cell.find(f"{{{MAIN_NS}}}is")
                    if inline is not None:
                        value = "".join(node.text or "" for node in inline.iter(f"{{{MAIN_NS}}}t"))
                    elif value_node is None:
                        value = ""
                    elif cell.attrib.get("t") == "s":
                        value = shared[int(value_node.text)]
                    else:
                        value = value_node.text or ""
                    cells[column_number(ref)] = value.strip()
                rows.append([cells.get(index, "") for index in range(max(cells, default=-1) + 1)])
            result[name] = rows
    return result


def clean_number(value):
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return value or "-"


def normalize_group_stages(matches):
    """Expand legacy pool labels such as 小组赛A into per-pool round labels."""
    pools = {}
    for item in matches:
        stage = str(item.get("stage") or "").strip()
        match = re.fullmatch(r"小组赛([A-ZＡ-Ｚ])", stage) or re.fullmatch(r"瑞士轮([A-ZＡ-Ｚ])组", stage)
        if match:
            pools.setdefault((str(item.get("season")), item.get("zone"), match.group(1)), []).append(item)
    for (_, _, group), rows in pools.items():
        rounds = []
        for item in sorted(rows, key=lambda row: float(row.get("order") or 0)):
            teams = {
                f"{item.get('redSchool', '')}|{item.get('redTeam', '')}",
                f"{item.get('blueSchool', '')}|{item.get('blueTeam', '')}",
            }
            round_index = next((index for index, used in enumerate(rounds) if teams.isdisjoint(used)), None)
            if round_index is None:
                rounds.append(set())
                round_index = len(rounds) - 1
            rounds[round_index].update(teams)
            item["stage"] = f"{group}组第{round_index + 1}轮"
    return matches


def normalize_known_legacy_stages(matches):
    """Name the few legacy rows whose workbook stage is generic or blank."""
    known = {
        ("2016", "踢馆赛", "-"): "踢馆赛（赛段待核）",
        ("2017", "踢馆赛", "40"): "踢馆资格争夺战",
        ("2017", "踢馆赛", "41"): "踢馆资格争夺战",
        ("2017", "踢馆赛", "42"): "踢馆资格争夺战",
        ("2024", "港澳台及海外赛区", "7"): "晋级名额争夺战",
        ("2024", "港澳台及海外赛区", "8"): "晋级名额争夺战",
        ("2025", "复活赛第二赛段", "34"): "淘汰赛第一轮",
        ("2025", "复活赛第二赛段", "35"): "复活赛名额争夺战",
    }
    for item in matches:
        key = (str(item.get("season")), item.get("zone"), str(item.get("order")))
        if key in known:
            item["stage"] = known[key]
    return matches


def derive_rankings_from_matches(matches, rankings):
    """Fill missing event rankings from completed main-bracket results."""
    result_order = {"冠军": 1, "亚军": 2, "季军": 3, "殿军": 4, "八强": 5, "十六强": 9, "未出线": 17}
    existing = {
        (str(item.get("season")), item.get("zone"), item.get("school"), item.get("team")): item
        for item in rankings if item.get("school") and item.get("team")
    }
    existing_by_team = {
        (str(item.get("season")), item.get("zone"), item.get("team")): item
        for item in rankings if item.get("team")
    }
    events = {}
    for item in matches:
        events.setdefault((str(item.get("season")), item.get("zone")), []).append(item)

    def team_key(event, item, side):
        return event + (item.get(f"{side}School"), item.get(f"{side}Team"))

    def scores(item):
        try:
            return int(float(item.get("redScore"))), int(float(item.get("blueScore")))
        except (TypeError, ValueError):
            return None

    for event, rows in events.items():
        official_event_rankings = [item for item in rankings if (str(item.get("season")), item.get("zone")) == event]
        has_official_results = any(item.get("result") for item in official_event_rankings)
        derived = {}
        for item in rows:
            if "全明星" in str(item.get("stage") or ""):
                continue
            for side in ("red", "blue"):
                key = team_key(event, item, side)
                if key[-2] and key[-1]:
                    derived.setdefault(key, "未出线")
        for item in rows:
            stage = str(item.get("stage") or "")
            if re.search(r"全明星|名额|排位|复活|踢馆|邀请|友谊", stage):
                continue
            if re.search(r"16\s*进\s*8|1/8决赛|淘汰赛16进8", stage):
                for side in ("red", "blue"):
                    derived[team_key(event, item, side)] = "十六强"
            if re.search(r"8\s*进\s*4|1/4决赛|8强争夺", stage):
                for side in ("red", "blue"):
                    derived[team_key(event, item, side)] = "八强"
        for item in rows:
            stage = str(item.get("stage") or "").strip()
            score = scores(item)
            if not score:
                continue
            if re.search(r"季军|三四名决赛", stage):
                winner_result, loser_result = "季军", "殿军"
            elif re.search(r"冠军争夺(?:战|赛)", stage) or stage == "决赛":
                winner_result, loser_result = "冠军", "亚军"
            else:
                continue
            winner, loser = (("red", "blue") if score[0] > score[1] else ("blue", "red"))
            derived[team_key(event, item, winner)] = winner_result
            derived[team_key(event, item, loser)] = loser_result
        for key, result in derived.items():
            if key in existing:
                if not existing[key].get("result"):
                    existing[key]["result"] = result
                    existing[key]["sortOrder"] = result_order[result]
                continue
            if has_official_results:
                continue
            team_match = existing_by_team.get((key[0], key[1], key[3]))
            if team_match is not None:
                if not team_match.get("result"):
                    team_match["result"] = result
                    team_match["sortOrder"] = result_order[result]
                continue
            season, zone, school, team = key
            item = {"season": season, "zone": zone, "school": school, "team": team,
                    "result": result, "sortOrder": result_order[result]}
            rankings.append(item)
            existing[key] = item
            existing_by_team[(season, zone, team)] = item
    for item in rankings:
        if not item.get("result"):
            item["result"] = "未出线"
            item["sortOrder"] = result_order["未出线"]
    rankings.sort(key=lambda item: (str(item.get("season")), str(item.get("zone")),
                                    int(item.get("sortOrder") or 999), str(item.get("school")), str(item.get("team"))))
    return rankings


def build_payload(sheets):
    """Normalize match rows and keep uncertain records marked for UI filtering."""
    columns = ["id", "season", "zone", "order", "stage", "redSchool", "redTeam",
               "blueSchool", "blueTeam", "redScore", "blueScore", "note"]
    matches = []
    positions = {}
    for uncertain, name in ((False, "2015-2025赛果全记录"), (True, "缺失赛果")):
        for source_row in sheets[name][1:]:
            row = source_row + [""] * (12 - len(source_row))
            if not row[0] or not row[5] or not row[7]:
                continue
            item = dict(zip(columns, row[:12]))
            item["season"] = str(item["season"]).replace(".0", "")
            item["redScore"] = clean_number(item["redScore"])
            item["blueScore"] = clean_number(item["blueScore"])
            item["uncertain"] = uncertain
            if item["id"] in positions:
                if uncertain:
                    matches[positions[item["id"]]] = item
            else:
                positions[item["id"]] = len(matches)
                matches.append(item)

    qualifiers = []
    for source_row in sheets["2026全国赛名单"][1:]:
        row = source_row + [""] * (23 - len(source_row))
        if row[0] and row[1]:
            qualifiers.append({
                "school": row[1], "team": row[2], "zone": row[3], "type": row[4],
                "rank2025": clean_number(row[5]), "result": row[17] or "待赛",
                "regionalCount": clean_number(row[18]), "nationalCount": clean_number(row[19]),
            })
    rankings = []
    ranking_sheet = sheets.get("分区赛名单", [])
    directions = "西南|西北|中南|华北|华东|东北|东部|西部|南部|北部|中部"
    for year, start in zip(range(2015, 2027), range(0, 48, 4)):
        current_zone = ""
        ranking_order = 0
        remaining = 0
        for source_row in ranking_sheet:
            row = source_row + [""] * (start + 3 - len(source_row))
            school, team, result = row[start:start + 3]
            heading = re.search(rf"({directions})(?:赛区|分区赛)[^\d]*(\d+)", school)
            if heading:
                direction = heading.group(1)
                if year == 2021:
                    current_zone = direction[0] + "区"
                elif year >= 2022 and year != 2023:
                    current_zone = direction + "赛区"
                else:
                    current_zone = direction
                remaining = int(heading.group(2))
                ranking_order = 0
                continue
            if school in {"学校", "学校\nSchool"} or team in {"队名", "队伍", "战队名称", "队伍\nTeam"}:
                continue
            if current_zone and remaining > 0 and school and team:
                ranking_order += 1
                remaining -= 1
                rankings.append({
                    "season": str(year), "zone": current_zone, "school": school,
                    "team": team, "result": result or "未出线", "sortOrder": ranking_order,
                })
                if remaining == 0:
                    current_zone = ""
    extra_path = Path("results_2026.json")
    if extra_path.exists():
        extra = json.loads(extra_path.read_text(encoding="utf-8"))
        for item in extra.get("matches", []):
            if item.get("id") not in positions:
                positions[item["id"]] = len(matches)
                matches.append(item)
        if not rankings:
            rankings.extend(extra.get("rankings", []))
    normalize_group_stages(matches)
    normalize_known_legacy_stages(matches)
    derive_rankings_from_matches(matches, rankings)
    return {"matches": matches, "qualifiers": qualifiers, "rankings": rankings}
