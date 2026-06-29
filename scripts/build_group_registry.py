"""Build the group posting registry — the record of WHERE we post and the status.

Single place that answers "which groups do we post to, are we a member, and how
many posts has each received?". Merges three sources:
  - groups.yaml            : configured posting targets (enabled/disabled + order)
  - data/joined_groups.json: membership truth + real-estate-friendly candidates
  - data/jobs.db           : per-group posting stats (verified posts, last posted)

Outputs:
  - data/group_registry.json  (machine-readable, stable added_at preserved)
  - data/group_registry.csv   (at-a-glance)

Status per group:
  active     = in groups.yaml, enabled (we post here)
  registered = in groups.yaml, disabled (held: membership unconfirmed, etc.)
  candidate  = joined + property-friendly but NOT yet in groups.yaml (ramp pool)

Run after each posting cycle so new groups + fresh post counts are recorded.

Usage:
    python scripts/build_group_registry.py
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402

REGISTRY_JSON = ROOT / "data" / "group_registry.json"
REGISTRY_CSV = ROOT / "data" / "group_registry.csv"
JOINED_JSON = ROOT / "data" / "joined_groups.json"
GROUPS_YAML = ROOT / "groups.yaml"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_yaml_groups() -> list[dict]:
    data = yaml.safe_load(GROUPS_YAML.read_text(encoding="utf-8")) or {}
    return [g for g in data.get("groups", []) if isinstance(g, dict)]


def _load_joined() -> dict[str, dict]:
    if not JOINED_JSON.exists():
        return {}
    try:
        data = json.loads(JOINED_JSON.read_text(encoding="utf-8"))
        return {str(g["group_id"]): g for g in data.get("groups", [])}
    except Exception:  # noqa: BLE001 - tolerate a missing/old file
        return {}


def _posting_stats(db_path: Path) -> dict[str, dict[str, Any]]:
    """group_id -> {posts_verified, posts_attempted, last_posted_at}."""
    if not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT group_id,
                   SUM(CASE WHEN status='posted' THEN 1 ELSE 0 END) AS verified,
                   COUNT(*) AS attempted,
                   MAX(CASE WHEN status='posted' THEN posted_at END) AS last_posted
            FROM job_targets GROUP BY group_id
            """
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {
        str(r["group_id"]): {
            "posts_verified": int(r["verified"] or 0),
            "posts_attempted": int(r["attempted"] or 0),
            "last_posted_at": r["last_posted"] or "",
        }
        for r in rows
    }


def _load_existing() -> dict[str, dict]:
    if REGISTRY_JSON.exists():
        try:
            data = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
            return {str(g["group_id"]): g for g in data.get("groups", [])}
        except Exception:  # noqa: BLE001
            return {}
    return {}


def build_registry() -> dict[str, Any]:
    settings = Settings.load()
    yaml_groups = _load_yaml_groups()
    joined = _load_joined()
    stats = _posting_stats(settings.db_path)
    existing = _load_existing()
    now = _now()

    records: dict[str, dict] = {}

    # 1) Configured posting targets (groups.yaml).
    for g in yaml_groups:
        gid = str(g["id"])
        enabled = bool(g.get("enabled", True))
        st = stats.get(gid, {})
        prev = existing.get(gid, {})
        records[gid] = {
            "group_id": gid,
            "name": g.get("name", ""),
            "url": g.get("post_url", f"https://www.facebook.com/groups/{gid}"),
            "status": "active" if enabled else "registered",
            "enabled": enabled,
            "selection_order": g.get("selection_order", "newest"),
            "member": joined.get(gid, {}).get("group_id") is not None,
            "category": joined.get(gid, {}).get("category", ""),
            "posts_verified": st.get("posts_verified", 0),
            "posts_attempted": st.get("posts_attempted", 0),
            "last_posted_at": st.get("last_posted_at", ""),
            "added_at": prev.get("added_at", now),
        }

    # 2) Joined + property-friendly groups not yet configured = ramp candidates.
    for gid, jg in joined.items():
        if gid in records or not jg.get("property_friendly"):
            continue
        prev = existing.get(gid, {})
        records[gid] = {
            "group_id": gid,
            "name": jg.get("name", ""),
            "url": jg.get("url", f"https://www.facebook.com/groups/{gid}"),
            "status": "candidate",
            "enabled": False,
            "selection_order": "",
            "member": True,
            "category": jg.get("category", ""),
            "posts_verified": stats.get(gid, {}).get("posts_verified", 0),
            "posts_attempted": stats.get(gid, {}).get("posts_attempted", 0),
            "last_posted_at": stats.get(gid, {}).get("last_posted_at", ""),
            "added_at": prev.get("added_at", now),
        }

    rows = sorted(
        records.values(),
        key=lambda r: ({"active": 0, "registered": 1, "candidate": 2}.get(r["status"], 3), -r["posts_verified"]),
    )
    REGISTRY_JSON.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_JSON.write_text(
        json.dumps({"updated_at": now, "groups": rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with REGISTRY_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["状態", "グループ名", "ID", "カテゴリ", "順序", "所属", "投稿確認", "試行", "最終投稿", "URL"])
        for r in rows:
            w.writerow([
                r["status"], r["name"], r["group_id"], r["category"], r["selection_order"],
                "✓" if r["member"] else "", r["posts_verified"], r["posts_attempted"],
                str(r["last_posted_at"])[:10], r["url"],
            ])

    summary = {
        "total": len(rows),
        "active": sum(1 for r in rows if r["status"] == "active"),
        "registered": sum(1 for r in rows if r["status"] == "registered"),
        "candidate": sum(1 for r in rows if r["status"] == "candidate"),
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    result = build_registry()
    print(json.dumps(result["summary"], ensure_ascii=False))
    print(f"written: {REGISTRY_JSON}  and  {REGISTRY_CSV}")


if __name__ == "__main__":
    main()
