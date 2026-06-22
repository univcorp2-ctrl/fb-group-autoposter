"""Bridge FB posting status into EstateBoard so 投稿済/未投稿 is visible there.

Single source of truth: jobs.db (the autoposter's posting record). This script
projects that truth into EstateBoard's two views:

  1. `output/received/master_properties.jsonl` — the persistent anchor store.
     Posted records gain `_posted_to_fb` (ISO ts), `_posted_groups`, and
     `_posted_screenshot`. These underscore-prefixed fields survive the next
     scrape merge (see EstateBoard scripts/_store.py), so a full `enrich` run
     can surface them as the leftmost 投稿済 column.
  2. `docs/data.json` — the live dashboard data. We patch it in place so the
     dashboard shows 投稿済 immediately, without waiting for a full enrich run.

The join must never drift: the autoposter key is `eb-{propertyId or id}` but the
dashboard shows the record's top-level `id`. We bridge ONLY through the master
store so both sides derive from the same record.

Best-effort by design: if the EstateBoard repo is absent this logs a warning and
returns cleanly. It must never crash the posting pipeline.

Usage:
    python scripts/sync_estateboard_status.py [--eb-root PATH]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger("sync_estateboard_status")

DEFAULT_EB_ROOT = Path(
    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard"
)
POSTED_COLUMN = "投稿済"
POSTED_LABEL = "✅ 投稿済"
POSTED_TO_COLUMN = "投稿先"
POSTED_DATE_COLUMN = "投稿日"


def _group_name_map() -> dict[str, str]:
    """Build {group_id: human name} from groups.yaml (best-effort)."""
    try:
        from config import load_groups

        return {str(g["id"]): str(g.get("name") or g["id"]) for g in load_groups()}
    except Exception as exc:  # noqa: BLE001 - never block the sync on config issues
        log.warning("could not load group names: %s: %s", type(exc).__name__, exc)
        return {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_posted_meta(db_path: str) -> dict[str, dict[str, Any]]:
    """property_id -> {posted_at, groups, screenshot} for posted/uncertain rows.

    posted_at = latest of all posted/uncertain targets for that property.
    groups    = sorted set of group_ids the property was posted to.
    screenshot= one screenshot path (the latest non-empty), or "".
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT j.property_id AS pid, t.group_id, t.posted_at, t.screenshot
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE t.status IN ('posted', 'uncertain')
            ORDER BY COALESCE(t.posted_at, '') ASC
            """
        ).fetchall()
    finally:
        conn.close()

    meta: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = r["pid"]
        entry = meta.setdefault(pid, {"posted_at": None, "groups": set(), "screenshot": ""})
        if r["group_id"]:
            entry["groups"].add(str(r["group_id"]))
        posted_at = r["posted_at"]
        if posted_at and (entry["posted_at"] is None or posted_at > entry["posted_at"]):
            entry["posted_at"] = posted_at
        if r["screenshot"]:
            entry["screenshot"] = str(r["screenshot"])
    return meta


def _join_key(record: dict[str, Any]) -> str:
    """Reproduce the autoposter key exactly: eb-{propertyId or id}."""
    return "eb-" + str(record.get("propertyId") or record.get("id"))


def _atomic_write(path: Path, render: Any) -> None:
    """Write via a temp file in the same dir then os.replace (crash-safe)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        render(f)
    os.replace(tmp, path)


def _group_names(group_ids: Any, name_map: dict[str, str]) -> list[str]:
    """Resolve group_ids -> human names, falling back to the id when unknown."""
    return [name_map.get(str(gid), str(gid)) for gid in sorted(group_ids)]


def patch_master(
    master_path: Path,
    posted_meta: dict[str, dict[str, Any]],
    name_map: dict[str, str],
) -> tuple[int, dict[str, dict[str, str]]]:
    """Stamp posted records in master_properties.jsonl.

    Returns (count, display_info) where display_info maps the record's display
    id -> {"groups": "name1, name2", "date": "YYYY-MM-DD"} for the dashboard.
    `_posted_groups` is stored on each record as a list of NAMES (id fallback).
    """
    if not master_path.exists():
        log.warning("EstateBoard master not found, skipping master patch: %s", master_path)
        return 0, {}

    records: list[dict[str, Any]] = []
    with master_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    marked = 0
    display_info: dict[str, dict[str, str]] = {}
    for rec in records:
        key = _join_key(rec)
        info = posted_meta.get(key)
        if info:
            posted_at = info["posted_at"] or _now_iso()
            names = _group_names(info["groups"], name_map)
            rec["_posted_to_fb"] = posted_at
            rec["_posted_groups"] = names  # NAMES (id fallback), not raw ids
            rec["_posted_screenshot"] = info["screenshot"] or ""
            display_info[str(rec.get("id"))] = {
                "groups": ", ".join(names),
                "date": str(posted_at)[:10],
            }
            marked += 1
        elif rec.get("_posted_to_fb"):
            # Not posted per current truth -> clear any stale stamp.
            rec["_posted_to_fb"] = None

    def render(f: Any) -> None:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False))
            f.write("\n")

    _atomic_write(master_path, render)
    log.info("master patched: %d records marked posted (of %d)", marked, len(records))
    return marked, display_info


_INJECTED_COLUMNS = (POSTED_COLUMN, POSTED_TO_COLUMN, POSTED_DATE_COLUMN)


def patch_data_json(data_path: Path, display_info: dict[str, dict[str, str]]) -> int:
    """Add leading 投稿済 / 投稿先 / 投稿日 columns to docs/data.json.

    投稿先 = comma-joined group NAMES the property was posted to (right after
    投稿済); 投稿日 = the posting date. Returns the count of items marked.
    """
    if not data_path.exists():
        log.warning("EstateBoard data.json not found, skipping dashboard patch: %s", data_path)
        return 0

    data = json.loads(data_path.read_text(encoding="utf-8"))
    columns = [c for c in (data.get("columns") or []) if c not in _INJECTED_COLUMNS]
    # 投稿済 → 投稿先 → 投稿日 then the rest.
    data["columns"] = [POSTED_COLUMN, POSTED_TO_COLUMN, POSTED_DATE_COLUMN] + list(columns)

    marked = 0
    new_items: list[dict[str, Any]] = []
    for item in data.get("items", []):
        info = display_info.get(str(item.get("ID")))
        is_posted = info is not None
        if is_posted:
            marked += 1
        rebuilt = {
            POSTED_COLUMN: POSTED_LABEL if is_posted else "",
            POSTED_TO_COLUMN: info["groups"] if is_posted else "",
            POSTED_DATE_COLUMN: info["date"] if is_posted else "",
        }
        for k, v in item.items():
            if k not in _INJECTED_COLUMNS:
                rebuilt[k] = v
        new_items.append(rebuilt)
    data["items"] = new_items

    def render(f: Any) -> None:
        json.dump(data, f, ensure_ascii=False, indent=2)

    _atomic_write(data_path, render)
    log.info("data.json patched: %d items marked posted (of %d)", marked, len(new_items))
    return marked


def sync_estateboard_status(
    db_path: str | Path,
    eb_root: str | Path | None = None,
) -> dict[str, Any]:
    """Project jobs.db posting status into the EstateBoard master + dashboard.

    Returns a summary dict. Never raises for an absent EstateBoard repo.
    """
    eb_root_path = Path(eb_root) if eb_root else DEFAULT_EB_ROOT
    if not eb_root_path.exists():
        log.warning("EstateBoard repo not found, nothing to sync: %s", eb_root_path)
        return {"master_marked": 0, "data_marked": 0, "skipped": True}

    posted_meta = load_posted_meta(str(db_path))
    name_map = _group_name_map()
    master_path = eb_root_path / "output" / "received" / "master_properties.jsonl"
    data_path = eb_root_path / "docs" / "data.json"

    master_marked, display_info = patch_master(master_path, posted_meta, name_map)
    data_marked = patch_data_json(data_path, display_info)

    summary = {
        "master_marked": master_marked,
        "data_marked": data_marked,
        "posted_properties": len(posted_meta),
        "skipped": False,
    }
    log.info("EstateBoard sync done: %s", json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> None:
    setup_logging()
    ap = argparse.ArgumentParser(description="Bridge FB posting status into EstateBoard")
    ap.add_argument(
        "--eb-root",
        default=None,
        help=f"EstateBoard repo root (default: {DEFAULT_EB_ROOT})",
    )
    args = ap.parse_args()

    settings = Settings.load()
    summary = sync_estateboard_status(settings.db_path, eb_root=args.eb_root)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
