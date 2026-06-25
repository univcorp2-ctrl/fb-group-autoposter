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

DEFAULT_EB_ROOT = Path(
    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard"
)
POSTED_COLUMN = "投稿済"
POSTED_LABEL = "✅ 投稿済"
POSTED_TO_COLUMN = "投稿先"
POSTED_DATE_COLUMN = "投稿日"
# Row-data field (not a visible column) holding the direct post permalink so the
# dashboard can render 投稿先 as a hyperlink to the actual Facebook post.
POSTED_TO_URL_FIELD = "投稿先URL"


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
    """property_id -> {posted_at, groups, screenshot, permalinks} for VERIFIED rows.

    Only status='posted' counts — i.e. a post we actually found live on the group
    (permalink captured). 'uncertain' (submitted but unconfirmed) is deliberately
    EXCLUDED so the dashboard's 投稿済 never shows a post that may not be public.

    posted_at  = latest of all verified targets for that property.
    groups     = sorted set of group_ids the property was verified-posted to.
    screenshot = one screenshot path (the latest non-empty), or "".
    permalinks = sorted list of direct post URLs.
    """
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
            pid, {"posted_at": None, "groups": set(), "screenshot": "", "permalinks": set(), "to_url": ""}
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
            # Rows are ASC by posted_at, so the last permalink seen is the latest
            # -> the primary direct-post URL the dashboard links 投稿先 to.
            entry["to_url"] = str(r["permalink"])
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


def _prop(record: dict[str, Any], key: str) -> Any:
    """Read a `property.*` value from a flattened or nested master record."""
    if f"property.{key}" in record:
        return record[f"property.{key}"]
    prop = record.get("property")
    if isinstance(prop, dict):
        return prop.get(key)
    return None


def _display_fields(record: dict[str, Any]) -> dict[str, Any]:
    """Dashboard columns we can fill for a posted property that is missing from
    docs/data.json (e.g. priced outside the enrich price band). Lets a posted
    listing show on the web regardless of price; unknown columns stay blank."""
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
                "to_url": info.get("to_url", ""),  # direct post permalink for the 投稿先 hyperlink
                "fields": _display_fields(rec),
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
            # Row-data only (NOT a visible column): the dashboard's 投稿先 formatter
            # turns the group name into a hyperlink to this direct post URL.
            POSTED_TO_URL_FIELD: info.get("to_url", "") if is_posted else "",
        }
        for k, v in item.items():
            if k not in _INJECTED_COLUMNS and k != POSTED_TO_URL_FIELD:
                rebuilt[k] = v
        new_items.append(rebuilt)

    # Posted properties that are NOT in the dashboard dataset (e.g. priced
    # outside the enrich price band) would otherwise be invisible on the web.
    # Append a row for each from the master fields so EVERY post shows up.
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
        marked, appended, len(new_items),
    )
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
    pushed = _git_sync_eb(eb_root_path, master_path, data_path)

    summary = {
        "master_marked": master_marked,
        "data_marked": data_marked,
        "posted_properties": len(posted_meta),
        "pushed": pushed,
        "skipped": False,
    }
    log.info("EstateBoard sync done: %s", json.dumps(summary, ensure_ascii=False))
    return summary


def _git_sync_eb(eb_root: Path, master_path: Path, data_path: Path) -> bool:
    """Commit + push the patched EstateBoard files so the LIVE dashboard
    (Cloudflare Pages deploys from the repo) reflects posting status in near
    real time. Without this, the bridge only patched local files and the public
    site stayed stale. Best-effort: never raises, never blocks posting.

    The EstateBoard daily job may regenerate data.json without the marks; the
    next posting/verify run re-patches and re-pushes here, so it self-heals."""
    import subprocess

    rels = [str(data_path.relative_to(eb_root))]
    if master_path.exists():
        rels.append(str(master_path.relative_to(eb_root)))

    def _git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=str(eb_root), capture_output=True, text=True, timeout=60, check=False
        )

    try:
        # Only commit when something actually changed (avoid empty commits).
        status = _git("status", "--porcelain", *rels)
        if not status.stdout.strip():
            return False
        _git("add", *rels)
        commit = _git("commit", "-m", "data: reflect FB posting status on dashboard")
        if commit.returncode != 0 and "nothing to commit" in (commit.stdout + commit.stderr):
            return False
        push = _git("push")
        if push.returncode != 0:
            log.warning("EstateBoard push failed: %s", (push.stderr or push.stdout)[:200])
        # The live dashboard (estateboard.pages.dev) is deployed via
        # `wrangler pages deploy docs`, NOT git auto-deploy — so a git push alone
        # does NOT update the public site. Deploy here so posting status appears
        # live. Best-effort: needs local wrangler auth (present on the operator's
        # PC); skipped cleanly in CI/headless without it.
        deployed = _wrangler_deploy_eb(eb_root)
        log.info("EstateBoard committed + pushed; deployed=%s", deployed)
        return True
    except Exception as exc:  # noqa: BLE001 - sync must never crash the run
        log.warning("EstateBoard git sync skipped: %s: %s", type(exc).__name__, exc)
        return False


def _wrangler_deploy_eb(eb_root: Path) -> bool:
    """Deploy docs/ to Cloudflare Pages so the public dashboard reflects the
    patched data.json. Mirrors EstateBoard's daily_pipeline deploy step."""
    import subprocess

    try:
        cp = subprocess.run(
            ["npx", "wrangler", "pages", "deploy", "docs",
             "--project-name=estateboard", "--commit-dirty=true"],
            cwd=str(eb_root), capture_output=True, text=True, timeout=600, shell=True, check=False,
        )
        if cp.returncode != 0:
            log.warning("wrangler deploy skipped/failed: %s", (cp.stderr or cp.stdout)[-200:])
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - deploy is best-effort
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
