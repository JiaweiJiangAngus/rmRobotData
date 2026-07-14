"""Helpers for loading and saving split RoboMaster result datasets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent / "data"
RMUC_DIR = DATA_DIR / "rmuc_results"
RMUL_DIR = DATA_DIR / "rmul_results"
RMUC_LEGACY = DATA_DIR / "schedule_results.json"
RMUL_LEGACY = DATA_DIR / "rmul_results.json"


def _safe_name(value: Any) -> str:
    text = str(value or "未标注").strip() or "未标注"
    return "".join("_" if char in '/\\:*?"<>|' else char for char in text)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_partitioned_matches(root: Path) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    match_root = root / "matches"
    if not match_root.exists():
        return matches
    for path in sorted(match_root.glob("*/*.json")):
        data = _read_json(path, [])
        if isinstance(data, list):
            matches.extend(data)
    return matches


def _save_partitioned_matches(root: Path, matches: list[dict[str, Any]]) -> None:
    match_root = root / "matches"
    if match_root.exists():
        shutil.rmtree(match_root)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in matches:
        grouped.setdefault((str(item.get("season", "未标注")), str(item.get("zone", "未标注"))), []).append(item)
    for (season, zone), rows in sorted(grouped.items()):
        rows.sort(key=lambda item: (
            str(item.get("stage", "")),
            int(item.get("order") or 0) if str(item.get("order") or "").isdigit() else str(item.get("order") or ""),
            str(item.get("id", "")),
        ))
        _write_json(match_root / _safe_name(season) / f"{_safe_name(zone)}.json", rows)


def load_rmuc_results(base_dir: Path | None = None) -> dict[str, Any] | None:
    base = base_dir or DATA_DIR
    root = base / "rmuc_results"
    legacy_root = base / "schedule_results"
    legacy = base / "schedule_results.json"
    if root.exists():
        payload = {
            "matches": _load_partitioned_matches(root),
            "qualifiers": _read_json(root / "qualifiers.json", []),
            "rankings": _read_json(root / "rankings.json", []),
        }
        return payload
    if legacy_root.exists():
        payload = {
            "matches": _load_partitioned_matches(legacy_root),
            "qualifiers": _read_json(legacy_root / "qualifiers.json", []),
            "rankings": _read_json(legacy_root / "rankings.json", []),
        }
        return payload
    if legacy.exists():
        return _read_json(legacy, None)
    return None


def save_rmuc_results(payload: dict[str, Any], base_dir: Path | None = None) -> None:
    root = (base_dir or DATA_DIR) / "rmuc_results"
    _save_partitioned_matches(root, list(payload.get("matches", [])))
    _write_json(root / "qualifiers.json", payload.get("qualifiers", []))
    _write_json(root / "rankings.json", payload.get("rankings", []))


def load_schedule_results(base_dir: Path | None = None) -> dict[str, Any] | None:
    return load_rmuc_results(base_dir)


def save_schedule_results(payload: dict[str, Any], base_dir: Path | None = None) -> None:
    save_rmuc_results(payload, base_dir)


def load_rmul_results(base_dir: Path | None = None) -> dict[str, Any] | None:
    root = (base_dir or DATA_DIR) / "rmul_results"
    legacy = (base_dir or DATA_DIR) / "rmul_results.json"
    if root.exists():
        payload = {
            "matches": _load_partitioned_matches(root),
            "collections": _read_json(root / "collections.json", []),
            "coverage": _read_json(root / "coverage.json", []),
            "rankings": _read_json(root / "rankings.json", []),
            "missingReplays": _read_json(root / "missing_replays.json", []),
            "supplementedMatches": _read_json(root / "supplemented_matches.json", []),
            "inferredMatches": _read_json(root / "inferred_matches.json", []),
            "nonMatchOrderGaps": _read_json(root / "non_match_order_gaps.json", []),
            "rankingSources": _read_json(root / "ranking_sources.json", []),
        }
        return payload
    if legacy.exists():
        return _read_json(legacy, None)
    return None


def save_rmul_results(payload: dict[str, Any], base_dir: Path | None = None) -> None:
    root = (base_dir or DATA_DIR) / "rmul_results"
    _save_partitioned_matches(root, list(payload.get("matches", [])))
    _write_json(root / "collections.json", payload.get("collections", []))
    _write_json(root / "coverage.json", payload.get("coverage", []))
    _write_json(root / "rankings.json", payload.get("rankings", []))
    _write_json(root / "missing_replays.json", payload.get("missingReplays", []))
    _write_json(root / "supplemented_matches.json", payload.get("supplementedMatches", []))
    _write_json(root / "inferred_matches.json", payload.get("inferredMatches", []))
    _write_json(root / "non_match_order_gaps.json", payload.get("nonMatchOrderGaps", []))
    _write_json(root / "ranking_sources.json", payload.get("rankingSources", []))
