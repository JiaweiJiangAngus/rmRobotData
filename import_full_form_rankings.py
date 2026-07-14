import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


SOURCE = Path("/home/jwj/Downloads/RoboMaster_历年完整形态排名_精简版_已补全2025.xlsx")
OUTPUT = Path(__file__).resolve().parent / "data" / "rmuc_results" / "full_form_rankings.json"
YEARS = {"2022", "2023", "2024", "2025", "2026"}
NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def cell_column(cell_ref):
    match = re.match(r"([A-Z]+)", cell_ref or "")
    if not match:
        return ""
    column = 0
    for char in match.group(1):
        column = column * 26 + ord(char) - 64
    return column - 1


def text_of(node):
    return "".join(node.itertext()) if node is not None else ""


def read_shared_strings(archive):
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return [text_of(item) for item in root.findall("a:si", NS)]


def read_sheet_paths(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall("rel:Relationship", NS)
    }
    sheets = []
    for sheet in workbook.findall(".//a:sheet", NS):
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get(f"{{{NS['r']}}}id")
        target = rel_map.get(rid, "")
        if not name or not target:
            continue
        if not target.startswith("xl/"):
            target = f"xl/{target.lstrip('/')}"
        sheets.append((name, target))
    return sheets


def read_cell(cell, shared_strings):
    value = cell.find("a:v", NS)
    if value is None:
        inline = cell.find("a:is", NS)
        return text_of(inline).strip()
    raw = value.text or ""
    if cell.attrib.get("t") == "s":
        try:
            return shared_strings[int(raw)].strip()
        except (ValueError, IndexError):
            return ""
    return raw.strip()


def read_rows(archive, sheet_path, shared_strings):
    root = ET.fromstring(archive.read(sheet_path))
    rows = []
    for row in root.findall(".//a:sheetData/a:row", NS):
        values = []
        for cell in row.findall("a:c", NS):
            index = cell_column(cell.attrib.get("r", ""))
            while len(values) <= index:
                values.append("")
            values[index] = read_cell(cell, shared_strings)
        rows.append(values)
    return rows


def parse_rank(value):
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def build_payload(source):
    with ZipFile(source) as archive:
        shared_strings = read_shared_strings(archive)
        rankings = []
        for sheet_name, sheet_path in read_sheet_paths(archive):
            season = str(sheet_name).strip()
            if season not in YEARS:
                continue
            for row in read_rows(archive, sheet_path, shared_strings)[2:]:
                rank = parse_rank(row[0] if len(row) > 0 else "")
                school = (row[1] if len(row) > 1 else "").strip()
                team = (row[2] if len(row) > 2 else "").strip()
                if not rank or not school:
                    continue
                rankings.append({
                    "season": season,
                    "rank": rank,
                    "school": school,
                    "team": team,
                })
    rankings.sort(key=lambda item: (item["season"], item["rank"], item["school"], item["team"]))
    return {
        "source": str(source),
        "description": "RoboMaster 2022-2026 超级对抗赛完整形态考核排名",
        "rankings": rankings,
    }


def main():
    if not SOURCE.exists():
        raise SystemExit(f"找不到完整形态考核表：{SOURCE}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = build_payload(SOURCE)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    years = sorted({item["season"] for item in payload["rankings"]})
    print(f"写入 {OUTPUT}：{len(payload['rankings'])} 条，年份 {', '.join(years)}")


if __name__ == "__main__":
    main()
