import csv
import html
import json
import sys
from pathlib import Path


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
        "局均兑换经济数",
        "双倍易伤时间",
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
  <style>
    :root {{
      --bg: #f4efe7;
      --panel: rgba(255, 250, 242, 0.82);
      --panel-strong: rgba(255, 247, 236, 0.96);
      --line: rgba(107, 79, 52, 0.14);
      --text: #2d241b;
      --muted: #78624a;
      --accent: #b85c38;
      --accent-deep: #8f3b1f;
      --accent-soft: rgba(184, 92, 56, 0.12);
      --shadow: 0 18px 50px rgba(89, 57, 28, 0.12);
      --radius: 24px;
      --radius-sm: 16px;
      --font-sans: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
      --font-display: "ZCOOL XiaoWei", "STKaiti", "KaiTi", serif;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      font-family: var(--font-sans);
      background:
        radial-gradient(circle at top left, rgba(255, 206, 156, 0.5), transparent 30%),
        radial-gradient(circle at 80% 10%, rgba(176, 216, 255, 0.35), transparent 26%),
        linear-gradient(180deg, #f9f3eb 0%, #f4efe7 45%, #efe8dc 100%);
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
      background: rgba(237, 170, 92, 0.28);
    }}

    body::after {{
      bottom: -12rem;
      left: -12rem;
      background: rgba(95, 149, 186, 0.18);
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
      border: 1px solid rgba(255, 255, 255, 0.5);
      backdrop-filter: blur(12px);
      box-shadow: var(--shadow);
      border-radius: var(--radius);
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
      background: rgba(255,255,255,0.78);
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
      background: rgba(255,255,255,0.75);
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
      background: rgba(255, 252, 247, 0.55);
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

    .axis-list {{
      display: grid;
      gap: 10px;
    }}

    .axis-card {{
      padding: 14px;
      border-radius: 18px;
      background: linear-gradient(180deg, rgba(255,255,255,0.94), rgba(250, 242, 233, 0.9));
      border: 1px solid rgba(107, 79, 52, 0.1);
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
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <div class="hero-card">
        <span class="eyebrow">RM DATA DASHBOARD</span>
        <h1 id="heroTitle">{safe_title}</h1>
        <p id="heroSubtitle">把原来偏“文本堆叠”的查询结果整理成网页化仪表盘了。现在可以按兵种切换、按关键字搜索、按任意指标排序；当筛到单支战队时，会直接在表格上方显示七边形雷达图，对比它在赛区里的兵种综合水平。</p>
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
          <input id="searchInput" type="text" placeholder="例如 华南理工 / 南部 / 英雄">
        </div>
        <div class="field">
          <label for="zoneSelect">赛区选择</label>
          <select id="zoneSelect"></select>
        </div>
        <div class="field">
          <label for="typeSelect">兵种选择</label>
          <select id="typeSelect"></select>
        </div>
        <div class="field">
          <label for="metricSelect">排序指标</label>
          <select id="metricSelect"></select>
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
        <div class="table-topbar">
          <div>
            <h2 id="tableTitle">数据列表</h2>
            <div class="table-meta" id="tableMeta">准备中...</div>
          </div>
        </div>
        <div class="chart-grid" id="chartGrid"></div>
        <div class="table-wrap">
          <table>
            <thead id="tableHead"></thead>
            <tbody id="tableBody"></tbody>
          </table>
          <div class="empty" id="emptyState" hidden>当前筛选条件下没有结果。</div>
        </div>
      </section>
    </section>
  </div>

  <script>
    const payload = {payload_json};
    const baseColumns = ["赛区", "学校", "战队", "兵种"];
    const metricPriority = [
      "小弹丸命中率",
      "大弹丸命中率",
      "KDA得分",
      "对敌伤害量",
      "建筑伤害",
      "击杀数",
      "场均发弹量",
      "局均兑换经济数",
      "双倍易伤时间",
    ];
    const radarAxes = [
      {{ type: "英雄", metricKey: "对敌伤害量", fallbackMetricKeys: ["建筑伤害"], metricLabel: "局均总伤害" }},
      {{ type: "步兵", metricKey: "对敌伤害量", metricLabel: "局均总伤害" }},
      {{ type: "哨兵", metricKey: "对敌伤害量", metricLabel: "局均总伤害" }},
      {{ type: "无人机", metricKey: "对敌伤害量", metricLabel: "局均总伤害" }},
      {{ type: "雷达", metricKey: "双倍易伤时间", metricLabel: "局均易伤时长" }},
      {{ type: "工程", metricKey: "局均兑换经济数", metricLabel: "局均兑换经济" }},
      {{ type: "飞镖", metricKey: "建筑伤害", metricLabel: "局均建筑伤害" }},
    ];
    const league3v3Types = ["英雄", "步兵", "哨兵"];
    const radarScaleSteps = [0.6, 1, 2, 3];

    let state = {{
      selectedZone: payload.initialZone || "全部",
      selectedType: payload.initialType || "全部",
      metric: payload.defaultMetric || "",
      direction: "desc",
      keyword: payload.initialKeyword || "",
      limit: 50,
      activeSortColumn: payload.defaultMetric || "",
      activeSortDirection: "desc",
    }};

    const els = {{
      heroTitle: document.getElementById("heroTitle"),
      heroSubtitle: document.getElementById("heroSubtitle"),
      teamCount: document.getElementById("teamCount"),
      zoneCount: document.getElementById("zoneCount"),
      typeCount: document.getElementById("typeCount"),
      avgMetric: document.getElementById("avgMetric"),
      searchInput: document.getElementById("searchInput"),
      zoneSelect: document.getElementById("zoneSelect"),
      typeSelect: document.getElementById("typeSelect"),
      metricSelect: document.getElementById("metricSelect"),
      sortDirection: document.getElementById("sortDirection"),
      rowLimit: document.getElementById("rowLimit"),
      tableHead: document.getElementById("tableHead"),
      tableBody: document.getElementById("tableBody"),
      tableTitle: document.getElementById("tableTitle"),
      tableMeta: document.getElementById("tableMeta"),
      chartGrid: document.getElementById("chartGrid"),
      emptyState: document.getElementById("emptyState"),
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
      return [row["学校"] || "", row["战队"] || ""].join("::");
    }}

    function getTeamLabel(row) {{
      return [row["学校"], row["战队"]].filter(Boolean).join(" / ") || "未知队伍";
    }}

    function is3v3LeagueZone(zoneName) {{
      if (!zoneName || zoneName === "全部") return false;
      const normalized = String(zoneName).toLowerCase().replace(/\s+/g, "");
      return normalized.includes("3v3联盟赛") || normalized.includes("3vs3联盟赛");
    }}

    function getAllowedTypesForZone(zoneName) {{
      return is3v3LeagueZone(zoneName) ? league3v3Types : payload.types;
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

    function getAxisMetricValue(row, axis) {{
      if (!row) return null;
      if (axis.metricKey === "__dart_total_hits__") {{
        const dartColumns = ["累计命中前哨站数", "累计命中固定靶数", "累计随机固定靶数", "累计随机移动靶数"];
        const values = dartColumns
          .map((column) => row[column])
          .filter((value) => typeof value === "number" && Number.isFinite(value));
        if (!values.length) return null;
        return values.reduce((sum, value) => sum + value, 0);
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
          <line x1="${{center}}" y1="${{center}}" x2="${{outer.x}}" y2="${{outer.y}}" stroke="rgba(143,59,31,0.16)" stroke-width="1" />
          <circle cx="${{dot.x}}" cy="${{dot.y}}" r="4.5" fill="#8f3b1f" />
          <text x="${{label.x}}" y="${{label.y}}" text-anchor="${{anchor}}" font-size="13" fill="#5a4633">${{escapeHtml(axis.type)}}</text>
        `;
      }}).join("");

      const scaleMarkup = radarScaleSteps.map((step) => {{
        const y = center - (step / 3) * radius;
        return `
          <text x="${{center + 10}}" y="${{y + 4}}" font-size="11" fill="rgba(120, 98, 74, 0.95)">
            ${{Math.round(step * 100)}}%
          </text>
        `;
      }}).join("");

      const overflowAxes = radar.axes.filter((axis) => axis.overflow).map((axis) => axis.type);
      const noteText = overflowAxes.length
        ? `注: ${{overflowAxes.join("、")}} 超过 300% 均值，图形按外圈封顶显示。`
        : (radar.axes.length === 3
          ? "注: 3V3 联盟赛仅展示英雄、步兵、哨兵，三条轴都按局均总伤害计算。"
          : "注: 英雄、步兵、哨兵、无人机按局均总伤害，雷达按局均易伤时长，工程按局均兑换经济，飞镖按局均建筑伤害。");

      return `
        <article class="chart-card radar-card">
          <div class="radar-header">
            <div>
              <span class="eyebrow">ZONE RADAR</span>
              <h3>${{escapeHtml(radar.teamLabel)}} ${{escapeHtml(radar.shapeLabel)}}</h3>
              <p>${{escapeHtml(radar.zoneName)}}赛区基线下的兵种综合水平，100% 表示该赛区该兵种均值。</p>
            </div>
          </div>
          <div class="radar-layout">
            <div class="radar-stage">
              <div class="radar-legend">
                <span class="legend-chip">等高线: 60% / 100% / 200% / 300%</span>
                <span class="legend-chip">100% = 该赛区对应兵种均值</span>
              </div>
              <svg class="radar-svg" viewBox="0 0 ${{size}} ${{size}}" role="img" aria-label="${{escapeHtml(radar.teamLabel)}} 赛区七边形雷达图">
                <defs>
                  <linearGradient id="radarAreaFill" x1="0%" y1="0%" x2="100%" y2="100%">
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
                <polygon points="${{areaPoints}}" fill="url(#radarAreaFill)" stroke="#b85c38" stroke-width="3" />
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
                      赛区均值: ${{escapeHtml(formatValue(axis.zoneAverage))}}
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

      if (state.selectedZone !== "全部") {{
        rows = rows.filter((row) => row["赛区"] === state.selectedZone);
        if (is3v3LeagueZone(state.selectedZone)) {{
          rows = rows.filter((row) => league3v3Types.includes(row["兵种"]));
        }}
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

    function getVisibleColumns(rows) {{
      const metricColumns = getMetricColumns().filter((column) =>
        rows.some((row) => hasData(row[column]))
      );
      return [...baseColumns, ...metricColumns];
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

    function renderFilterSelects() {{
      const zones = ["全部", ...payload.zones];
      const types = ["全部", ...getAllowedTypesForZone(state.selectedZone)];

      if (!zones.includes(state.selectedZone)) {{
        state.selectedZone = "全部";
      }}
      if (!types.includes(state.selectedType)) {{
        state.selectedType = "全部";
      }}

      renderSelectOptions(els.zoneSelect, zones, state.selectedZone);
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

    function renderCharts(rows) {{
      const singleTeam = getSingleTeamCandidate(rows);
      if (singleTeam) {{
        els.chartGrid.innerHTML = renderRadarCard(buildRadarModel(singleTeam.key, singleTeam.zone));
        return;
      }}

      if (!state.metric) {{
        els.chartGrid.innerHTML = "";
        return;
      }}

      const chartRows = rows
        .filter((row) => typeof row[state.metric] === "number")
        .slice(0, 10);

      if (!chartRows.length) {{
        els.chartGrid.innerHTML = "";
        return;
      }}

      const topValue = chartRows[0][state.metric] || 1;
      els.chartGrid.innerHTML = `
        <article class="chart-card">
          <h3>${{escapeHtml(state.metric)}} Top 10</h3>
          <p class="chart-subtitle">按当前筛选结果自动排序，方便快速看前十名对比。</p>
          <div class="bar-list">
            ${{chartRows.map((row, index) => {{
              const value = row[state.metric];
              const width = Math.max(8, Math.round((value / topValue) * 100));
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
      `;
    }}

    function renderTable(rows, columns) {{
      els.tableHead.innerHTML = `
        <tr>
          <th data-column="__index__">序号</th>
          ${{columns.map((column) => `
            <th data-column="${{escapeHtml(column)}}">
              ${{escapeHtml(column)}}${{column === state.activeSortColumn ? (state.activeSortDirection === "asc" ? " ↑" : " ↓") : ""}}
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

      els.emptyState.hidden = true;
      els.tableBody.innerHTML = rows.map((row, index) => `
        <tr>
          <td class="metric-cell">${{index + 1}}</td>
          ${{columns.map((column) => {{
            const value = row[column];
            const isMetric = !baseColumns.includes(column);
            if (!isMetric) {{
              return `<td>${{escapeHtml(formatValue(value))}}</td>`;
            }}
            return `<td class="metric-cell">${{escapeHtml(formatValue(value))}}</td>`;
          }}).join("")}}
        </tr>
      `).join("");
    }}

    function renderMeta(filteredRows) {{
      const metricLabel = state.activeSortColumn || state.metric || "默认";
      const titleParts = [];
      if (state.selectedZone !== "全部") titleParts.push(state.selectedZone);
      if (state.selectedType !== "全部") titleParts.push(state.selectedType);

      const currentTitle = titleParts.length
        ? `${{titleParts.join(" · ")}} 数据列表`
        : "综合数据列表";
      const heroTitle = titleParts.length
        ? `${{titleParts.join(" · ")}}`
        : payload.title;
      const singleTeam = getSingleTeamCandidate(filteredRows);
      const radarLabel = getRadarShapeLabel(singleTeam ? singleTeam.zone : state.selectedZone);

      els.heroTitle.textContent = heroTitle;
      els.heroSubtitle.textContent = filteredRows.length
        ? (singleTeam
          ? `当前已锁定 ${{singleTeam.label}}，${{radarLabel}}会直接显示在表格上方，对比它在 ${{singleTeam.zone}} 赛区里的兵种综合水平。`
          : `当前筛选命中 ${{filteredRows.length}} 条记录，你可以继续切赛区、兵种和排序指标，页面会自动收起无数据字段。`)
        : "当前筛选下没有可展示的数据，可以换个赛区、兵种或搜索词再试。";
      els.tableTitle.textContent = currentTitle;
      els.tableMeta.textContent = singleTeam
        ? `当前显示 ${{filteredRows.length}} 条匹配记录，按“${{metricLabel}}”排序，已在上方展示赛区综合雷达图`
        : `当前显示 ${{filteredRows.length}} 条匹配记录，按“${{metricLabel}}”排序`;
      document.title = heroTitle;
    }}

    function render() {{
      renderFilterSelects();
      const filteredRows = getFilteredRows();
      renderMetricSelect(filteredRows);
      const visibleColumns = getVisibleColumns(filteredRows);
      const rows = getVisibleRows(filteredRows, visibleColumns);
      renderSummary(filteredRows);
      renderMeta(filteredRows);
      renderCharts(rows);
      renderTable(rows, visibleColumns);
    }}

    els.searchInput.addEventListener("input", (event) => {{
      state.keyword = event.target.value.trim();
      render();
    }});

    els.zoneSelect.addEventListener("change", (event) => {{
      state.selectedZone = event.target.value;
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
      render();
    }});

    els.sortDirection.addEventListener("change", (event) => {{
      state.direction = event.target.value;
      state.activeSortDirection = event.target.value;
      render();
    }});

    els.rowLimit.addEventListener("change", (event) => {{
      state.limit = Number(event.target.value);
      render();
    }});

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

    metric = choose_default_metric(columns, default_sort)
    robot_types = sorted({str(row["兵种"]) for row in rows if row.get("兵种")})
    payload = {
        "title": title,
        "columns": columns,
        "rows": rows,
        "zones": sorted({str(row["赛区"]) for row in rows if row.get("赛区")}),
        "types": robot_types,
        "defaultMetric": metric,
        "summary": build_summary(rows, metric) if metric else {},
        "initialZone": initial_zone,
        "initialType": initial_type,
        "initialKeyword": initial_keyword,
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
