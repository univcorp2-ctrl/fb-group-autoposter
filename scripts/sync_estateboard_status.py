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
from src.estateboard_adapter import PROPERTY_TYPE_JA  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger("sync_estateboard_status")

DEFAULT_EB_ROOT = Path(r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard")
POSTED_COLUMN = "投稿済"
POSTED_LABEL = "✅ 投稿済"
POSTED_TO_COLUMN = "投稿先"
POSTED_DATE_COLUMN = "投稿日"
POSTED_TO_URL_FIELD = "投稿先URL"


def _group_name_map() -> dict[str, str]:
    try:
        from config import load_groups

        return {str(g["id"]): str(g.get("name") or g["id"]) for g in load_groups()}
    except Exception as exc:  # noqa: BLE001
        log.warning("could not load group names: %s: %s", type(exc).__name__, exc)
        return {}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_posted_meta(db_path: str) -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT j.property_id AS pid, t.group_id, t.posted_at, t.screenshot, t.permalink
            FROM job_targets t JOIN jobs j ON j.job_id = t.job_id
            WHERE t.status = 'posted'
            ORDER BY COALESCE(t.posted_at, '') ASC
            """
        ).fetchall()
    finally:
        conn.close()

    meta: dict[str, dict[str, Any]] = {}
    for r in rows:
        pid = r["pid"]
        entry = meta.setdefault(
            pid,
            {
                "posted_at": None,
                "groups": set(),
                "screenshot": "",
                "permalinks": set(),
                "to_url": "",
            },
        )
        if r["group_id"]:
            entry["groups"].add(str(r["group_id"]))
        posted_at = r["posted_at"]
        if posted_at and (entry["posted_at"] is None or posted_at > entry["posted_at"]):
            entry["posted_at"] = posted_at
        if r["screenshot"]:
            entry["screenshot"] = str(r["screenshot"])
        if r["permalink"]:
            entry["permalinks"].add(str(r["permalink"]))
            entry["to_url"] = str(r["permalink"])
    return meta


def _join_key(record: dict[str, Any]) -> str:
    return "eb-" + str(record.get("propertyId") or record.get("id"))


def _atomic_write(path: Path, render: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        render(f)
    os.replace(tmp, path)


def _group_names(group_ids: Any, name_map: dict[str, str]) -> list[str]:
    return [name_map.get(str(gid), str(gid)) for gid in sorted(group_ids)]


def _prop(record: dict[str, Any], key: str) -> Any:
    if f"property.{key}" in record:
        return record[f"property.{key}"]
    prop = record.get("property")
    if isinstance(prop, dict):
        return prop.get(key)
    return None


def _display_fields(record: dict[str, Any]) -> dict[str, Any]:
    try:
        price = float(_prop(record, "price"))
    except (TypeError, ValueError):
        price = 0.0
    city = str(_prop(record, "cityLabel") or "")
    rest = str(_prop(record, "restAddress") or "")
    return {
        "ID": str(record.get("id") or ""),
        "物件名": str(_prop(record, "label") or record.get("label") or ""),
        "種別": PROPERTY_TYPE_JA.get(str(_prop(record, "propertyType") or ""), ""),
        "都道府県": str(_prop(record, "prefectureLabel") or ""),
        "市区町村": city,
        "住所": (city + rest) if (city or rest) else "",
        "最寄駅": str(_prop(record, "nearestStation1") or ""),
        "価格(万円)": round(price / 10000) if price else "",
        "詳細URL": str(record.get("detail_url") or ""),
    }


def patch_master(
    master_path: Path,
    posted_meta: dict[str, dict[str, Any]],
    name_map: dict[str, str],
) -> tuple[int, dict[str, dict[str, str]]]:
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
            rec["_posted_groups"] = names
            rec["_posted_screenshot"] = info["screenshot"] or ""
            display_info[str(rec.get("id"))] = {
                "groups": ", ".join(names),
                "date": str(posted_at)[:10],
                "to_url": info.get("to_url", ""),
                "fields": _display_fields(rec),
            }
            marked += 1
        elif rec.get("_posted_to_fb"):
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
    if not data_path.exists():
        log.warning("EstateBoard data.json not found, skipping dashboard patch: %s", data_path)
        return 0

    data = json.loads(data_path.read_text(encoding="utf-8"))
    columns = [c for c in (data.get("columns") or []) if c not in _INJECTED_COLUMNS]
    full_columns = [POSTED_COLUMN, POSTED_TO_COLUMN, POSTED_DATE_COLUMN] + list(columns)
    data["columns"] = full_columns

    marked = 0
    seen_ids: set[str] = set()
    new_items: list[dict[str, Any]] = []
    for item in data.get("items", []):
        item_id = str(item.get("ID"))
        info = display_info.get(item_id)
        is_posted = info is not None
        if is_posted:
            marked += 1
            seen_ids.add(item_id)
        rebuilt = {
            POSTED_COLUMN: POSTED_LABEL if is_posted else "",
            POSTED_TO_COLUMN: info["groups"] if is_posted else "",
            POSTED_DATE_COLUMN: info["date"] if is_posted else "",
            POSTED_TO_URL_FIELD: info.get("to_url", "") if is_posted else "",
        }
        for k, v in item.items():
            if k not in _INJECTED_COLUMNS and k != POSTED_TO_URL_FIELD:
                rebuilt[k] = v
        new_items.append(rebuilt)

    appended = 0
    for disp_id, info in display_info.items():
        if disp_id in seen_ids:
            continue
        row = {c: "" for c in full_columns}
        row[POSTED_COLUMN] = POSTED_LABEL
        row[POSTED_TO_COLUMN] = info["groups"]
        row[POSTED_DATE_COLUMN] = info["date"]
        row[POSTED_TO_URL_FIELD] = info.get("to_url", "")
        for k, v in (info.get("fields") or {}).items():
            if k in row:
                row[k] = v
        new_items.append(row)
        appended += 1
        marked += 1

    data["items"] = new_items
    data["count"] = len(new_items)

    def render(f: Any) -> None:
        json.dump(data, f, ensure_ascii=False, indent=2)

    _atomic_write(data_path, render)
    log.info(
        "data.json patched: %d marked posted (%d appended that were missing) of %d items",
        marked,
        appended,
        len(new_items),
    )
    return marked


def sync_estateboard_status(
    db_path: str | Path,
    eb_root: str | Path | None = None,
) -> dict[str, Any]:
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
    published = _git_sync_eb(eb_root_path, master_path, data_path)

    summary = {
        "master_marked": master_marked,
        "data_marked": data_marked,
        "posted_properties": len(posted_meta),
        "pushed": published,
        "published": published,
        "skipped": False,
    }
    log.info("EstateBoard sync done: %s", json.dumps(summary, ensure_ascii=False))
    return summary


def _git_sync_eb(eb_root: Path, master_path: Path, data_path: Path) -> bool:
    """Commit, reconcile, push, and deploy the patched EstateBoard files.

    True means both the git push (when needed) and the Cloudflare Pages deploy
    succeeded. A failed push/deploy must never be reported as success.
    """
    import subprocess

    rels = [str(data_path.relative_to(eb_root))]
    if master_path.exists():
        rels.append(str(master_path.relative_to(eb_root)))

    def _git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=str(eb_root),
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )

    try:
        status = _git("status", "--porcelain", *rels)
        if status.returncode != 0:
            log.warning("EstateBoard git status failed: %s", (status.stderr or status.stdout)[-500:])
            return False

        if not status.stdout.strip():
            deployed = _wrangler_deploy_eb(eb_root)
            log.info("EstateBoard git clean; deploy retry result=%s", deployed)
            return deployed

        _git("add", *rels)
        commit = _git("commit", "-m", "data: reflect FB posting status on dashboard")
        commit_text = commit.stdout + commit.stderr
        if commit.returncode != 0 and "nothing to commit" not in commit_text:
            log.warning("EstateBoard commit failed: %s", commit_text[-500:])
            return False

        push = _git("push")
        if push.returncode != 0:
            first_error = (push.stderr or push.stdout)[-500:]
            log.warning("EstateBoard push failed; attempting safe rebase recovery: %s", first_error)
            fetch = _git("fetch", "origin", "main")
            if fetch.returncode != 0:
                log.warning("EstateBoard fetch failed: %s", (fetch.stderr or fetch.stdout)[-500:])
                return False
            rebase = _git("rebase", "origin/main")
            if rebase.returncode != 0:
                log.warning("EstateBoard rebase failed: %s", (rebase.stderr or rebase.stdout)[-500:])
                _git("rebase", "--abort")
                return False
            push = _git("push")
            if push.returncode != 0:
                log.warning("EstateBoard push retry failed: %s", (push.stderr or push.stdout)[-500:])
                return False

        deployed = _wrangler_deploy_eb(eb_root)
        if not deployed:
            log.warning("EstateBoard push succeeded but Pages deploy failed")
            return False
        log.info("EstateBoard committed + pushed + deployed successfully")
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("EstateBoard git sync skipped: %s: %s", type(exc).__name__, exc)
        return False


def _wrangler_deploy_eb(eb_root: Path) -> bool:
    import subprocess

    try:
        cp = subprocess.run(
            [
                "npx",
                "wrangler",
                "pages",
                "deploy",
                "docs",
                "--project-name=estateboard",
                "--commit-dirty=true",
            ],
            cwd=str(eb_root),
            capture_output=True,
            text=True,
            timeout=600,
            shell=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if cp.returncode != 0:
            log.warning("wrangler deploy skipped/failed: %s", (cp.stderr or cp.stdout)[-500:])
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("wrangler deploy skipped: %s: %s", type(exc).__name__, exc)
        return False


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
