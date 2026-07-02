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
            if current_zone and remaining > 0 and school and team:
                ranking_order += 1
                remaining -= 1
                rankings.append({
                    "season": str(year), "zone": current_zone, "school": school,
                    "team": team, "result": result or "未列名次", "sortOrder": ranking_order,
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
    return {"matches": matches, "qualifiers": qualifiers, "rankings": rankings}
