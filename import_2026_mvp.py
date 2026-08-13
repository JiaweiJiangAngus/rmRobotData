#!/usr/bin/env python3
"""Import the 2026 national-finals MVP workbook into dashboard text files."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile


XML_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
OUTPUT_ROLES = ("英雄", "步兵3", "步兵4", "哨兵", "无人机", "雷达", "工程", "飞镖")
EXPECTED_TEAMS = {"全国赛": 32, "复活赛": 16}
HEADER_ROLES = {
    "英雄1": "英雄",
    "工程2": "工程",
    "步兵3": "步兵3",
    "步兵4": "步兵4",
    "无人机6": "无人机",
    "哨兵7": "哨兵",
    "飞镖8": "飞镖",
    "雷达9": "雷达",
}


def column_number(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference)
    if not letters:
        raise ValueError(f"invalid cell reference: {reference}")
    result = 0
    for char in letters.group():
        result = result * 26 + ord(char) - ord("A") + 1
    return result


def read_xlsx_rows(path: Path) -> list[dict[int, str]]:
    with ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("x:si", XML_NS):
                shared_strings.append("".join(node.text or "" for node in item.iterfind(".//x:t", XML_NS)))

        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        rows: list[dict[int, str]] = []
        for row in sheet.findall(".//x:sheetData/x:row", XML_NS):
            values: dict[int, str] = {}
            for cell in row.findall("x:c", XML_NS):
                reference = cell.get("r", "")
                value_node = cell.find("x:v", XML_NS)
                value = value_node.text if value_node is not None and value_node.text is not None else ""
                if cell.get("t") == "s" and value:
                    value = shared_strings[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iterfind(".//x:t", XML_NS))
                values[column_number(reference)] = value.strip()
            rows.append(values)
        return rows


def parse_sections(rows: list[dict[int, str]]) -> dict[str, list[dict[str, object]]]:
    sections = {name: [] for name in EXPECTED_TEAMS}
    current_section = ""
    role_columns: dict[int, str] = {}

    for row in rows:
        first_cell = row.get(1, "")
        if first_cell in sections:
            current_section = first_cell
            role_columns = {
                column: HEADER_ROLES[value]
                for column, value in row.items()
                if value in HEADER_ROLES
            }
            continue
        if not current_section or not row.get(2) or not row.get(3):
            continue

        counts: dict[str, int] = {}
        for column, role in role_columns.items():
            raw_value = row.get(column, "")
            counts[role] = int(float(raw_value)) if raw_value else 0
        sections[current_section].append({
            "school": row[2],
            "team": row[3],
            "counts": counts,
        })

    for section, expected_count in EXPECTED_TEAMS.items():
        actual_count = len(sections[section])
        if actual_count != expected_count:
            raise ValueError(f"{section}: expected {expected_count} teams, found {actual_count}")
    return sections


def write_outputs(sections: dict[str, list[dict[str, object]]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for section, teams in sections.items():
        zone = f"2026{section}"
        output = output_dir / f"mvp_{zone}.txt"
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(("赛区", "学校", "战队", "兵种", "MVP次数"))
            for item in teams:
                counts = item["counts"]
                for role in OUTPUT_ROLES:
                    writer.writerow((zone, item["school"], item["team"], role, counts[role]))
        print(f"saved {len(teams) * len(OUTPUT_ROLES)} rows to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", nargs="?", type=Path, default=Path.home() / "Desktop" / "全国赛MVP.xlsx")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    args = parser.parse_args()
    sections = parse_sections(read_xlsx_rows(args.workbook))
    write_outputs(sections, args.output_dir)


if __name__ == "__main__":
    main()
