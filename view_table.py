import csv
import html
import json
import os
import sys
from pathlib import Path

from team_eval_rules import get_team_evaluation_config

try:
    from build_results_dashboard import build_payload as build_schedule_payload
    from build_results_dashboard import read_workbook as read_results_workbook
except ImportError:
    build_schedule_payload = None
    read_results_workbook = None


DEFAULT_RESULTS_XLSX = Path("/home/jwj/Downloads/RoboMaster 2015-2026 赛果记录.xlsx")


def load_schedule_data():
    """Load and normalize the historical match workbook when it is available."""
    configured = os.environ.get("RM_RESULTS_XLSX")
    path = Path(configured) if configured else DEFAULT_RESULTS_XLSX
    if not path.exists() or read_results_workbook is None:
        return {"matches": [], "qualifiers": []}
    return build_schedule_payload(read_results_workbook(path))


def load_replay_links():
    path = Path(__file__).resolve().parent / "data" / "replay_links.json"
    links = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            links.update(json.load(handle))
    extra_path = Path(__file__).resolve().parent / "results_2026.json"
    if extra_path.exists():
        with extra_path.open("r", encoding="utf-8") as handle:
            links.update(json.load(handle).get("replayLinks", {}))
    return links


def parse_value(raw):
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return value



DART_SCORE_COLUMN = "总场次飞镖分数"
RADAR_SCORE_COLUMN = "局均雷达分数"
MVP_COUNT_COLUMN = "MVP次数"
MVP_DATA_PREFIX = "mvp_"


def normalize_key_part(value):
    if value is None:
        return ""
    return str(value).strip()


def get_number(row, column):
    value = row.get(column)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def weighted_sum(row, weights):
    has_any_value = False
    total = 0.0
    for column, weight in weights:
        value = get_number(row, column)
        if value is None:
            continue
        has_any_value = True
        total += value * weight
    return round(total, 2) if has_any_value else None


def add_column_after(columns, new_column, anchor_columns):
    if new_column in columns:
        return columns

    insert_at = None
    for anchor in anchor_columns:
        if anchor in columns:
            insert_at = columns.index(anchor) + 1
    if insert_at is None:
        columns.append(new_column)
    else:
        columns.insert(insert_at, new_column)
    return columns


def add_derived_metrics(columns, rows):
    columns = list(columns)
    add_column_after(columns, DART_SCORE_COLUMN, [
        "累计命中前哨站数",
        "累计命中固定靶数",
        "累计随机固定靶数",
        "累计随机移动靶数",
        "累计移动靶末端命中数",
    ])
    add_column_after(columns, RADAR_SCORE_COLUMN, [
        "双倍易伤时间",
        "雷达反制时长",
        "雷达解算成功次数",
        "额外伤害",
    ])

    dart_weights = [
        ("累计命中前哨站数", 1),
        ("累计命中固定靶数", 5),
        ("累计随机固定靶数", 10),
        ("累计随机移动靶数", 100),
        ("累计移动靶末端命中数", 200),
    ]

    radar_weights = [
        ("双倍易伤时间", 1),
        ("雷达反制时长", 20 / 45),
        ("雷达解算成功次数", 200),
    ]

    for row in rows:
        robot_type = row.get("兵种")
        if robot_type == "飞镖":
            row[DART_SCORE_COLUMN] = weighted_sum(row, dart_weights)
        else:
            row[DART_SCORE_COLUMN] = None

        if robot_type == "雷达":
            row[RADAR_SCORE_COLUMN] = weighted_sum(row, radar_weights)
        else:
            row[RADAR_SCORE_COLUMN] = None

    return columns, rows


def load_mvp_rows():
    data_dirs = [
        Path("data"),
        Path(__file__).resolve().parent / "data",
    ]
    data_dir = next((path for path in data_dirs if path.exists()), None)
    if data_dir is None:
        return []

    rows = []
    expected_columns = ["赛区", "学校", "战队", "兵种", MVP_COUNT_COLUMN]
    for path in sorted(data_dir.glob(f"{MVP_DATA_PREFIX}*.txt")):
        fallback_zone = path.stem[len(MVP_DATA_PREFIX):]
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                row = {column: parse_value(raw_row.get(column, "")) for column in expected_columns}
                row["赛区"] = row.get("赛区") or fallback_zone
                if not row.get("学校") or not row.get("战队") or not row.get("兵种"):
                    continue
                if row.get(MVP_COUNT_COLUMN) is None:
                    row[MVP_COUNT_COLUMN] = 0
                rows.append(row)
    return rows


def build_mvp_count_lookup(mvp_rows):
    lookup = {}
    infantry_totals = {}

    for row in mvp_rows:
        zone = normalize_key_part(row.get("赛区"))
        school = normalize_key_part(row.get("学校"))
        team = normalize_key_part(row.get("战队"))
        robot_type = normalize_key_part(row.get("兵种"))
        value = get_number(row, MVP_COUNT_COLUMN)
        if not zone or not school or not team or not robot_type or value is None:
            continue

        key = (zone, school, team, robot_type)
        lookup[key] = value

        if robot_type in {"步兵3", "步兵4"}:
            infantry_key = (zone, school, team)
            infantry_totals[infantry_key] = infantry_totals.get(infantry_key, 0.0) + value

    for (zone, school, team), total in infantry_totals.items():
        lookup[(zone, school, team, "步兵")] = total

    return lookup


def add_mvp_counts(columns, rows, mvp_rows):
    if not mvp_rows:
        return columns, rows

    columns = list(columns)
    add_column_after(columns, MVP_COUNT_COLUMN, [DART_SCORE_COLUMN, RADAR_SCORE_COLUMN])
    mvp_lookup = build_mvp_count_lookup(mvp_rows)

    for row in rows:
        key = (
            normalize_key_part(row.get("赛区")),
            normalize_key_part(row.get("学校")),
            normalize_key_part(row.get("战队")),
            normalize_key_part(row.get("兵种")),
        )
        row[MVP_COUNT_COLUMN] = mvp_lookup.get(key)

    return columns, rows


def normalize_preferred_metric(preferred_metric, columns):
    preferred_aliases = {
        "累计随机移动靶数": DART_SCORE_COLUMN,
        "累计移动靶末端命中数": DART_SCORE_COLUMN,
        "建筑伤害": DART_SCORE_COLUMN,
        "雷达反制时长": RADAR_SCORE_COLUMN,
        "雷达解算成功次数": RADAR_SCORE_COLUMN,
        "双倍易伤时间": RADAR_SCORE_COLUMN,
    }
    replacement = preferred_aliases.get(preferred_metric)
    if replacement in columns:
        return replacement
    return preferred_metric


def build_summary(rows, metric):
    numeric_values = []
    teams = set()
    zones = set()
    robot_types = set()

    for row in rows:
        team_name = row.get("战队")
        zone_name = row.get("赛区")
        robot_type = row.get("兵种")
        value = row.get(metric)

        if team_name:
            teams.add(str(team_name))
        if zone_name:
            zones.add(str(zone_name))
        if robot_type:
            robot_types.add(str(robot_type))
        if isinstance(value, (int, float)):
            numeric_values.append(float(value))

    avg_value = sum(numeric_values) / len(numeric_values) if numeric_values else None
    return {
        "teamCount": len(teams),
        "zoneCount": len(zones),
        "typeCount": len(robot_types),
        "avgMetric": None if avg_value is None else round(avg_value, 2),
    }


def choose_default_metric(columns, preferred_metric):
    preferred_metric = normalize_preferred_metric(preferred_metric, columns)
    if preferred_metric and preferred_metric in columns:
        return preferred_metric

    base_columns = {"赛区", "学校", "战队", "兵种"}
    priority_columns = [
        "小弹丸命中率",
        "大弹丸命中率",
        "KDA得分",
        "对敌伤害量",
        "建筑伤害",
        "击杀数",
        "场均发弹量",
        "局均组装经济数",
        "局均组装成功次数",
        "局均兑换经济数",
        DART_SCORE_COLUMN,
        RADAR_SCORE_COLUMN,
        MVP_COUNT_COLUMN,
        "雷达反制时长",
        "雷达解算成功次数",
        "双倍易伤时间",
        "累计移动靶末端命中数",
    ]

    for column in priority_columns:
        if column in columns:
            return column

    for column in columns:
        if column in base_columns:
            continue
        return column
    return ""


def render_html(title, payload):
    safe_title = html.escape(title)
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_title}</title>
  <script>
    (() => {{
      const savedTheme = localStorage.getItem("rm-dashboard-theme");
      const savedDensity = localStorage.getItem("rm-dashboard-density") || "standard";
      const savedBackground = localStorage.getItem("rm-dashboard-background");
      const prefersNight = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      const theme = savedTheme || (prefersNight ? "night" : "day");
      const background = savedBackground === "simple" ? "simple" : "fancy";
      document.documentElement.dataset.theme = theme;
      document.documentElement.dataset.density = savedDensity;
      document.documentElement.dataset.background = background;
    }})();
  </script>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f4efe7;
      --page-bg:
        radial-gradient(circle at top left, rgba(255, 206, 156, 0.5), transparent 30%),
        radial-gradient(circle at 80% 10%, rgba(176, 216, 255, 0.35), transparent 26%),
        linear-gradient(180deg, #f9f3eb 0%, #f4efe7 45%, #efe8dc 100%);
      --panel: rgba(255, 250, 242, 0.82);
      --panel-strong: rgba(255, 247, 236, 0.96);
      --panel-soft: rgba(255, 255, 255, 0.66);
      --line: rgba(107, 79, 52, 0.14);
      --glass-line: rgba(255, 255, 255, 0.5);
      --text: #2d241b;
      --muted: #78624a;
      --accent: #b85c38;
      --accent-deep: #8f3b1f;
      --accent-soft: rgba(184, 92, 56, 0.12);
      --table-alt: rgba(255, 252, 247, 0.55);
      --input-bg: rgba(255,255,255,0.78);
      --button-bg: rgba(255,255,255,0.75);
      --glow-warm: rgba(237, 170, 92, 0.28);
      --glow-cool: rgba(95, 149, 186, 0.18);
      --shadow: 0 18px 50px rgba(89, 57, 28, 0.12);
      --radius: 24px;
      --radius-sm: 16px;
      --font-sans: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      --font-display: "ZCOOL XiaoWei", "STKaiti", "KaiTi", serif;
      --grid-color: rgba(107, 79, 52, 0.075);
      --grid-accent: rgba(184, 92, 56, 0.13);
      --aurora-a: rgba(255, 190, 122, 0.34);
      --aurora-b: rgba(94, 154, 196, 0.20);
      --aurora-c: rgba(184, 92, 56, 0.16);
      --sparkle: rgba(255, 255, 255, 0.62);
    }}

    html[data-theme="night"] {{
      color-scheme: dark;
      --bg: #0f1724;
      --page-bg:
        radial-gradient(circle at top left, rgba(70, 96, 130, 0.34), transparent 32%),
        radial-gradient(circle at 82% 8%, rgba(184, 92, 56, 0.16), transparent 28%),
        linear-gradient(180deg, #101827 0%, #0d1420 46%, #090f19 100%);
      --panel: rgba(20, 29, 44, 0.84);
      --panel-strong: rgba(19, 27, 40, 0.96);
      --panel-soft: rgba(30, 41, 59, 0.66);
      --line: rgba(226, 232, 240, 0.13);
      --glass-line: rgba(226, 232, 240, 0.14);
      --text: #e8edf5;
      --muted: #a6b2c2;
      --accent: #d88457;
      --accent-deep: #ffb27a;
      --accent-soft: rgba(216, 132, 87, 0.16);
      --table-alt: rgba(255, 255, 255, 0.035);
      --input-bg: rgba(12, 18, 29, 0.72);
      --button-bg: rgba(30, 41, 59, 0.74);
      --glow-warm: rgba(216, 132, 87, 0.15);
      --glow-cool: rgba(91, 141, 204, 0.16);
      --shadow: 0 18px 60px rgba(0, 0, 0, 0.34);
      --grid-color: rgba(148, 163, 184, 0.085);
      --grid-accent: rgba(216, 132, 87, 0.16);
      --aurora-a: rgba(63, 127, 255, 0.19);
      --aurora-b: rgba(216, 132, 87, 0.17);
      --aurora-c: rgba(93, 234, 218, 0.10);
      --sparkle: rgba(226, 232, 240, 0.36);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: var(--font-sans);
      background: var(--page-bg);
    }}

    body::before,
    body::after {{
      content: "";
      position: fixed;
      inset: auto;
      width: 28rem;
      height: 28rem;
      border-radius: 999px;
      filter: blur(24px);
      pointer-events: none;
      z-index: 0;
      opacity: 0.4;
    }}

    body::before {{
      top: -10rem;
      right: -10rem;
      background: var(--glow-warm);
    }}

    body::after {{
      bottom: -12rem;
      left: -12rem;
      background: var(--glow-cool);
    }}

    .animated-backdrop {{
      position: fixed;
      inset: 0;
      overflow: hidden;
      pointer-events: none;
      z-index: 0;
    }}

    .animated-backdrop .grid {{
      position: absolute;
      inset: -20%;
      background-image:
        linear-gradient(var(--grid-color) 1px, transparent 1px),
        linear-gradient(90deg, var(--grid-color) 1px, transparent 1px),
        radial-gradient(circle at 50% 50%, var(--grid-accent), transparent 34%);
      background-size: 46px 46px, 46px 46px, 780px 780px;
      mask-image: radial-gradient(ellipse at 50% 18%, rgba(0,0,0,0.86), transparent 72%);
      opacity: 0.62;
      transform: perspective(900px) rotateX(62deg) translateY(-20%);
      transform-origin: top center;
      animation: grid-drift 34s linear infinite;
    }}

    .animated-backdrop .aurora {{
      position: absolute;
      inset: -18% -10% auto -10%;
      height: 58%;
      background:
        radial-gradient(ellipse at 20% 35%, var(--aurora-a), transparent 45%),
        radial-gradient(ellipse at 66% 22%, var(--aurora-b), transparent 42%),
        radial-gradient(ellipse at 86% 58%, var(--aurora-c), transparent 40%);
      filter: blur(34px) saturate(1.08);
      opacity: 0.9;
      animation: aurora-flow 18s ease-in-out infinite alternate;
    }}

    .animated-backdrop .orb {{
      position: absolute;
      width: 18rem;
      height: 18rem;
      border-radius: 999px;
      background: radial-gradient(circle, var(--aurora-a), transparent 68%);
      filter: blur(18px);
      opacity: 0.38;
      animation: orb-float 16s ease-in-out infinite alternate;
    }}

    .animated-backdrop .orb.one {{
      top: 16%;
      left: 6%;
    }}

    .animated-backdrop .orb.two {{
      right: 7%;
      bottom: 12%;
      width: 22rem;
      height: 22rem;
      background: radial-gradient(circle, var(--aurora-b), transparent 68%);
      animation-duration: 20s;
      animation-delay: -5s;
    }}

    .animated-backdrop .spark {{
      position: absolute;
      inset: 0;
      background-image:
        radial-gradient(circle, var(--sparkle) 0 1px, transparent 1.6px),
        radial-gradient(circle, var(--sparkle) 0 1px, transparent 1.4px);
      background-size: 92px 92px, 137px 137px;
      background-position: 18px 22px, 70px 54px;
      opacity: 0.22;
      animation: sparkle-drift 26s linear infinite;
    }}

    .hero-card,
    .summary-card,
    .control-panel,
    .table-panel,
    .chart-card,
    .stat,
    .axis-card,
    .radar-panel,
    .mvp-panel,
    .league-panel {{
      position: relative;
    }}

    .hero-card::before,
    .summary-card::before,
    .control-panel::before,
    .table-panel::before {{
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
      pointer-events: none;
      background: linear-gradient(135deg, rgba(255,255,255,0.28), transparent 32%, rgba(255,255,255,0.08));
      opacity: 0.7;
    }}

    html[data-theme="night"] .hero-card::before,
    html[data-theme="night"] .summary-card::before,
    html[data-theme="night"] .control-panel::before,
    html[data-theme="night"] .table-panel::before {{
      background: linear-gradient(135deg, rgba(255,255,255,0.10), transparent 36%, rgba(216,132,87,0.07));
      opacity: 0.86;
    }}

    .hero-card > *,
    .summary-card > *,
    .control-panel > *,
    .table-panel > * {{
      position: relative;
      z-index: 1;
    }}

    .stat,
    .chart-card,
    .axis-card,
    .type-tab,
    .theme-toggle {{
      will-change: transform;
    }}

    .stat:hover,
    .chart-card:hover,
    .axis-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 14px 34px rgba(0,0,0,0.10);
    }}

    html[data-theme="night"] .stat:hover,
    html[data-theme="night"] .chart-card:hover,
    html[data-theme="night"] .axis-card:hover {{
      box-shadow: 0 16px 38px rgba(0,0,0,0.28), 0 0 0 1px rgba(216,132,87,0.08);
    }}

    @keyframes grid-drift {{
      from {{ background-position: 0 0, 0 0, 0 0; }}
      to {{ background-position: 46px 46px, 46px 46px, 220px 120px; }}
    }}

    @keyframes aurora-flow {{
      from {{ transform: translate3d(-2%, -1%, 0) scale(1); }}
      to {{ transform: translate3d(3%, 4%, 0) scale(1.06); }}
    }}

    @keyframes orb-float {{
      from {{ transform: translate3d(0, 0, 0) scale(1); }}
      to {{ transform: translate3d(42px, -34px, 0) scale(1.12); }}
    }}

    @keyframes sparkle-drift {{
      from {{ transform: translate3d(0, 0, 0); }}
      to {{ transform: translate3d(-92px, 92px, 0); }}
    }}

    @media (prefers-reduced-motion: reduce) {{
      .animated-backdrop .grid,
      .animated-backdrop .aurora,
      .animated-backdrop .orb,
      .animated-backdrop .spark {{
        animation: none;
      }}

      .stat:hover,
      .chart-card:hover,
      .axis-card:hover,
      .type-tab:hover,
      .theme-toggle:hover {{
        transform: none;
      }}
    }}

    .page {{
      position: relative;
      z-index: 1;
      max-width: 1720px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }}

    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.7fr);
      gap: 20px;
      align-items: stretch;
      margin-bottom: 22px;
    }}

    .hero-card,
    .summary-card,
    .control-panel,
    .table-panel {{
      background: var(--panel);
      border: 1px solid var(--glass-line);
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
      border-radius: var(--radius);
    }}

    .hero-toolbar {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }}

    .theme-toggle {{
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--button-bg);
      color: var(--text);
      padding: 8px 13px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      box-shadow: 0 8px 22px rgba(0,0,0,0.08);
      transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease;
    }}

    .theme-toggle:hover {{
      transform: translateY(-1px);
      border-color: var(--accent);
    }}

    .hero-card {{
      padding: 28px 30px;
      overflow: hidden;
      position: relative;
    }}

    .hero-card::after {{
      content: "";
      position: absolute;
      inset: auto -4rem -5rem auto;
      width: 18rem;
      height: 18rem;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(184, 92, 56, 0.24), transparent 70%);
    }}

    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.54);
      color: var(--accent-deep);
      font-size: 13px;
      letter-spacing: 0.08em;
    }}

    h1 {{
      margin: 18px 0 10px;
      font-family: var(--font-display);
      font-size: clamp(34px, 6vw, 54px);
      line-height: 1.08;
      font-weight: 400;
    }}

    .hero p {{
      margin: 0;
      max-width: 44rem;
      color: var(--muted);
      line-height: 1.75;
      font-size: 15px;
    }}

    .summary-card {{
      padding: 22px;
      display: grid;
      gap: 14px;
      align-content: start;
    }}

    .summary-title {{
      font-size: 14px;
      color: var(--muted);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}

    .stat {{
      padding: 16px;
      border-radius: var(--radius-sm);
      background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(255,245,235,0.74));
      border: 1px solid var(--line);
      transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
    }}

    .stat-label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }}

    .stat-value {{
      font-size: 28px;
      font-weight: 700;
      letter-spacing: -0.03em;
    }}

    .main-grid {{
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      gap: 20px;
    }}

    .control-panel {{
      padding: 22px;
      height: fit-content;
      position: sticky;
      top: 20px;
    }}

    .panel-title {{
      margin: 0 0 16px;
      font-size: 18px;
    }}

    .field {{
      margin-bottom: 14px;
    }}

    .field label {{
      display: block;
      margin-bottom: 8px;
      font-size: 13px;
      color: var(--muted);
    }}

    .field input,
    .field select {{
      width: 100%;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 14px;
      font-size: 14px;
      background: var(--input-bg);
      color: var(--text);
      outline: none;
      transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
    }}

    .field input:focus,
    .field select:focus {{
      border-color: rgba(184, 92, 56, 0.45);
      box-shadow: 0 0 0 4px rgba(184, 92, 56, 0.1);
      transform: translateY(-1px);
    }}

    .zone-checklist {{
      display: grid;
      gap: 8px;
      max-height: 260px;
      overflow: auto;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--panel-soft);
    }}

    .zone-option {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
      padding: 8px 10px;
      border-radius: 10px;
      color: var(--muted);
      cursor: pointer;
      transition: background 0.18s ease, color 0.18s ease;
    }}

    .zone-option:hover,
    .zone-option.active {{
      background: var(--accent-soft);
      color: var(--accent-deep);
    }}

    .zone-option input {{
      width: 16px;
      height: 16px;
      flex: 0 0 auto;
      accent-color: var(--accent);
    }}

    .zone-option span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 13px;
    }}

    .type-tabs {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 10px 0 18px;
    }}

    .type-tab {{
      border: 0;
      cursor: pointer;
      padding: 10px 14px;
      border-radius: 999px;
      background: var(--button-bg);
      color: var(--muted);
      font-size: 13px;
      transition: transform 0.18s ease, background 0.18s ease, color 0.18s ease, box-shadow 0.18s ease;
    }}

    .type-tab:hover {{
      transform: translateY(-1px);
    }}

    .type-tab.active {{
      background: linear-gradient(135deg, var(--accent), #cd7b52);
      color: #fff;
      box-shadow: 0 12px 24px rgba(184, 92, 56, 0.24);
    }}

    .table-panel {{
      padding: 20px;
      overflow: hidden;
    }}

    .table-topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 16px;
    }}

    .table-topbar h2 {{
      margin: 0;
      font-size: 24px;
      font-family: var(--font-display);
      font-weight: 400;
    }}

    .table-meta {{
      color: var(--muted);
      font-size: 14px;
    }}

    .chart-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 12px;
      margin-bottom: 18px;
    }}

    .chart-card {{
      padding: 18px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.9), rgba(252,245,236,0.78));
      border: 1px solid var(--line);
      transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
    }}

    .chart-card h3 {{
      margin: 0 0 6px;
      font-size: 18px;
      color: var(--text);
      font-weight: 600;
    }}

    .chart-subtitle {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
    }}

    .bar-list {{
      display: grid;
      gap: 12px;
    }}

    .bar-item {{
      display: grid;
      grid-template-columns: 56px minmax(180px, 260px) minmax(280px, 1fr) 96px;
      gap: 12px;
      align-items: center;
    }}

    .bar-rank {{
      color: var(--accent-deep);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}

    .bar-team {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--text);
      font-size: 13px;
    }}

    .bar-team small {{
      display: block;
      margin-top: 2px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.3;
    }}

    .bar-value {{
      text-align: right;
      color: var(--accent-deep);
      font-variant-numeric: tabular-nums;
      font-size: 13px;
    }}

    .bar-track {{
      overflow: hidden;
      height: 14px;
      border-radius: 999px;
      background: rgba(184, 92, 56, 0.12);
    }}

    .bar-fill {{
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, #d88457, #b85c38);
      transform-origin: left center;
      animation: grow 0.7s ease;
    }}

    .strength-table-wrap {{
      overflow: auto;
      max-height: 560px;
      border: 1px solid rgba(107, 79, 52, 0.1);
      border-radius: 14px;
      background: rgba(255,255,255,0.54);
    }}

    .strength-table {{
      width: 100%;
      min-width: 900px;
      border-collapse: collapse;
      font-size: 13px;
    }}

    .strength-table th,
    .strength-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid rgba(107, 79, 52, 0.1);
      text-align: right;
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }}

    .strength-table th {{
      position: sticky;
      top: 0;
      z-index: 1;
      background: rgba(255, 250, 242, 0.96);
      color: var(--muted);
      font-weight: 700;
    }}

    .strength-table th:first-child,
    .strength-table th:nth-child(2),
    .strength-table td:first-child,
    .strength-table td:nth-child(2) {{
      text-align: left;
    }}

    .strength-table td:first-child {{
      color: var(--accent-deep);
      font-weight: 700;
    }}

    .strength-table td:nth-child(2) {{
      max-width: 260px;
      overflow: hidden;
      text-overflow: ellipsis;
      color: var(--text);
    }}

    .strength-table .total-cell {{
      color: var(--accent-deep);
      font-weight: 800;
    }}

    @keyframes grow {{
      from {{ transform: scaleX(0.1); opacity: 0.4; }}
      to {{ transform: scaleX(1); opacity: 1; }}
    }}

    .table-wrap {{
      overflow: auto;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.62);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1320px;
    }}

    thead th {{
      position: sticky;
      top: 0;
      z-index: 2;
      background: rgba(250, 241, 231, 0.96);
      backdrop-filter: blur(10px);
      color: var(--accent-deep);
      text-align: left;
      font-size: 13px;
      letter-spacing: 0.04em;
      cursor: pointer;
    }}

    th, td {{
      padding: 14px 14px;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
      font-size: 14px;
    }}

    tbody tr {{
      transition: background 0.18s ease, transform 0.18s ease;
    }}

    tbody tr:nth-child(2n) {{
      background: var(--table-alt);
    }}

    tbody tr:hover {{
      background: var(--accent-soft);
    }}

    .metric-cell {{
      font-variant-numeric: tabular-nums;
    }}

    .muted {{
      color: var(--muted);
    }}

    .empty {{
      padding: 24px;
      text-align: center;
      color: var(--muted);
    }}

    .team-row {{
      cursor: pointer;
    }}

    .team-row:hover {{
      transform: translateY(-1px);
    }}

    .radar-card {{
      padding: 0;
      overflow: hidden;
    }}

    .radar-header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      padding: 24px 26px 12px;
      align-items: flex-start;
    }}

    .radar-header h3 {{
      margin: 10px 0 8px;
      font-family: var(--font-display);
      font-size: clamp(28px, 4vw, 40px);
      font-weight: 400;
      line-height: 1.1;
    }}

    .radar-header p {{
      margin: 0;
      max-width: 42rem;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.7;
    }}

    .radar-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(280px, 0.85fr);
      gap: 18px;
      padding: 0 26px 26px;
    }}

    .radar-stage,
    .radar-side {{
      border-radius: 22px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.74);
    }}

    .radar-stage {{
      padding: 18px 18px 12px;
    }}

    .radar-side {{
      padding: 18px;
      display: grid;
      gap: 12px;
      align-content: start;
    }}

    .radar-legend {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}

    .legend-chip {{
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(184, 92, 56, 0.1);
      color: var(--accent-deep);
      font-size: 12px;
    }}

    .radar-svg {{
      width: 100%;
      height: auto;
      display: block;
    }}

    .radar-note {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
    }}

    .insight-card {{
      display: grid;
      gap: 16px;
    }}

    .insight-header {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: flex-start;
    }}

    .insight-header h3 {{
      margin: 8px 0 6px;
      font-family: var(--font-display);
      font-size: clamp(24px, 3vw, 34px);
      font-weight: 400;
    }}

    .insight-summary {{
      margin: 0;
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }}

    .insight-score {{
      min-width: 104px;
      text-align: right;
      color: var(--accent-deep);
      font-variant-numeric: tabular-nums;
    }}

    .insight-score strong {{
      display: block;
      font-size: 30px;
      line-height: 1;
    }}

    .insight-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }}

    .insight-section {{
      min-width: 0;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}

    .insight-section h4 {{
      margin: 0 0 10px;
      font-size: 14px;
      color: var(--text);
    }}

    .insight-list {{
      display: grid;
      gap: 8px;
    }}

    .insight-chip {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      min-width: 0;
      padding: 8px 10px;
      border-radius: 12px;
      background: var(--panel-soft);
      border: 1px solid rgba(107, 79, 52, 0.1);
      font-size: 13px;
    }}

    .insight-chip span:first-child {{
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--text);
    }}

    .insight-chip span:last-child {{
      color: var(--accent-deep);
      font-variant-numeric: tabular-nums;
      flex: 0 0 auto;
    }}

    .insight-chip-block {{
      display: grid;
      align-items: start;
      gap: 4px;
    }}

    .insight-chip-block span:first-child {{
      white-space: normal;
    }}

    .insight-chip-block small {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }}

    .insight-note {{
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.65;
    }}

    .axis-list {{
      display: grid;
      gap: 10px;
    }}

    .axis-card {{
      padding: 14px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(250, 242, 233, 0.9));
      border: 1px solid rgba(107, 79, 52, 0.1);
      transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
    }}

    .axis-top {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
      align-items: baseline;
    }}

    .axis-name {{
      font-size: 15px;
      font-weight: 700;
    }}

    .axis-ratio {{
      color: var(--accent-deep);
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }}

    .axis-meta {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.7;
    }}

    html[data-theme="night"] .hero-card::after {{
      background: radial-gradient(circle, rgba(216, 132, 87, 0.15), transparent 70%);
    }}

    html[data-theme="night"] .summary-grid,
    html[data-theme="night"] .zone-checklist,
    html[data-theme="night"] .table-wrap,
    html[data-theme="night"] .radar-panel,
    html[data-theme="night"] .mvp-panel,
    html[data-theme="night"] .league-panel {{
      border-color: var(--line);
      background: rgba(15, 23, 36, 0.42);
    }}

    html[data-theme="night"] input,
    html[data-theme="night"] select {{
      border-color: var(--line);
      background: var(--input-bg);
      color: var(--text);
    }}

    html[data-theme="night"] input::placeholder {{
      color: rgba(226, 232, 240, 0.52);
    }}

    html[data-theme="night"] th {{
      background: rgba(15, 23, 36, 0.96);
      color: var(--accent-deep);
    }}

    html[data-theme="night"] td {{
      border-color: var(--line);
    }}

    html[data-theme="night"] tbody tr:hover {{
      background: var(--accent-soft);
    }}

    html[data-theme="night"] .empty {{
      background: rgba(15, 23, 36, 0.84);
    }}

    html[data-theme="night"] .eyebrow {{
      background: rgba(30, 41, 59, 0.68);
      border: 1px solid var(--line);
      color: var(--accent-deep);
    }}

    html[data-theme="night"] .stat,
    html[data-theme="night"] .chart-card,
    html[data-theme="night"] .axis-card {{
      background: linear-gradient(180deg, rgba(24, 34, 50, 0.94), rgba(15, 23, 36, 0.90));
      border-color: var(--line);
    }}

    html[data-theme="night"] .strength-table-wrap,
    html[data-theme="night"] .table-wrap,
    html[data-theme="night"] .radar-stage,
    html[data-theme="night"] .radar-side {{
      background: rgba(12, 18, 29, 0.68);
      border-color: var(--line);
    }}

    html[data-theme="night"] .strength-table th {{
      background: rgba(15, 23, 36, 0.98);
      color: var(--muted);
    }}

    html[data-theme="night"] .strength-table th,
    html[data-theme="night"] .strength-table td,
    html[data-theme="night"] .insight-chip {{
      border-color: var(--line);
    }}

    html[data-theme="night"] .insight-chip {{
      background: rgba(20, 29, 44, 0.72);
    }}

    html[data-theme="night"] .bar-track,
    html[data-theme="night"] .legend-chip {{
      background: rgba(216, 132, 87, 0.14);
    }}

    html[data-theme="night"] select option {{
      background: #111827;
      color: var(--text);
    }}

    @media (max-width: 1100px) {{
      .hero,
      .main-grid {{
        grid-template-columns: 1fr;
      }}

      .control-panel {{
        position: static;
      }}

      .radar-layout {{
        grid-template-columns: 1fr;
      }}

      .insight-grid {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}
    }}

    @media (max-width: 720px) {{
      .insight-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 640px) {{
      .page {{
        padding: 18px 12px 28px;
      }}

      .hero-card,
      .summary-card,
      .control-panel,
      .table-panel {{
        border-radius: 22px;
      }}

      .summary-grid {{
        grid-template-columns: 1fr 1fr;
      }}

      .table-topbar {{
        align-items: flex-start;
        flex-direction: column;
      }}

      .bar-item {{
        grid-template-columns: 50px minmax(0, 1fr);
      }}

      .bar-track {{
        grid-column: 1 / -1;
      }}

      .bar-value {{
        text-align: left;
      }}

      .radar-header,
      .radar-layout {{
        padding-left: 16px;
        padding-right: 16px;
      }}

      .radar-header {{
        flex-direction: column;
      }}
    }}


    /* ========== Mecha Cockpit Skin v3 ========== */
    :root {{
      --bg: #e8ecef;
      --page-bg:
        radial-gradient(circle at 12% 10%, rgba(24, 102, 154, 0.18), transparent 28%),
        radial-gradient(circle at 86% 0%, rgba(225, 72, 40, 0.15), transparent 32%),
        linear-gradient(135deg, #f6f8fb 0%, #dfe6ec 42%, #f3f5f7 100%);
      --panel: rgba(244, 248, 251, 0.82);
      --panel-strong: rgba(255, 255, 255, 0.94);
      --panel-soft: rgba(235, 242, 247, 0.72);
      --line: rgba(26, 43, 58, 0.14);
      --glass-line: rgba(255, 255, 255, 0.66);
      --text: #17212b;
      --muted: #5f7080;
      --accent: #e6532e;
      --accent-deep: #b83318;
      --accent-soft: rgba(230, 83, 46, 0.12);
      --hud-cyan: #087ea4;
      --hud-cyan-soft: rgba(8, 126, 164, 0.12);
      --hud-green: #0b8a73;
      --hud-warn: #e6a700;
      --table-alt: rgba(8, 126, 164, 0.045);
      --input-bg: rgba(255,255,255,0.82);
      --button-bg: rgba(245,250,253,0.82);
      --shadow: 0 22px 60px rgba(15, 28, 40, 0.14);
      --grid-color: rgba(8, 126, 164, 0.08);
      --grid-accent: rgba(230, 83, 46, 0.14);
      --aurora-a: rgba(8, 126, 164, 0.20);
      --aurora-b: rgba(230, 83, 46, 0.17);
      --aurora-c: rgba(11, 138, 115, 0.12);
      --sparkle: rgba(8, 126, 164, 0.48);
      --armor-edge: rgba(23, 33, 43, 0.17);
      --scanline: rgba(8, 126, 164, 0.22);
    }}

    html[data-theme="night"] {{
      --bg: #04070d;
      --page-bg:
        radial-gradient(circle at 12% 8%, rgba(0, 180, 255, 0.18), transparent 30%),
        radial-gradient(circle at 82% 2%, rgba(255, 73, 35, 0.16), transparent 34%),
        linear-gradient(135deg, #05070c 0%, #09111f 42%, #02040a 100%);
      --panel: rgba(9, 18, 31, 0.76);
      --panel-strong: rgba(10, 19, 34, 0.94);
      --panel-soft: rgba(10, 25, 43, 0.70);
      --line: rgba(107, 211, 255, 0.16);
      --glass-line: rgba(117, 211, 255, 0.18);
      --text: #eaf7ff;
      --muted: #8ea4b7;
      --accent: #ff5c32;
      --accent-deep: #ff9b5f;
      --accent-soft: rgba(255, 92, 50, 0.14);
      --hud-cyan: #37d8ff;
      --hud-cyan-soft: rgba(55, 216, 255, 0.12);
      --hud-green: #33f5b4;
      --hud-warn: #ffd166;
      --table-alt: rgba(55, 216, 255, 0.035);
      --input-bg: rgba(4, 12, 22, 0.76);
      --button-bg: rgba(8, 21, 37, 0.82);
      --shadow: 0 24px 70px rgba(0, 0, 0, 0.46);
      --grid-color: rgba(55, 216, 255, 0.10);
      --grid-accent: rgba(255, 92, 50, 0.18);
      --aurora-a: rgba(55, 216, 255, 0.17);
      --aurora-b: rgba(255, 92, 50, 0.16);
      --aurora-c: rgba(51, 245, 180, 0.10);
      --sparkle: rgba(127, 225, 255, 0.46);
      --armor-edge: rgba(117, 211, 255, 0.16);
      --scanline: rgba(55, 216, 255, 0.25);
    }}

    body {{
      background: var(--page-bg);
      overflow-x: hidden;
    }}

    body::before {{
      width: 34rem;
      height: 34rem;
      background: radial-gradient(circle, var(--aurora-b), transparent 68%);
      filter: blur(35px);
    }}

    body::after {{
      width: 32rem;
      height: 32rem;
      background: radial-gradient(circle, var(--aurora-a), transparent 70%);
      filter: blur(34px);
    }}

    .animated-backdrop {{
      background:
        linear-gradient(115deg, transparent 0 16%, rgba(255,255,255,0.025) 16.1% 16.8%, transparent 16.9% 100%),
        linear-gradient(245deg, transparent 0 72%, rgba(255,255,255,0.028) 72.2% 73%, transparent 73.2% 100%);
    }}

    html[data-theme="night"] .animated-backdrop {{
      background:
        linear-gradient(115deg, transparent 0 16%, rgba(55,216,255,0.04) 16.1% 16.8%, transparent 16.9% 100%),
        linear-gradient(245deg, transparent 0 72%, rgba(255,92,50,0.04) 72.2% 73%, transparent 73.2% 100%);
    }}

    .animated-backdrop .grid {{
      inset: -28%;
      opacity: 0.76;
      background-image:
        linear-gradient(var(--grid-color) 1px, transparent 1px),
        linear-gradient(90deg, var(--grid-color) 1px, transparent 1px),
        linear-gradient(30deg, transparent 0 48%, var(--grid-accent) 49%, transparent 50%),
        radial-gradient(circle at 50% 50%, var(--grid-accent), transparent 34%);
      background-size: 42px 42px, 42px 42px, 128px 128px, 820px 820px;
      mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,.72) 18%, rgba(0,0,0,.92) 52%, transparent 100%);
      transform: perspective(950px) rotateX(66deg) translateY(-24%);
      animation: grid-drift 24s linear infinite;
    }}

    .animated-backdrop .hex-field {{
      position: absolute;
      inset: 0;
      opacity: 0.25;
      background-image:
        linear-gradient(30deg, var(--grid-color) 12%, transparent 12.5%, transparent 87%, var(--grid-color) 87.5%, var(--grid-color)),
        linear-gradient(150deg, var(--grid-color) 12%, transparent 12.5%, transparent 87%, var(--grid-color) 87.5%, var(--grid-color)),
        linear-gradient(30deg, var(--grid-color) 12%, transparent 12.5%, transparent 87%, var(--grid-color) 87.5%, var(--grid-color)),
        linear-gradient(150deg, var(--grid-color) 12%, transparent 12.5%, transparent 87%, var(--grid-color) 87.5%, var(--grid-color));
      background-size: 72px 126px;
      background-position: 0 0, 0 0, 36px 63px, 36px 63px;
      animation: hex-slide 36s linear infinite;
    }}

    .animated-backdrop .mech-blueprint {{
      position: absolute;
      right: clamp(16px, 5vw, 90px);
      top: 96px;
      width: min(34vw, 520px);
      aspect-ratio: 1 / 1.25;
      opacity: 0.20;
      filter: drop-shadow(0 0 18px var(--hud-cyan-soft));
      background:
        linear-gradient(90deg, transparent 38%, var(--hud-cyan) 38% 39.2%, transparent 39.2% 60.8%, var(--hud-cyan) 60.8% 62%, transparent 62%),
        linear-gradient(0deg, transparent 14%, var(--hud-cyan) 14% 15.2%, transparent 15.2% 30%, var(--hud-cyan) 30% 31%, transparent 31% 66%, var(--hud-cyan) 66% 67.2%, transparent 67.2%),
        radial-gradient(circle at 50% 14%, transparent 0 10%, var(--hud-cyan) 10.2% 11.4%, transparent 11.8%),
        linear-gradient(135deg, transparent 0 18%, var(--hud-cyan-soft) 18% 23%, transparent 23% 78%, var(--hud-cyan-soft) 78% 83%, transparent 83%);
      clip-path: polygon(50% 2%, 68% 18%, 63% 36%, 82% 45%, 74% 75%, 60% 70%, 57% 98%, 43% 98%, 40% 70%, 26% 75%, 18% 45%, 37% 36%, 32% 18%);
      border: 1px solid var(--hud-cyan);
      animation: blueprint-pulse 4s ease-in-out infinite alternate;
    }}

    .animated-backdrop .reticle {{
      position: absolute;
      left: clamp(14px, 6vw, 120px);
      top: 34%;
      width: 168px;
      height: 168px;
      border-radius: 50%;
      border: 1px solid var(--hud-cyan);
      opacity: 0.22;
      box-shadow: 0 0 0 24px rgba(55,216,255,0.02), inset 0 0 26px var(--hud-cyan-soft);
      animation: reticle-lock 5.5s ease-in-out infinite;
    }}

    .animated-backdrop .reticle::before,
    .animated-backdrop .reticle::after {{
      content: "";
      position: absolute;
      background: var(--hud-cyan);
      opacity: 0.75;
    }}

    .animated-backdrop .reticle::before {{
      left: 50%;
      top: -28px;
      width: 1px;
      height: 224px;
    }}

    .animated-backdrop .reticle::after {{
      left: -28px;
      top: 50%;
      width: 224px;
      height: 1px;
    }}

    .animated-backdrop .scanline {{
      position: absolute;
      inset: -20% 0 auto 0;
      height: 160px;
      background: linear-gradient(to bottom, transparent, var(--scanline), transparent);
      opacity: 0.26;
      transform: translateY(-20vh);
      animation: scan-pass 7.5s linear infinite;
    }}

    .animated-backdrop .warning-stripes {{
      position: absolute;
      left: -80px;
      bottom: 9%;
      width: 420px;
      height: 28px;
      opacity: 0.18;
      transform: rotate(-22deg);
      background: repeating-linear-gradient(90deg, var(--accent) 0 18px, transparent 18px 34px);
      filter: blur(0.2px);
    }}

    .hud-frame {{
      position: fixed;
      inset: 14px;
      z-index: 2;
      pointer-events: none;
      opacity: 0.55;
      background:
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) left top / 104px 1px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) left top / 1px 104px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) right top / 104px 1px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) right top / 1px 104px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) left bottom / 104px 1px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) left bottom / 1px 104px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) right bottom / 104px 1px no-repeat,
        linear-gradient(var(--hud-cyan), var(--hud-cyan)) right bottom / 1px 104px no-repeat;
      mix-blend-mode: multiply;
    }}

    html[data-theme="night"] .hud-frame {{
      mix-blend-mode: screen;
      opacity: 0.62;
    }}

    .page {{
      max-width: 1760px;
      padding-top: 24px;
    }}

    .cockpit-rail {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 0 0 14px;
      color: var(--hud-cyan);
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }}

    .cockpit-rail span {{
      min-width: 0;
      padding: 8px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: linear-gradient(90deg, var(--hud-cyan-soft), transparent);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .hero-card,
    .summary-card,
    .control-panel,
    .table-panel,
    .chart-card {{
      border: 1px solid var(--glass-line);
      background:
        linear-gradient(135deg, rgba(255,255,255,0.18), transparent 28%),
        linear-gradient(180deg, var(--panel), var(--panel-strong));
      box-shadow: var(--shadow), inset 0 0 0 1px rgba(255,255,255,0.06);
      clip-path: polygon(0 16px, 16px 0, 100% 0, 100% calc(100% - 16px), calc(100% - 16px) 100%, 0 100%);
    }}

    .hero-card::before,
    .summary-card::before,
    .control-panel::before,
    .table-panel::before,
    .chart-card::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      border-radius: inherit;
      background:
        linear-gradient(90deg, var(--hud-cyan) 0 54px, transparent 54px calc(100% - 72px), var(--accent) calc(100% - 72px) 100%) top / 100% 2px no-repeat,
        linear-gradient(90deg, var(--accent) 0 36px, transparent 36px calc(100% - 42px), var(--hud-cyan) calc(100% - 42px) 100%) bottom / 100% 2px no-repeat;
      opacity: 0.36;
    }}

    .hero-card > *,
    .summary-card > *,
    .control-panel > *,
    .table-panel > *,
    .chart-card > * {{
      position: relative;
      z-index: 1;
    }}

    .hero-toolbar {{
      margin-bottom: 14px;
    }}

    .toolbar-actions {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}

    .eyebrow {{
      border: 1px solid var(--line);
      background:
        linear-gradient(90deg, var(--accent-soft), var(--hud-cyan-soft));
      color: var(--accent-deep);
      font-weight: 900;
      letter-spacing: 0.13em;
      box-shadow: inset 0 0 18px rgba(255,255,255,0.08);
    }}

    h1 {{
      font-family: "Arial Black", "Noto Sans SC", "Microsoft YaHei", sans-serif;
      font-weight: 900;
      letter-spacing: -0.06em;
      text-transform: uppercase;
      text-shadow: 0 0 28px rgba(55,216,255,0.14);
    }}

    .combat-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 20px;
    }}

    .combat-strip span {{
      padding: 9px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: linear-gradient(90deg, var(--panel-soft), transparent);
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
    }}

    .combat-strip b {{
      color: var(--hud-cyan);
    }}

    .theme-toggle {{
      border-color: var(--line);
      background:
        linear-gradient(135deg, var(--button-bg), var(--hud-cyan-soft));
      color: var(--text);
      font-weight: 900;
      letter-spacing: 0.04em;
      box-shadow: 0 10px 28px rgba(0,0,0,0.12), inset 0 0 0 1px rgba(255,255,255,0.08);
    }}

    .theme-toggle:hover {{
      border-color: var(--hud-cyan);
      box-shadow: 0 0 0 1px var(--hud-cyan-soft), 0 12px 30px rgba(0,0,0,0.16);
    }}

    .summary-card {{
      background:
        linear-gradient(135deg, rgba(230,83,46,0.08), transparent 34%),
        linear-gradient(180deg, var(--panel), var(--panel-strong));
    }}

    .summary-title,
    .panel-title,
    .table-topbar h2,
    .chart-card h3,
    .radar-header h3,
    .insight-header h3 {{
      font-family: "Arial Black", "Noto Sans SC", "Microsoft YaHei", sans-serif;
      letter-spacing: -0.03em;
    }}

    .stat {{
      background:
        linear-gradient(135deg, var(--hud-cyan-soft), transparent 52%),
        linear-gradient(180deg, rgba(255,255,255,0.72), rgba(233,241,247,0.62));
      border-color: var(--line);
      clip-path: polygon(0 10px, 10px 0, 100% 0, 100% 100%, 0 100%);
    }}

    html[data-theme="night"] .stat {{
      background:
        linear-gradient(135deg, rgba(55,216,255,0.09), transparent 52%),
        linear-gradient(180deg, rgba(10,24,42,0.92), rgba(5,12,23,0.86));
    }}

    .stat-value {{
      color: var(--hud-cyan);
      text-shadow: 0 0 24px var(--hud-cyan-soft);
    }}

    .control-panel {{
      top: 18px;
    }}

    .field input,
    .field select,
    .zone-checklist {{
      border-color: var(--line);
      background: var(--input-bg);
      box-shadow: inset 0 0 18px rgba(0,0,0,0.025);
    }}

    .field input:focus,
    .field select:focus {{
      border-color: var(--hud-cyan);
      box-shadow: 0 0 0 4px var(--hud-cyan-soft), inset 0 0 18px rgba(0,0,0,0.035);
    }}

    .zone-option:hover,
    .zone-option.active {{
      background: linear-gradient(90deg, var(--hud-cyan-soft), var(--accent-soft));
      color: var(--text);
    }}

    .type-tab {{
      border: 1px solid var(--line);
      background: linear-gradient(135deg, var(--button-bg), transparent);
      font-weight: 800;
    }}

    .type-tab.active {{
      background: linear-gradient(135deg, var(--accent), var(--hud-cyan));
      color: #fff;
      box-shadow: 0 0 26px var(--accent-soft);
    }}

    .table-wrap,
    .strength-table-wrap,
    .radar-stage,
    .radar-side {{
      background: rgba(255,255,255,0.58);
      border-color: var(--line);
      box-shadow: inset 0 0 32px rgba(8,126,164,0.035);
    }}

    html[data-theme="night"] .table-wrap,
    html[data-theme="night"] .strength-table-wrap,
    html[data-theme="night"] .radar-stage,
    html[data-theme="night"] .radar-side {{
      background: rgba(4, 12, 22, 0.66);
      box-shadow: inset 0 0 34px rgba(55,216,255,0.04);
    }}

    thead th,
    .strength-table th {{
      background: linear-gradient(180deg, var(--panel-strong), rgba(255,255,255,0.84));
      color: var(--hud-cyan);
      text-transform: uppercase;
      font-weight: 900;
    }}

    html[data-theme="night"] thead th,
    html[data-theme="night"] .strength-table th {{
      background: linear-gradient(180deg, rgba(6,18,32,0.98), rgba(5,12,23,0.92));
      color: var(--hud-cyan);
    }}

    tbody tr {{
      position: relative;
    }}

    tbody tr:hover {{
      background: linear-gradient(90deg, var(--hud-cyan-soft), var(--accent-soft));
      box-shadow: inset 3px 0 0 var(--hud-cyan);
    }}

    .row-rank {{
      color: var(--muted);
      font-weight: 900;
    }}

    .row-rank.rank-top {{
      color: var(--accent-deep);
      text-shadow: 0 0 14px var(--accent-soft);
    }}

    .team-name-cell {{
      font-weight: 800;
    }}

    .type-badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 46px;
      padding: 5px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
      color: var(--text);
      font-size: 12px;
      font-weight: 900;
      letter-spacing: 0.05em;
    }}

    .type-badge[data-type="英雄"] {{ background: rgba(255,92,50,0.14); color: var(--accent-deep); }}
    .type-badge[data-type="步兵"],
    .type-badge[data-type="步兵3"],
    .type-badge[data-type="步兵4"] {{ background: rgba(55,216,255,0.13); color: var(--hud-cyan); }}
    .type-badge[data-type="哨兵"] {{ background: rgba(51,245,180,0.13); color: var(--hud-green); }}
    .type-badge[data-type="无人机"] {{ background: rgba(159,122,234,0.15); color: #8b5cf6; }}
    .type-badge[data-type="雷达"] {{ background: rgba(24,180,255,0.16); color: var(--hud-cyan); }}
    .type-badge[data-type="工程"] {{ background: rgba(255,209,102,0.18); color: #b7791f; }}
    .type-badge[data-type="飞镖"] {{ background: rgba(255,92,50,0.16); color: var(--accent-deep); }}

    .focus-metric {{
      position: relative;
      overflow: hidden;
      color: var(--text);
      font-weight: 900;
    }}

    .focus-metric .metric-value {{
      position: relative;
      z-index: 1;
    }}

    .focus-metric .metric-heat {{
      position: absolute;
      left: 10px;
      bottom: 5px;
      width: var(--heat, 0%);
      max-width: calc(100% - 20px);
      height: 3px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--accent), var(--hud-cyan));
      box-shadow: 0 0 12px var(--hud-cyan-soft);
      opacity: 0.9;
    }}

    .bar-track {{
      height: 16px;
      border: 1px solid var(--line);
      background:
        linear-gradient(90deg, transparent 0 24%, rgba(255,255,255,0.10) 24% 25%, transparent 25% 49%, rgba(255,255,255,0.10) 49% 50%, transparent 50% 74%, rgba(255,255,255,0.10) 74% 75%, transparent 75%),
        var(--hud-cyan-soft);
    }}

    .bar-fill {{
      background: linear-gradient(90deg, var(--accent), var(--hud-cyan));
      box-shadow: 0 0 16px var(--accent-soft);
    }}

    .legend-chip,
    .insight-chip,
    .axis-card {{
      border-color: var(--line);
      background: linear-gradient(135deg, var(--panel-soft), transparent);
    }}

    .radar-svg polygon[fill^="url"] {{
      filter: drop-shadow(0 0 8px var(--hud-cyan-soft));
    }}

    html[data-density="compact"] .page {{
      max-width: 1880px;
    }}

    html[data-density="compact"] .hero {{
      grid-template-columns: minmax(0, 1fr) 420px;
      margin-bottom: 14px;
    }}

    html[data-density="compact"] .hero-card,
    html[data-density="compact"] .summary-card,
    html[data-density="compact"] .control-panel,
    html[data-density="compact"] .table-panel {{
      padding: 16px;
    }}

    html[data-density="compact"] .hero p {{
      line-height: 1.55;
    }}

    html[data-density="compact"] .combat-strip {{
      margin-top: 12px;
    }}

    html[data-density="compact"] th,
    html[data-density="compact"] td {{
      padding: 9px 11px;
      font-size: 13px;
    }}

    html[data-density="compact"] .chart-card {{
      padding: 14px;
    }}

    html[data-density="compact"] .bar-list {{
      gap: 8px;
    }}

    html[data-density="compact"] .field {{
      margin-bottom: 10px;
    }}

    html[data-density="compact"] .zone-checklist {{
      max-height: 210px;
    }}

    @keyframes hex-slide {{
      from {{ transform: translate3d(0,0,0); }}
      to {{ transform: translate3d(-72px,63px,0); }}
    }}

    @keyframes scan-pass {{
      0% {{ transform: translateY(-24vh); opacity: 0; }}
      12% {{ opacity: 0.26; }}
      70% {{ opacity: 0.22; }}
      100% {{ transform: translateY(124vh); opacity: 0; }}
    }}

    @keyframes reticle-lock {{
      0%, 100% {{ transform: scale(0.98) rotate(0deg); opacity: 0.16; }}
      50% {{ transform: scale(1.04) rotate(3deg); opacity: 0.28; }}
    }}

    @keyframes blueprint-pulse {{
      from {{ opacity: 0.13; transform: translateY(0); }}
      to {{ opacity: 0.23; transform: translateY(-8px); }}
    }}



    /* ========== Readability Hotfix v4: lighter mecha background ========== */
    :root {{
      --page-bg:
        radial-gradient(circle at 12% 8%, rgba(35, 118, 170, 0.13), transparent 30%),
        radial-gradient(circle at 86% 0%, rgba(225, 72, 40, 0.10), transparent 34%),
        linear-gradient(135deg, #fafcff 0%, #edf3f7 44%, #f8fafc 100%);
      --panel: rgba(250, 253, 255, 0.90);
      --panel-strong: rgba(255, 255, 255, 0.98);
      --panel-soft: rgba(242, 247, 251, 0.86);
      --text: #111c27;
      --muted: #475968;
      --line: rgba(22, 37, 50, 0.16);
      --glass-line: rgba(255, 255, 255, 0.78);
      --input-bg: rgba(255,255,255,0.92);
      --button-bg: rgba(250,253,255,0.92);
      --grid-color: rgba(8, 126, 164, 0.052);
      --grid-accent: rgba(230, 83, 46, 0.09);
      --shadow: 0 18px 46px rgba(15, 28, 40, 0.10);
    }}

    html[data-theme="night"] {{
      --bg: #151f2d;
      --page-bg:
        radial-gradient(circle at 12% 8%, rgba(64, 156, 214, 0.15), transparent 32%),
        radial-gradient(circle at 84% 2%, rgba(255, 103, 64, 0.11), transparent 34%),
        linear-gradient(135deg, #182332 0%, #142033 46%, #101927 100%);
      --panel: rgba(27, 39, 56, 0.92);
      --panel-strong: rgba(31, 45, 63, 0.98);
      --panel-soft: rgba(38, 53, 73, 0.86);
      --line: rgba(173, 207, 229, 0.18);
      --glass-line: rgba(190, 220, 240, 0.20);
      --text: #f4f8fc;
      --muted: #c5d2df;
      --accent: #ff7650;
      --accent-deep: #ffc19d;
      --accent-soft: rgba(255, 118, 80, 0.13);
      --hud-cyan: #76ddff;
      --hud-cyan-soft: rgba(118, 221, 255, 0.11);
      --hud-green: #78f3c6;
      --hud-warn: #ffe08a;
      --table-alt: rgba(255, 255, 255, 0.045);
      --input-bg: rgba(34, 49, 68, 0.94);
      --button-bg: rgba(40, 57, 78, 0.92);
      --shadow: 0 18px 54px rgba(0, 0, 0, 0.30);
      --grid-color: rgba(118, 221, 255, 0.055);
      --grid-accent: rgba(255, 118, 80, 0.10);
      --aurora-a: rgba(118, 221, 255, 0.11);
      --aurora-b: rgba(255, 118, 80, 0.10);
      --aurora-c: rgba(120, 243, 198, 0.07);
      --sparkle: rgba(210, 235, 250, 0.26);
      --armor-edge: rgba(190, 220, 240, 0.15);
      --scanline: rgba(118, 221, 255, 0.13);
    }}

    body::before,
    body::after {{
      opacity: 0.22;
    }}

    html[data-theme="night"] body::before,
    html[data-theme="night"] body::after {{
      opacity: 0.16;
      filter: blur(44px);
    }}

    .animated-backdrop .grid {{
      opacity: 0.42;
      mask-image: linear-gradient(to bottom, transparent 0%, rgba(0,0,0,.48) 20%, rgba(0,0,0,.58) 55%, transparent 100%);
    }}

    .animated-backdrop .hex-field {{
      opacity: 0.14;
    }}

    .animated-backdrop .mech-blueprint {{
      opacity: 0.12;
    }}

    .animated-backdrop .reticle {{
      opacity: 0.12;
    }}

    .animated-backdrop .scanline {{
      opacity: 0.13;
    }}

    .animated-backdrop .warning-stripes {{
      opacity: 0.11;
    }}

    html[data-theme="night"] .animated-backdrop .grid {{
      opacity: 0.30;
    }}

    html[data-theme="night"] .animated-backdrop .hex-field,
    html[data-theme="night"] .animated-backdrop .reticle,
    html[data-theme="night"] .animated-backdrop .scanline,
    html[data-theme="night"] .animated-backdrop .warning-stripes {{
      opacity: 0.09;
    }}

    html[data-theme="night"] .animated-backdrop .mech-blueprint {{
      opacity: 0.08;
    }}

    .hud-frame {{
      opacity: 0.36;
    }}

    html[data-theme="night"] .hud-frame {{
      opacity: 0.30;
    }}

    .hero-card,
    .summary-card,
    .control-panel,
    .table-panel,
    .chart-card {{
      background:
        linear-gradient(135deg, rgba(255,255,255,0.14), transparent 30%),
        linear-gradient(180deg, var(--panel), var(--panel-strong));
    }}

    html[data-theme="night"] .hero-card,
    html[data-theme="night"] .summary-card,
    html[data-theme="night"] .control-panel,
    html[data-theme="night"] .table-panel,
    html[data-theme="night"] .chart-card {{
      background:
        linear-gradient(135deg, rgba(118,221,255,0.055), transparent 34%),
        linear-gradient(180deg, rgba(33, 48, 68, 0.96), rgba(24, 36, 53, 0.98));
      box-shadow: var(--shadow), inset 0 0 0 1px rgba(255,255,255,0.045);
    }}

    html[data-theme="night"] .summary-card {{
      background:
        linear-gradient(135deg, rgba(255,118,80,0.07), transparent 36%),
        linear-gradient(180deg, rgba(33, 48, 68, 0.96), rgba(24, 36, 53, 0.98));
    }}

    html[data-theme="night"] .stat {{
      background:
        linear-gradient(135deg, rgba(118,221,255,0.065), transparent 52%),
        linear-gradient(180deg, rgba(43, 59, 80, 0.96), rgba(30, 43, 61, 0.98));
    }}

    .table-wrap,
    .strength-table-wrap,
    .radar-stage,
    .radar-side {{
      background: rgba(255,255,255,0.78);
    }}

    html[data-theme="night"] .table-wrap,
    html[data-theme="night"] .strength-table-wrap,
    html[data-theme="night"] .radar-stage,
    html[data-theme="night"] .radar-side {{
      background: rgba(32, 46, 65, 0.90);
      box-shadow: inset 0 0 20px rgba(118,221,255,0.025);
    }}

    html[data-theme="night"] thead th,
    html[data-theme="night"] .strength-table th {{
      background: linear-gradient(180deg, rgba(45, 62, 84, 0.99), rgba(34, 49, 69, 0.98));
      color: #d9f6ff;
    }}

    html[data-theme="night"] td,
    html[data-theme="night"] .strength-table td,
    html[data-theme="night"] .team-name-cell,
    html[data-theme="night"] .focus-metric {{
      color: #f4f8fc;
    }}

    html[data-theme="night"] .row-rank,
    html[data-theme="night"] .combat-strip span,
    html[data-theme="night"] .summary-desc,
    html[data-theme="night"] .hint,
    html[data-theme="night"] .muted {{
      color: #c5d2df;
    }}

    html[data-theme="night"] input,
    html[data-theme="night"] select,
    html[data-theme="night"] .zone-checklist {{
      background: rgba(38, 54, 74, 0.96);
      color: #f4f8fc;
    }}

    h1,
    .stat-value,
    .combat-strip b {{
      text-shadow: none;
    }}

    @media (prefers-reduced-motion: reduce) {{
      .animated-backdrop .hex-field,
      .animated-backdrop .reticle,
      .animated-backdrop .scanline,
      .animated-backdrop .mech-blueprint {{
        animation: none;
      }}
    }}

    @media (max-width: 900px) {{
      .cockpit-rail {{
        grid-template-columns: 1fr 1fr;
      }}
      .animated-backdrop .mech-blueprint {{
        opacity: 0.10;
        width: 70vw;
      }}
    }}

    @media (max-width: 640px) {{
      .cockpit-rail {{ display: none; }}
      .toolbar-actions {{ width: 100%; justify-content: flex-start; }}
      .hud-frame {{ inset: 8px; }}
    }}


    /* ===== 重装机甲皮肤：重点不再是荧光，而是装甲、接缝、铆钉、液压和机库层级 ===== */
    :root {{
      --armor-dark: #2c3138;
      --armor-mid: #4d5560;
      --armor-light: #8b96a3;
      --armor-edge: rgba(42, 48, 56, 0.34);
      --paint-red: #c33b2f;
      --paint-yellow: #e4a92e;
      --bolt: rgba(36, 42, 50, 0.46);
      --steel-scratch: rgba(255, 255, 255, 0.26);
      --visor: rgba(24, 111, 145, 0.16);
      --mecha-shadow: rgba(22, 27, 32, 0.24);
    }}

    html[data-theme="night"] {{
      --armor-dark: #111820;
      --armor-mid: #242d38;
      --armor-light: #607080;
      --armor-edge: rgba(153, 174, 194, 0.24);
      --paint-red: #ff4e3d;
      --paint-yellow: #ffd15c;
      --bolt: rgba(224, 237, 250, 0.32);
      --steel-scratch: rgba(255, 255, 255, 0.10);
      --visor: rgba(42, 218, 255, 0.18);
      --mecha-shadow: rgba(0, 0, 0, 0.46);
    }}

    body {{
      background:
        radial-gradient(circle at 50% 0%, rgba(255,255,255,0.18), transparent 24%),
        linear-gradient(180deg, #d7d4cb 0%, #bfc2c1 42%, #a9adaf 100%);
    }}

    html[data-theme="night"] body {{
      background:
        radial-gradient(circle at 50% -10%, rgba(48, 83, 104, 0.26), transparent 30%),
        linear-gradient(180deg, #06090d 0%, #0d1219 42%, #0b0f14 100%);
    }}

    .animated-backdrop {{
      overflow: hidden;
      background:
        linear-gradient(90deg, rgba(0,0,0,0.08), transparent 16%, transparent 84%, rgba(0,0,0,0.08)),
        repeating-linear-gradient(90deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 92px),
        repeating-linear-gradient(0deg, rgba(0,0,0,0.055) 0 2px, transparent 2px 92px),
        var(--page-bg);
    }}

    .animated-backdrop::before {{
      content: "";
      position: absolute;
      inset: -80px;
      opacity: 0.55;
      background:
        linear-gradient(115deg, transparent 0 12%, rgba(255,255,255,0.06) 12% 13%, transparent 13% 36%, rgba(0,0,0,0.10) 36% 37%, transparent 37%),
        repeating-linear-gradient(135deg, transparent 0 28px, rgba(0,0,0,0.06) 28px 30px, transparent 30px 72px);
      mix-blend-mode: multiply;
      pointer-events: none;
    }}

    html[data-theme="night"] .animated-backdrop::before {{
      opacity: 0.72;
      mix-blend-mode: screen;
      background:
        linear-gradient(115deg, transparent 0 12%, rgba(120,190,220,0.08) 12% 13%, transparent 13% 36%, rgba(255,96,72,0.08) 36% 37%, transparent 37%),
        repeating-linear-gradient(135deg, transparent 0 28px, rgba(255,255,255,0.035) 28px 30px, transparent 30px 72px);
    }}

    .aurora, .orb, .spark {{
      display: none;
    }}

    .grid {{
      opacity: 0.22;
      transform: perspective(720px) rotateX(62deg) translateY(10vh);
      background-size: 92px 92px, 92px 92px;
      mask-image: linear-gradient(to bottom, transparent, #000 24%, #000 74%, transparent);
    }}

    .hex-field {{
      opacity: 0.16;
      filter: none;
    }}

    .warning-stripes {{
      opacity: 0.18;
      background:
        repeating-linear-gradient(135deg, var(--paint-yellow) 0 14px, rgba(0,0,0,0.42) 14px 28px),
        linear-gradient(90deg, transparent, rgba(0,0,0,0.12), transparent);
      clip-path: polygon(0 0, 16% 0, 10% 100%, 0 100%);
    }}

    .mech-blueprint {{
      display: none;
    }}

    .mecha-hangar {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      opacity: 0.86;
    }}

    .bay-door {{
      position: absolute;
      top: 9vh;
      bottom: 6vh;
      width: min(18vw, 260px);
      background:
        radial-gradient(circle at 24px 24px, var(--bolt) 0 3px, transparent 4px) 0 0 / 58px 58px,
        linear-gradient(90deg, rgba(255,255,255,0.10), transparent 36%, rgba(0,0,0,0.14)),
        repeating-linear-gradient(0deg, transparent 0 54px, var(--armor-edge) 54px 56px),
        linear-gradient(180deg, var(--armor-mid), var(--armor-dark));
      border: 1px solid var(--armor-edge);
      box-shadow: inset 0 0 28px rgba(0,0,0,0.22), 0 24px 60px var(--mecha-shadow);
      clip-path: polygon(0 0, 88% 0, 100% 7%, 100% 93%, 88% 100%, 0 100%);
    }}

    .bay-door.left {{ left: -42px; }}
    .bay-door.right {{
      right: -42px;
      transform: scaleX(-1);
    }}

    .bay-door::after {{
      content: "ARMOR BAY";
      position: absolute;
      top: 42px;
      left: 26px;
      writing-mode: vertical-rl;
      letter-spacing: 0.18em;
      font-size: 12px;
      font-weight: 900;
      color: rgba(255,255,255,0.42);
      text-shadow: 0 1px 0 rgba(0,0,0,0.3);
    }}

    .gantry {{
      position: absolute;
      left: 8vw;
      right: 8vw;
      height: 42px;
      border: 1px solid var(--armor-edge);
      background:
        radial-gradient(circle at 18px 50%, var(--bolt) 0 3px, transparent 4px) 0 0 / 64px 100%,
        repeating-linear-gradient(90deg, transparent 0 72px, rgba(0,0,0,0.12) 72px 75px),
        linear-gradient(180deg, var(--armor-light), var(--armor-mid) 48%, var(--armor-dark));
      box-shadow: inset 0 -10px 22px rgba(0,0,0,0.18), 0 14px 34px var(--mecha-shadow);
      clip-path: polygon(24px 0, calc(100% - 24px) 0, 100% 50%, calc(100% - 24px) 100%, 24px 100%, 0 50%);
      opacity: 0.8;
    }}

    .gantry.top {{ top: 20px; }}
    .gantry.bottom {{ bottom: 18px; transform: rotate(180deg); opacity: 0.58; }}

    .hydraulic-set {{
      position: absolute;
      inset: 0;
      pointer-events: none;
      opacity: 0.52;
    }}

    .hydraulic-set span {{
      position: absolute;
      width: 9px;
      height: min(34vh, 360px);
      top: 18vh;
      border-radius: 10px;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.30), transparent 20% 72%, rgba(0,0,0,0.22)),
        linear-gradient(180deg, #aeb7c0, #4b5560 42%, #151b22 43% 57%, #7e8994);
      box-shadow: 0 0 0 1px var(--armor-edge), 0 22px 44px var(--mecha-shadow);
    }}

    .hydraulic-set span:nth-child(1) {{ left: 9.6vw; transform: rotate(8deg); }}
    .hydraulic-set span:nth-child(2) {{ left: 13.2vw; top: 36vh; height: min(25vh, 280px); transform: rotate(-11deg); }}
    .hydraulic-set span:nth-child(3) {{ right: 9.6vw; transform: rotate(-8deg); }}
    .hydraulic-set span:nth-child(4) {{ right: 13.2vw; top: 36vh; height: min(25vh, 280px); transform: rotate(11deg); }}

    .mecha-suit {{
      position: absolute;
      right: clamp(16px, 4vw, 82px);
      top: 13vh;
      width: min(28vw, 390px);
      height: min(58vh, 620px);
      opacity: 0.18;
      filter: drop-shadow(0 34px 50px var(--mecha-shadow));
      transform: rotate(-2deg);
      pointer-events: none;
    }}

    html[data-theme="night"] .mecha-suit {{ opacity: 0.30; }}

    .mecha-head, .mecha-core, .mecha-shoulder, .mecha-arm, .mecha-leg {{
      position: absolute;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.16), transparent 18%),
        linear-gradient(180deg, var(--armor-light), var(--armor-mid) 42%, var(--armor-dark));
      border: 1px solid var(--armor-edge);
      box-shadow: inset 0 -14px 24px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.12);
    }}

    .mecha-head {{
      left: 38%; top: 0; width: 24%; height: 13%;
      clip-path: polygon(18% 0, 82% 0, 100% 34%, 86% 100%, 14% 100%, 0 34%);
    }}

    .mecha-head i {{
      position: absolute;
      left: 18%; right: 18%; top: 44%; height: 14%;
      background: linear-gradient(90deg, transparent, var(--hud-cyan), transparent);
      box-shadow: 0 0 22px var(--hud-cyan-soft);
    }}

    .mecha-core {{
      left: 28%; top: 15%; width: 44%; height: 34%;
      clip-path: polygon(18% 0, 82% 0, 100% 22%, 90% 100%, 10% 100%, 0 22%);
    }}

    .mecha-core span {{
      position: absolute;
      left: 34%; top: 32%; width: 32%; aspect-ratio: 1;
      border-radius: 50%;
      background: radial-gradient(circle, var(--accent) 0 18%, transparent 20% 48%, var(--accent) 50% 54%, transparent 56%);
      box-shadow: 0 0 28px var(--accent-soft);
    }}

    .mecha-shoulder {{ top: 17%; width: 30%; height: 15%; }}
    .mecha-shoulder.left {{ left: 0; clip-path: polygon(0 22%, 88% 0, 100% 72%, 18% 100%); }}
    .mecha-shoulder.right {{ right: 0; clip-path: polygon(12% 0, 100% 22%, 82% 100%, 0 72%); }}

    .mecha-arm {{ top: 34%; width: 18%; height: 35%; }}
    .mecha-arm.left {{ left: 5%; clip-path: polygon(22% 0, 100% 8%, 72% 100%, 0 88%); }}
    .mecha-arm.right {{ right: 5%; clip-path: polygon(0 8%, 78% 0, 100% 88%, 28% 100%); }}

    .mecha-leg {{ top: 52%; width: 22%; height: 42%; }}
    .mecha-leg.left {{ left: 27%; clip-path: polygon(8% 0, 92% 0, 100% 100%, 0 94%); }}
    .mecha-leg.right {{ right: 27%; clip-path: polygon(8% 0, 92% 0, 100% 94%, 0 100%); }}

    .page {{
      position: relative;
      z-index: 2;
      max-width: min(1540px, calc(100vw - 36px));
    }}

    .cockpit-rail {{
      position: relative;
      padding: 10px 18px;
      border: 1px solid var(--armor-edge);
      background:
        linear-gradient(90deg, rgba(0,0,0,0.16), transparent 12% 88%, rgba(0,0,0,0.16)),
        repeating-linear-gradient(135deg, transparent 0 18px, rgba(255,255,255,0.06) 18px 19px, transparent 19px 38px),
        linear-gradient(180deg, rgba(255,255,255,0.12), rgba(0,0,0,0.08));
      clip-path: polygon(18px 0, calc(100% - 18px) 0, 100% 50%, calc(100% - 18px) 100%, 18px 100%, 0 50%);
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.05), 0 14px 34px var(--mecha-shadow);
    }}

    .cockpit-rail span {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}

    .cockpit-rail span::before {{
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--hud-green);
      box-shadow: 0 0 12px var(--hud-green);
    }}

    .hero-card, .summary-card, .control-panel, .table-panel, .chart-card, .radar-panel, .mvp-panel, .league-panel {{
      position: relative;
      border: 1px solid var(--armor-edge) !important;
      border-radius: 0 !important;
      clip-path: polygon(18px 0, calc(100% - 18px) 0, 100% 18px, 100% calc(100% - 18px), calc(100% - 18px) 100%, 18px 100%, 0 calc(100% - 18px), 0 18px);
      background:
        radial-gradient(circle at 18px 18px, var(--bolt) 0 3px, transparent 4px) 0 0 / 88px 88px,
        radial-gradient(circle at calc(100% - 18px) 18px, var(--bolt) 0 3px, transparent 4px) 0 0 / 88px 88px,
        linear-gradient(135deg, rgba(255,255,255,0.16), transparent 18%),
        repeating-linear-gradient(0deg, transparent 0 38px, rgba(0,0,0,0.035) 38px 39px),
        linear-gradient(180deg, var(--panel-strong), var(--panel)) !important;
      box-shadow:
        inset 0 0 0 1px rgba(255,255,255,0.08),
        inset 0 -18px 32px rgba(0,0,0,0.08),
        0 20px 50px var(--mecha-shadow) !important;
    }}

    html[data-theme="night"] .hero-card,
    html[data-theme="night"] .summary-card,
    html[data-theme="night"] .control-panel,
    html[data-theme="night"] .table-panel,
    html[data-theme="night"] .chart-card,
    html[data-theme="night"] .radar-panel,
    html[data-theme="night"] .mvp-panel,
    html[data-theme="night"] .league-panel {{
      background:
        radial-gradient(circle at 18px 18px, var(--bolt) 0 3px, transparent 4px) 0 0 / 88px 88px,
        radial-gradient(circle at calc(100% - 18px) 18px, var(--bolt) 0 3px, transparent 4px) 0 0 / 88px 88px,
        linear-gradient(135deg, rgba(255,255,255,0.07), transparent 18%),
        repeating-linear-gradient(0deg, transparent 0 38px, rgba(255,255,255,0.025) 38px 39px),
        linear-gradient(180deg, rgba(30,38,48,0.96), rgba(15,21,30,0.92)) !important;
    }}

    .hero-card::before, .summary-card::before, .control-panel::before, .table-panel::before, .chart-card::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(90deg, var(--paint-red) 0 82px, transparent 82px calc(100% - 132px), var(--paint-yellow) calc(100% - 132px) calc(100% - 42px), transparent calc(100% - 42px)) top / 100% 4px no-repeat,
        linear-gradient(90deg, transparent 0 36px, var(--armor-edge) 36px calc(100% - 36px), transparent calc(100% - 36px)) bottom / 100% 1px no-repeat;
      opacity: 0.78;
    }}

    .hero-card::after, .summary-card::after, .control-panel::after, .table-panel::after, .chart-card::after {{
      content: "";
      position: absolute;
      right: 16px;
      bottom: 14px;
      width: 94px;
      height: 22px;
      pointer-events: none;
      opacity: 0.30;
      background:
        repeating-linear-gradient(135deg, var(--paint-yellow) 0 7px, rgba(0,0,0,0.42) 7px 14px);
      clip-path: polygon(9px 0, 100% 0, calc(100% - 9px) 100%, 0 100%);
    }}

    .hero {{
      grid-template-columns: minmax(0, 1.6fr) minmax(320px, 0.72fr);
      align-items: stretch;
    }}

    .hero-card {{
      overflow: hidden;
      padding-top: 30px;
    }}

    .hero-card h1 {{
      letter-spacing: -0.04em;
      text-transform: uppercase;
      text-shadow: 0 2px 0 rgba(0,0,0,0.10);
    }}

    html[data-theme="night"] .hero-card h1 {{
      text-shadow: 0 0 28px rgba(55,216,255,0.12), 0 2px 0 rgba(0,0,0,0.65);
    }}

    .hero-toolbar {{
      border-bottom: 1px solid var(--armor-edge);
      padding-bottom: 12px;
      margin-bottom: 16px;
    }}

    .eyebrow, .summary-title, .panel-title, .table-title, .chart-card h3 {{
      font-family: "DIN Alternate", "Arial Narrow", var(--font-sans);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .theme-toggle, button, select, input {{
      border-radius: 0 !important;
      clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px);
    }}

    .theme-toggle {{
      border-color: var(--armor-edge) !important;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.18), transparent 34%),
        linear-gradient(180deg, var(--button-bg), rgba(0,0,0,0.05)) !important;
      box-shadow: inset 0 -8px 14px rgba(0,0,0,0.08);
    }}

    .stat {{
      position: relative;
      border-radius: 0 !important;
      clip-path: polygon(12px 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%, 0 12px);
      border: 1px solid var(--armor-edge) !important;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.14), transparent 36%),
        linear-gradient(180deg, var(--panel-soft), rgba(0,0,0,0.03)) !important;
    }}

    .stat::before {{
      content: "";
      position: absolute;
      left: 12px; top: 10px;
      width: 34px; height: 3px;
      background: var(--accent);
      box-shadow: 42px 0 0 var(--hud-cyan-soft);
    }}

    .zone-checklist, .table-wrap, .strength-table-wrap, .radar-stage, .radar-side {{
      border-radius: 0 !important;
      clip-path: polygon(12px 0, 100% 0, 100% calc(100% - 12px), calc(100% - 12px) 100%, 0 100%, 0 12px);
      border-color: var(--armor-edge) !important;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.12), transparent 22%),
        var(--panel-soft) !important;
    }}

    .table-wrap {{
      max-height: 72vh;
      overflow: auto;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04), inset 0 0 32px rgba(0,0,0,0.08);
    }}

    thead th {{
      position: sticky;
      top: 0;
      z-index: 6;
      backdrop-filter: blur(14px);
      background:
        linear-gradient(180deg, rgba(255,255,255,0.20), rgba(0,0,0,0.05)),
        var(--panel-strong) !important;
      border-bottom: 1px solid var(--accent) !important;
    }}

    tbody tr {{
      background-image: linear-gradient(90deg, transparent, rgba(255,255,255,0.035), transparent);
    }}

    tbody tr:hover {{
      transform: none !important;
      background:
        linear-gradient(90deg, var(--accent-soft), transparent 42%),
        linear-gradient(180deg, rgba(255,255,255,0.06), transparent) !important;
      box-shadow: inset 4px 0 0 var(--accent), inset 0 1px 0 var(--armor-edge), inset 0 -1px 0 var(--armor-edge);
    }}

    .row-rank {{
      font-family: "DIN Alternate", "Arial Narrow", var(--font-sans);
      letter-spacing: 0.04em;
    }}

    .rank-top {{
      color: var(--paint-yellow) !important;
      text-shadow: 0 0 16px rgba(228,169,46,0.22);
    }}

    .type-badge {{
      border-radius: 0 !important;
      clip-path: polygon(8px 0, 100% 0, calc(100% - 8px) 100%, 0 100%);
      border: 1px solid currentColor;
      box-shadow: inset 0 -8px 14px rgba(0,0,0,0.08);
    }}

    .metric-heat {{
      height: 4px !important;
      border-radius: 0 !important;
      background:
        linear-gradient(90deg, var(--accent), var(--paint-yellow)) left / var(--heat) 100% no-repeat,
        rgba(127, 127, 127, 0.14) !important;
      box-shadow: 0 0 16px rgba(228,169,46,0.16);
    }}

    .bar-track {{
      border-radius: 0 !important;
      background:
        linear-gradient(90deg, rgba(0,0,0,0.16), rgba(255,255,255,0.05)),
        rgba(127,127,127,0.14) !important;
      border: 1px solid var(--armor-edge);
    }}

    .bar-fill {{
      border-radius: 0 !important;
      box-shadow: inset 0 -8px 12px rgba(0,0,0,0.14), 0 0 16px var(--accent-soft);
    }}

    .radar-svg {{
      filter: drop-shadow(0 18px 22px rgba(0,0,0,0.12));
    }}

    .axis-card {{
      border-radius: 0 !important;
      clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px);
      border: 1px solid var(--armor-edge) !important;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.12), transparent 28%),
        var(--panel-soft) !important;
    }}

    .control-panel .field label::before {{
      content: "▰";
      color: var(--paint-red);
      margin-right: 6px;
      font-size: 0.85em;
    }}

    .table-topbar {{
      border-bottom: 1px solid var(--armor-edge);
      padding-bottom: 14px;
    }}

    .chart-grid {{
      gap: 18px;
    }}

    html[data-density="compact"] .table-wrap {{
      max-height: 78vh;
    }}

    html[data-density="compact"] td,
    html[data-density="compact"] th {{
      padding-top: 7px !important;
      padding-bottom: 7px !important;
    }}

    @media (max-width: 1100px) {{
      .bay-door, .hydraulic-set, .mecha-suit {{ opacity: 0.12; }}
      .hero {{ grid-template-columns: 1fr; }}
    }}

    @media (max-width: 720px) {{
      .mecha-hangar, .mecha-suit, .hydraulic-set {{ display: none; }}
      .page {{ max-width: calc(100vw - 20px); }}
    }}

  

    /* ========== Low-rivet readability patch v5: 机甲感保留，背景铆钉退场 ========== */
    .mecha-hangar {{
      opacity: 0.28 !important;
      filter: saturate(0.78) contrast(0.86) !important;
    }}

    .bay-door {{
      width: min(13vw, 190px) !important;
      opacity: 0.28 !important;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.07), transparent 34%, rgba(0,0,0,0.08)),
        repeating-linear-gradient(0deg, transparent 0 84px, rgba(0,0,0,0.055) 84px 86px),
        linear-gradient(180deg, var(--armor-mid), var(--armor-dark)) !important;
      box-shadow: inset 0 0 18px rgba(0,0,0,0.12), 0 16px 36px rgba(0,0,0,0.10) !important;
    }}

    html[data-theme="night"] .bay-door {{
      opacity: 0.22 !important;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.045), transparent 34%, rgba(0,0,0,0.10)),
        repeating-linear-gradient(0deg, transparent 0 96px, rgba(255,255,255,0.035) 96px 98px),
        linear-gradient(180deg, rgba(45,55,67,0.58), rgba(19,27,38,0.54)) !important;
    }}

    .bay-door::after {{
      opacity: 0.28 !important;
      letter-spacing: 0.22em !important;
    }}

    .gantry {{
      opacity: 0.20 !important;
      height: 34px !important;
      background:
        repeating-linear-gradient(90deg, transparent 0 108px, rgba(0,0,0,0.08) 108px 110px),
        linear-gradient(180deg, var(--armor-light), var(--armor-mid) 52%, var(--armor-dark)) !important;
      box-shadow: inset 0 -6px 12px rgba(0,0,0,0.10), 0 8px 20px rgba(0,0,0,0.08) !important;
    }}

    .gantry.bottom {{
      opacity: 0.12 !important;
    }}

    .hydraulic-set {{
      opacity: 0.24 !important;
    }}

    .mecha-suit {{
      opacity: 0.12 !important;
      filter: drop-shadow(0 18px 28px rgba(0,0,0,0.12)) blur(0.15px) !important;
    }}

    html[data-theme="night"] .mecha-suit {{
      opacity: 0.10 !important;
    }}

    .hero-card, .summary-card, .control-panel, .table-panel, .chart-card, .radar-panel, .mvp-panel, .league-panel {{
      background:
        linear-gradient(135deg, rgba(255,255,255,0.13), transparent 16%),
        linear-gradient(180deg, var(--panel-strong), var(--panel)) !important;
      backdrop-filter: blur(7px) saturate(1.05) !important;
      -webkit-backdrop-filter: blur(7px) saturate(1.05) !important;
    }}

    html[data-theme="night"] .hero-card,
    html[data-theme="night"] .summary-card,
    html[data-theme="night"] .control-panel,
    html[data-theme="night"] .table-panel,
    html[data-theme="night"] .chart-card,
    html[data-theme="night"] .radar-panel,
    html[data-theme="night"] .mvp-panel,
    html[data-theme="night"] .league-panel {{
      background:
        linear-gradient(135deg, rgba(255,255,255,0.055), transparent 16%),
        linear-gradient(180deg, rgba(34,43,55,0.965), rgba(18,25,35,0.95)) !important;
    }}

    .hero-card::before, .summary-card::before, .control-panel::before, .table-panel::before, .chart-card::before {{
      opacity: 0.52 !important;
    }}

    .hero-card::after, .summary-card::after, .control-panel::after, .table-panel::after, .chart-card::after {{
      opacity: 0.46 !important;
    }}

    .table-wrap, .strength-table-wrap, .radar-stage, .radar-side, .stat {{
      background-image: none !important;
    }}

    tbody td, .metric, .team-name, .college-name, .muted, .small-note {{
      text-shadow: none !important;
    }}

    table tbody tr:hover {{
      box-shadow: inset 3px 0 0 var(--accent), inset 0 0 0 999px rgba(52, 129, 181, 0.055) !important;
    }}

    @media (max-width: 900px) {{
      .bay-door, .gantry, .hydraulic-set, .mecha-suit {{
        opacity: 0.08 !important;
      }}
    }}



    /* ========== Tactical Brief + View Optimizer ========== */
    .tactical-brief {{
      display: grid;
      grid-template-columns: minmax(220px, 0.95fr) minmax(0, 1.45fr);
      gap: 14px;
      margin: 0 0 16px;
      padding: 16px;
      border-radius: 22px;
      border: 1px solid var(--glass-line);
      background:
        linear-gradient(135deg, rgba(255,255,255,0.78), rgba(237, 244, 248, 0.62)),
        linear-gradient(90deg, rgba(230, 83, 46, 0.10), transparent 38%, rgba(8, 126, 164, 0.08));
      box-shadow: 0 14px 34px rgba(15, 28, 40, 0.10);
      overflow: hidden;
      position: relative;
    }}

    .tactical-brief::before {{
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background:
        linear-gradient(90deg, var(--accent) 0 5px, transparent 5px),
        linear-gradient(180deg, rgba(255,255,255,0.26), transparent 34%);
      opacity: 0.8;
    }}

    .tactical-brief > * {{
      position: relative;
      z-index: 1;
    }}

    html[data-theme="night"] .tactical-brief {{
      background:
        linear-gradient(135deg, rgba(16, 30, 48, 0.88), rgba(10, 20, 34, 0.76)),
        linear-gradient(90deg, rgba(255, 92, 50, 0.12), transparent 40%, rgba(55, 216, 255, 0.08));
      border-color: rgba(117, 211, 255, 0.16);
      box-shadow: 0 18px 42px rgba(0,0,0,0.32);
    }}

    .brief-head {{
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 10px;
      min-width: 0;
    }}

    .brief-kicker {{
      font-size: 11px;
      letter-spacing: 0.18em;
      color: var(--accent-deep);
      font-weight: 900;
    }}

    .brief-title {{
      margin: 0;
      font-size: 20px;
      line-height: 1.25;
      font-weight: 900;
      letter-spacing: -0.02em;
    }}

    .brief-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}

    .brief-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.58);
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }}

    html[data-theme="night"] .brief-chip {{
      background: rgba(4, 12, 22, 0.48);
    }}

    .brief-body {{
      display: grid;
      gap: 10px;
      align-content: center;
    }}

    .brief-line {{
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr);
      gap: 9px;
      align-items: start;
      color: var(--text);
      font-size: 14px;
      line-height: 1.65;
    }}

    .brief-line b {{
      color: var(--accent-deep);
    }}

    .brief-icon {{
      width: 22px;
      height: 22px;
      display: inline-grid;
      place-items: center;
      border-radius: 7px;
      color: var(--accent-deep);
      background: var(--accent-soft);
      font-size: 12px;
      font-weight: 900;
      margin-top: 2px;
    }}

    .metric-presets {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}

    .metric-preset {{
      border: 1px solid var(--line);
      background: var(--button-bg);
      color: var(--text);
      border-radius: 14px;
      padding: 9px 10px;
      font: inherit;
      font-size: 12px;
      font-weight: 850;
      cursor: pointer;
      transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
    }}

    .metric-preset:hover {{
      transform: translateY(-1px);
      border-color: var(--accent);
      background: var(--accent-soft);
    }}

    .metric-preset.active {{
      color: var(--accent-deep);
      border-color: rgba(230, 83, 46, 0.38);
      background: linear-gradient(135deg, var(--accent-soft), rgba(8,126,164,0.06));
    }}

    .view-hint {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }}

    html[data-density="compact"] .tactical-brief {{
      padding: 12px;
      gap: 10px;
    }}

    html[data-density="compact"] .brief-title {{
      font-size: 17px;
    }}

    html[data-density="compact"] .brief-line {{
      font-size: 12.5px;
      line-height: 1.45;
    }}

    @media (max-width: 900px) {{
      .tactical-brief {{
        grid-template-columns: 1fr;
      }}

      .metric-presets {{
        grid-template-columns: 1fr;
      }}
    }}



    /* ========== Analysis Extensions: credibility, outliers, disclaimer ========== */
    .brief-disclaimer,
    .insight-disclaimer,
    .diagnostic-note {{
      border: 1px dashed rgba(120, 132, 148, 0.42);
      background: rgba(255, 255, 255, 0.46);
      color: var(--muted);
      border-radius: 14px;
      padding: 10px 12px;
      font-size: 12px;
      line-height: 1.65;
    }}

    html[data-theme="night"] .brief-disclaimer,
    html[data-theme="night"] .insight-disclaimer,
    html[data-theme="night"] .diagnostic-note {{
      background: rgba(6, 16, 28, 0.38);
      border-color: rgba(145, 197, 255, 0.20);
    }}

    .brief-disclaimer {{
      grid-column: 1 / -1;
      margin-top: 2px;
    }}

    .insight-disclaimer {{
      margin-top: 14px;
    }}

    .diagnostic-card h3 {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .diagnostic-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin: 12px 0;
    }}

    .diagnostic-stat {{
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 10px 11px;
      background: rgba(255,255,255,0.48);
      min-width: 0;
    }}

    html[data-theme="night"] .diagnostic-stat {{
      background: rgba(10, 24, 40, 0.44);
    }}

    .diagnostic-label {{
      font-size: 11px;
      color: var(--muted);
      font-weight: 800;
    }}

    .diagnostic-value {{
      margin-top: 3px;
      font-size: 20px;
      font-weight: 950;
      color: var(--text);
      font-variant-numeric: tabular-nums;
    }}

    .diagnostic-pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}

    .diagnostic-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.42);
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
    }}

    .diagnostic-pill[data-level="high"] {{ color: #087f5b; border-color: rgba(8,127,91,0.28); }}
    .diagnostic-pill[data-level="mid"] {{ color: #9a5b00; border-color: rgba(184,113,0,0.30); }}
    .diagnostic-pill[data-level="low"] {{ color: #b42318; border-color: rgba(180,35,24,0.30); }}
    html[data-theme="night"] .diagnostic-pill[data-level="high"] {{ color: #6ee7b7; }}
    html[data-theme="night"] .diagnostic-pill[data-level="mid"] {{ color: #facc15; }}
    html[data-theme="night"] .diagnostic-pill[data-level="low"] {{ color: #fb7185; }}

    .outlier-list {{
      display: grid;
      gap: 9px;
      margin-top: 12px;
    }}

    .outlier-item {{
      display: grid;
      grid-template-columns: minmax(130px, 1.2fr) minmax(70px, 0.45fr) minmax(0, 1fr);
      gap: 10px;
      align-items: center;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,0.42);
    }}

    html[data-theme="night"] .outlier-item {{
      background: rgba(10, 24, 40, 0.36);
    }}

    .outlier-team {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 900;
    }}

    .outlier-score {{
      font-weight: 950;
      color: var(--accent-deep);
      font-variant-numeric: tabular-nums;
    }}

    .outlier-reason {{
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .role-grid {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
    }}

    .role-row {{
      display: grid;
      grid-template-columns: 64px minmax(0, 1fr) 76px;
      gap: 10px;
      align-items: center;
      font-size: 13px;
    }}

    .role-track {{
      position: relative;
      height: 9px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(120, 132, 148, 0.16);
    }}

    .role-fill {{
      position: absolute;
      inset: 0 auto 0 0;
      width: var(--w);
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), rgba(8,126,164,0.72));
    }}

    @media (max-width: 760px) {{
      .diagnostic-grid {{ grid-template-columns: 1fr; }}
      .outlier-item {{ grid-template-columns: 1fr; }}
      .role-row {{ grid-template-columns: 54px minmax(0, 1fr) 62px; }}
    }}


    /* ========== Deep Review Toolkit: metric guide, snapshot, copy brief ========== */
    .review-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}

    .review-chip-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}

    .review-chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 9px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.42);
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
    }}

    html[data-theme="night"] .review-chip {{
      background: rgba(10, 24, 40, 0.38);
    }}

    .metric-guide-card .metric-name {{
      display: inline-flex;
      align-items: center;
      width: fit-content;
      padding: 7px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent-deep);
      font-size: 12px;
      font-weight: 950;
      margin-bottom: 10px;
    }}

    .metric-guide-card .metric-desc {{
      margin: 0;
      line-height: 1.72;
      color: var(--text);
      font-size: 13px;
    }}

    .metric-rule-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }}

    .metric-rule {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 11px;
      background: rgba(255,255,255,0.42);
      min-width: 0;
    }}

    html[data-theme="night"] .metric-rule {{
      background: rgba(10, 24, 40, 0.36);
    }}

    .metric-rule b {{
      display: block;
      margin-bottom: 4px;
      color: var(--text);
      font-size: 12px;
    }}

    .metric-rule span {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }}

    .snapshot-list {{
      display: grid;
      gap: 9px;
      margin-top: 12px;
    }}

    .snapshot-row {{
      display: grid;
      grid-template-columns: 42px minmax(150px, 1.15fr) minmax(120px, 0.9fr) 86px 92px;
      gap: 10px;
      align-items: center;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: rgba(255,255,255,0.42);
      font-size: 12px;
    }}

    html[data-theme="night"] .snapshot-row {{
      background: rgba(10, 24, 40, 0.36);
    }}

    .snapshot-rank {{
      font-weight: 950;
      color: var(--accent-deep);
      font-variant-numeric: tabular-nums;
    }}

    .snapshot-team,
    .snapshot-meta {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .snapshot-team {{
      font-weight: 900;
      color: var(--text);
    }}

    .snapshot-meta {{
      color: var(--muted);
    }}

    .snapshot-value {{
      text-align: right;
      font-weight: 950;
      color: var(--accent-deep);
      font-variant-numeric: tabular-nums;
    }}

    .snapshot-ratio {{
      justify-self: end;
      padding: 4px 7px;
      border-radius: 999px;
      border: 1px solid var(--line);
      color: var(--muted);
      font-weight: 900;
      font-variant-numeric: tabular-nums;
    }}

    .snapshot-ratio[data-level="high"] {{ color: #087f5b; border-color: rgba(8,127,91,0.30); }}
    .snapshot-ratio[data-level="mid"] {{ color: #9a5b00; border-color: rgba(184,113,0,0.30); }}
    .snapshot-ratio[data-level="low"] {{ color: #b42318; border-color: rgba(180,35,24,0.30); }}
    html[data-theme="night"] .snapshot-ratio[data-level="high"] {{ color: #6ee7b7; }}
    html[data-theme="night"] .snapshot-ratio[data-level="mid"] {{ color: #facc15; }}
    html[data-theme="night"] .snapshot-ratio[data-level="low"] {{ color: #fb7185; }}

    .copy-brief-body {{
      margin: 12px 0;
      padding: 12px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.42);
      color: var(--text);
      font-size: 13px;
      line-height: 1.72;
      white-space: pre-line;
    }}

    html[data-theme="night"] .copy-brief-body {{
      background: rgba(10, 24, 40, 0.36);
    }}

    .copy-brief-button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      background: linear-gradient(135deg, var(--accent), #cd7b52);
      color: #fff;
      padding: 9px 13px;
      font-size: 13px;
      font-weight: 950;
      cursor: pointer;
      box-shadow: 0 10px 22px rgba(184, 92, 56, 0.20);
    }}

    .copy-brief-button:active {{
      transform: translateY(1px);
    }}

    .action-list {{
      display: grid;
      gap: 9px;
      margin-top: 12px;
    }}

    .action-item {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 10px 11px;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.42);
      color: var(--text);
      font-size: 13px;
      line-height: 1.62;
    }}

    html[data-theme="night"] .action-item {{
      background: rgba(10, 24, 40, 0.36);
    }}

    .action-index {{
      display: inline-grid;
      place-items: center;
      width: 26px;
      height: 26px;
      border-radius: 9px;
      background: var(--accent-soft);
      color: var(--accent-deep);
      font-weight: 950;
    }}


    /* ========== Team Compare Bay: wide 8-team battle station ========== */
    .compare-panel {{
      margin: 0 0 18px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 22px;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.62), rgba(255,255,255,0.28)),
        var(--panel-soft);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 14px 34px rgba(0,0,0,0.08);
      overflow: hidden;
    }}

    html[data-theme="night"] .compare-panel {{
      background:
        linear-gradient(135deg, rgba(18, 38, 58, 0.72), rgba(7, 18, 31, 0.48)),
        rgba(10, 24, 40, 0.42);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 14px 38px rgba(0,0,0,0.22);
    }}

    .compare-panel .compare-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }}

    .compare-panel h3 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}

    .compare-cap {{
      padding: 7px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--accent-deep);
      background: var(--accent-soft);
      font-size: 13px;
      font-weight: 950;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }}

    .compare-tools {{
      display: grid;
      grid-template-columns: minmax(150px, 0.85fr) minmax(220px, 1.15fr) minmax(320px, 1.8fr) minmax(190px, 0.9fr);
      gap: 12px;
      align-items: stretch;
    }}

    .compare-field {{
      min-width: 0;
      display: grid;
      gap: 6px;
    }}

    .compare-field label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: 0.04em;
    }}

    .compare-field input,
    .compare-field select {{
      width: 100%;
      min-height: 48px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 15px;
      background: var(--input-bg);
      color: var(--text);
      font-size: 14px;
      font-weight: 780;
      outline: none;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.22);
    }}

    .compare-field select {{
      text-overflow: ellipsis;
    }}

    .compare-field input:focus,
    .compare-field select:focus {{
      border-color: rgba(184, 92, 56, 0.48);
      box-shadow: 0 0 0 4px rgba(184, 92, 56, 0.1), inset 0 1px 0 rgba(255,255,255,0.22);
    }}

    .compare-button-row {{
      display: grid;
      grid-template-columns: 1.1fr 0.75fr;
      gap: 10px;
      align-items: end;
    }}

    .compare-button {{
      min-height: 48px;
      border: 1px solid var(--line);
      border-radius: 15px;
      padding: 12px 14px;
      background: linear-gradient(135deg, var(--accent-soft), rgba(255,255,255,0.34));
      color: var(--accent-deep);
      font-size: 14px;
      font-weight: 950;
      cursor: pointer;
      transition: transform 0.16s ease, border-color 0.16s ease, opacity 0.16s ease;
    }}

    .compare-button:hover:not(:disabled) {{
      transform: translateY(-1px);
      border-color: var(--accent-deep);
    }}

    .compare-button.secondary {{
      background: var(--button-bg);
      color: var(--muted);
    }}

    .compare-button:disabled {{
      opacity: 0.45;
      cursor: not-allowed;
      transform: none;
    }}

    .compare-tray {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 10px;
      margin-top: 14px;
      min-height: 42px;
    }}

    .compare-chip {{
      display: flex;
      align-items: center;
      gap: 9px;
      min-width: 0;
      max-width: 100%;
      padding: 10px 11px;
      border: 1px solid var(--line);
      border-radius: 15px;
      background: rgba(255,255,255,0.48);
      color: var(--text);
      font-size: 13px;
      font-weight: 880;
    }}

    html[data-theme="night"] .compare-chip {{
      background: rgba(10, 24, 40, 0.42);
    }}

    .compare-chip i {{
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--dot);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--dot), transparent 78%);
      flex: 0 0 auto;
    }}

    .compare-chip span {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    .compare-chip button {{
      border: 0;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-weight: 950;
      padding: 0 2px;
    }}

    .compare-hint {{
      color: var(--muted);
      font-size: 12px;
      line-height: 1.6;
      margin-top: 8px;
    }}

    .compare-radar-card {{
      grid-column: 1 / -1;
    }}

    .compare-radar-layout {{
      display: grid;
      grid-template-columns: minmax(320px, 520px) minmax(260px, 1fr);
      gap: 16px;
      align-items: start;
      margin-top: 14px;
    }}

    .compare-svg-wrap {{
      position: relative;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: radial-gradient(circle at 50% 40%, rgba(255,255,255,0.42), transparent 62%), rgba(255,255,255,0.22);
      overflow: hidden;
    }}

    html[data-theme="night"] .compare-svg-wrap {{
      background: radial-gradient(circle at 50% 40%, rgba(55,216,255,0.08), transparent 62%), rgba(10, 24, 40, 0.36);
    }}

    .compare-svg {{
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
    }}

    .compare-legend {{
      display: grid;
      gap: 8px;
    }}

    .compare-legend-row {{
      display: grid;
      grid-template-columns: 14px minmax(0, 1fr) 74px;
      gap: 9px;
      align-items: center;
      padding: 8px 9px;
      border: 1px solid var(--line);
      border-radius: 13px;
      background: rgba(255,255,255,0.38);
      font-size: 12px;
    }}

    html[data-theme="night"] .compare-legend-row {{
      background: rgba(10, 24, 40, 0.34);
    }}

    .compare-color {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      background: var(--c);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--c), transparent 78%);
    }}

    .compare-name {{
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 900;
    }}

    .compare-score {{
      text-align: right;
      color: var(--accent-deep);
      font-weight: 950;
      font-variant-numeric: tabular-nums;
    }}

    .compare-summary {{
      margin-top: 12px;
      display: grid;
      gap: 8px;
    }}

    .compare-summary-line {{
      display: flex;
      gap: 8px;
      align-items: flex-start;
      padding: 9px 10px;
      border-radius: 13px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.34);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.65;
    }}

    html[data-theme="night"] .compare-summary-line {{
      background: rgba(10, 24, 40, 0.32);
    }}

    .compare-summary-line b {{
      color: var(--text);
    }}

    .compare-disclaimer {{
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 15px;
      border: 1px dashed var(--line);
      color: var(--muted);
      font-size: 12px;
      line-height: 1.7;
      background: rgba(255,255,255,0.28);
    }}

    html[data-theme="night"] .compare-disclaimer {{
      background: rgba(10, 24, 40, 0.26);
    }}

    @media (max-width: 1280px) {{
      .compare-tools {{
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }}

      .compare-button-row {{
        align-items: stretch;
      }}
    }}

    @media (max-width: 720px) {{
      .compare-panel {{
        padding: 14px;
      }}

      .compare-tools {{
        grid-template-columns: 1fr;
      }}

      .compare-tray {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 980px) {{
      .compare-radar-layout {{
        grid-template-columns: 1fr;
      }}
    }}

    @media (max-width: 980px) {{
      .review-grid,
      .metric-rule-grid {{
        grid-template-columns: 1fr;
      }}

      .snapshot-row {{
        grid-template-columns: 38px minmax(0, 1fr) 76px;
      }}

      .snapshot-meta,
      .snapshot-ratio {{
        display: none;
      }}
    }}


    /* ========== Per-role table pages + focused ranking metric ========== */
    .table-type-pages {{
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin: 0 0 14px;
      padding: 10px;
      border: 1px solid var(--line);
      background: var(--panel-soft);
    }}

    .table-type-pages[hidden] {{
      display: none;
    }}

    .table-type-page {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 38px;
      padding: 8px 12px;
      border: 1px solid var(--line);
      background: var(--button-bg);
      color: var(--muted);
      font: inherit;
      font-size: 13px;
      font-weight: 900;
      cursor: pointer;
    }}

    .table-type-page span {{
      min-width: 22px;
      padding: 2px 6px;
      background: rgba(127, 127, 127, 0.12);
      color: inherit;
      font-size: 11px;
      text-align: center;
    }}

    .table-type-page:hover {{
      border-color: var(--accent);
      color: var(--text);
    }}

    .table-type-page.active {{
      border-color: var(--accent);
      background: linear-gradient(135deg, var(--accent), var(--hud-cyan));
      color: #fff;
      box-shadow: 0 9px 22px var(--accent-soft);
    }}

    thead th.active-metric-header {{
      min-width: 142px;
      color: var(--accent-deep) !important;
      background:
        linear-gradient(90deg, var(--accent-soft), var(--hud-cyan-soft)),
        var(--panel-strong) !important;
      box-shadow: inset 3px 0 0 var(--accent), inset 0 -3px 0 var(--accent);
    }}

    .sort-focus-badge {{
      display: inline-block;
      margin-left: 7px;
      padding: 2px 6px;
      background: var(--accent);
      color: #fff;
      font-size: 10px;
      line-height: 1.4;
      letter-spacing: 0;
      vertical-align: 1px;
    }}

    td.focus-metric {{
      background: linear-gradient(90deg, var(--accent-soft), var(--hud-cyan-soft));
      box-shadow: inset 3px 0 0 var(--accent);
      color: var(--accent-deep);
    }}

    td.focus-metric-empty {{
      color: var(--muted);
    }}

    .below-table-grid {{
      margin: 18px 0 0;
    }}

    .below-table-grid[hidden] {{
      display: none;
    }}


    /* ========== Background switch: simple / fancy ========== */
    html[data-background="simple"] body {{
      background: linear-gradient(180deg, #f4f6f8 0%, #e8edf1 100%);
    }}

    html[data-background="simple"][data-theme="night"] body {{
      background: linear-gradient(180deg, #17212d 0%, #0f1722 100%);
    }}

    html[data-background="simple"] body::before,
    html[data-background="simple"] body::after,
    html[data-background="simple"] .animated-backdrop,
    html[data-background="simple"] .hud-frame,
    html[data-background="simple"] .cockpit-rail {{
      display: none;
    }}

    /* ========== 一级数据板块：机器人数据 / 赛程赛果 ========== */
    .dataset-nav {{
      position: sticky;
      top: 0;
      z-index: 80;
      display: flex;
      gap: 8px;
      margin: 0 0 18px;
      padding: 10px;
      border: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel-strong) 90%, transparent);
      backdrop-filter: blur(18px);
      box-shadow: var(--shadow);
    }}
    .dataset-tab {{
      flex: 1;
      min-height: 48px;
      border: 1px solid var(--line);
      background: var(--button-bg);
      color: var(--muted);
      font: inherit;
      font-weight: 950;
      cursor: pointer;
    }}
    .dataset-tab.active {{
      border-color: var(--accent);
      color: #fff;
      background: linear-gradient(135deg, var(--accent), var(--hud-cyan));
      box-shadow: 0 0 24px var(--accent-soft);
    }}
    .dataset-board[hidden] {{ display: none !important; }}
    .schedule-board {{ display: grid; gap: 16px; }}
    .schedule-hero, .schedule-controls, .schedule-panel, .schedule-summary {{
      border: 1px solid var(--glass-line);
      background: var(--panel);
      box-shadow: var(--shadow);
      backdrop-filter: blur(14px);
    }}
    .schedule-hero {{ padding: 28px; }}
    .schedule-hero h1 {{ margin: 8px 0; font-size: clamp(30px, 5vw, 58px); }}
    .schedule-hero p {{ max-width: 920px; margin: 0; color: var(--muted); line-height: 1.8; }}
    .schedule-summary {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1px; }}
    .schedule-stat {{ padding: 20px; background: var(--panel-soft); }}
    .schedule-stat b {{ display: block; font-size: 29px; color: var(--accent-deep); }}
    .schedule-stat span {{ color: var(--muted); font-size: 12px; }}
    .schedule-controls {{ display: grid; grid-template-columns: 150px 190px 210px 1fr auto; gap: 10px; padding: 14px; }}
    .schedule-controls select, .schedule-controls input {{
      min-width: 0; height: 42px; border: 1px solid var(--line); background: var(--input-bg);
      color: var(--text); padding: 0 12px; font: inherit;
    }}
    .schedule-check {{ display: flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .schedule-panel {{ padding: 18px; }}
    .schedule-panel-head {{ display: flex; justify-content: space-between; gap: 18px; align-items: end; margin-bottom: 12px; }}
    .schedule-panel h2 {{ margin: 0; }}
    .schedule-count {{ color: var(--muted); font-size: 12px; }}
    .schedule-list {{ display: grid; gap: 8px; }}
    .schedule-stage-group {{ display: grid; gap: 8px; margin-bottom: 16px; }}
    .schedule-stage-group:last-child {{ margin-bottom: 0; }}
    .schedule-stage-heading {{
      display: flex; align-items: center; justify-content: space-between; gap: 12px;
      padding: 10px 13px; border-left: 4px solid var(--accent);
      background: linear-gradient(90deg, var(--accent-soft), transparent); color: var(--text);
    }}
    .schedule-stage-heading b {{ font-size: 14px; }}
    .schedule-stage-heading span {{ color: var(--muted); font-size: 11px; }}
    .schedule-match {{
      display: grid; grid-template-columns: 90px minmax(150px,1fr) 110px minmax(150px,1fr) 170px;
      align-items: center; min-height: 74px; border: 1px solid var(--line); background: var(--panel-strong);
    }}
    .schedule-meta, .schedule-tail {{ padding: 10px 13px; color: var(--muted); font-size: 11px; }}
    .schedule-meta {{ border-right: 1px solid var(--line); }}
    .schedule-meta b, .schedule-stage {{ display: block; color: var(--text); font-weight: 950; }}
    .schedule-team {{ padding: 10px 15px; min-width: 0; }}
    .schedule-team.red {{ text-align: right; }}
    .schedule-team b, .schedule-team small {{ display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .schedule-team small {{ margin-top: 4px; color: var(--muted); }}
    .schedule-score {{ display: flex; justify-content: center; gap: 9px; font-size: 24px; font-weight: 950; }}
    .schedule-score .red {{ color: var(--accent); }} .schedule-score .blue {{ color: var(--hud-cyan); }}
    .schedule-tail {{ border-left: 1px solid var(--line); }}
    .schedule-flag {{ display: inline-block; margin-top: 4px; padding: 2px 5px; color: #7a5900; background: #ffe59a; }}
    .schedule-replay {{
      display: inline-block; margin-top: 6px; padding: 4px 7px; border: 1px solid color-mix(in srgb, var(--hud-cyan), transparent 45%);
      color: var(--hud-cyan); background: var(--hud-cyan-soft); font-weight: 900; text-decoration: none;
    }}
    .schedule-replay:hover {{ border-color: var(--accent); color: var(--accent-deep); }}
    .schedule-empty {{ padding: 60px 20px; text-align: center; color: var(--muted); }}
    .schedule-pagination {{ display: flex; justify-content: center; align-items: center; gap: 10px; margin-top: 16px; }}
    .schedule-pagination button {{ border: 1px solid var(--line); background: var(--button-bg); color: var(--text); padding: 9px 15px; cursor: pointer; }}
    .schedule-pagination button:disabled {{ opacity: .35; cursor: default; }}
    .season-recap {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }}
    .recap-card {{ padding: 13px; border: 1px solid var(--line); background: var(--panel-soft); }}
    .recap-card b {{ display: block; }} .recap-card span {{ color: var(--muted); font-size: 11px; }}
    .schedule-source {{ margin-top: 14px; color: var(--muted); font-size: 12px; line-height: 1.7; }}
    .schedule-source a {{ color: var(--accent-deep); font-weight: 900; }}
    @media (max-width: 900px) {{
      .schedule-summary {{ grid-template-columns: 1fr 1fr; }}
      .schedule-controls {{ grid-template-columns: 1fr 1fr; }}
      .schedule-controls input {{ grid-column: 1 / -1; }}
      .schedule-match {{ grid-template-columns: 62px minmax(0,1fr) 76px minmax(0,1fr); }}
      .schedule-tail {{ grid-column: 1 / -1; border-left: 0; border-top: 1px solid var(--line); }}
      .season-recap {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    @media (max-width: 560px) {{
      .dataset-nav {{ position: relative; }}
      .schedule-controls {{ grid-template-columns: 1fr; }} .schedule-controls input {{ grid-column: auto; }}
      .schedule-match {{ grid-template-columns: 48px minmax(0,1fr) 60px minmax(0,1fr); }}
      .schedule-team {{ padding: 8px; }} .schedule-team b {{ font-size: 12px; }}
      .season-recap {{ grid-template-columns: 1fr; }}
    }}

  </style>
</head>
<body>
  <div class="animated-backdrop" aria-hidden="true">
    <div class="aurora"></div>
    <div class="grid"></div>
    <div class="hex-field"></div>
    <div class="mech-blueprint"></div>
    <div class="reticle"></div>
    <div class="scanline"></div>
    <div class="warning-stripes"></div>
    <div class="orb one"></div>
    <div class="orb two"></div>
    <div class="spark"></div>
    <div class="mecha-hangar">
      <div class="bay-door left"></div>
      <div class="bay-door right"></div>
      <div class="gantry top"></div>
      <div class="gantry bottom"></div>
    </div>
    <div class="mecha-suit" aria-hidden="true">
      <div class="mecha-head"><i></i></div>
      <div class="mecha-core"><span></span></div>
      <div class="mecha-shoulder left"></div>
      <div class="mecha-shoulder right"></div>
      <div class="mecha-arm left"></div>
      <div class="mecha-arm right"></div>
      <div class="mecha-leg left"></div>
      <div class="mecha-leg right"></div>
    </div>
    <div class="hydraulic-set" aria-hidden="true">
      <span></span><span></span><span></span><span></span>
    </div>
  </div>
  <div class="hud-frame" aria-hidden="true"></div>
  <div class="page">
    <div class="cockpit-rail" aria-hidden="true">
      <span>T-DT ARMOR-BAY</span>
      <span>SERVO LINK READY</span>
      <span>BALLISTIC DATA CORE</span>
      <span>TACTICAL VIEW ONLINE</span>
    </div>
    <nav class="dataset-nav" aria-label="数据板块">
      <button class="dataset-tab active" type="button" data-dataset-tab="robot">01　机器人数据</button>
      <button class="dataset-tab" type="button" data-dataset-tab="schedule">02　赛程赛果</button>
    </nav>
    <div class="dataset-board" id="robotBoard" data-dataset-board="robot">
    <section class="hero">
      <div class="hero-card">
        <div class="hero-toolbar">
          <span class="eyebrow">RM ARMOR BAY // MECHA DATA CORE</span>
          <div class="toolbar-actions">
            <button id="backgroundToggle" class="theme-toggle background-toggle" type="button" aria-label="切换到简约背景">✦ 背景：正常</button>
            <button id="densityToggle" class="theme-toggle density-toggle" type="button" aria-label="切换表格密度">▤ 紧凑</button>
            <button id="themeToggle" class="theme-toggle" type="button" aria-label="切换白昼或夜间模式">🌙 夜间</button>
          </div>
        </div>
        <h1 id="heroTitle">{safe_title}</h1>
        <p id="heroSubtitle">这是按机甲驾驶舱思路重做的 RM 数据分析面板：左侧像武器/传感器控制台，右侧是装甲数据舱。可以按兵种、赛区、关键词筛选，按任意指标排序；筛到单支战队时会生成兵种能力雷达图和 MVP 追踪视图。</p>
        <div class="combat-strip" aria-hidden="true">
          <span><b>CORE</b> ONLINE</span>
          <span><b>RADAR</b> SYNC</span>
          <span><b>MVP</b> TRACE</span>
          <span><b>TACTIC</b> SCOUT</span>
        </div>
      </div>
      <aside class="summary-card">
        <div class="summary-title">当前概览</div>
        <div class="summary-grid">
          <div class="stat">
            <div class="stat-label">队伍数量</div>
            <div class="stat-value" id="teamCount">0</div>
          </div>
          <div class="stat">
            <div class="stat-label">赛区数量</div>
            <div class="stat-value" id="zoneCount">0</div>
          </div>
          <div class="stat">
            <div class="stat-label">兵种数量</div>
            <div class="stat-value" id="typeCount">0</div>
          </div>
          <div class="stat">
            <div class="stat-label">指标均值</div>
            <div class="stat-value" id="avgMetric">-</div>
          </div>
        </div>
      </aside>
    </section>

    <section class="main-grid">
      <aside class="control-panel">
        <h2 class="panel-title">筛选与排序</h2>
        <div class="field">
          <label for="searchInput">搜索学校 / 战队 / 赛区</label>
          <input id="searchInput" type="text" placeholder="例如 tdt / 北部 / 无人机">
        </div>
        <div class="field">
          <label>赛区选择</label>
          <div class="zone-checklist" id="zoneChecklist"></div>
        </div>
        <div class="field">
          <label for="typeSelect">兵种选择</label>
          <select id="typeSelect"></select>
        </div>
        <div class="field">
          <label for="metricSelect">排序指标</label>
          <select id="metricSelect"></select>
          <div class="metric-presets" id="metricPresetBar">
            <button class="metric-preset" type="button" data-metric-preset="自瞄命中综合">自瞄命中</button>
            <button class="metric-preset" type="button" data-metric-preset="火力输出综合">火力输出</button>
            <button class="metric-preset" type="button" data-metric-preset="MVP次数">MVP追踪</button>
            <button class="metric-preset" type="button" data-metric-preset="局均雷达分数">雷达压制</button>
            <button class="metric-preset" type="button" data-metric-preset="局均组装经济数">工程经济</button>
            <button class="metric-preset" type="button" data-metric-preset="总场次飞镖分数">飞镖打击</button>
          </div>
          <div class="view-hint">常用指标可以直接点，不用在长下拉框里翻。</div>
        </div>
        <div class="field">
          <label for="sortDirection">排序方向</label>
          <select id="sortDirection">
            <option value="desc">从高到低</option>
            <option value="asc">从低到高</option>
          </select>
        </div>
        <div class="field">
          <label for="rowLimit">显示数量</label>
          <select id="rowLimit">
            <option value="20">前 20 条</option>
            <option value="50" selected>前 50 条</option>
            <option value="100">前 100 条</option>
            <option value="9999">全部</option>
          </select>
        </div>

      </aside>

      <section class="table-panel">
        <section class="compare-panel compare-wide" aria-label="队伍比拼台">
          <div class="compare-head">
            <div>
              <h3>队伍比拼台</h3>
              <div class="view-hint">最多 8 支队伍，适合做跨赛区/同赛区内部比拼；右侧会叠加七边形雷达图。</div>
            </div>
            <span class="compare-cap" id="compareCap">0/8</span>
          </div>
          <div class="compare-tools">
            <div class="compare-field">
              <label for="compareZoneSelect">对比赛区</label>
              <select id="compareZoneSelect" aria-label="选择对比赛区"></select>
            </div>
            <div class="compare-field">
              <label for="compareSearchInput">搜索队伍</label>
              <input id="compareSearchInput" type="text" placeholder="战队名关键词">
            </div>
            <div class="compare-field">
              <label for="compareTeamSelect">候选队伍</label>
              <select id="compareTeamSelect" aria-label="选择对比队伍"></select>
            </div>
            <div class="compare-button-row">
              <button id="compareAddButton" class="compare-button" type="button">加入比拼</button>
              <button id="compareClearButton" class="compare-button secondary" type="button">清空</button>
            </div>
          </div>
          <div class="compare-tray" id="compareTray"></div>
          <div class="compare-hint">口径：每支队伍按它所在赛区的同兵种均值归一化，100% 表示该赛区该兵种平均水平；只作复盘参考，不代表官方排名。</div>
        </section>
        <div class="table-topbar">
          <div>
            <h2 id="tableTitle">数据列表</h2>
            <div class="table-meta" id="tableMeta">准备中...</div>
          </div>
        </div>
        <section class="tactical-brief" id="tacticalBrief" aria-live="polite"></section>
        <div class="chart-grid" id="chartGrid"></div>
        <div class="table-type-pages" id="tableTypePages" role="tablist" aria-label="按兵种切换数据页" hidden></div>
        <div class="table-wrap">
          <table>
            <thead id="tableHead"></thead>
            <tbody id="tableBody"></tbody>
          </table>
          <div class="empty" id="emptyState" hidden>当前筛选条件下没有结果。</div>
        </div>
        <div class="chart-grid below-table-grid" id="belowTableGrid" aria-label="数据表下方的综合排名"></div>
      </section>
    </section>
    </div>

    <div class="dataset-board schedule-board" id="scheduleBoard" data-dataset-board="schedule" hidden>
      <section class="schedule-hero">
        <span class="eyebrow">RM MATCH ARCHIVE // 2015—2026</span>
        <h1>历年赛程与赛果</h1>
        <p>已将原始工作簿归纳为统一的“赛季—赛区—阶段—红蓝双方—比分”结构。2015—2025 按逐场赛果查询；2026 工作簿目前记录的是全国赛名单与最终席位，因此单独归纳，不计入逐场对阵总数。</p>
      </section>
      <section class="schedule-summary" aria-label="赛程数据概览">
        <div class="schedule-stat"><b id="scheduleMatchCount">0</b><span>有效逐场记录</span></div>
        <div class="schedule-stat"><b id="scheduleTeamCount">0</b><span>历史战队组合</span></div>
        <div class="schedule-stat"><b id="scheduleSchoolCount">0</b><span>参赛高校</span></div>
        <div class="schedule-stat"><b id="scheduleUncertainCount">0</b><span>待核记录</span></div>
      </section>
      <section class="schedule-controls" aria-label="赛程筛选">
        <select id="scheduleSeason"><option value="">全部赛季</option></select>
        <select id="scheduleZone"><option value="">全部赛区</option></select>
        <select id="scheduleStage"><option value="">全部比赛阶段</option></select>
        <input id="scheduleSearch" type="search" placeholder="搜索学校、战队或备注">
        <label class="schedule-check"><input id="scheduleIncludeUncertain" type="checkbox" checked>包含待核</label>
      </section>
      <section class="schedule-panel">
        <div class="schedule-panel-head"><div><span class="eyebrow">MATCH SCHEDULE</span><h2>逐场赛程</h2></div><span class="schedule-count" id="scheduleCountLabel"></span></div>
        <div class="schedule-list" id="scheduleList"></div>
        <div class="schedule-pagination"><button id="schedulePrev" type="button">上一页</button><span class="schedule-count" id="schedulePageLabel"></span><button id="scheduleNext" type="button">下一页</button></div>
      </section>
      <section class="schedule-panel">
        <div class="schedule-panel-head"><div><span class="eyebrow">SEASON RECAP</span><h2>按赛季归纳</h2></div><span class="schedule-count">场次 · 参赛队伍 · 决赛阶段</span></div>
        <div class="season-recap" id="seasonRecap"></div>
      </section>
      <section class="schedule-panel">
        <div class="schedule-panel-head"><div><span class="eyebrow">ZONE RANKING</span><h2 id="zoneRankingTitle">当前赛区排名</h2></div><span class="schedule-count" id="qualifierCountLabel"></span></div>
        <div class="season-recap" id="qualifierRecap"></div>
        <p class="schedule-source">数据来源：<a href="https://bbs.robomaster.com/article/1883355" target="_blank" rel="noopener">RoboMaster 社区赛果记录</a>　·　回放来源：<a href="https://space.bilibili.com/20554233" target="_blank" rel="noopener">RoboMaster机甲大师 B 站官方空间</a><br>只有通过年份、赛区、场次和双方战队核验的视频才显示“直接看回放”；未确认的场次不显示链接。“待核”数据可能存在比分、红蓝方或赛程顺序不明。</p>
      </section>
    </div>
  </div>

  <script>
    const payload = {payload_json};
    const baseColumns = ["赛区", "学校", "战队", "兵种"];
    const metricPriority = [
      "自瞄命中综合",
      "火力输出综合",
      "小弹丸命中率",
      "大弹丸命中率",
      "KDA得分",
      "对敌伤害量",
      "建筑伤害",
      "击杀数",
      "场均发弹量",
      "局均组装经济数",
      "局均组装成功次数",
      "局均兑换经济数",
      "总场次飞镖分数",
      "局均雷达分数",
      "MVP次数",
      "雷达反制时长",
      "雷达解算成功次数",
      "双倍易伤时间",
      "累计移动靶末端命中数",
    ];
    const effectiveZeroMetricColumns = new Set([
      "累计移动靶末端命中数",
      "总场次飞镖分数",
      "局均雷达分数",
      "MVP次数",
    ]);
    const radarAxes = [
      {{ type: "英雄", metricKey: "对敌伤害量", fallbackMetricKeys: ["建筑伤害"], metricLabel: "局均总伤害" }},
      {{ type: "步兵", metricKey: "对敌伤害量", metricLabel: "局均总伤害" }},
      {{ type: "哨兵", metricKey: "对敌伤害量", metricLabel: "局均总伤害" }},
      {{ type: "无人机", metricKey: "对敌伤害量", metricLabel: "局均总伤害" }},
      {{ type: "雷达", metricKey: "局均雷达分数", fallbackMetricKeys: ["双倍易伤时间"], metricLabel: "局均雷达分数" }},
      {{ type: "工程", metricKey: "局均组装经济数", fallbackMetricKeys: ["局均兑换经济数"], metricLabel: "局均工程经济" }},
      {{ type: "飞镖", metricKey: "总场次飞镖分数", fallbackMetricKeys: ["建筑伤害"], metricLabel: "总场次飞镖分数" }},
    ];
    const mvpRadarAxes = [
      {{ type: "英雄", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "步兵3", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "步兵4", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "哨兵", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "无人机", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "雷达", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "工程", metricKey: "MVP次数", metricLabel: "MVP次数" }},
      {{ type: "飞镖", metricKey: "MVP次数", metricLabel: "MVP次数" }},
    ];
    const league3v3Types = ["英雄", "步兵", "哨兵"];
    const radarScaleSteps = [0.6, 1, 2, 3];

    const compareMaxTeams = 8;
    const comparePalette = [
      "#ff5c32", "#37d8ff", "#33f5b4", "#ffd166",
      "#a78bfa", "#f472b6", "#60a5fa", "#f97316"
    ];

    let state = {{
      selectedZones: payload.initialZone && payload.initialZone !== "全部" ? [payload.initialZone] : [],
      selectedType: payload.initialType || "全部",
      metric: payload.defaultMetric || "",
      direction: "desc",
      keyword: payload.initialKeyword || "",
      limit: 50,
      activeSortColumn: payload.defaultMetric || "",
      activeSortDirection: "desc",
      tableTypePage: "",

      compareSelections: [],
      compareZone: payload.initialZone && payload.initialZone !== "全部" ? payload.initialZone : "",
      compareKeyword: "",
    }};
    let insightTypewriterRun = 0;

    const els = {{
      heroTitle: document.getElementById("heroTitle"),
      heroSubtitle: document.getElementById("heroSubtitle"),
      teamCount: document.getElementById("teamCount"),
      zoneCount: document.getElementById("zoneCount"),
      typeCount: document.getElementById("typeCount"),
      avgMetric: document.getElementById("avgMetric"),
      searchInput: document.getElementById("searchInput"),
      zoneChecklist: document.getElementById("zoneChecklist"),
      typeSelect: document.getElementById("typeSelect"),
      metricSelect: document.getElementById("metricSelect"),
      sortDirection: document.getElementById("sortDirection"),
      rowLimit: document.getElementById("rowLimit"),
      tableHead: document.getElementById("tableHead"),
      tableBody: document.getElementById("tableBody"),
      tableTitle: document.getElementById("tableTitle"),
      tableMeta: document.getElementById("tableMeta"),
      chartGrid: document.getElementById("chartGrid"),
      tacticalBrief: document.getElementById("tacticalBrief"),
      tableTypePages: document.getElementById("tableTypePages"),
      belowTableGrid: document.getElementById("belowTableGrid"),
      emptyState: document.getElementById("emptyState"),
      themeToggle: document.getElementById("themeToggle"),
      backgroundToggle: document.getElementById("backgroundToggle"),
      densityToggle: document.getElementById("densityToggle"),

      compareZoneSelect: document.getElementById("compareZoneSelect"),
      compareSearchInput: document.getElementById("compareSearchInput"),
      compareTeamSelect: document.getElementById("compareTeamSelect"),
      compareAddButton: document.getElementById("compareAddButton"),
      compareClearButton: document.getElementById("compareClearButton"),
      compareTray: document.getElementById("compareTray"),
      compareCap: document.getElementById("compareCap"),
    }};

    els.searchInput.value = state.keyword;

    function formatValue(value) {{
      if (value === null || value === undefined || value === "") return "-";
      if (typeof value === "number") {{
        const fixed = Number.isInteger(value) ? value.toString() : value.toFixed(2);
        return fixed.replace(/\\.00$/, "");
      }}
      return String(value);
    }}

    function escapeHtml(value) {{
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function formatPercent(value) {{
      if (value === null || value === undefined || !Number.isFinite(value)) return "-";
      return `${{Math.round(value * 100)}}%`;
    }}

    function getTeamKey(row) {{
      return [row["学校"] || "", row["战队"] || ""]
        .map((value) => String(value).trim())
        .join("::");
    }}

    function getTeamLabel(row) {{
      return [row["学校"], row["战队"]].filter(Boolean).join(" / ") || "未知队伍";
    }}

    function is3v3LeagueZone(zoneName) {{
      if (!zoneName || zoneName === "全部") return false;
      const normalized = String(zoneName).toLowerCase().replace(/\\s+/g, "");
      return normalized.includes("3v3联盟赛") || normalized.includes("3vs3联盟赛");
    }}

    function getSelectedZones() {{
      return state.selectedZones.filter((zone) => payload.zones.includes(zone));
    }}

    function getSelectedZoneLabel() {{
      const zones = getSelectedZones();
      if (!zones.length) return "全部赛区";
      if (zones.length === 1) return zones[0];
      return `${{zones.length}} 个赛区`;
    }}

    function getAllowedTypesForZone(zoneName) {{
      return is3v3LeagueZone(zoneName) ? league3v3Types : payload.types;
    }}

    function getAllowedTypesForSelectedZones() {{
      const zones = getSelectedZones();
      if (zones.length > 0 && zones.every((zone) => is3v3LeagueZone(zone))) {{
        return league3v3Types;
      }}
      return payload.types;
    }}

    function getRadarAxesForZone(zoneName) {{
      if (!is3v3LeagueZone(zoneName)) return radarAxes;
      return radarAxes.filter((axis) => league3v3Types.includes(axis.type));
    }}

    function getRadarShapeLabel(zoneName) {{
      return is3v3LeagueZone(zoneName) ? "三角形雷达图" : "七边形雷达图";
    }}

    function getZoneRows(zoneName) {{
      if (!zoneName || zoneName === "全部") return [];
      const allowedTypes = getAllowedTypesForZone(zoneName);
      return payload.rows.filter((row) => row["赛区"] === zoneName && allowedTypes.includes(row["兵种"]));
    }}

    function getMvpRows() {{
      return Array.isArray(payload.mvpRows) ? payload.mvpRows : [];
    }}

    function getMvpZoneRows(zoneName) {{
      if (!zoneName || zoneName === "全部") return [];
      return getMvpRows().filter((row) => row["赛区"] === zoneName);
    }}

    function getSingleTeamCandidate(rows) {{
      if (!rows.length) return null;

      const zones = new Set(rows.map((row) => row["赛区"]).filter(Boolean));
      if (zones.size !== 1) return null;

      const teamMap = new Map();
      rows.forEach((row) => {{
        const key = getTeamKey(row);
        if (!key.trim()) return;
        if (!teamMap.has(key)) {{
          teamMap.set(key, {{
            key,
            label: getTeamLabel(row),
            zone: row["赛区"],
          }});
        }}
      }});

      if (teamMap.size !== 1) return null;
      return Array.from(teamMap.values())[0];
    }}

    function getFiniteNumber(row, column) {{
      const value = row ? row[column] : null;
      return typeof value === "number" && Number.isFinite(value) ? value : null;
    }}

    const virtualMetricColumns = ["自瞄命中综合", "火力输出综合"];
    const attackTypes = new Set(["英雄", "步兵", "哨兵", "无人机"]);

    function getAimHitValue(row) {{
      const type = row ? row["兵种"] : "";
      if (type === "英雄") return getFiniteNumber(row, "大弹丸命中率");
      if (type === "步兵" || type === "哨兵" || type === "无人机") return getFiniteNumber(row, "小弹丸命中率");
      return null;
    }}

    function getFireRawValue(row) {{
      const type = row ? row["兵种"] : "";
      if (!attackTypes.has(type)) return null;
      if (type === "英雄") {{
        return getFiniteNumber(row, "建筑伤害")
          ?? getFiniteNumber(row, "击杀数")
          ?? getFiniteNumber(row, "场均击杀数");
      }}
      return getFiniteNumber(row, "对敌伤害量")
        ?? getFiniteNumber(row, "建筑伤害")
        ?? getFiniteNumber(row, "击杀数")
        ?? getFiniteNumber(row, "场均击杀数");
    }}

    function buildAverageMap(rows, valueGetter) {{
      const bucket = new Map();
      rows.forEach((row) => {{
        const value = valueGetter(row);
        if (typeof value !== "number" || !Number.isFinite(value)) return;
        const key = `${{row["赛区"] || "全部"}}::${{row["兵种"] || "未知兵种"}}`;
        if (!bucket.has(key)) bucket.set(key, []);
        bucket.get(key).push(value);
      }});
      const averageMap = new Map();
      bucket.forEach((values, key) => {{
        const avg = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
        averageMap.set(key, avg);
      }});
      return averageMap;
    }}

    function initializeVirtualMetrics() {{
      virtualMetricColumns.forEach((column) => {{
        if (!payload.columns.includes(column)) payload.columns.push(column);
      }});

      const fireAverageMap = buildAverageMap(payload.rows, getFireRawValue);
      payload.rows.forEach((row) => {{
        row["自瞄命中综合"] = getAimHitValue(row);
        const rawFire = getFireRawValue(row);
        const fireKey = `${{row["赛区"] || "全部"}}::${{row["兵种"] || "未知兵种"}}`;
        const fireAvg = fireAverageMap.get(fireKey);
        row["火力输出综合"] = (typeof rawFire === "number" && Number.isFinite(rawFire) && fireAvg && fireAvg > 0)
          ? (rawFire / fireAvg) * 100
          : null;
      }});
    }}

    function calculateDartScore(row) {{
      const weights = [
        ["累计命中前哨站数", 1],
        ["累计命中固定靶数", 5],
        ["累计随机固定靶数", 10],
        ["累计随机移动靶数", 100],
        ["累计移动靶末端命中数", 200],
      ];
      let hasValue = false;
      let total = 0;
      weights.forEach(([column, weight]) => {{
        const value = getFiniteNumber(row, column);
        if (value === null) return;
        hasValue = true;
        total += value * weight;
      }});
      return hasValue ? total : null;
    }}

    function calculateRadarScore(row) {{
      const markerTime = getFiniteNumber(row, "双倍易伤时间");
      const counterTime = getFiniteNumber(row, "雷达反制时长");
      const parseScore = getFiniteNumber(row, "雷达解算成功次数");
      if (markerTime === null && counterTime === null && parseScore === null) return null;
      return (markerTime || 0) + ((counterTime || 0) / 45 * 20) + ((parseScore || 0) * 200);
    }}

    function getAxisMetricValue(row, axis) {{
      if (!row) return null;
      if (axis.metricKey === "总场次飞镖分数") {{
        const value = getFiniteNumber(row, "总场次飞镖分数");
        return value === null ? calculateDartScore(row) : value;
      }}
      if (axis.metricKey === "局均雷达分数") {{
        const value = getFiniteNumber(row, "局均雷达分数");
        return value === null ? calculateRadarScore(row) : value;
      }}

      const metricKeys = [axis.metricKey, ...(axis.fallbackMetricKeys || [])];
      for (const key of metricKeys) {{
        const value = row[key];
        if (typeof value === "number" && Number.isFinite(value)) {{
          return value;
        }}
      }}
      return null;
    }}

    function buildRadarModel(teamKey, zoneName) {{
      const zoneRows = getZoneRows(zoneName);
      if (!zoneRows.length) return null;

      const teamRows = zoneRows.filter((row) => getTeamKey(row) === teamKey);
      if (!teamRows.length) return null;

      const teamLabel = getTeamLabel(teamRows[0]);
      const axes = getRadarAxesForZone(zoneName).map((axis) => {{
        const zoneTypeRows = zoneRows.filter((row) => row["兵种"] === axis.type);
        const teamRow = teamRows.find((row) => row["兵种"] === axis.type);
        const zoneValues = zoneTypeRows
          .map((row) => getAxisMetricValue(row, axis))
          .filter((value) => value !== null);
        const zoneAverage = zoneValues.length
          ? zoneValues.reduce((sum, value) => sum + value, 0) / zoneValues.length
          : null;
        const teamValue = getAxisMetricValue(teamRow, axis);

        let ratio = null;
        if (teamValue !== null && zoneAverage !== null) {{
          ratio = zoneAverage === 0 ? 0 : teamValue / zoneAverage;
        }}

        return {{
          ...axis,
          teamValue,
          zoneAverage,
          ratio,
          clippedRatio: ratio === null ? 0 : Math.max(0, Math.min(ratio, 3)),
          overflow: ratio !== null && ratio > 3,
        }};
      }});

      return {{ teamLabel, zoneName, axes, shapeLabel: getRadarShapeLabel(zoneName) }};
    }}

    function buildMvpRadarModel(teamKey, zoneName) {{
      const zoneRows = getMvpZoneRows(zoneName);
      if (!zoneRows.length) return null;

      const teamRows = zoneRows.filter((row) => getTeamKey(row) === teamKey);
      if (!teamRows.length) return null;

      const teamLabel = getTeamLabel(teamRows[0]);
      const teamValueByType = new Map();
      mvpRadarAxes.forEach((axis) => {{
        const row = teamRows.find((item) => item["兵种"] === axis.type);
        teamValueByType.set(axis.type, getFiniteNumber(row, "MVP次数") || 0);
      }});
      const teamTotal = Array.from(teamValueByType.values()).reduce((sum, value) => sum + value, 0);
      const teamAverage = teamTotal / mvpRadarAxes.length;
      const axes = mvpRadarAxes.map((axis) => {{
        const teamValue = teamValueByType.get(axis.type) || 0;
        const baseline = teamTotal > 0 ? teamAverage : null;

        let ratio = null;
        if (baseline !== null) {{
          ratio = baseline === 0 ? 0 : teamValue / baseline;
        }}

        return {{
          ...axis,
          teamValue,
          zoneAverage: baseline,
          ratio,
          clippedRatio: ratio === null ? 0 : Math.max(0, Math.min(ratio, 3)),
          overflow: ratio !== null && ratio > 3,
          zoneAverageLabel: "队内均值",
        }};
      }});

      return {{
        teamLabel,
        zoneName,
        axes,
        shapeLabel: "MVP八边形雷达图",
        eyebrow: "MVP RADAR",
        title: `${{teamLabel}} MVP八边形雷达图`,
        description: `${{zoneName}}赛区 MVP 次数分布；每个轴按该队 8 个兵种 MVP 次数的队内均值归一化。`,
        gradientId: "mvpRadarAreaFill",
        legendChips: [
          "等高线: 60% / 100% / 200% / 300%",
          "100% = 该队 8 个兵种 MVP 总数 / 8",
        ],
        noteText: "注: MVP 图展示队内 MVP 分布比例；轴值 = 该兵种 MVP 次数 /（该队 8 个兵种 MVP 总数 / 8）。",
      }};
    }}

    function getRadarPoint(index, ratio, center, radius, count) {{
      const angle = (-Math.PI / 2) + (Math.PI * 2 * index) / count;
      const scaled = (ratio / 3) * radius;
      return {{
        x: center + Math.cos(angle) * scaled,
        y: center + Math.sin(angle) * scaled,
        angle,
      }};
    }}

    function renderRadarCard(radar) {{
      if (!radar) {{
        return `
          <article class="chart-card radar-card">
            <div class="radar-header">
              <div>
                <h3>综合雷达图</h3>
                <p>当前筛选没有足够的数据来生成赛区对比雷达图。</p>
              </div>
            </div>
          </article>
        `;
      }}

      const eyebrow = radar.eyebrow || "ZONE RADAR";
      const radarTitle = radar.title || `${{radar.teamLabel}} ${{radar.shapeLabel}}`;
      const radarDescription = radar.description || `${{radar.zoneName}}赛区基线下的兵种综合水平，100% 表示该赛区该兵种均值。`;
      const gradientId = radar.gradientId || "radarAreaFill";
      const legendChips = radar.legendChips || [
        "等高线: 60% / 100% / 200% / 300%",
        "100% = 该赛区对应兵种均值",
      ];
      const size = 420;
      const center = size / 2;
      const radius = 146;
      const axisCount = radar.axes.length;
      const gridPolygons = radarScaleSteps.map((step) => {{
        const points = radar.axes.map((_, index) => {{
          const point = getRadarPoint(index, step, center, radius, axisCount);
          return `${{point.x.toFixed(2)}},${{point.y.toFixed(2)}}`;
        }}).join(" ");
        return {{ step, points }};
      }});

      const areaPoints = radar.axes.map((axis, index) => {{
        const point = getRadarPoint(index, axis.clippedRatio, center, radius, axisCount);
        return `${{point.x.toFixed(2)}},${{point.y.toFixed(2)}}`;
      }}).join(" ");

      const axisMarkup = radar.axes.map((axis, index) => {{
        const outer = getRadarPoint(index, 3, center, radius, axisCount);
        const label = getRadarPoint(index, 3.32, center, radius, axisCount);
        const dot = getRadarPoint(index, axis.clippedRatio, center, radius, axisCount);
        const anchor = label.x < center - 20 ? "end" : (label.x > center + 20 ? "start" : "middle");
        return `
          <line x1="${{center}}" y1="${{center}}" x2="${{outer.x}}" y2="${{outer.y}}" stroke="var(--line)" stroke-width="1" />
          <circle cx="${{dot.x}}" cy="${{dot.y}}" r="4.5" fill="var(--accent-deep)" />
          <text x="${{label.x}}" y="${{label.y}}" text-anchor="${{anchor}}" font-size="13" fill="var(--text)">${{escapeHtml(axis.type)}}</text>
        `;
      }}).join("");

      const scaleMarkup = radarScaleSteps.map((step) => {{
        const y = center - (step / 3) * radius;
        return `
          <text x="${{center + 10}}" y="${{y + 4}}" font-size="11" fill="var(--muted)">
            ${{Math.round(step * 100)}}%
          </text>
        `;
      }}).join("");

      const overflowAxes = radar.axes.filter((axis) => axis.overflow).map((axis) => axis.type);
      const defaultNoteText = overflowAxes.length
        ? `注: ${{overflowAxes.join("、")}} 超过 300% 均值，图形按外圈封顶显示。`
        : (radar.axes.length === 3
          ? "注: 3V3 联盟赛仅展示英雄、步兵、哨兵，三条轴都按局均总伤害计算。"
          : "注: 英雄、步兵、哨兵、无人机按局均总伤害，雷达按局均雷达分数，工程优先按局均组装经济，飞镖按总场次飞镖分数。");
      const noteText = radar.noteText || defaultNoteText;

      return `
        <article class="chart-card radar-card">
          <div class="radar-header">
            <div>
              <span class="eyebrow">${{escapeHtml(eyebrow)}}</span>
              <h3>${{escapeHtml(radarTitle)}}</h3>
              <p>${{escapeHtml(radarDescription)}}</p>
            </div>
          </div>
          <div class="radar-layout">
            <div class="radar-stage">
              <div class="radar-legend">
                ${{legendChips.map((chip) => `<span class="legend-chip">${{escapeHtml(chip)}}</span>`).join("")}}
              </div>
              <svg class="radar-svg" viewBox="0 0 ${{size}} ${{size}}" role="img" aria-label="${{escapeHtml(radarTitle)}}">
                <defs>
                  <linearGradient id="${{escapeHtml(gradientId)}}" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stop-color="#d88457" stop-opacity="0.45" />
                    <stop offset="100%" stop-color="#b85c38" stop-opacity="0.22" />
                  </linearGradient>
                </defs>
                <polygon points="${{gridPolygons[3].points}}" fill="rgba(212,168,74,0.05)" stroke="#c9a227" stroke-width="2.4" />
                ${{gridPolygons.slice(0, 3).map((grid, index) => `
                  <polygon
                    points="${{grid.points}}"
                    fill="none"
                    stroke="${{grid.step === 1 ? "#c83f2b" : `rgba(143,59,31,${{index === 1 ? 0.24 : 0.18}})`}}"
                    stroke-width="${{grid.step === 1 ? 2.8 : 1}}"
                    stroke-dasharray="${{grid.step === 0.6 ? "4 4" : "none"}}"
                  />
                `).join("")}}
                ${{axisMarkup}}
                <polygon points="${{areaPoints}}" fill="url(#${{escapeHtml(gradientId)}})" stroke="#b85c38" stroke-width="3" />
                ${{scaleMarkup}}
              </svg>
              <div class="radar-note">${{escapeHtml(noteText)}}</div>
            </div>
            <aside class="radar-side">
              <div class="summary-title">维度明细</div>
              <div class="axis-list">
                ${{radar.axes.map((axis) => `
                  <article class="axis-card">
                    <div class="axis-top">
                      <div class="axis-name">${{escapeHtml(axis.type)}}</div>
                      <div class="axis-ratio">${{axis.ratio === null ? "缺数据" : escapeHtml(formatPercent(axis.ratio))}}</div>
                    </div>
                    <div class="axis-meta">
                      队伍${{escapeHtml(axis.metricLabel)}}: ${{escapeHtml(formatValue(axis.teamValue))}}<br>
                      ${{escapeHtml(axis.zoneAverageLabel || "赛区均值")}}: ${{escapeHtml(formatValue(axis.zoneAverage))}}
                    </div>
                  </article>
                `).join("")}}
              </div>
            </aside>
          </div>
        </article>
      `;
    }}

    function getMetricColumns() {{
      return payload.columns.filter((column) => !baseColumns.includes(column));
    }}

    function getFilteredRows() {{
      let rows = payload.rows.slice();
      const selectedZones = getSelectedZones();

      if (selectedZones.length) {{
        rows = rows.filter((row) => selectedZones.includes(row["赛区"]));
        rows = rows.filter((row) => !is3v3LeagueZone(row["赛区"]) || league3v3Types.includes(row["兵种"]));
      }}

      if (state.selectedType !== "全部") {{
        rows = rows.filter((row) => row["兵种"] === state.selectedType);
      }}

      if (state.keyword) {{
        const keywords = state.keyword.toLowerCase().split(/\\s+/).filter(Boolean);
        rows = rows.filter((row) => {{
          const haystack = payload.columns
            .map((column) => row[column])
            .filter((value) => value !== null && value !== undefined)
            .join(" ")
            .toLowerCase();
          return keywords.some((keyword) => haystack.includes(keyword));
        }});
      }}

      return rows;
    }}

    function hasData(value) {{
      return value !== null && value !== undefined && value !== "";
    }}

    function hasMetricData(column, value) {{
      if (!hasData(value)) return false;
      if (effectiveZeroMetricColumns.has(column)) return true;
      if (typeof value === "number") return Number.isFinite(value) && value !== 0;
      return true;
    }}

    function getVisibleColumns(rows) {{
      const metricColumns = getMetricColumns().filter((column) =>
        rows.some((row) => hasMetricData(column, row[column]))
      );
      return [...baseColumns, ...metricColumns];
    }}

    function getCurrentTableMetric() {{
      if (state.activeSortColumn && !baseColumns.includes(state.activeSortColumn)) {{
        return state.activeSortColumn;
      }}
      return state.metric && !baseColumns.includes(state.metric) ? state.metric : "";
    }}

    function getTablePageTypes() {{
      const selectedZones = getSelectedZones();
      if (selectedZones.length && selectedZones.every((zone) => is3v3LeagueZone(zone))) {{
        return league3v3Types.slice();
      }}
      return radarAxes.map((axis) => axis.type);
    }}

    function pickTablePageForMetric(rows, metric) {{
      if (!metric) return "";
      return getTablePageTypes().find((type) =>
        rows.some((row) => row["兵种"] === type && hasMetricData(metric, row[metric]))
      ) || "";
    }}

    function focusTablePageForMetric(metric) {{
      if (state.selectedType !== "全部") return;
      const rows = getFilteredRows();
      const currentPageHasMetric = rows.some((row) =>
        row["兵种"] === state.tableTypePage && hasMetricData(metric, row[metric])
      );
      if (!currentPageHasMetric) {{
        state.tableTypePage = pickTablePageForMetric(rows, metric) || state.tableTypePage;
      }}
    }}

    function renderTableTypePages(filteredRows) {{
      if (state.selectedType !== "全部") {{
        els.tableTypePages.hidden = true;
        els.tableTypePages.innerHTML = "";
        return filteredRows;
      }}

      const pageTypes = getTablePageTypes();
      if (!pageTypes.includes(state.tableTypePage)) {{
        state.tableTypePage = pickTablePageForMetric(filteredRows, getCurrentTableMetric()) || pageTypes[0] || "";
      }}

      els.tableTypePages.hidden = false;
      els.tableTypePages.innerHTML = pageTypes.map((type) => {{
        const count = filteredRows.filter((row) => row["兵种"] === type).length;
        const active = type === state.tableTypePage;
        return `
          <button
            class="table-type-page ${{active ? "active" : ""}}"
            type="button"
            role="tab"
            aria-selected="${{active ? "true" : "false"}}"
            data-table-type-page="${{escapeHtml(type)}}"
          >
            ${{escapeHtml(type)}}页 <span>${{count}}</span>
          </button>
        `;
      }}).join("");

      els.tableTypePages.querySelectorAll("[data-table-type-page]").forEach((button) => {{
        button.addEventListener("click", () => {{
          state.tableTypePage = button.dataset.tableTypePage;
          render();
        }});
      }});

      return filteredRows.filter((row) => row["兵种"] === state.tableTypePage);
    }}

    function getTableVisibleColumns(rows) {{
      const columns = getVisibleColumns(rows);
      const activeMetric = getCurrentTableMetric();
      if (activeMetric && payload.columns.includes(activeMetric) && !columns.includes(activeMetric)) {{
        columns.push(activeMetric);
      }}
      return columns;
    }}

    function orderTableColumns(columns, activeMetric) {{
      if (!activeMetric || !columns.includes(activeMetric)) return columns.slice();
      const ordered = columns.filter((column) => column !== activeMetric);
      const teamIndex = ordered.indexOf("战队");
      ordered.splice(teamIndex >= 0 ? teamIndex + 1 : 0, 0, activeMetric);
      return ordered;
    }}

    function pickMetric(metrics) {{
      if (state.metric && metrics.includes(state.metric)) {{
        return state.metric;
      }}
      if (state.activeSortColumn && metrics.includes(state.activeSortColumn)) {{
        return state.activeSortColumn;
      }}
      for (const column of metricPriority) {{
        if (metrics.includes(column)) return column;
      }}
      return metrics[0] || "";
    }}

    function sortRows(rows, columns) {{
      const fallbackMetric = pickMetric(columns.filter((column) => !baseColumns.includes(column)));
      if (!columns.includes(state.activeSortColumn)) {{
        state.activeSortColumn = columns.includes(fallbackMetric) ? fallbackMetric : "赛区";
        state.activeSortDirection = columns.includes(state.activeSortColumn) && !baseColumns.includes(state.activeSortColumn)
          ? state.direction
          : "asc";
      }}

      const sortColumn = state.activeSortColumn || state.metric;
      const direction = state.activeSortDirection || state.direction;

      rows.sort((left, right) => {{
        const a = left[sortColumn];
        const b = right[sortColumn];
        const aIsNumber = typeof a === "number";
        const bIsNumber = typeof b === "number";
        const sortIsMetric = !baseColumns.includes(sortColumn);

        if (sortIsMetric && aIsNumber !== bIsNumber) {{
          // Sorting metric columns should keep rows with actual numeric data ahead of blanks.
          return aIsNumber ? -1 : 1;
        }}

        if (aIsNumber && bIsNumber) {{
          return direction === "asc" ? a - b : b - a;
        }}

        const aText = (a ?? "").toString();
        const bText = (b ?? "").toString();
        return direction === "asc"
          ? aText.localeCompare(bText, "zh-CN")
          : bText.localeCompare(aText, "zh-CN");
      }});

      return rows;
    }}

    function getVisibleRows(filteredRows, columns) {{
      const rows = sortRows(filteredRows.slice(), columns);

      return rows.slice(0, state.limit);
    }}

    function renderSelectOptions(selectEl, options, selectedValue) {{
      selectEl.innerHTML = options.map((option) => `
        <option value="${{escapeHtml(option)}}" ${{option === selectedValue ? "selected" : ""}}>
          ${{escapeHtml(option)}}
        </option>
      `).join("");
    }}

    function renderMetricSelect(rows) {{
      const metrics = getVisibleColumns(rows).filter((column) => !baseColumns.includes(column));
      state.metric = pickMetric(metrics);
      if (!metrics.includes(state.activeSortColumn)) {{
        state.activeSortColumn = state.metric;
        state.activeSortDirection = state.direction;
      }}

      els.metricSelect.innerHTML = metrics.map((metric) => `
        <option value="${{escapeHtml(metric)}}" ${{metric === state.metric ? "selected" : ""}}>
          ${{escapeHtml(metric)}}
        </option>
      `).join("");

      els.metricSelect.disabled = metrics.length === 0;
    }}

    function renderZoneChecklist() {{
      const selectedZones = new Set(getSelectedZones());
      const allSelected = selectedZones.size === 0;
      const options = [
        {{ value: "全部", label: "全部赛区", checked: allSelected }},
        ...payload.zones.map((zone) => ({{
          value: zone,
          label: zone,
          checked: selectedZones.has(zone),
        }})),
      ];

      els.zoneChecklist.innerHTML = options.map((option) => `
        <label class="zone-option ${{option.checked ? "active" : ""}}" title="${{escapeHtml(option.label)}}">
          <input type="checkbox" value="${{escapeHtml(option.value)}}" ${{option.checked ? "checked" : ""}}>
          <span>${{escapeHtml(option.label)}}</span>
        </label>
      `).join("");

      els.zoneChecklist.querySelectorAll("input").forEach((input) => {{
        input.addEventListener("change", () => {{
          if (input.value === "全部") {{
            state.selectedZones = [];
          }} else {{
            const nextZones = new Set(getSelectedZones());
            if (input.checked) {{
              nextZones.add(input.value);
            }} else {{
              nextZones.delete(input.value);
            }}
            state.selectedZones = Array.from(nextZones);
          }}
          render();
        }});
      }});
    }}

    function renderFilterSelects() {{
      state.selectedZones = getSelectedZones();
      const types = ["全部", ...getAllowedTypesForSelectedZones()];

      if (!types.includes(state.selectedType)) {{
        state.selectedType = "全部";
      }}

      renderZoneChecklist();
      renderSelectOptions(els.typeSelect, types, state.selectedType);
    }}

    function renderSummary(rows) {{
      const teams = new Set(rows.map((row) => row["战队"]).filter(Boolean));
      const zones = new Set(rows.map((row) => row["赛区"]).filter(Boolean));
      const types = new Set(rows.map((row) => row["兵种"]).filter(Boolean));
      const metricValues = rows
        .map((row) => row[state.metric])
        .filter((value) => typeof value === "number");

      const avgMetric = metricValues.length
        ? metricValues.reduce((sum, value) => sum + value, 0) / metricValues.length
        : null;

      els.teamCount.textContent = teams.size;
      els.zoneCount.textContent = zones.size;
      els.typeCount.textContent = types.size;
      els.avgMetric.textContent = avgMetric === null ? "-" : formatValue(avgMetric);
    }}



    function getMetricValues(rows, metric) {{
      if (!metric) return [];
      return rows
        .map((row) => row[metric])
        .filter((value) => typeof value === "number" && Number.isFinite(value));
    }}

    function getAverage(values) {{
      return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    }}

    function buildZoneAverageRanking(rows, metric) {{
      const zoneMap = new Map();
      rows.forEach((row) => {{
        const zone = row["赛区"] || "未知赛区";
        const value = row[metric];
        if (typeof value !== "number" || !Number.isFinite(value)) return;
        if (!zoneMap.has(zone)) zoneMap.set(zone, []);
        zoneMap.get(zone).push(value);
      }});
      return Array.from(zoneMap.entries())
        .map(([zone, values]) => ({{ zone, count: values.length, average: getAverage(values) }}))
        .filter((item) => item.average !== null)
        .sort((left, right) => state.activeSortDirection === "asc" ? left.average - right.average : right.average - left.average);
    }}

    function getDominantType(rows) {{
      const typeMap = new Map();
      rows.forEach((row) => {{
        const type = row["兵种"] || "未知兵种";
        typeMap.set(type, (typeMap.get(type) || 0) + 1);
      }});
      return Array.from(typeMap.entries()).sort((a, b) => b[1] - a[1])[0] || null;
    }}

    function renderMetricPresets(visibleColumns) {{
      document.querySelectorAll("[data-metric-preset]").forEach((button) => {{
        const metric = button.dataset.metricPreset;
        const enabled = visibleColumns.includes(metric);
        button.disabled = !enabled;
        button.classList.toggle("active", metric === state.activeSortColumn || metric === state.metric);
        button.style.opacity = enabled ? "1" : "0.42";
        const presetHint = metric === "自瞄命中综合"
          ? "英雄使用大弹丸命中率；步兵、哨兵、无人机使用小弹丸命中率"
          : (metric === "火力输出综合"
            ? "覆盖英雄、步兵、哨兵、无人机；飞镖单独归入飞镖打击"
            : `切换到：${{metric}}`);
        button.title = enabled ? presetHint : `当前筛选下没有“${{metric}}”数据`;
      }});
    }}

    function renderTacticalBrief(filteredRows, sortedRows, visibleColumns) {{
      const metric = state.activeSortColumn && !baseColumns.includes(state.activeSortColumn)
        ? state.activeSortColumn
        : state.metric;
      const selectedZones = getSelectedZones();
      const singleTeam = getSingleTeamCandidate(filteredRows);
      const metricValues = getMetricValues(filteredRows, metric);
      const avg = getAverage(metricValues);
      const topRow = sortedRows.find((row) => typeof row[metric] === "number" && Number.isFinite(row[metric])) || sortedRows[0];
      const topLabel = topRow ? getTeamLabel(topRow) : "暂无队伍";
      const topValue = topRow && typeof topRow[metric] === "number" ? formatValue(topRow[metric]) : "-";
      const zoneRank = metric ? buildZoneAverageRanking(filteredRows, metric) : [];
      const bestZone = zoneRank[0];
      const dominantType = getDominantType(filteredRows);
      const sampleProfile = buildSampleProfile(filteredRows, metric);
      const chips = [
        `样本 ${{filteredRows.length}} 条`,
        `指标 ${{metric || "未选择"}}`,
        selectedZones.length ? `${{selectedZones.length}} 个赛区` : "全部赛区",
        state.selectedType !== "全部" ? state.selectedType : "全部兵种",
        `可信度 ${{sampleProfile.label}}`,
      ];

      const lines = [];
      if (!filteredRows.length) {{
        lines.push("当前筛选没有命中数据，优先检查搜索词、赛区和兵种是否同时卡得太死。");
      }} else if (singleTeam) {{
        const radar = buildRadarModel(singleTeam.key, singleTeam.zone);
        const mvpRadar = buildMvpRadarModel(singleTeam.key, singleTeam.zone);
        if (radar && radar.axes && radar.axes.length) {{
          const validAxes = radar.axes.filter((axis) => axis.ratio !== null && Number.isFinite(axis.ratio));
          const strongest = validAxes.slice().sort((a, b) => b.ratio - a.ratio)[0];
          const weakest = validAxes.slice().sort((a, b) => a.ratio - b.ratio)[0];
          if (strongest) lines.push(`该队伍在 <b>${{escapeHtml(strongest.type)}}</b> 轴最突出，约为赛区均值的 <b>${{escapeHtml(formatPercent(strongest.ratio))}}</b>。`);
          if (weakest && weakest !== strongest) lines.push(`短板更可能出现在 <b>${{escapeHtml(weakest.type)}}</b> 轴，约为赛区均值的 <b>${{escapeHtml(formatPercent(weakest.ratio))}}</b>，适合重点复盘。`);
        }}
        if (mvpRadar && mvpRadar.axes) {{
          const mvpTotal = mvpRadar.axes.reduce((sum, axis) => sum + (typeof axis.teamValue === "number" ? axis.teamValue : 0), 0);
          if (mvpTotal > 0) lines.push(`MVP 追踪共记录 <b>${{escapeHtml(formatValue(mvpTotal))}}</b> 次，说明这队不只是单项数据亮眼，也有实际对局贡献痕迹。`);
        }}
        if (!lines.length) lines.push("该队伍已锁定，但部分雷达/MVP维度缺数据，建议结合原始比赛录像或单兵表继续看。")
      }} else {{
        if (topRow) lines.push(`当前排序下首位是 <b>${{escapeHtml(topLabel)}}</b>，${{escapeHtml(metric || "当前指标")}} 为 <b>${{escapeHtml(topValue)}}</b>。`);
        if (bestZone && zoneRank.length > 1) lines.push(`<b>${{escapeHtml(bestZone.zone)}}</b> 在当前指标均值上领先，均值约 <b>${{escapeHtml(formatValue(bestZone.average))}}</b>，可优先看该赛区头部队伍。`);
        if (dominantType) lines.push(`当前样本里 <b>${{escapeHtml(dominantType[0])}}</b> 数量最多，共 <b>${{dominantType[1]}}</b> 条；如果想公平比较，建议再锁定单一兵种。`);
        if (avg !== null) lines.push(`当前指标均值约 <b>${{escapeHtml(formatValue(avg))}}</b>，表格高亮列可以快速看谁明显高于均线。`);
      }}

      if (sampleProfile.level !== "high") {{
        const sampleWarning = sampleProfile.warnings.length ? sampleProfile.warnings.join("、") : "有效样本还不算充足";
        lines.push(`当前筛选可信度为 <b>${{escapeHtml(sampleProfile.label)}}</b>：${{escapeHtml(sampleWarning)}}，结论建议作为排查线索。`);
      }}
      if (filteredRows.length > 80) {{
        lines.push("样本量比较大，建议切到紧凑视图，或者先用赛区/兵种筛选收窄，读表效率会高很多。");
      }}
      if (selectedZones.length > 1 && state.selectedType === "全部") {{
        lines.push("跨赛区 + 全兵种会把不同职责混在一起，看结论时最好把它当总览，不要直接当单兵强弱排名。")
      }}

      els.tacticalBrief.innerHTML = `
        <div class="brief-head">
          <div>
            <div class="brief-kicker">TACTICAL BRIEF</div>
            <h3 class="brief-title">当前筛选简要点评</h3>
          </div>
          <div class="brief-chips">
            ${{chips.map((chip) => `<span class="brief-chip">${{escapeHtml(chip)}}</span>`).join("")}}
          </div>
        </div>
        <div class="brief-body">
          ${{lines.slice(0, 6).map((line, index) => `
            <div class="brief-line">
              <span class="brief-icon">${{index + 1}}</span>
              <span>${{line}}</span>
            </div>
          `).join("")}}
        </div>
        <div class="brief-disclaimer">判断声明：页面里的“强势、短板、打法画像、总实力”等表述只基于当前公开统计口径和筛选条件，是辅助复盘用的个人数据判断，不代表官方排名，也不用于引战；关键结论仍建议结合录像、赛程强度、阵容变动和临场策略复核。</div>
      `;
      renderMetricPresets(visibleColumns);
    }}


    function renderZoneComparisonCard(rows) {{
      const selectedZones = getSelectedZones();
      if (selectedZones.length < 2 || !state.metric) return "";

      const zoneStats = selectedZones.map((zone) => {{
        const values = rows
          .filter((row) => row["赛区"] === zone)
          .map((row) => row[state.metric])
          .filter((value) => typeof value === "number" && Number.isFinite(value));
        const average = values.length
          ? values.reduce((sum, value) => sum + value, 0) / values.length
          : null;
        return {{ zone, average, count: values.length }};
      }}).filter((item) => item.average !== null);

      if (zoneStats.length < 2) return "";

      zoneStats.sort((left, right) => {{
        return state.activeSortDirection === "asc"
          ? left.average - right.average
          : right.average - left.average;
      }});

      const maxValue = Math.max(...zoneStats.map((item) => item.average), 0);
      return `
        <article class="chart-card">
          <h3>${{escapeHtml(state.metric)}} 赛区均值对比</h3>
          <p class="chart-subtitle">按当前筛选条件汇总所选赛区，每个条形使用该赛区当前指标的均值。</p>
          <div class="bar-list">
            ${{zoneStats.map((item, index) => {{
              const width = maxValue > 0
                ? Math.max(8, Math.min(100, Math.round((item.average / maxValue) * 100)))
                : 8;
              return `
                <div class="bar-item">
                  <div class="bar-rank">#${{index + 1}}</div>
                  <div class="bar-team" title="${{escapeHtml(item.zone)}}">${{escapeHtml(item.zone)}}</div>
                  <div class="bar-track" title="${{escapeHtml(`${{item.count}} 条记录`)}}">
                    <div class="bar-fill" style="width: ${{width}}%"></div>
                  </div>
                  <div class="bar-value">${{escapeHtml(formatValue(item.average))}}</div>
                </div>
              `;
            }}).join("")}}
          </div>
        </article>
      `;
    }}




    function normalizeCompareText(value) {{
      return String(value || "").trim().toLowerCase();
    }}

    function getCompareSelectionId(zone, key) {{
      return `${{zone}}@@${{key}}`;
    }}

    function getCompareCandidateRows() {{
      const zone = state.compareZone || payload.zones[0] || "";
      const keyword = normalizeCompareText(state.compareKeyword);
      const teamMap = new Map();
      payload.rows.forEach((row) => {{
        if (zone && row["赛区"] !== zone) return;
        if (!getAllowedTypesForZone(row["赛区"]).includes(row["兵种"])) return;
        const key = getTeamKey(row);
        if (!key.trim()) return;
        const label = getTeamLabel(row);
        const searchText = normalizeCompareText(`${{row["学校"] || ""}} ${{row["战队"] || ""}} ${{row["赛区"] || ""}}`);
        if (keyword && !searchText.includes(keyword)) return;
        if (!teamMap.has(key)) {{
          teamMap.set(key, {{
            key,
            zone: row["赛区"],
            label,
            school: row["学校"] || "",
            team: row["战队"] || "",
          }});
        }}
      }});
      return Array.from(teamMap.values()).sort((left, right) => left.label.localeCompare(right.label, "zh-Hans-CN"));
    }}

    function getCompareTeamModel(selection) {{
      const radar = buildRadarModel(selection.key, selection.zone);
      if (!radar || !Array.isArray(radar.axes)) return null;
      const validAxes = radar.axes.filter((axis) => typeof axis.ratio === "number" && Number.isFinite(axis.ratio));
      const avgRatio = validAxes.length
        ? validAxes.reduce((sum, axis) => sum + axis.ratio, 0) / validAxes.length
        : null;
      const strongest = validAxes.slice().sort((a, b) => b.ratio - a.ratio)[0] || null;
      const weakest = validAxes.slice().sort((a, b) => a.ratio - b.ratio)[0] || null;
      return {{
        ...selection,
        radar,
        validAxes,
        avgRatio,
        strongest,
        weakest,
      }};
    }}

    function buildCompareRadarModels() {{
      return state.compareSelections
        .map(getCompareTeamModel)
        .filter(Boolean);
    }}

    function renderCompareControls() {{
      if (!els.compareZoneSelect || !els.compareTeamSelect) return;
      const zones = payload.zones || [];
      const currentZone = state.compareZone && zones.includes(state.compareZone)
        ? state.compareZone
        : (getSelectedZones()[0] || zones[0] || "");
      state.compareZone = currentZone;
      els.compareZoneSelect.innerHTML = zones.map((zone) => `
        <option value="${{escapeHtml(zone)}}" ${{zone === currentZone ? "selected" : ""}}>${{escapeHtml(zone)}}</option>
      `).join("");

      const candidates = getCompareCandidateRows();
      els.compareTeamSelect.innerHTML = candidates.length
        ? candidates.map((item) => {{
          const id = getCompareSelectionId(item.zone, item.key);
          const alreadyAdded = state.compareSelections.some((selection) => selection.id === id);
          return `<option value="${{escapeHtml(id)}}" ${{alreadyAdded ? "disabled" : ""}}>${{escapeHtml(item.label)}}</option>`;
        }}).join("")
        : `<option value="">无匹配队伍</option>`;

      if (els.compareSearchInput && els.compareSearchInput.value !== state.compareKeyword) {{
        els.compareSearchInput.value = state.compareKeyword;
      }}

      if (els.compareCap) {{
        els.compareCap.textContent = `${{state.compareSelections.length}}/${{compareMaxTeams}}`;
      }}

      if (els.compareAddButton) {{
        els.compareAddButton.disabled = !candidates.length || state.compareSelections.length >= compareMaxTeams;
        els.compareAddButton.textContent = state.compareSelections.length >= compareMaxTeams ? "已满 8 支" : "加入比拼";
      }}

      if (els.compareClearButton) {{
        els.compareClearButton.disabled = state.compareSelections.length === 0;
      }}

      if (els.compareTray) {{
        els.compareTray.innerHTML = state.compareSelections.length
          ? state.compareSelections.map((selection, index) => `
            <span class="compare-chip" style="--dot:${{comparePalette[index % comparePalette.length]}}" title="${{escapeHtml(selection.zone)}}">
              <i></i><span>${{escapeHtml(selection.label)}}</span>
              <button type="button" data-remove-compare="${{escapeHtml(selection.id)}}" aria-label="移除 ${{escapeHtml(selection.label)}}">×</button>
            </span>
          `).join("")
          : `<span class="compare-hint">还没加入队伍。先选赛区，再搜学校/战队，点“加入比拼”。</span>`;
      }}
    }}

    function addCurrentCompareTeam() {{
      if (!els.compareTeamSelect) return;
      if (state.compareSelections.length >= compareMaxTeams) return;
      const selectedId = els.compareTeamSelect.value;
      if (!selectedId) return;
      if (state.compareSelections.some((selection) => selection.id === selectedId)) return;
      const candidates = getCompareCandidateRows();
      const candidate = candidates.find((item) => getCompareSelectionId(item.zone, item.key) === selectedId);
      if (!candidate) return;
      state.compareSelections.push({{
        id: selectedId,
        key: candidate.key,
        zone: candidate.zone,
        label: candidate.label,
      }});
      render();
    }}

    function removeCompareTeam(id) {{
      state.compareSelections = state.compareSelections.filter((selection) => selection.id !== id);
      render();
    }}

    function renderCompareRadarCard() {{
      const models = buildCompareRadarModels();
      if (!models.length) return "";

      const axisTypes = radarAxes.map((axis) => axis.type);
      const axisMeta = new Map(radarAxes.map((axis) => [axis.type, axis]));
      const size = 460;
      const center = size / 2;
      const radius = 158;
      const axisCount = axisTypes.length;
      const gridPolygons = radarScaleSteps.map((step) => {{
        const points = axisTypes.map((_, index) => {{
          const point = getRadarPoint(index, step, center, radius, axisCount);
          return `${{point.x.toFixed(2)}},${{point.y.toFixed(2)}}`;
        }}).join(" ");
        return {{ step, points }};
      }});
      const axisMarkup = axisTypes.map((type, index) => {{
        const outer = getRadarPoint(index, 3, center, radius, axisCount);
        const label = getRadarPoint(index, 3.36, center, radius, axisCount);
        const anchor = label.x < center - 20 ? "end" : (label.x > center + 20 ? "start" : "middle");
        return `
          <line x1="${{center}}" y1="${{center}}" x2="${{outer.x}}" y2="${{outer.y}}" stroke="var(--line)" stroke-width="1" />
          <text x="${{label.x}}" y="${{label.y}}" text-anchor="${{anchor}}" font-size="13" fill="var(--text)">${{escapeHtml(type)}}</text>
        `;
      }}).join("");
      const scaleMarkup = radarScaleSteps.map((step) => {{
        const y = center - (step / 3) * radius;
        return `<text x="${{center + 10}}" y="${{y + 4}}" font-size="11" fill="var(--muted)">${{Math.round(step * 100)}}%</text>`;
      }}).join("");
      const teamPolygons = models.map((model, index) => {{
        const axisByType = new Map(model.radar.axes.map((axis) => [axis.type, axis]));
        const color = comparePalette[index % comparePalette.length];
        const points = axisTypes.map((type, axisIndex) => {{
          const axis = axisByType.get(type);
          const ratio = axis && typeof axis.ratio === "number" && Number.isFinite(axis.ratio)
            ? Math.max(0, Math.min(axis.ratio, 3))
            : 0;
          const point = getRadarPoint(axisIndex, ratio, center, radius, axisCount);
          return `${{point.x.toFixed(2)}},${{point.y.toFixed(2)}}`;
        }}).join(" ");
        const dots = axisTypes.map((type, axisIndex) => {{
          const axis = axisByType.get(type);
          const ratio = axis && typeof axis.ratio === "number" && Number.isFinite(axis.ratio)
            ? Math.max(0, Math.min(axis.ratio, 3))
            : 0;
          if (ratio <= 0) return "";
          const point = getRadarPoint(axisIndex, ratio, center, radius, axisCount);
          return `<circle cx="${{point.x.toFixed(2)}}" cy="${{point.y.toFixed(2)}}" r="3.4" fill="${{color}}" />`;
        }}).join("");
        return `
          <polygon points="${{points}}" fill="${{color}}" fill-opacity="0.08" stroke="${{color}}" stroke-width="2.6" stroke-opacity="0.92" />
          ${{dots}}
        `;
      }}).join("");

      const sortedModels = models.slice().sort((left, right) => (right.avgRatio || 0) - (left.avgRatio || 0));
      const topModel = sortedModels[0];
      const overlapZones = new Set(models.map((model) => model.zone));
      const summaryLines = [];
      if (topModel && typeof topModel.avgRatio === "number") {{
        summaryLines.push(`综合均值最高的是 <b>${{escapeHtml(topModel.label)}}</b>，可用轴平均约 <b>${{escapeHtml(formatPercent(topModel.avgRatio))}}</b>。`);
      }}
      const strongLines = sortedModels.slice(0, 3).map((model) => {{
        if (!model.strongest) return null;
        return `<b>${{escapeHtml(model.label)}}</b> 的相对突出轴是 <b>${{escapeHtml(model.strongest.type)}}</b>（${{escapeHtml(formatPercent(model.strongest.ratio))}}）。`;
      }}).filter(Boolean);
      if (strongLines.length) summaryLines.push(strongLines.join(" "));
      if (overlapZones.size > 1) {{
        summaryLines.push("当前属于跨赛区对比，图中每支队伍都按自己所在赛区归一化，更适合看队内结构和相对均值，不适合写成绝对强弱。")
      }}
      if (models.length >= compareMaxTeams) {{
        summaryLines.push("已达到 8 支上限；继续比较建议先移除低关注队伍，避免雷达线过密影响读图。")
      }}

      return `
        <article class="chart-card compare-radar-card">
          <div class="radar-header">
            <div>
              <span class="eyebrow">TEAM COMPARE BAY</span>
              <h3>多队伍内部比拼雷达图</h3>
              <p>最多叠加 8 支队伍。每条线按“队伍该兵种关键指标 / 所在赛区同兵种均值”计算，100% 表示该赛区平均水平。</p>
            </div>
          </div>
          <div class="compare-radar-layout">
            <div class="compare-svg-wrap">
              <svg class="compare-svg" viewBox="0 0 ${{size}} ${{size}}" role="img" aria-label="多队伍内部比拼雷达图">
                <polygon points="${{gridPolygons[3].points}}" fill="rgba(212,168,74,0.04)" stroke="#c9a227" stroke-width="2.2" />
                ${{gridPolygons.slice(0, 3).map((grid, index) => `
                  <polygon
                    points="${{grid.points}}"
                    fill="none"
                    stroke="${{grid.step === 1 ? "#c83f2b" : `rgba(143,59,31,${{index === 1 ? 0.24 : 0.16}})`}}"
                    stroke-width="${{grid.step === 1 ? 2.5 : 1}}"
                    stroke-dasharray="${{grid.step === 0.6 ? "4 4" : "none"}}"
                  />
                `).join("")}}
                ${{axisMarkup}}
                ${{teamPolygons}}
                ${{scaleMarkup}}
              </svg>
            </div>
            <div>
              <div class="compare-legend">
                ${{models.map((model, index) => {{
                  const color = comparePalette[index % comparePalette.length];
                  const score = typeof model.avgRatio === "number" ? formatPercent(model.avgRatio) : "-";
                  return `
                    <div class="compare-legend-row" title="${{escapeHtml(model.zone)}}">
                      <i class="compare-color" style="--c:${{color}}"></i>
                      <span class="compare-name">${{escapeHtml(model.label)}} · ${{escapeHtml(model.zone)}}</span>
                      <span class="compare-score">${{escapeHtml(score)}}</span>
                    </div>
                  `;
                }}).join("")}}
              </div>
              <div class="compare-summary">
                ${{summaryLines.slice(0, 4).map((line, index) => `
                  <div class="compare-summary-line"><span class="brief-icon">${{index + 1}}</span><span>${{line}}</span></div>
                `).join("")}}
              </div>
              <div class="compare-disclaimer">免责声明：该比拼只基于当前公开统计口径和筛选条件，且跨赛区时已经按各自赛区均值归一化；它适合做侦察、复盘和选片线索，不代表官方排名，不用于引战。关键判断仍需结合录像、对手强度、赛程阶段、阵容变化和实际战术职责复核。</div>
            </div>
          </div>
        </article>
      `;
    }}

    function getCurrentAnalysisMetric() {{
      return state.activeSortColumn && !baseColumns.includes(state.activeSortColumn)
        ? state.activeSortColumn
        : (!baseColumns.includes(state.metric) ? state.metric : "");
    }}

    function buildSampleProfile(rows, metric) {{
      const total = rows.length;
      const numericValues = metric ? getMetricValues(rows, metric) : [];
      const coverage = total ? numericValues.length / total : 0;
      const teamCount = new Set(rows.map((row) => getTeamKey(row)).filter((key) => key && key.trim())).size;
      const zoneCount = new Set(rows.map((row) => row["赛区"]).filter(Boolean)).size;
      const typeCount = new Set(rows.map((row) => row["兵种"]).filter(Boolean)).size;
      const metricAverage = getAverage(numericValues);
      let level = "low";
      let label = "低可信";
      if (total >= 40 && numericValues.length >= 18 && coverage >= 0.55) {{
        level = "high";
        label = "高可信";
      }} else if (total >= 12 && numericValues.length >= 6 && coverage >= 0.35) {{
        level = "mid";
        label = "中可信";
      }}
      const warnings = [];
      if (total < 12) warnings.push("样本量偏小");
      if (coverage < 0.35) warnings.push("当前指标缺失较多");
      if (zoneCount > 1 && state.selectedType === "全部") warnings.push("跨赛区全兵种混排");
      if (typeCount > 1 && ["自瞄命中综合", "火力输出综合"].includes(metric)) warnings.push("综合指标已做兵种适配，但仍建议锁定兵种复核");
      return {{
        total,
        numericCount: numericValues.length,
        coverage,
        teamCount,
        zoneCount,
        typeCount,
        metricAverage,
        level,
        label,
        warnings,
      }};
    }}

    function getTeamDisplayLabel(row) {{
      return [row["学校"], row["战队"]].filter(Boolean).join(" / ") || "未知队伍";
    }}

    function getMetricOutliers(rows, metric, limit = 5) {{
      if (!metric) return [];
      const points = rows
        .map((row) => ({{ row, value: getFiniteNumber(row, metric) }}))
        .filter((item) => item.value !== null);
      if (points.length < 6) return [];
      const values = points.map((item) => item.value);
      const avg = getAverage(values);
      if (avg === null) return [];
      const variance = values.reduce((sum, value) => sum + Math.pow(value - avg, 2), 0) / values.length;
      const std = Math.sqrt(variance);
      if (!Number.isFinite(std) || std <= 1e-9) return [];
      return points
        .map((item) => ({{
          ...item,
          avg,
          z: (item.value - avg) / std,
          delta: item.value - avg,
        }}))
        .filter((item) => Math.abs(item.z) >= 1.45)
        .sort((left, right) => Math.abs(right.z) - Math.abs(left.z))
        .slice(0, limit);
    }}

    function renderSampleProfileCard(rows) {{
      const metric = getCurrentAnalysisMetric();
      if (!rows.length || !metric) return "";
      const profile = buildSampleProfile(rows, metric);
      const warningText = profile.warnings.length
        ? profile.warnings.join("、")
        : "当前筛选维度相对干净，适合做快速横向比较。";
      return `
        <article class="chart-card diagnostic-card">
          <h3>筛选可信度</h3>
          <p class="chart-subtitle">先看样本覆盖，再看排名；避免把缺失多、混排多的视图当成绝对强弱。</p>
          <div class="diagnostic-grid">
            <div class="diagnostic-stat">
              <div class="diagnostic-label">有效指标覆盖</div>
              <div class="diagnostic-value">${{escapeHtml(formatPercent(profile.coverage))}}</div>
            </div>
            <div class="diagnostic-stat">
              <div class="diagnostic-label">可比队伍</div>
              <div class="diagnostic-value">${{escapeHtml(formatValue(profile.teamCount))}}</div>
            </div>
            <div class="diagnostic-stat">
              <div class="diagnostic-label">指标均值</div>
              <div class="diagnostic-value">${{escapeHtml(formatValue(profile.metricAverage))}}</div>
            </div>
          </div>
          <div class="diagnostic-pill-row">
            <span class="diagnostic-pill" data-level="${{profile.level}}">${{escapeHtml(profile.label)}}</span>
            <span class="diagnostic-pill">样本 ${{escapeHtml(formatValue(profile.total))}} 条</span>
            <span class="diagnostic-pill">有效 ${{escapeHtml(formatValue(profile.numericCount))}} 条</span>
          </div>
          <p class="diagnostic-note">${{escapeHtml(warningText)}}</p>
        </article>
      `;
    }}

    function renderMetricOutlierCard(rows) {{
      const metric = getCurrentAnalysisMetric();
      const outliers = getMetricOutliers(rows, metric);
      if (!outliers.length) return "";
      return `
        <article class="chart-card diagnostic-card">
          <h3>异常高低值提醒</h3>
          <p class="chart-subtitle">只标记偏离当前筛选均值较大的记录，用来提示“值得复核”，不是直接判强弱。</p>
          <div class="outlier-list">
            ${{outliers.map((item) => {{
              const row = item.row;
              const direction = item.z >= 0 ? "高于" : "低于";
              const reason = `${{row["赛区"] || "未知赛区"}} · ${{row["兵种"] || "未知兵种"}} · ${{direction}}均值 ${{escapeHtml(formatValue(Math.abs(item.delta)))}}`;
              return `
                <div class="outlier-item">
                  <div class="outlier-team" title="${{escapeHtml(getTeamDisplayLabel(row))}}">${{escapeHtml(getTeamDisplayLabel(row))}}</div>
                  <div class="outlier-score">${{escapeHtml(formatValue(item.value))}}</div>
                  <div class="outlier-reason" title="${{escapeHtml(reason)}}">${{escapeHtml(reason)}}</div>
                </div>
              `;
            }}).join("")}}
          </div>
        </article>
      `;
    }}

    function renderRoleCoverageCard(rows) {{
      const metric = getCurrentAnalysisMetric();
      if (!rows.length || !metric) return "";
      const roleMap = new Map();
      rows.forEach((row) => {{
        const type = row["兵种"] || "未知";
        const value = getFiniteNumber(row, metric);
        if (!roleMap.has(type)) roleMap.set(type, {{ type, count: 0, numeric: 0, sum: 0 }});
        const item = roleMap.get(type);
        item.count += 1;
        if (value !== null) {{
          item.numeric += 1;
          item.sum += value;
        }}
      }});
      const roles = Array.from(roleMap.values())
        .map((item) => ({{
          ...item,
          average: item.numeric ? item.sum / item.numeric : null,
          coverage: item.count ? item.numeric / item.count : 0,
        }}))
        .sort((left, right) => right.count - left.count)
        .slice(0, 7);
      if (roles.length < 2) return "";
      const maxCount = Math.max(...roles.map((item) => item.count), 1);
      return `
        <article class="chart-card diagnostic-card">
          <h3>兵种覆盖结构</h3>
          <p class="chart-subtitle">看当前视图主要由哪些兵种构成，避免样本结构偏一边导致结论歪掉。</p>
          <div class="role-grid">
            ${{roles.map((item) => {{
              const width = Math.max(8, Math.round((item.count / maxCount) * 100));
              const tail = item.average === null ? "无有效指标" : `均值 ${{formatValue(item.average)}} · 覆盖 ${{formatPercent(item.coverage)}}`;
              return `
                <div class="role-row">
                  <span>${{escapeHtml(item.type)}}</span>
                  <span class="role-track" title="${{escapeHtml(tail)}}"><i class="role-fill" style="--w:${{width}}%"></i></span>
                  <span>${{escapeHtml(formatValue(item.count))}} 条</span>
                </div>
              `;
            }}).join("")}}
          </div>
        </article>
      `;
    }}


    function rowMatchesKeyword(row) {{
      if (!state.keyword) return true;
      const keywords = state.keyword.toLowerCase().split(/\\s+/).filter(Boolean);
      if (!keywords.length) return true;
      const haystack = payload.columns
        .map((column) => row[column])
        .filter((value) => value !== null && value !== undefined)
        .join(" ")
        .toLowerCase();
      return keywords.some((keyword) => haystack.includes(keyword));
    }}

    function getCrossZoneRankingRows(selectedZones) {{
      const selectedZoneSet = new Set(selectedZones);
      return payload.rows.filter((row) => {{
        if (!selectedZoneSet.has(row["赛区"])) return false;
        if (!getAllowedTypesForZone(row["赛区"]).includes(row["兵种"])) return false;
        return rowMatchesKeyword(row);
      }});
    }}

    function getCrossZoneRankingAxes(selectedZones) {{
      const axisTypes = new Set();
      selectedZones.forEach((zone) => {{
        getRadarAxesForZone(zone).forEach((axis) => axisTypes.add(axis.type));
      }});
      return radarAxes.filter((axis) => axisTypes.has(axis.type));
    }}

    function buildCombinedAxisAverageMap(selectedZones, axes) {{
      const selectedZoneSet = new Set(selectedZones);
      const averageMap = new Map();
      axes.forEach((axis) => {{
        const values = payload.rows
          .filter((row) => selectedZoneSet.has(row["赛区"]))
          .filter((row) => getAllowedTypesForZone(row["赛区"]).includes(row["兵种"]))
          .filter((row) => row["兵种"] === axis.type)
          .map((row) => getAxisMetricValue(row, axis))
          .filter((value) => value !== null && Number.isFinite(value));
        const average = values.length
          ? values.reduce((sum, value) => sum + value, 0) / values.length
          : null;
        averageMap.set(axis.type, average);
      }});
      return averageMap;
    }}

    function buildCrossZoneTeamRanking() {{
      const selectedZones = getSelectedZones();
      if (selectedZones.length < 2) return [];

      const rows = getCrossZoneRankingRows(selectedZones);
      if (!rows.length) return [];

      const axes = getCrossZoneRankingAxes(selectedZones);
      const axisAverageMap = buildCombinedAxisAverageMap(selectedZones, axes);
      const teamMap = new Map();

      rows.forEach((row) => {{
        const robotType = row["兵种"];
        const axis = axes.find((item) => item.type === robotType);
        if (!axis) return;

        const teamValue = getAxisMetricValue(row, axis);
        const combinedAverage = axisAverageMap.get(robotType);
        if (teamValue === null || combinedAverage === null || !Number.isFinite(combinedAverage)) return;

        const teamKey = getTeamKey(row);
        if (!teamKey.trim()) return;
        if (!teamMap.has(teamKey)) {{
          teamMap.set(teamKey, {{
            key: teamKey,
            label: getTeamLabel(row),
            zones: new Set(),
            axisValuesByType: new Map(),
          }});
        }}

        const entry = teamMap.get(teamKey);
        entry.zones.add(row["赛区"]);
        if (!entry.axisValuesByType.has(robotType)) {{
          entry.axisValuesByType.set(robotType, []);
        }}
        entry.axisValuesByType.get(robotType).push(teamValue);
      }});

      return Array.from(teamMap.values()).map((entry) => {{
        const axisScores = axes.map((axis) => {{
          const values = entry.axisValuesByType.get(axis.type) || [];
          const combinedAverage = axisAverageMap.get(axis.type);
          if (!values.length || combinedAverage === null || !Number.isFinite(combinedAverage)) {{
            return {{ ...axis, ratio: null, teamValue: null, combinedAverage }};
          }}
          const teamValue = values.reduce((sum, value) => sum + value, 0) / values.length;
          const ratio = combinedAverage === 0 ? (teamValue > 0 ? 3 : 1) : teamValue / combinedAverage;
          return {{
            ...axis,
            ratio: Number.isFinite(ratio) ? ratio : null,
            teamValue,
            combinedAverage,
          }};
        }});
        const validScores = axisScores
          .map((axis) => axis.ratio)
          .filter((ratio) => ratio !== null && Number.isFinite(ratio));
        const score = validScores.length
          ? validScores.reduce((sum, value) => sum + value, 0) / validScores.length
          : null;
        return {{
          ...entry,
          axes: axisScores,
          zoneCount: entry.zones.size,
          axisCount: validScores.length,
          score,
        }};
      }})
        .filter((entry) => entry.score !== null)
        .sort((left, right) => right.score - left.score);
    }}

    function renderCrossZoneRankingCard() {{
      const selectedZones = getSelectedZones();
      if (selectedZones.length < 2) return "";

      const ranking = buildCrossZoneTeamRanking();
      if (ranking.length < 2) return "";

      const axes = ranking[0].axes || [];
      return `
        <article class="chart-card">
          <h3>跨赛区总实力表</h3>
          <p class="chart-subtitle">纵轴为学校 / 战队，横轴为兵种；每个兵种列 = 该队关键数据 / 所选赛区合并后的该兵种均值，总分为可用兵种列平均。声明：总实力排名仅代表个人观点，无引战倾向。</p>
          <div class="strength-table-wrap">
            <table class="strength-table">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>学校 / 战队</th>
                  ${{axes.map((axis) => `<th>${{escapeHtml(axis.type)}}</th>`).join("")}}
                  <th>总分</th>
                </tr>
              </thead>
              <tbody>
                ${{ranking.map((item, index) => {{
                  const zoneText = Array.from(item.zones).join("、");
                  return `
                    <tr>
                      <td>#${{index + 1}}</td>
                      <td title="${{escapeHtml(zoneText)}}">${{escapeHtml(item.label)}}</td>
                      ${{item.axes.map((axis) => {{
                        const title = axis.ratio === null
                          ? "该兵种缺少可用数据"
                          : `${{axis.metricLabel}}: 队伍 ${{formatValue(axis.teamValue)}} / 合并均值 ${{formatValue(axis.combinedAverage)}}`;
                        return `<td title="${{escapeHtml(title)}}">${{escapeHtml(axis.ratio === null ? "-" : formatPercent(axis.ratio))}}</td>`;
                      }}).join("")}}
                      <td class="total-cell">${{escapeHtml(formatPercent(item.score))}}</td>
                    </tr>
                  `;
                }}).join("")}}
              </tbody>
            </table>
          </div>
        </article>
      `;
    }}

    function renderBelowTableCards() {{
      const crossZoneRankingCard = renderCrossZoneRankingCard();
      els.belowTableGrid.innerHTML = crossZoneRankingCard;
      els.belowTableGrid.hidden = !crossZoneRankingCard;
    }}

    function getTeamEvaluationConfig() {{
      return payload.teamEvaluation || {{}};
    }}

    function getAxisTip(axisType) {{
      const config = getTeamEvaluationConfig();
      return (config.axisTips && config.axisTips[axisType]) || "";
    }}

    function getRatedAxes(radar) {{
      if (!radar || !Array.isArray(radar.axes)) return [];
      return radar.axes
        .filter((axis) => typeof axis.ratio === "number" && Number.isFinite(axis.ratio))
        .map((axis) => ({{
          type: axis.type,
          ratio: axis.ratio,
          value: axis.teamValue,
          metricLabel: axis.metricLabel,
        }}));
    }}

    function sortByRatioDesc(left, right) {{
      return right.ratio - left.ratio;
    }}

    function sortByRatioAsc(left, right) {{
      return left.ratio - right.ratio;
    }}

    function joinAxisNames(items) {{
      return items.map((item) => item.type).join("、");
    }}

    function getEvaluationMetrics() {{
      const config = getTeamEvaluationConfig();
      return Array.isArray(config.perGameMetrics) ? config.perGameMetrics : [];
    }}

    function getConfiguredMetricColumns(metric) {{
      return [metric.column, ...(metric.fallbackColumns || [])].filter(Boolean);
    }}

    function getConfiguredMetricValue(row, metric) {{
      for (const column of getConfiguredMetricColumns(metric)) {{
        const value = getFiniteNumber(row, column);
        if (value !== null) return {{ value, column }};
      }}
      return null;
    }}

    function getMetricRatio(teamValue, zoneAverage, lowerIsBetter) {{
      if (teamValue === null || zoneAverage === null) return null;
      if (lowerIsBetter) {{
        if (teamValue === 0) return zoneAverage === 0 ? 1 : 3;
        return zoneAverage / teamValue;
      }}
      if (zoneAverage === 0) return teamValue > 0 ? 3 : 1;
      return teamValue / zoneAverage;
    }}

    function joinMetricNames(items) {{
      return items.map((item) => `${{item.type}}${{item.label}}`).join("、");
    }}

    function getTacticalMetricConfig() {{
      const config = getTeamEvaluationConfig();
      return config.tacticalMetrics || {{}};
    }}

    function getTacticalMetricsForType(teamKey, zoneName, robotType) {{
      const metricConfig = getTacticalMetricConfig();
      const metrics = Array.isArray(metricConfig[robotType]) ? metricConfig[robotType] : [];
      if (!metrics.length) return [];

      const zoneRows = getZoneRows(zoneName);
      const teamRows = zoneRows.filter((row) => getTeamKey(row) === teamKey);
      const teamRow = teamRows.find((row) => row["兵种"] === robotType);
      if (!teamRow) return [];

      return metrics.map((metric) => {{
        const metricValue = getConfiguredMetricValue(teamRow, metric);
        if (!metricValue) return null;

        const zoneValues = zoneRows
          .filter((row) => row["兵种"] === robotType)
          .map((row) => getConfiguredMetricValue(row, metric))
          .filter(Boolean)
          .map((item) => item.value);
        if (!zoneValues.length) return null;

        const zoneAverage = zoneValues.reduce((sum, value) => sum + value, 0) / zoneValues.length;
        const ratio = getMetricRatio(metricValue.value, zoneAverage, Boolean(metric.lowerIsBetter));
        if (ratio === null || !Number.isFinite(ratio)) return null;

        return {{
          type: robotType,
          label: metric.label || metricValue.column,
          column: metricValue.column,
          teamValue: metricValue.value,
          zoneAverage,
          ratio,
          lowerIsBetter: Boolean(metric.lowerIsBetter),
        }};
      }}).filter(Boolean);
    }}

    function getMetricByLabel(metrics, label) {{
      return metrics.find((metric) => metric.label === label) || null;
    }}

    function metricRatio(metrics, label) {{
      const metric = getMetricByLabel(metrics, label);
      return metric && typeof metric.ratio === "number" ? metric.ratio : null;
    }}

    function metricIsStrong(metrics, label, threshold) {{
      const ratio = metricRatio(metrics, label);
      return ratio !== null && ratio >= threshold;
    }}

    function metricIsWeak(metrics, label, threshold) {{
      const ratio = metricRatio(metrics, label);
      return ratio !== null && ratio <= threshold;
    }}

    function averageMetricRatios(metrics, labels) {{
      const wanted = new Set(labels);
      const values = metrics
        .filter((metric) => wanted.has(metric.label))
        .map((metric) => metric.ratio)
        .filter((ratio) => typeof ratio === "number" && Number.isFinite(ratio));
      if (!values.length) return null;
      return values.reduce((sum, value) => sum + value, 0) / values.length;
    }}

    function formatTacticalMetric(metric) {{
      if (!metric) return "";
      return `${{metric.label}} ${{formatValue(metric.teamValue)}}（均值 ${{formatValue(metric.zoneAverage)}}，${{formatPercent(metric.ratio)}}）`;
    }}

    function buildMvpEvidenceByType(mvpRadar, focusThreshold, quietThreshold) {{
      const evidence = new Map();
      if (!mvpRadar || !Array.isArray(mvpRadar.axes) || !mvpRadar.axes.length) return evidence;

      const axesByType = new Map(mvpRadar.axes.map((axis) => [axis.type, axis]));
      const teamTotal = mvpRadar.axes.reduce((sum, axis) => sum + (getFiniteNumber(axis, "teamValue") || 0), 0);
      if (teamTotal <= 0) return evidence;

      const teamAverage = teamTotal / mvpRadar.axes.length;
      const putEvidence = (type, axisTypes) => {{
        const count = axisTypes.reduce((sum, axisType) => {{
          const axis = axesByType.get(axisType);
          return sum + (getFiniteNumber(axis, "teamValue") || 0);
        }}, 0);
        const baseline = teamAverage * axisTypes.length;
        const ratio = baseline > 0 ? count / baseline : null;
        const level = ratio === null
          ? "none"
          : (ratio >= focusThreshold ? "focus" : (ratio <= quietThreshold ? "quiet" : "neutral"));
        evidence.set(type, {{ type, count, ratio, level, available: true }});
      }};

      putEvidence("英雄", ["英雄"]);
      putEvidence("步兵", ["步兵3", "步兵4"]);
      putEvidence("哨兵", ["哨兵"]);
      putEvidence("无人机", ["无人机"]);
      putEvidence("雷达", ["雷达"]);
      putEvidence("工程", ["工程"]);
      putEvidence("飞镖", ["飞镖"]);
      return evidence;
    }}

    function getMvpSupportText(mvpEvidence) {{
      if (!mvpEvidence || !mvpEvidence.available || mvpEvidence.ratio === null) {{
        return "MVP 暂无有效样本，不参与主判断。";
      }}
      const countText = `${{formatValue(mvpEvidence.count)}} 次`;
      if (mvpEvidence.level === "focus") {{
        return `MVP 有 ${{countText}}，高于该队对应位置的平均分布，可以作为高光佐证。`;
      }}
      if (mvpEvidence.level === "quiet") {{
        return `MVP 只有 ${{countText}}，说明高光不常落在这里，但不直接推翻局均判断。`;
      }}
      return `MVP 为 ${{countText}}，接近队内分布，只作为中性旁证。`;
    }}

    function makeTacticalProfile(type, title, status, confidence, detail, metrics, evidenceLabels, mvpEvidence) {{
      const candidateMetrics = evidenceLabels
        .map((label) => getMetricByLabel(metrics, label))
        .filter(Boolean);
      const directionalMetrics = status === "weak"
        ? candidateMetrics.filter((metric) => metric.ratio <= 1)
        : candidateMetrics.filter((metric) => metric.ratio >= 1);
      const evidenceMetrics = (directionalMetrics.length ? directionalMetrics : candidateMetrics)
        .sort(status === "weak" ? sortByRatioAsc : sortByRatioDesc)
        .slice(0, 3);
      const evidenceText = evidenceMetrics.length
        ? evidenceMetrics.map(formatTacticalMetric).join("；")
        : "关键数据样本不足。";

      return {{
        type,
        title,
        status,
        confidence: confidence || 1,
        detail,
        evidenceMetrics,
        evidenceText,
        mvpEvidence,
        mvpText: getMvpSupportText(mvpEvidence),
      }};
    }}

    function classifyHeroTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["大弹丸命中率", "建筑伤害", "KDA得分", "场均击杀", "场均死亡"]) || 1;
      const weakSignalCount = ["大弹丸命中率", "建筑伤害", "KDA得分", "场均击杀"]
        .filter((label) => metricIsWeak(metrics, label, thresholds.low))
        .length;
      if (score <= thresholds.weak || weakSignalCount >= 3) {{
        return makeTacticalProfile(
          "英雄",
          "英雄支撑偏弱",
          "weak",
          score,
          "英雄关键输出和生存数据低于赛区均值时，才更适合判断为英雄位偏弱，而不是简单说打法偏近战或远程。",
          metrics,
          ["KDA得分", "建筑伤害", "大弹丸命中率", "场均死亡"],
          mvpEvidence
        );
      }}
      if (metricIsStrong(metrics, "部署命中", thresholds.high)) {{
        return makeTacticalProfile(
          "英雄",
          "远程英雄压制型",
          "tactic",
          Math.max(metricRatio(metrics, "部署命中") || 1, score),
          "部署命中明显高，说明英雄更常通过远程架点、部署命中和安全距离制造价值。",
          metrics,
          ["部署命中", "大弹丸命中率", "建筑伤害"],
          mvpEvidence
        );
      }}
      if (metricIsStrong(metrics, "建筑伤害", thresholds.high) || metricIsStrong(metrics, "场均击杀", thresholds.high)) {{
        return makeTacticalProfile(
          "英雄",
          "近战英雄切入型",
          "tactic",
          Math.max(metricRatio(metrics, "建筑伤害") || 1, metricRatio(metrics, "场均击杀") || 1, score),
          "部署命中不是主信号，但建筑伤害、击杀或 KDA 有支撑，更像跟随正面节奏完成近距离压制和拆建筑。",
          metrics,
          ["建筑伤害", "场均击杀", "KDA得分"],
          mvpEvidence
        );
      }}
      return makeTacticalProfile(
        "英雄",
        "常规正面英雄",
        "balanced",
        score,
        "部署命中没有明显拉开，英雄更像随队伍正面节奏补伤害和拆建筑。",
        metrics,
        ["大弹丸命中率", "建筑伤害", "KDA得分"],
        mvpEvidence
      );
    }}

    function classifyInfantryTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["小弹丸命中率", "对敌伤害", "KDA得分", "场均击杀", "场均死亡"]) || 1;
      if (score <= thresholds.weak || metricIsWeak(metrics, "对敌伤害", thresholds.critical)) {{
        return makeTacticalProfile("步兵", "步兵线偏弱", "weak", score, "步兵的命中、伤害、KDA 或生存低于赛区均值时，才说明正面交换质量有问题。", metrics, ["对敌伤害", "KDA得分", "小弹丸命中率", "场均死亡"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "对敌伤害", thresholds.high) && metricIsStrong(metrics, "场均击杀", thresholds.high)) {{
        return makeTacticalProfile("步兵", "正面输出击杀型", "tactic", Math.max(metricRatio(metrics, "对敌伤害") || 1, metricRatio(metrics, "场均击杀") || 1), "伤害和击杀同时高，说明步兵线更像主动接团、持续给正面压力的核心输出。", metrics, ["对敌伤害", "场均击杀", "KDA得分"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "对敌伤害", thresholds.high) || metricIsStrong(metrics, "场均助攻", thresholds.high)) {{
        return makeTacticalProfile("步兵", "火力消耗压制型", "tactic", Math.max(metricRatio(metrics, "对敌伤害") || 1, metricRatio(metrics, "场均助攻") || 1), "伤害或助攻更突出，说明步兵线更偏持续消耗、压血线和给队友创造收割窗口。", metrics, ["对敌伤害", "场均助攻", "小弹丸命中率"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "场均死亡", thresholds.high)) {{
        return makeTacticalProfile("步兵", "稳健控线型", "balanced", Math.max(metricRatio(metrics, "场均死亡") || 1, score), "死亡控制较好，步兵线更偏稳健控线，价值不一定全部体现在击杀。", metrics, ["场均死亡", "KDA得分", "小弹丸命中率"], mvpEvidence);
      }}
      return makeTacticalProfile("步兵", "均衡对枪型", "balanced", score, "步兵线各项接近赛区均值，打法更像常规正面交换。", metrics, ["小弹丸命中率", "对敌伤害", "KDA得分"], mvpEvidence);
    }}

    function classifyGuardTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["小弹丸命中率", "对敌伤害", "KDA得分", "场均死亡"]) || 1;
      if (score <= thresholds.weak) {{
        return makeTacticalProfile("哨兵", "哨兵防线偏弱", "weak", score, "哨兵伤害、KDA 或死亡控制低于均值时，防线容错会被明显压低。", metrics, ["对敌伤害", "KDA得分", "场均死亡"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "场均死亡", thresholds.high) && (metricIsStrong(metrics, "KDA得分", 1.02) || metricIsStrong(metrics, "对敌伤害", 1.02))) {{
        return makeTacticalProfile("哨兵", "防线稳固型", "tactic", Math.max(metricRatio(metrics, "场均死亡") || 1, score), "死亡控制好且输出不低，说明哨兵更像防线稳定器，能抬高整队容错。", metrics, ["场均死亡", "KDA得分", "对敌伤害"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "对敌伤害", thresholds.high) || metricIsStrong(metrics, "场均击杀", thresholds.high)) {{
        return makeTacticalProfile("哨兵", "主动火力哨兵", "tactic", Math.max(metricRatio(metrics, "对敌伤害") || 1, metricRatio(metrics, "场均击杀") || 1), "伤害或击杀高，说明哨兵不只是守点，也在参与正面火力压制。", metrics, ["对敌伤害", "场均击杀", "小弹丸命中率"], mvpEvidence);
      }}
      return makeTacticalProfile("哨兵", "常规防守型", "balanced", score, "哨兵数据接近赛区均值，主要承担常规防守和牵制。", metrics, ["小弹丸命中率", "对敌伤害", "KDA得分"], mvpEvidence);
    }}

    function classifyDroneTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["场均发弹", "小弹丸命中率", "对敌伤害", "KDA得分", "场均击杀"]) || 1;
      if (score <= thresholds.weak || metricIsWeak(metrics, "对敌伤害", thresholds.critical)) {{
        return makeTacticalProfile("无人机", "无人机收益偏低", "weak", score, "无人机发弹、伤害或 KDA 低时，空中单位对正面局势的转化不够明显。", metrics, ["场均发弹", "对敌伤害", "KDA得分"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "对敌伤害", thresholds.high) && metricIsStrong(metrics, "场均击杀", thresholds.high)) {{
        return makeTacticalProfile("无人机", "空中收割型", "tactic", Math.max(metricRatio(metrics, "对敌伤害") || 1, metricRatio(metrics, "场均击杀") || 1), "伤害和击杀同时高，说明无人机更像抓残血、打局部收割的空中火力点。", metrics, ["对敌伤害", "场均击杀", "KDA得分"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "场均发弹", thresholds.high) && metricIsStrong(metrics, "对敌伤害", 1.02)) {{
        return makeTacticalProfile("无人机", "高频火力覆盖型", "tactic", Math.max(metricRatio(metrics, "场均发弹") || 1, metricRatio(metrics, "对敌伤害") || 1), "发弹量高且伤害有转化，说明无人机更偏持续覆盖和压制走位。", metrics, ["场均发弹", "对敌伤害", "小弹丸命中率"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "建筑伤害", thresholds.high)) {{
        return makeTacticalProfile("无人机", "建筑骚扰型", "tactic", Math.max(metricRatio(metrics, "建筑伤害") || 1, score), "建筑伤害高，说明无人机有一定战略目标骚扰价值。", metrics, ["建筑伤害", "对敌伤害", "KDA得分"], mvpEvidence);
      }}
      return makeTacticalProfile("无人机", "机会支援型", "balanced", score, "无人机数据没有单项特别拔尖，更像跟随局势寻找输出窗口。", metrics, ["场均发弹", "对敌伤害", "KDA得分"], mvpEvidence);
    }}

    function classifyRadarTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["雷达收益", "双倍易伤", "反制时长", "解算成功", "额外伤害"]) || 1;
      if (score <= thresholds.weak || metricIsWeak(metrics, "雷达收益", thresholds.critical)) {{
        return makeTacticalProfile("雷达", "雷达收益偏低", "weak", score, "雷达收益低时，说明信息、易伤或反制没有稳定转成团队优势。", metrics, ["雷达收益", "双倍易伤", "解算成功"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "双倍易伤", thresholds.high) || metricIsStrong(metrics, "解算成功", thresholds.high)) {{
        return makeTacticalProfile("雷达", "易伤信息放大型", "tactic", Math.max(metricRatio(metrics, "双倍易伤") || 1, metricRatio(metrics, "解算成功") || 1, score), "双倍易伤或解算成功高，说明雷达更偏把信息转成集火窗口。", metrics, ["双倍易伤", "解算成功", "雷达收益"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "反制时长", thresholds.high)) {{
        return makeTacticalProfile("雷达", "反制控制型", "tactic", Math.max(metricRatio(metrics, "反制时长") || 1, score), "反制时长高，说明雷达更像限制对方信息链的控制点。", metrics, ["反制时长", "雷达收益", "额外伤害"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "额外伤害", thresholds.high)) {{
        return makeTacticalProfile("雷达", "伤害转化型", "tactic", Math.max(metricRatio(metrics, "额外伤害") || 1, score), "额外伤害高，说明信息收益有更直接的伤害转化。", metrics, ["额外伤害", "双倍易伤", "雷达收益"], mvpEvidence);
      }}
      return makeTacticalProfile("雷达", "常规信息支撑型", "balanced", score, "雷达数据接近均值，主要承担常规信息支撑。", metrics, ["雷达收益", "双倍易伤", "额外伤害"], mvpEvidence);
    }}

    function classifyEngineerTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["组装经济", "兑换经济", "组装成功", "兑矿速度"]) || 1;
      if (score <= thresholds.weak) {{
        return makeTacticalProfile("工程", "工程经济偏弱", "weak", score, "工程经济、组装成功或兑矿速度低于均值时，会影响中后期资源循环。", metrics, ["组装经济", "兑换经济", "组装成功", "兑矿速度"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "组装经济", thresholds.high) || metricIsStrong(metrics, "组装成功", thresholds.high)) {{
        return makeTacticalProfile("工程", "组装经济滚动型", "tactic", Math.max(metricRatio(metrics, "组装经济") || 1, metricRatio(metrics, "组装成功") || 1, score), "组装经济或成功次数高，说明工程更偏通过组装和资源滚动给全队续航。", metrics, ["组装经济", "组装成功", "兑换经济"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "兑换经济", thresholds.high) && metricIsStrong(metrics, "兑矿速度", 1.02)) {{
        return makeTacticalProfile("工程", "稳定兑矿运营型", "tactic", Math.max(metricRatio(metrics, "兑换经济") || 1, metricRatio(metrics, "兑矿速度") || 1), "兑换经济高且兑矿速度不拖后腿，说明工程更偏稳定运营。", metrics, ["兑换经济", "兑矿速度", "组装成功"], mvpEvidence);
      }}
      return makeTacticalProfile("工程", "常规经济支撑型", "balanced", score, "工程数据接近均值，更多提供常规经济支撑。", metrics, ["组装经济", "兑换经济", "兑矿速度"], mvpEvidence);
    }}

    function classifyDartTactic(metrics, mvpEvidence, thresholds) {{
      const score = averageMetricRatios(metrics, ["飞镖收益", "随机移动靶", "末端移动靶", "随机固定靶", "固定靶", "前哨站"]) || 1;
      if (score <= thresholds.weak || metricIsWeak(metrics, "飞镖收益", thresholds.critical)) {{
        return makeTacticalProfile("飞镖", "飞镖收益偏低", "weak", score, "飞镖总收益或关键目标命中低时，战略目标压力不足。", metrics, ["飞镖收益", "随机移动靶", "末端移动靶"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "末端移动靶", thresholds.high) || metricIsStrong(metrics, "随机移动靶", thresholds.high)) {{
        return makeTacticalProfile("飞镖", "高价值目标打击型", "tactic", Math.max(metricRatio(metrics, "末端移动靶") || 1, metricRatio(metrics, "随机移动靶") || 1, score), "随机移动靶或末端移动靶高，说明飞镖更偏拿高价值目标收益。", metrics, ["末端移动靶", "随机移动靶", "飞镖收益"], mvpEvidence);
      }}
      if (metricIsStrong(metrics, "固定靶", thresholds.high) || metricIsStrong(metrics, "随机固定靶", thresholds.high)) {{
        return makeTacticalProfile("飞镖", "基础靶稳定拿分型", "tactic", Math.max(metricRatio(metrics, "固定靶") || 1, metricRatio(metrics, "随机固定靶") || 1, score), "固定靶和随机固定靶更突出，说明飞镖更偏稳定拿基础目标分。", metrics, ["固定靶", "随机固定靶", "飞镖收益"], mvpEvidence);
      }}
      return makeTacticalProfile("飞镖", "常规飞镖支援型", "balanced", score, "飞镖目标收益接近均值，没有明显高价值目标倾向。", metrics, ["飞镖收益", "随机固定靶", "固定靶"], mvpEvidence);
    }}

    function buildTacticalProfiles(teamKey, zoneName, mvpRadar, thresholds) {{
      const classifiers = {{
        "英雄": classifyHeroTactic,
        "步兵": classifyInfantryTactic,
        "哨兵": classifyGuardTactic,
        "无人机": classifyDroneTactic,
        "雷达": classifyRadarTactic,
        "工程": classifyEngineerTactic,
        "飞镖": classifyDartTactic,
      }};
      const mvpEvidenceByType = buildMvpEvidenceByType(mvpRadar, thresholds.mvpFocus, thresholds.mvpQuiet);

      return getAllowedTypesForZone(zoneName)
        .map((robotType) => {{
          const metrics = getTacticalMetricsForType(teamKey, zoneName, robotType);
          if (!metrics.length || !classifiers[robotType]) return null;
          return classifiers[robotType](metrics, mvpEvidenceByType.get(robotType), thresholds);
        }})
        .filter(Boolean);
    }}

    function buildPerGameMetricInsights(teamKey, zoneName, maxItems, strongThreshold, weakThreshold) {{
      const zoneRows = getZoneRows(zoneName);
      const teamRows = zoneRows.filter((row) => getTeamKey(row) === teamKey);
      const metricItems = [];

      getEvaluationMetrics().forEach((metric) => {{
        teamRows.forEach((teamRow) => {{
          const robotType = teamRow["兵种"];
          if (Array.isArray(metric.types) && !metric.types.includes(robotType)) return;
          const metricValue = getConfiguredMetricValue(teamRow, metric);
          if (!metricValue) return;

          const zoneValues = zoneRows
            .filter((row) => row["兵种"] === robotType)
            .map((row) => getConfiguredMetricValue(row, metric))
            .filter(Boolean)
            .map((item) => item.value);
          if (!zoneValues.length) return;

          const zoneAverage = zoneValues.reduce((sum, value) => sum + value, 0) / zoneValues.length;
          const ratio = getMetricRatio(metricValue.value, zoneAverage, Boolean(metric.lowerIsBetter));
          if (ratio === null || !Number.isFinite(ratio)) return;

          metricItems.push({{
            type: robotType,
            label: metric.label || metricValue.column,
            column: metricValue.column,
            teamValue: metricValue.value,
            zoneAverage,
            ratio,
            lowerIsBetter: Boolean(metric.lowerIsBetter),
          }});
        }});
      }});

      return {{
        items: metricItems,
        strong: metricItems
          .filter((item) => item.ratio >= strongThreshold)
          .sort(sortByRatioDesc)
          .slice(0, maxItems),
        weak: metricItems
          .filter((item) => item.ratio <= weakThreshold)
          .sort(sortByRatioAsc)
          .slice(0, maxItems),
      }};
    }}

    function buildTeamEvaluationModel(radar, mvpRadar, teamKey, zoneName) {{
      const config = getTeamEvaluationConfig();
      const maxItems = config.maxItems || 3;
      const strongThreshold = config.strongThreshold || 1.25;
      const eliteThreshold = config.eliteThreshold || 1.6;
      const weakThreshold = config.weakThreshold || 0.75;
      const criticalThreshold = config.criticalThreshold || 0.45;
      const mvpFocusThreshold = config.mvpFocusThreshold || 1.5;
      const mvpQuietThreshold = config.mvpQuietThreshold || 0.5;

      const radarAxes = getRatedAxes(radar);
      if (!radarAxes.length) return null;

      const avgRatio = radarAxes.reduce((sum, axis) => sum + axis.ratio, 0) / radarAxes.length;
      const strongAxes = radarAxes
        .filter((axis) => axis.ratio >= strongThreshold)
        .sort(sortByRatioDesc)
        .slice(0, maxItems);
      const weakAxes = radarAxes
        .filter((axis) => axis.ratio <= weakThreshold)
        .sort(sortByRatioAsc)
        .slice(0, maxItems);
      const eliteAxes = radarAxes.filter((axis) => axis.ratio >= eliteThreshold);
      const criticalAxes = radarAxes.filter((axis) => axis.ratio <= criticalThreshold);
      const metricInsights = buildPerGameMetricInsights(teamKey, zoneName, maxItems, strongThreshold, weakThreshold);

      const mvpAxes = getRatedAxes(mvpRadar);
      const mvpTotal = mvpRadar && Array.isArray(mvpRadar.axes)
        ? mvpRadar.axes.reduce((sum, axis) => sum + (getFiniteNumber(axis, "teamValue") || 0), 0)
        : 0;
      const mvpFocusAxes = mvpTotal > 0
        ? mvpAxes.filter((axis) => axis.ratio >= mvpFocusThreshold).sort(sortByRatioDesc).slice(0, maxItems)
        : [];
      const mvpQuietAxes = mvpTotal > 0
        ? mvpAxes.filter((axis) => axis.ratio <= mvpQuietThreshold).sort(sortByRatioAsc).slice(0, maxItems)
        : [];

      const tacticalThresholds = {{
        high: config.tacticalHighThreshold || 1.22,
        low: config.tacticalLowThreshold || 0.82,
        weak: config.tacticalWeakThreshold || 0.78,
        critical: config.tacticalCriticalThreshold || 0.55,
        mvpFocus: mvpFocusThreshold,
        mvpQuiet: mvpQuietThreshold,
      }};
      const tacticalProfiles = buildTacticalProfiles(teamKey, zoneName, mvpRadar, tacticalThresholds);
      const tacticProfiles = tacticalProfiles
        .filter((profile) => profile.status === "tactic")
        .sort((left, right) => right.confidence - left.confidence)
        .slice(0, maxItems);
      const balancedProfiles = tacticalProfiles
        .filter((profile) => profile.status === "balanced")
        .sort((left, right) => right.confidence - left.confidence)
        .slice(0, maxItems);
      const weakProfiles = tacticalProfiles
        .filter((profile) => profile.status === "weak")
        .sort((left, right) => left.confidence - right.confidence)
        .slice(0, maxItems);
      const tacticEvidenceItems = tacticalProfiles
        .flatMap((profile) => profile.evidenceMetrics.map((metric) => ({{
          ...metric,
          tacticType: profile.type,
          tacticTitle: profile.title,
        }})))
        .sort(sortByRatioDesc)
        .slice(0, maxItems + 1);
      const mvpEvidenceItems = tacticalProfiles
        .filter((profile) => profile.mvpEvidence && profile.mvpEvidence.available)
        .sort((left, right) => {{
          const leftRatio = left.mvpEvidence && left.mvpEvidence.ratio !== null ? left.mvpEvidence.ratio : 0;
          const rightRatio = right.mvpEvidence && right.mvpEvidence.ratio !== null ? right.mvpEvidence.ratio : 0;
          return rightRatio - leftRatio;
        }})
        .slice(0, maxItems);

      let level = "接近均线";
      if (avgRatio >= 1.15) level = "整体高于均线";
      if (avgRatio >= 1.35) level = "整体明显强势";
      if (avgRatio < 0.9) level = "整体略低于均线";

      const summaryParts = [];
      const primaryTactics = tacticProfiles.length ? tacticProfiles : balancedProfiles;
      if (primaryTactics.length) {{
        const primary = primaryTactics[0];
        summaryParts.push(`从局均数据看，${{radar.teamLabel}}最清晰的打法信号是${{primary.type}}的「${{primary.title}}」：${{primary.detail}}关键证据是${{primary.evidenceText}}。`);
        if (primaryTactics.length > 1) {{
          const secondary = primaryTactics.slice(1, 3).map((profile) => `${{profile.type}}「${{profile.title}}」`).join("、");
          summaryParts.push(`另外还能看到${{secondary}}，这些判断都来自同赛区同兵种的局均/场均对比，而不是 MVP 次数本身。`);
        }}
      }} else {{
        summaryParts.push(`当前可用的局均样本不足，暂时只能看到综合均值 ${{formatPercent(avgRatio)}}，${{level}}。`);
      }}

      if (weakProfiles.length) {{
        const weakText = weakProfiles.map((profile) => `${{profile.type}}「${{profile.title}}」`).join("、");
        const weakEvidence = weakProfiles.map((profile) => profile.evidenceText).join("；");
        summaryParts.push(`真正需要标成偏弱的是${{weakText}}，因为关键数据已经低于同赛区均值：${{weakEvidence}}。`);
      }} else if (metricInsights.weak.length) {{
        summaryParts.push(`没有兵种被直接判为偏弱，但 ${{joinMetricNames(metricInsights.weak)}} 有低于均值的信号，适合继续复盘对位压力和资源投入。`);
      }} else {{
        summaryParts.push("目前没有明确到足以判定“某兵种偏弱”的数据，评价重点应放在打法侧重点和稳定性，而不是强行找短板。");
      }}

      const focusedMvpProfiles = mvpEvidenceItems.filter((profile) => profile.mvpEvidence.level === "focus");
      if (focusedMvpProfiles.length) {{
        summaryParts.push(`MVP 只作为佐证：${{focusedMvpProfiles.map((profile) => `${{profile.type}}${{formatValue(profile.mvpEvidence.count)}}次`).join("、")}} 的高光分布和部分数据判断能互相印证。`);
      }} else if (mvpTotal > 0) {{
        summaryParts.push("MVP 分布没有形成决定性证据，所以不把它作为主判断，只用来解释哪些兵种更容易在关键局被看见。");
      }} else {{
        summaryParts.push("该筛选下没有有效 MVP 样本，战术判断完全按局均/场均数据给出。");
      }}

      return {{
        teamLabel: radar.teamLabel,
        zoneName: radar.zoneName,
        avgRatio,
        level,
        strongAxes,
        weakAxes,
        eliteAxes,
        criticalAxes,
        metricStrongItems: metricInsights.strong,
        metricWeakItems: metricInsights.weak,
        tacticalProfiles,
        tacticProfiles,
        balancedProfiles,
        weakProfiles,
        tacticEvidenceItems,
        mvpEvidenceItems,
        mvpFocusAxes,
        mvpQuietAxes,
        summary: summaryParts.join(""),
      }};
    }}

    function renderInsightItems(items, emptyText) {{
      if (!items.length) {{
        return `<p class="insight-note">${{escapeHtml(emptyText)}}</p>`;
      }}
      return `
        <div class="insight-list">
          ${{items.map((item) => `
            <div class="insight-chip" title="${{escapeHtml(getAxisTip(item.type))}}">
              <span>${{escapeHtml(item.type)}}</span>
              <span>${{escapeHtml(formatPercent(item.ratio))}}</span>
            </div>
          `).join("")}}
        </div>
      `;
    }}

    function renderMetricInsightItems(items, emptyText) {{
      if (!items.length) {{
        return `<p class="insight-note">${{escapeHtml(emptyText)}}</p>`;
      }}
      return `
        <div class="insight-list">
          ${{items.map((item) => {{
            const direction = item.lowerIsBetter ? "越低越好" : "越高越好";
            const detail = `队伍${{item.label}}: ${{formatValue(item.teamValue)}}；同赛区同兵种均值: ${{formatValue(item.zoneAverage)}}；${{direction}}`;
            return `
              <div class="insight-chip" title="${{escapeHtml(detail)}}">
                <span>${{escapeHtml(`${{item.type}} · ${{item.label}}`)}}</span>
                <span>${{escapeHtml(formatPercent(item.ratio))}}</span>
              </div>
            `;
          }}).join("")}}
        </div>
      `;
    }}

    function renderTacticalProfileItems(items, emptyText) {{
      if (!items.length) {{
        return `<p class="insight-note">${{escapeHtml(emptyText)}}</p>`;
      }}
      return `
        <div class="insight-list">
          ${{items.map((item) => {{
            const detail = `${{item.detail}} 证据：${{item.evidenceText}} ${{item.mvpText}}`;
            return `
              <div class="insight-chip insight-chip-block" title="${{escapeHtml(detail)}}">
                <span>${{escapeHtml(`${{item.type}} · ${{item.title}}`)}}</span>
                <small>${{escapeHtml(item.evidenceText)}}</small>
              </div>
            `;
          }}).join("")}}
        </div>
      `;
    }}

    function renderTacticalEvidenceItems(items, emptyText) {{
      if (!items.length) {{
        return `<p class="insight-note">${{escapeHtml(emptyText)}}</p>`;
      }}
      return `
        <div class="insight-list">
          ${{items.map((item) => {{
            const direction = item.lowerIsBetter ? "越低越好" : "越高越好";
            const detail = `${{item.tacticType}}${{item.tacticTitle}}：${{formatTacticalMetric(item)}}；${{direction}}`;
            return `
              <div class="insight-chip insight-chip-block" title="${{escapeHtml(detail)}}">
                <span>${{escapeHtml(`${{item.tacticType}} · ${{item.label}}`)}}</span>
                <small>${{escapeHtml(`队伍 ${{formatValue(item.teamValue)}} / 均值 ${{formatValue(item.zoneAverage)}} · ${{formatPercent(item.ratio)}}`)}}</small>
              </div>
            `;
          }}).join("")}}
        </div>
      `;
    }}

    function renderMvpEvidenceItems(items, emptyText) {{
      if (!items.length) {{
        return `<p class="insight-note">${{escapeHtml(emptyText)}}</p>`;
      }}
      return `
        <div class="insight-list">
          ${{items.map((item) => {{
            const evidence = item.mvpEvidence;
            return `
              <div class="insight-chip insight-chip-block" title="${{escapeHtml(item.mvpText)}}">
                <span>${{escapeHtml(`${{item.type}} · MVP ${{formatValue(evidence.count)}}次`)}}</span>
                <small>${{escapeHtml(`${{evidence.ratio === null ? "无比例" : formatPercent(evidence.ratio)}} · ${{item.title}}`)}}</small>
              </div>
            `;
          }}).join("")}}
        </div>
      `;
    }}

    function renderTeamEvaluationCard(evaluation) {{
      if (!evaluation) return "";
      const tacticDisplayItems = evaluation.tacticProfiles.length
        ? evaluation.tacticProfiles
        : evaluation.balancedProfiles;
      const tacticItemsMarkup = renderTacticalProfileItems(tacticDisplayItems, "局均数据暂时没有形成明确打法画像。");
      const evidenceItemsMarkup = renderTacticalEvidenceItems(evaluation.tacticEvidenceItems, "还没有足够的关键数据证据。");
      const riskItemsMarkup = evaluation.weakProfiles.length
        ? renderTacticalProfileItems(evaluation.weakProfiles, "没有明确偏弱兵种。")
        : renderMetricInsightItems(evaluation.metricWeakItems, "没有明确到足以判定偏弱的低位数据。");
      const riskNote = evaluation.weakProfiles.length
        ? "这里的“偏弱”只在关键局均/场均数据低于同赛区均值时出现。"
        : "不强行找短板；低位细项只作为复盘线索。";
      const mvpItemsMarkup = renderMvpEvidenceItems(evaluation.mvpEvidenceItems, "MVP 暂无有效样本。");
      const mvpNote = "MVP 只用于佐证高光归属，主判断仍以局均/场均和关键收益数据为准。";

      return `
        <article class="chart-card insight-card">
          <div class="insight-header">
            <div>
              <span class="eyebrow">TEAM SCOUT</span>
              <h3>${{escapeHtml(evaluation.teamLabel)}} 队伍简评</h3>
              <p class="insight-summary" data-typewriter="${{escapeHtml(evaluation.summary)}}">${{escapeHtml(evaluation.summary)}}</p>
            </div>
            <div class="insight-score">
              <strong>${{escapeHtml(formatPercent(evaluation.avgRatio))}}</strong>
              <span>综合均值</span>
            </div>
          </div>
          <div class="insight-grid">
            <section class="insight-section">
              <h4>打法画像</h4>
              ${{tacticItemsMarkup}}
            </section>
            <section class="insight-section">
              <h4>关键数据</h4>
              ${{evidenceItemsMarkup}}
              <p class="insight-note">优先展示能解释打法类型的局均/场均数据。</p>
            </section>
            <section class="insight-section">
              <h4>待复盘点</h4>
              ${{riskItemsMarkup}}
              <p class="insight-note">${{escapeHtml(riskNote)}}</p>
            </section>
            <section class="insight-section">
              <h4>MVP佐证</h4>
              ${{mvpItemsMarkup}}
              <p class="insight-note">${{escapeHtml(mvpNote)}}</p>
            </section>
          </div>
          <p class="insight-disclaimer">队伍判断声明：该简评是按同赛区同兵种的局均/场均数据做的辅助判断，不等于官方实力排名；“短板/强势/打法”只用于复盘讨论，不能脱离赛程难度、对手强度、阵容配置和临场战术单独下结论。</p>
        </article>
      `;
    }}

    function runInsightTypewriter() {{
      const runId = ++insightTypewriterRun;
      const summaries = els.chartGrid.querySelectorAll(".insight-summary[data-typewriter]");
      summaries.forEach((summary) => {{
        const fullText = summary.dataset.typewriter || "";
        let index = 0;
        summary.textContent = "";
        const tick = () => {{
          if (runId !== insightTypewriterRun) return;
          index = Math.min(fullText.length, index + 2);
          summary.textContent = fullText.slice(0, index);
          if (index < fullText.length) {{
            window.setTimeout(tick, 18);
          }}
        }};
        window.setTimeout(tick, 80);
      }});
    }}


    function getCurrentMetricLabel() {{
      return getCurrentAnalysisMetric() || state.metric || "当前指标";
    }}

    function getMetricDescriptor(metric) {{
      const fallback = {{
        title: metric || "当前指标",
        desc: "该指标来自原始统计表或派生列。用于排序时只能说明当前筛选口径下的相对表现，不建议脱离兵种职责和赛区环境直接判强弱。",
        rules: [
          ["适用范围", "随当前筛选条件变化，建议先锁定赛区和兵种再横向比较。"],
          ["复核建议", "头部/尾部异常值建议回看录像、对手强度和赛程阶段。"],
        ],
        caveat: "通用指标说明：表格统计是复盘线索，不等价于官方实力排名。",
      }};
      const descriptors = {{
        "自瞄命中综合": {{
          title: "自瞄命中综合",
          desc: "用于把不同输出兵种的命中表现放到同一个快选入口里看。英雄取大弹丸命中率；步兵、哨兵、无人机取小弹丸命中率；工程、雷达、飞镖不参与这个指标。",
          rules: [
            ["英雄", "大弹丸命中率"],
            ["步兵 / 哨兵 / 无人机", "小弹丸命中率"],
            ["不参与", "工程、雷达、飞镖"],
            ["阅读方式", "适合筛自瞄稳定性，不能单独代表输出强度。"],
          ],
          caveat: "命中率高不一定输出强，可能和射击距离、目标选择、弹量策略有关。",
        }},
        "火力输出综合": {{
          title: "火力输出综合",
          desc: "用于把能主动造成进攻收益的兵种放到同一个视图里看。英雄、步兵、哨兵、无人机参与；飞镖独立看飞镖打击，工程和雷达不参与。",
          rules: [
            ["英雄", "优先看建筑伤害，缺失时回退到击杀相关字段。"],
            ["步兵 / 哨兵 / 无人机", "优先看对敌伤害量，缺失时回退到建筑伤害或击杀字段。"],
            ["归一化", "按同赛区同兵种均值归一化，100 约等于同类平均水平。"],
            ["排除项", "飞镖、工程、雷达不混进火力输出。"],
          ],
          caveat: "综合火力是归一化复盘指标，不是官方定义；跨兵种看趋势，精确判断仍要回到单兵种数据。",
        }},
        "MVP次数": {{
          title: "MVP次数",
          desc: "用于观察高光归属和稳定贡献痕迹。它适合做佐证，不适合单独当实力排名。",
          rules: [
            ["优点", "能体现对局中被系统/规则记录到的突出贡献。"],
            ["局限", "会受赛程、对手、队伍分工和兵种职责影响。"],
          ],
          caveat: "MVP 是证据之一，不是唯一判断依据。",
        }},
        "局均雷达分数": {{
          title: "局均雷达分数",
          desc: "派生雷达指标，综合双倍易伤时间、雷达反制时长、雷达解算成功次数等收益，用来粗看雷达压制质量。",
          rules: [
            ["组成", "双倍易伤时间 + 雷达反制收益 + 解算成功收益。"],
            ["适用", "只适合雷达兵种筛选下重点比较。"],
          ],
          caveat: "雷达收益很依赖队友跟伤、对面反制和战术节奏。",
        }},
        "总场次飞镖分数": {{
          title: "总场次飞镖分数",
          desc: "派生飞镖指标，把不同靶型命中按权重折算成总分，用来更直观看飞镖打击收益。",
          rules: [
            ["固定靶", "按较低权重计入。"],
            ["移动靶 / 末端", "按较高权重计入。"],
            ["适用", "只适合飞镖数据横向比较。"],
          ],
          caveat: "飞镖收益和赛制阶段、战术选择、发射窗口密切相关。",
        }},
      }};
      return descriptors[metric] || fallback;
    }}

    function renderMetricGuideCard(rows) {{
      const metric = getCurrentMetricLabel();
      if (!metric) return "";
      const descriptor = getMetricDescriptor(metric);
      const values = getMetricValues(rows, metric);
      const avg = getAverage(values);
      const coverage = rows.length ? values.length / rows.length : 0;
      return `
        <article class="chart-card metric-guide-card">
          <h3>当前指标说明</h3>
          <span class="metric-name">${{escapeHtml(descriptor.title)}}</span>
          <p class="metric-desc">${{escapeHtml(descriptor.desc)}}</p>
          <div class="metric-rule-grid">
            ${{descriptor.rules.map(([name, detail]) => `
              <div class="metric-rule">
                <b>${{escapeHtml(name)}}</b>
                <span>${{escapeHtml(detail)}}</span>
              </div>
            `).join("")}}
          </div>
          <div class="review-chip-row">
            <span class="review-chip">有效 ${{escapeHtml(formatValue(values.length))}} / ${{escapeHtml(formatValue(rows.length))}}</span>
            <span class="review-chip">覆盖 ${{escapeHtml(formatPercent(coverage))}}</span>
            <span class="review-chip">均值 ${{escapeHtml(formatValue(avg))}}</span>
          </div>
          <p class="diagnostic-note">${{escapeHtml(descriptor.caveat)}}</p>
        </article>
      `;
    }}

    function renderTopSnapshotCard(rows) {{
      const metric = getCurrentMetricLabel();
      if (!metric || !rows.length) return "";
      const numericRows = rows.filter((row) => getFiniteNumber(row, metric) !== null).slice(0, 5);
      if (!numericRows.length) return "";
      const values = rows.map((row) => getFiniteNumber(row, metric)).filter((value) => value !== null);
      const avg = getAverage(values);
      return `
        <article class="chart-card snapshot-card">
          <h3>Top 对比快照</h3>
          <p class="chart-subtitle">把当前排序前几条压成复盘快照，方便快速看“谁领先、领先多少、属于哪个兵种/赛区”。</p>
          <div class="snapshot-list">
            ${{numericRows.map((row, index) => {{
              const value = getFiniteNumber(row, metric);
              const ratio = avg && avg !== 0 ? value / avg : null;
              const ratioLevel = ratio === null ? "mid" : (ratio >= 1.25 ? "high" : (ratio <= 0.75 ? "low" : "mid"));
              const ratioText = ratio === null ? "-" : `${{Math.round(ratio * 100)}}%均值`;
              const meta = [row["赛区"], row["兵种"]].filter(Boolean).join(" · ");
              return `
                <div class="snapshot-row">
                  <span class="snapshot-rank">#${{index + 1}}</span>
                  <span class="snapshot-team" title="${{escapeHtml(getTeamDisplayLabel(row))}}">${{escapeHtml(getTeamDisplayLabel(row))}}</span>
                  <span class="snapshot-meta" title="${{escapeHtml(meta)}}">${{escapeHtml(meta)}}</span>
                  <span class="snapshot-value">${{escapeHtml(formatValue(value))}}</span>
                  <span class="snapshot-ratio" data-level="${{ratioLevel}}">${{escapeHtml(ratioText)}}</span>
                </div>
              `;
            }}).join("")}}
          </div>
        </article>
      `;
    }}

    function buildReviewActions(rows, sortedRows) {{
      const metric = getCurrentMetricLabel();
      const actions = [];
      const profile = metric ? buildSampleProfile(rows, metric) : null;
      const selectedZones = getSelectedZones();
      const singleTeam = getSingleTeamCandidate(rows);
      if (!rows.length) {{
        return ["当前筛选没有命中数据，先放宽搜索词或取消部分赛区/兵种限制。"];
      }}
      if (singleTeam) {{
        const radar = buildRadarModel(singleTeam.key, singleTeam.zone);
        if (radar && radar.axes) {{
          const validAxes = radar.axes.filter((axis) => axis.ratio !== null && Number.isFinite(axis.ratio));
          const strongest = validAxes.slice().sort((a, b) => b.ratio - a.ratio)[0];
          const weakest = validAxes.slice().sort((a, b) => a.ratio - b.ratio)[0];
          if (strongest) actions.push(`先回看 ${{strongest.type}} 相关对局，确认它的高数据是稳定能力、特定对手收益，还是战术资源倾斜。`);
          if (weakest && weakest !== strongest) actions.push(`把 ${{weakest.type}} 作为待复盘点：看是数据缺失、职责不同，还是确实影响整体收益。`);
        }}
        actions.push("单队伍判断建议至少结合 2~3 场录像：看开局节奏、资源分配、关键团战和死亡原因，不只看总表。")
      }} else {{
        const top = sortedRows.find((row) => getFiniteNumber(row, metric) !== null);
        if (top) actions.push(`优先抽查当前第一名：${{getTeamDisplayLabel(top)}}，确认它在“${{metric}}”上的领先是否来自稳定发挥。`);
        if (selectedZones.length > 1) actions.push("跨赛区比较时先看趋势，再回到单赛区复核；不同赛区对手强度和赛程阶段会影响数据。")
        if (state.selectedType === "全部") actions.push("全兵种视图适合看总体结构，但真正比较强弱时建议切到单一兵种。")
      }}
      if (profile && profile.level !== "high") actions.push(`当前可信度为${{profile.label}}，建议把结论写成“值得关注/需要复核”，不要写成绝对强弱。`);
      const outliers = metric ? getMetricOutliers(rows, metric, 3) : [];
      if (outliers.length) actions.push("异常高低值已经被标出，建议先核对这些记录，避免单条极端数据拉偏判断。")
      if (!actions.length) actions.push("当前视图比较干净，可以直接看 Top 快照和指标说明，再挑 2~3 支队伍做录像复核。")
      return actions.slice(0, 5);
    }}

    function renderReviewActionCard(rows, sortedRows) {{
      const actions = buildReviewActions(rows, sortedRows);
      return `
        <article class="chart-card action-card">
          <h3>下一步复盘建议</h3>
          <p class="chart-subtitle">这部分不是判定结论，而是告诉你下一步该看哪里，适合做赛前侦察或赛后复盘入口。</p>
          <div class="action-list">
            ${{actions.map((action, index) => `
              <div class="action-item">
                <span class="action-index">${{index + 1}}</span>
                <span>${{escapeHtml(action)}}</span>
              </div>
            `).join("")}}
          </div>
        </article>
      `;
    }}

    function buildCurrentBriefText(rows, sortedRows) {{
      const metric = getCurrentMetricLabel();
      const selectedZones = getSelectedZones();
      const profile = metric ? buildSampleProfile(rows, metric) : null;
      const top = sortedRows.find((row) => getFiniteNumber(row, metric) !== null) || sortedRows[0];
      const lines = [];
      lines.push(`【RM 数据简评】筛选：${{selectedZones.length ? selectedZones.join("、") : "全部赛区"}} / ${{state.selectedType || "全部兵种"}} / 指标：${{metric}}`);
      lines.push(`样本：${{rows.length}} 条${{profile ? `，有效覆盖 ${{formatPercent(profile.coverage)}}，可信度 ${{profile.label}}` : ""}}。`);
      if (top) {{
        const value = getFiniteNumber(top, metric);
        lines.push(`当前排序首位：${{getTeamDisplayLabel(top)}}（${{[top["赛区"], top["兵种"]].filter(Boolean).join(" · ")}}），${{metric}}=${{formatValue(value)}}。`);
      }} else {{
        lines.push("当前筛选暂无可排序队伍。")
      }}
      if (profile && profile.warnings.length) lines.push(`复核提醒：${{profile.warnings.join("、")}}。`);
      lines.push("免责声明：以上只基于当前公开统计口径和筛选条件，是辅助复盘线索，不代表官方排名，也不用于引战；关键判断仍需结合录像、对手强度、赛程阶段和阵容变化。")
      return lines.join("\\n");
    }}

    function renderCopyBriefCard(rows, sortedRows) {{
      const text = buildCurrentBriefText(rows, sortedRows);
      window.rmCurrentBriefText = text;
      return `
        <article class="chart-card copy-brief-card">
          <h3>一键复制结论</h3>
          <p class="chart-subtitle">适合直接丢到群里或报告草稿里，再按你实际看录像的情况改。</p>
          <div class="copy-brief-body">${{escapeHtml(text)}}</div>
          <button class="copy-brief-button" type="button" data-copy-brief>复制这段简评</button>
        </article>
      `;
    }}

    function renderCharts(rows) {{
      const singleTeam = getSingleTeamCandidate(rows);
      if (singleTeam) {{
        const radar = buildRadarModel(singleTeam.key, singleTeam.zone);
        const mvpRadar = buildMvpRadarModel(singleTeam.key, singleTeam.zone);
        const cards = [];
        const compareCard = renderCompareRadarCard();
        if (compareCard) cards.push(compareCard);
        cards.push(renderTeamEvaluationCard(buildTeamEvaluationModel(radar, mvpRadar, singleTeam.key, singleTeam.zone)));
        cards.push(renderRadarCard(radar));
        if (mvpRadar) cards.push(renderRadarCard(mvpRadar));
        const metricGuideCard = renderMetricGuideCard(rows);
        if (metricGuideCard) cards.push(metricGuideCard);
        const actionCard = renderReviewActionCard(rows, rows);
        if (actionCard) cards.push(actionCard);
        const copyCard = renderCopyBriefCard(rows, rows);
        if (copyCard) cards.push(copyCard);
        const sampleCard = renderSampleProfileCard(rows);
        if (sampleCard) cards.push(sampleCard);
        const roleCard = renderRoleCoverageCard(rows);
        if (roleCard) cards.push(roleCard);
        els.chartGrid.innerHTML = cards.join("");
        runInsightTypewriter();
        return;
      }}

      if (!state.metric) {{
        insightTypewriterRun += 1;
        els.chartGrid.innerHTML = "";
        return;
      }}

      const cards = [];
      const compareCard = renderCompareRadarCard();
      if (compareCard) cards.push(compareCard);
      const metricGuideCard = renderMetricGuideCard(rows);
      if (metricGuideCard) cards.push(metricGuideCard);
      const topSnapshotCard = renderTopSnapshotCard(rows);
      if (topSnapshotCard) cards.push(topSnapshotCard);
      const actionCard = renderReviewActionCard(rows, rows);
      if (actionCard) cards.push(actionCard);
      const copyCard = renderCopyBriefCard(rows, rows);
      if (copyCard) cards.push(copyCard);
      const sampleCard = renderSampleProfileCard(rows);
      if (sampleCard) cards.push(sampleCard);
      const outlierCard = renderMetricOutlierCard(rows);
      if (outlierCard) cards.push(outlierCard);
      const roleCard = renderRoleCoverageCard(rows);
      if (roleCard) cards.push(roleCard);

      const comparisonCard = renderZoneComparisonCard(rows);
      if (comparisonCard) cards.push(comparisonCard);

      const chartRows = rows
        .filter((row) => typeof row[state.metric] === "number")
        .slice(0, 10);

      if (!chartRows.length) {{
        insightTypewriterRun += 1;
        els.chartGrid.innerHTML = cards.join("");
        return;
      }}

      const metricValues = chartRows
        .map((row) => row[state.metric])
        .filter((value) => typeof value === "number");
      const maxValue = Math.max(...metricValues, 0);
      const isAscending = state.activeSortDirection === "asc";
      const chartTitle = isAscending ? "最低 10 名" : "最高 10 名";
      const chartSubtitle = isAscending
        ? "按当前筛选结果升序展示，条形长度按当前图表中的最大值统一缩放。"
        : "按当前筛选结果降序展示，方便快速看前十名对比。";
      cards.push(`
        <article class="chart-card">
          <h3>${{escapeHtml(state.metric)}} ${{chartTitle}}</h3>
          <p class="chart-subtitle">${{chartSubtitle}}</p>
          <div class="bar-list">
            ${{chartRows.map((row, index) => {{
              const value = row[state.metric];
              const width = maxValue > 0
                ? Math.max(8, Math.min(100, Math.round((value / maxValue) * 100)))
                : 8;
              const teamLabel = [row["学校"], row["战队"]].filter(Boolean).join(" / ") || "未知队伍";
              const metaLabel = [row["赛区"], row["兵种"]].filter(Boolean).join(" · ");
              return `
                <div class="bar-item">
                  <div class="bar-rank">#${{index + 1}}</div>
                  <div class="bar-team" title="${{escapeHtml(teamLabel)}}">${{escapeHtml(teamLabel)}}</div>
                  <div class="bar-track" title="${{escapeHtml(metaLabel)}}">
                    <div class="bar-fill" style="width: ${{width}}%"></div>
                  </div>
                  <div class="bar-value">${{escapeHtml(formatValue(value))}}</div>
                </div>
              `;
            }}).join("")}}
          </div>
        </article>
      `);
      insightTypewriterRun += 1;
      els.chartGrid.innerHTML = cards.join("");
    }}

    function renderBaseCell(row, column) {{
      const value = row[column];
      const text = escapeHtml(formatValue(value));
      if (column === "兵种") {{
        return `<td><span class="type-badge" data-type="${{text}}">${{text}}</span></td>`;
      }}
      if (column === "战队") {{
        return `<td class="team-name-cell" title="${{text}}">${{text}}</td>`;
      }}
      return `<td>${{text}}</td>`;
    }}

    function renderTable(rows, columns) {{
      const activeMetricColumn = getCurrentTableMetric();
      const tableColumns = orderTableColumns(columns, activeMetricColumn);
      els.tableHead.innerHTML = `
        <tr>
          <th data-column="__index__">序号</th>
          ${{tableColumns.map((column) => `
            <th class="${{column === activeMetricColumn ? "active-metric-header" : ""}}" data-column="${{escapeHtml(column)}}">
              ${{escapeHtml(column)}}${{column === state.activeSortColumn ? (state.activeSortDirection === "asc" ? " ↑" : " ↓") : ""}}
              ${{column === activeMetricColumn ? '<span class="sort-focus-badge">当前专项</span>' : ""}}
            </th>
          `).join("")}}
        </tr>
      `;

      els.tableHead.querySelectorAll("th").forEach((th) => {{
        th.addEventListener("click", () => {{
          const column = th.dataset.column;
          if (!column || column === "__index__") return;

          if (state.activeSortColumn === column) {{
            state.activeSortDirection = state.activeSortDirection === "desc" ? "asc" : "desc";
          }} else {{
            state.activeSortColumn = column;
            state.activeSortDirection = baseColumns.includes(column) ? "asc" : "desc";
          }}

          render();
        }});
      }});

      if (!rows.length) {{
        els.tableBody.innerHTML = "";
        els.emptyState.hidden = false;
        return;
      }}

      const heatValues = activeMetricColumn
        ? rows.map((row) => row[activeMetricColumn]).filter((value) => typeof value === "number" && Number.isFinite(value))
        : [];
      const maxHeat = heatValues.length ? Math.max(...heatValues, 0) : 0;

      els.emptyState.hidden = true;
      els.tableBody.innerHTML = rows.map((row, index) => `
        <tr>
          <td class="metric-cell row-rank ${{index < 3 ? "rank-top" : ""}}">#${{index + 1}}</td>
          ${{tableColumns.map((column) => {{
            const value = row[column];
            const isMetric = !baseColumns.includes(column);
            if (!isMetric) return renderBaseCell(row, column);
            if (column === activeMetricColumn) {{
              if (typeof value === "number" && Number.isFinite(value)) {{
                const heat = maxHeat > 0 ? Math.max(6, Math.min(100, Math.round((value / maxHeat) * 100))) : 0;
                return `<td class="metric-cell focus-metric"><span class="metric-value">${{escapeHtml(formatValue(value))}}</span><i class="metric-heat" style="--heat: ${{heat}}%"></i></td>`;
              }}
              return `<td class="metric-cell focus-metric focus-metric-empty">-</td>`;
            }}
            return `<td class="metric-cell">${{escapeHtml(formatValue(value))}}</td>`;
          }}).join("")}}
        </tr>
      `).join("");
    }}

    function renderMeta(filteredRows, tableRows) {{
      const metricLabel = state.activeSortColumn || state.metric || "默认";
      const titleParts = [];
      const selectedZones = getSelectedZones();
      if (selectedZones.length) titleParts.push(getSelectedZoneLabel());
      if (state.selectedType !== "全部") titleParts.push(state.selectedType);

      const baseTableTitle = titleParts.length
        ? `${{titleParts.join(" · ")}} 数据列表`
        : "综合数据列表";
      const currentTitle = state.selectedType === "全部" && state.tableTypePage
        ? `${{baseTableTitle}} · ${{state.tableTypePage}}页`
        : baseTableTitle;
      const heroTitle = titleParts.length
        ? `${{titleParts.join(" · ")}}`
        : payload.title;
      const pageMeta = state.selectedType === "全部" && state.tableTypePage
        ? `${{state.tableTypePage}}页 ${{tableRows.length}} 条（全部兵种共 ${{filteredRows.length}} 条）`
        : `${{filteredRows.length}} 条`;
      const singleTeam = getSingleTeamCandidate(filteredRows);
      const radarLabel = getRadarShapeLabel(singleTeam ? singleTeam.zone : (selectedZones.length === 1 ? selectedZones[0] : "全部"));
      const mvpRadar = singleTeam ? buildMvpRadarModel(singleTeam.key, singleTeam.zone) : null;

      els.heroTitle.textContent = heroTitle;
      els.heroSubtitle.textContent = filteredRows.length
        ? (singleTeam
          ? `当前已锁定 ${{singleTeam.label}}，${{radarLabel}}会直接显示在表格上方，对比它在 ${{singleTeam.zone}} 赛区里的兵种综合水平。${{mvpRadar ? "检测到该队伍此赛区的 MVP 数据，已同步展示 MVP 雷达图。" : ""}}`
          : (selectedZones.length > 1
            ? `当前正在比较 ${{selectedZones.length}} 个赛区，主数据表可按兵种分页查看；跨赛区总实力表已经放在数据表下方，并按七边形雷达图规则汇总。`
            : `当前筛选命中 ${{filteredRows.length}} 条记录，你可以继续切赛区、兵种和排序指标，页面会自动收起无数据字段。`))
        : "当前筛选下没有可展示的数据，可以换个赛区、兵种或搜索词再试。";
      els.tableTitle.textContent = currentTitle;
      els.tableMeta.textContent = singleTeam
        ? `当前显示 ${{pageMeta}}，按“${{metricLabel}}”排序，已在上方展示赛区综合雷达图${{mvpRadar ? "和 MVP 雷达图" : ""}}`
        : (selectedZones.length > 1
          ? `当前显示 ${{pageMeta}}，已选择 ${{selectedZones.length}} 个赛区；下方总实力表按各兵种关键数据相对合并均值排序`
          : `当前显示 ${{pageMeta}}，按“${{metricLabel}}”排序`);
      document.title = heroTitle;
    }}

    function render() {{
      renderFilterSelects();
      const filteredRows = getFilteredRows();
      renderMetricSelect(filteredRows);

      renderCompareControls();
      const visibleColumns = getVisibleColumns(filteredRows);
      const sortedRows = sortRows(filteredRows.slice(), visibleColumns);
      const tablePageRows = renderTableTypePages(filteredRows);
      const tableVisibleColumns = getTableVisibleColumns(tablePageRows);
      const rows = sortRows(tablePageRows.slice(), tableVisibleColumns).slice(0, state.limit);
      renderSummary(filteredRows);
      renderMeta(filteredRows, tablePageRows);
      renderTacticalBrief(filteredRows, sortedRows, visibleColumns);
      renderCharts(sortedRows);
      renderTable(rows, tableVisibleColumns);
      renderBelowTableCards();
    }}


    document.querySelectorAll("[data-metric-preset]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const metric = button.dataset.metricPreset;
        const filteredRows = getFilteredRows();
        const visibleColumns = getVisibleColumns(filteredRows);
        if (!visibleColumns.includes(metric)) return;
        state.metric = metric;
        state.activeSortColumn = metric;
        state.activeSortDirection = "desc";
        state.direction = "desc";
        els.sortDirection.value = "desc";
        focusTablePageForMetric(metric);
        render();
      }});
    }});

    els.searchInput.addEventListener("input", (event) => {{
      state.keyword = event.target.value.trim();
      render();
    }});

    els.typeSelect.addEventListener("change", (event) => {{
      state.selectedType = event.target.value;
      render();
    }});

    els.metricSelect.addEventListener("change", (event) => {{
      state.metric = event.target.value;
      state.activeSortColumn = event.target.value;
      state.activeSortDirection = els.sortDirection.value;
      focusTablePageForMetric(event.target.value);
      render();
    }});

    els.sortDirection.addEventListener("change", (event) => {{
      state.direction = event.target.value;
      state.activeSortDirection = event.target.value;
      render();
    }});

    const themeLabels = {{
      day: "☀️ 白昼",
      night: "🌙 夜间",
    }};
    const densityLabels = {{
      standard: "▤ 紧凑",
      compact: "▥ 标准",
    }};
    const backgroundLabels = {{
      fancy: "✦ 背景：花哨",
      simple: "▧ 背景：简洁",
    }};

    function getCurrentTheme() {{
      return document.documentElement.dataset.theme === "night" ? "night" : "day";
    }}

    function setTheme(theme) {{
      const nextTheme = theme === "night" ? "night" : "day";
      document.documentElement.dataset.theme = nextTheme;
      localStorage.setItem("rm-dashboard-theme", nextTheme);
      if (els.themeToggle) {{
        els.themeToggle.textContent = themeLabels[nextTheme];
        els.themeToggle.setAttribute("aria-label", nextTheme === "night" ? "切换到白昼模式" : "切换到夜间模式");
      }}
    }}

    function getCurrentBackground() {{
      return document.documentElement.dataset.background === "simple" ? "simple" : "fancy";
    }}

    function setBackground(background) {{
      const nextBackground = background === "simple" ? "simple" : "fancy";
      document.documentElement.dataset.background = nextBackground;
      localStorage.setItem("rm-dashboard-background", nextBackground);
      if (els.backgroundToggle) {{
        els.backgroundToggle.textContent = backgroundLabels[nextBackground];
        els.backgroundToggle.setAttribute(
          "aria-label",
          nextBackground === "fancy" ? "切换到简洁背景" : "切换到花哨背景"
        );
        els.backgroundToggle.setAttribute("aria-pressed", nextBackground === "simple" ? "true" : "false");
      }}
    }}

    function getCurrentDensity() {{
      return document.documentElement.dataset.density === "compact" ? "compact" : "standard";
    }}

    function setDensity(density) {{
      const nextDensity = density === "compact" ? "compact" : "standard";
      document.documentElement.dataset.density = nextDensity;
      localStorage.setItem("rm-dashboard-density", nextDensity);
      if (els.densityToggle) {{
        els.densityToggle.textContent = densityLabels[nextDensity];
        els.densityToggle.setAttribute("aria-label", nextDensity === "compact" ? "切换到标准视图" : "切换到紧凑视图");
      }}
    }}

    els.rowLimit.addEventListener("change", (event) => {{
      state.limit = Number(event.target.value);
      render();
    }});


    if (els.compareZoneSelect) {{
      els.compareZoneSelect.addEventListener("change", (event) => {{
        state.compareZone = event.target.value;
        renderCompareControls();
      }});
    }}

    if (els.compareSearchInput) {{
      els.compareSearchInput.addEventListener("input", (event) => {{
        state.compareKeyword = event.target.value.trim();
        renderCompareControls();
      }});
    }}

    if (els.compareAddButton) {{
      els.compareAddButton.addEventListener("click", () => {{
        addCurrentCompareTeam();
      }});
    }}

    if (els.compareClearButton) {{
      els.compareClearButton.addEventListener("click", () => {{
        state.compareSelections = [];
        render();
      }});
    }}

    if (els.compareTray) {{
      els.compareTray.addEventListener("click", (event) => {{
        const button = event.target.closest("[data-remove-compare]");
        if (!button) return;
        removeCompareTeam(button.dataset.removeCompare);
      }});
    }}

    if (els.themeToggle) {{
      setTheme(getCurrentTheme());
      els.themeToggle.addEventListener("click", () => {{
        setTheme(getCurrentTheme() === "night" ? "day" : "night");
      }});
    }}

    if (els.backgroundToggle) {{
      setBackground(getCurrentBackground());
      els.backgroundToggle.addEventListener("click", () => {{
        setBackground(getCurrentBackground() === "fancy" ? "simple" : "fancy");
      }});
    }}

    if (els.densityToggle) {{
      setDensity(getCurrentDensity());
      els.densityToggle.addEventListener("click", () => {{
        setDensity(getCurrentDensity() === "compact" ? "standard" : "compact");
      }});
    }}


    document.addEventListener("click", async (event) => {{
      const button = event.target.closest("[data-copy-brief]");
      if (!button) return;
      const text = window.rmCurrentBriefText || "";
      if (!text) return;
      const originalText = button.textContent;
      try {{
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          await navigator.clipboard.writeText(text);
        }} else {{
          const textarea = document.createElement("textarea");
          textarea.value = text;
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          document.body.removeChild(textarea);
        }}
        button.textContent = "已复制";
      }} catch (error) {{
        button.textContent = "复制失败，手动选中上方文字";
      }} finally {{
        window.setTimeout(() => {{
          button.textContent = originalText;
        }}, 1600);
      }}
    }});

    /* 一级板块切换 + 赛程赛果分页 */
    const scheduleData = payload.scheduleData || {{ matches: [], qualifiers: [] }};
    let schedulePage = 1;
    const schedulePageSize = 30;

    function scheduleEscape(value) {{
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({{
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }})[char]);
    }}

    function uniqueScheduleValues(key) {{
      return [...new Set(scheduleData.matches.map((item) => item[key]).filter(Boolean))]
        .sort((a, b) => key === "season"
          ? Number(b) - Number(a)
          : String(a).localeCompare(String(b), "zh-CN", {{ numeric: true }}));
    }}

    function fillScheduleSelect(id, values, placeholder, preferredValue = "") {{
      const select = document.getElementById(id);
      if (!select) return;
      const previousValue = select.value;
      select.innerHTML = `<option value="">${{scheduleEscape(placeholder)}}</option>` + values.map((value) =>
        `<option value="${{scheduleEscape(value)}}">${{scheduleEscape(value)}}</option>`
      ).join("");
      const nextValue = values.includes(preferredValue)
        ? preferredValue
        : (values.includes(previousValue) ? previousValue : "");
      select.value = nextValue;
    }}

    function getScheduleValuesFor(key, season = "", zone = "") {{
      return [...new Set(scheduleData.matches.filter((item) =>
        (!season || item.season === season) && (!zone || item.zone === zone)
      ).map((item) => item[key]).filter(Boolean))].sort((a, b) =>
        String(a).localeCompare(String(b), "zh-CN", {{ numeric: true }})
      );
    }}

    function getPreferredFinalZone(values) {{
      return ["全国赛", "总决赛"].find((value) => values.includes(value)) || values[0] || "";
    }}

    function refreshScheduleZoneOptions(forceFinal = false) {{
      const season = document.getElementById("scheduleSeason").value;
      const values = getScheduleValuesFor("zone", season);
      const preferred = forceFinal ? getPreferredFinalZone(values) : document.getElementById("scheduleZone").value;
      fillScheduleSelect("scheduleZone", values, "全部赛区", preferred);
      refreshScheduleStageOptions();
    }}

    function refreshScheduleStageOptions() {{
      const season = document.getElementById("scheduleSeason").value;
      const zone = document.getElementById("scheduleZone").value;
      fillScheduleSelect("scheduleStage", getScheduleValuesFor("stage", season, zone), "全部比赛阶段");
    }}

    function renderScheduleSummary() {{
      const teams = new Set();
      const schools = new Set();
      scheduleData.matches.forEach((item) => {{
        teams.add(`${{item.redSchool}}|${{item.redTeam}}`);
        teams.add(`${{item.blueSchool}}|${{item.blueTeam}}`);
        schools.add(item.redSchool);
        schools.add(item.blueSchool);
      }});
      document.getElementById("scheduleMatchCount").textContent = scheduleData.matches.length.toLocaleString();
      document.getElementById("scheduleTeamCount").textContent = teams.size.toLocaleString();
      document.getElementById("scheduleSchoolCount").textContent = schools.size.toLocaleString();
      document.getElementById("scheduleUncertainCount").textContent = scheduleData.matches.filter((item) => item.uncertain).length.toLocaleString();

      const recap = uniqueScheduleValues("season").map((season) => {{
        const rows = scheduleData.matches.filter((item) => item.season === season);
        const seasonTeams = new Set();
        rows.forEach((item) => {{ seasonTeams.add(item.redTeam); seasonTeams.add(item.blueTeam); }});
        const finals = rows.filter((item) => /决赛|冠军|季军/.test(item.stage || "")).length;
        return `<article class="recap-card"><b>${{scheduleEscape(season)}} 赛季</b><span>${{rows.length.toLocaleString()}} 场 · ${{seasonTeams.size}} 支队伍 · ${{finals}} 场淘汰/决赛记录</span></article>`;
      }}).join("");
      document.getElementById("seasonRecap").innerHTML = recap;

      renderZoneRankings();
    }}

    function renderZoneRankings() {{
      const season = document.getElementById("scheduleSeason").value;
      const zone = document.getElementById("scheduleZone").value;
      const rankings = (scheduleData.rankings || []).filter((item) =>
        (!season || item.season === season) && (!zone || item.zone === zone)
      ).sort((a, b) => String(a.zone).localeCompare(String(b.zone), "zh-CN") ||
        Number(a.sortOrder || 999) - Number(b.sortOrder || 999));
      document.getElementById("zoneRankingTitle").textContent = zone ? `${{season || "当前"}} ${{zone}}排名` : `${{season || "当前"}} 各赛区排名`;
      const rankedCount = rankings.filter((item) => item.result && item.result !== "未列名次").length;
      document.getElementById("qualifierCountLabel").textContent = rankings.length ? `${{rankings.length}} 支队伍 · ${{rankedCount}} 支已有名次` : "暂无排名数据";
      document.getElementById("qualifierRecap").innerHTML = rankings.length ? rankings.map((item) =>
        `<article class="recap-card"><b>${{scheduleEscape(item.result || "未列名次")}} · ${{scheduleEscape(item.team)}}</b><span>${{scheduleEscape(item.school)}} · ${{scheduleEscape(item.zone)}}</span></article>`
      ).join("") : '<div class="schedule-empty">当前赛区暂无官方排名数据。</div>';
    }}

    function getFilteredSchedule() {{
      const season = document.getElementById("scheduleSeason").value;
      const zone = document.getElementById("scheduleZone").value;
      const stage = document.getElementById("scheduleStage").value;
      const keyword = document.getElementById("scheduleSearch").value.trim().toLowerCase();
      const includeUncertain = document.getElementById("scheduleIncludeUncertain").checked;
      return scheduleData.matches.filter((item) => {{
        if (season && item.season !== season) return false;
        if (zone && item.zone !== zone) return false;
        if (stage && item.stage !== stage) return false;
        if (!includeUncertain && item.uncertain) return false;
        if (!keyword) return true;
        return [item.redSchool, item.redTeam, item.blueSchool, item.blueTeam, item.note]
          .join(" ").toLowerCase().includes(keyword);
      }}).sort((a, b) => {{
        const seasonDifference = Number(b.season) - Number(a.season);
        if (seasonDifference) return seasonDifference;
        const orderDifference = Number(b.order || 0) - Number(a.order || 0);
        if (orderDifference) return orderDifference;
        return Number(b.id || 0) - Number(a.id || 0);
      }});
    }}

    function getReplayLink(item) {{
      const key = `${{item.season}}|${{item.zone}}|${{item.order}}|${{item.id}}`;
      return (payload.replayLinks || {{}})[key] || null;
    }}

    function renderSchedule() {{
      renderZoneRankings();
      const rows = getFilteredSchedule();
      const pages = Math.max(1, Math.ceil(rows.length / schedulePageSize));
      schedulePage = Math.min(schedulePage, pages);
      const visible = rows.slice((schedulePage - 1) * schedulePageSize, schedulePage * schedulePageSize);
      const stageGroups = [];
      visible.forEach((item) => {{
        const stageName = item.stage || "阶段未明";
        let group = stageGroups.find((entry) => entry.name === stageName);
        if (!group) {{
          group = {{ name: stageName, rows: [] }};
          stageGroups.push(group);
        }}
        group.rows.push(item);
      }});
      document.getElementById("scheduleList").innerHTML = visible.length ? stageGroups.map((group) => {{
        const stageTotal = rows.filter((item) => (item.stage || "阶段未明") === group.name).length;
        const cards = group.rows.map((item) => {{
        const replay = getReplayLink(item);
        const replayButton = replay
          ? `<br><a class="schedule-replay" href="${{scheduleEscape(replay.url)}}" target="_blank" rel="noopener" title="${{scheduleEscape(replay.title)}}">▶ 直接看回放</a>`
          : "";
        return `
        <article class="schedule-match">
          <div class="schedule-meta"><b>${{scheduleEscape(item.season)}}</b>${{scheduleEscape(item.zone || "未标注")}}</div>
          <div class="schedule-team red"><b>${{scheduleEscape(item.redTeam)}}</b><small>${{scheduleEscape(item.redSchool)}}</small></div>
          <div class="schedule-score"><span class="red">${{scheduleEscape(item.redScore)}}</span><span>:</span><span class="blue">${{scheduleEscape(item.blueScore)}}</span></div>
          <div class="schedule-team"><b>${{scheduleEscape(item.blueTeam)}}</b><small>${{scheduleEscape(item.blueSchool)}}</small></div>
          <div class="schedule-tail"><span class="schedule-stage">${{scheduleEscape(item.stage || "阶段未明")}}</span>第 ${{scheduleEscape(item.order || "—")}} 场${{item.note ? ` · ${{scheduleEscape(item.note)}}` : ""}}${{item.uncertain ? '<br><span class="schedule-flag">待核记录</span>' : ""}}${{replayButton}}</div>
        </article>`;
        }}).join("");
        return `<section class="schedule-stage-group">
          <div class="schedule-stage-heading"><b>${{scheduleEscape(group.name)}}</b><span>本页 ${{group.rows.length}} 场 · 共 ${{stageTotal}} 场</span></div>
          ${{cards}}
        </section>`;
      }}).join("") : '<div class="schedule-empty">当前筛选条件下没有赛程记录。</div>';
      document.getElementById("scheduleCountLabel").textContent = `共 ${{rows.length.toLocaleString()}} 场，当前显示 ${{visible.length}} 场`;
      document.getElementById("schedulePageLabel").textContent = `第 ${{schedulePage}} / ${{pages}} 页`;
      document.getElementById("schedulePrev").disabled = schedulePage <= 1;
      document.getElementById("scheduleNext").disabled = schedulePage >= pages;
    }}

    document.querySelectorAll("[data-dataset-tab]").forEach((button) => {{
      button.addEventListener("click", () => {{
        const target = button.dataset.datasetTab;
        document.querySelectorAll("[data-dataset-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
        document.querySelectorAll("[data-dataset-board]").forEach((board) => board.hidden = board.dataset.datasetBoard !== target);
        localStorage.setItem("rm-dashboard-board", target);
        if (target === "schedule") renderSchedule();
        window.scrollTo({{ top: 0, behavior: "smooth" }});
      }});
    }});
    document.getElementById("scheduleSeason").addEventListener("change", () => {{
      schedulePage = 1;
      refreshScheduleZoneOptions(true);
      renderSchedule();
    }});
    document.getElementById("scheduleZone").addEventListener("change", () => {{
      schedulePage = 1;
      refreshScheduleStageOptions();
      renderSchedule();
    }});
    ["scheduleStage", "scheduleIncludeUncertain"].forEach((id) =>
      document.getElementById(id).addEventListener("change", () => {{ schedulePage = 1; renderSchedule(); }})
    );
    document.getElementById("scheduleSearch").addEventListener("input", () => {{ schedulePage = 1; renderSchedule(); }});
    document.getElementById("schedulePrev").addEventListener("click", () => {{ schedulePage -= 1; renderSchedule(); }});
    document.getElementById("scheduleNext").addEventListener("click", () => {{ schedulePage += 1; renderSchedule(); }});
    const scheduleSeasons = uniqueScheduleValues("season");
    fillScheduleSelect("scheduleSeason", scheduleSeasons, "全部赛季", scheduleSeasons[0] || "");
    refreshScheduleZoneOptions(true);
    renderScheduleSummary();
    renderSchedule();
    const savedBoard = localStorage.getItem("rm-dashboard-board");
    if (savedBoard === "schedule") document.querySelector('[data-dataset-tab="schedule"]').click();

    initializeVirtualMetrics();
    render();
  </script>
</body>
</html>
"""


def main(csv_file, title, default_sort=None, initial_zone="全部", initial_type="全部", initial_keyword=""):
    csv_path = Path(csv_file)
    if not csv_path.exists():
        print(f"CSV not found: {csv_path}")
        return 1

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        rows = []
        for raw_row in reader:
            row = {column: parse_value(raw_row.get(column, "")) for column in columns}
            rows.append(row)

    columns, rows = add_derived_metrics(columns, rows)
    mvp_rows = load_mvp_rows()
    columns, rows = add_mvp_counts(columns, rows, mvp_rows)

    metric = choose_default_metric(columns, default_sort)
    robot_types = sorted({str(row["兵种"]) for row in rows if row.get("兵种")})
    payload = {
        "title": title,
        "columns": columns,
        "rows": rows,
        "zones": sorted({str(row["赛区"]) for row in rows if row.get("赛区")}),
        "types": robot_types,
        "mvpRows": mvp_rows,
        "teamEvaluation": get_team_evaluation_config(),
        "defaultMetric": metric,
        "summary": build_summary(rows, metric) if metric else {},
        "initialZone": initial_zone,
        "initialType": initial_type,
        "initialKeyword": initial_keyword,
        "scheduleData": load_schedule_data(),
        "replayLinks": load_replay_links(),
    }

    output_path = csv_path.with_name("robot_dashboard.html")
    output_path.write_text(render_html(title, payload), encoding="utf-8")
    print(f"网页报告已生成: {output_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        sort_col = sys.argv[3] if len(sys.argv) > 3 else None
        zone = sys.argv[4] if len(sys.argv) > 4 else "全部"
        robot_type = sys.argv[5] if len(sys.argv) > 5 else "全部"
        keyword = sys.argv[6] if len(sys.argv) > 6 else ""
        raise SystemExit(main(sys.argv[1], sys.argv[2], sort_col, zone, robot_type, keyword))
    raise SystemExit("Usage: python3 view_table.py <csv_file> <title> [default_sort] [initial_zone] [initial_type] [initial_keyword]")
