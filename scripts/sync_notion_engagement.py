"""Record daily FB post engagement into a Notion database for time-series monitoring.

Reads data/engagement.json (written by scripts/monitor_engagement.py) and UPSERTS
one row per (日付, 物件ID, グループ) per day into a Notion database via the REST API.

Idempotency: re-running on the same day UPDATES the existing row (numbers refreshed)
instead of duplicating it, while each new day appends a fresh snapshot — building a
time series of engagement per post.

Best-effort by design (mirrors the Telegram integration): if NOTION_TOKEN or
NOTION_DATABASE_ID is unset, or the engagement snapshot is missing, this logs and
exits 0. It must never crash the posting pipeline.

Usage:
    python scripts/sync_notion_engagement.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402

log = logging.getLogger("sync_notion_engagement")

SNAPSHOT = ROOT / "data" / "engagement.json"
NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
JST = timezone(timedelta(hours=9))

# Exact Notion property names (the database is created separately; these must match).
PROP_TITLE = "物件×グループ"
PROP_DATE = "日付"
PROP_PROPERTY_ID = "物件ID"
PROP_GROUP = "グループ"
PROP_REACTIONS = "リアクション"
PROP_COMMENTS = "コメント"
PROP_SHARES = "シェア"
PROP_SCORE = "スコア"
PROP_PERMALINK = "permalink"
PROP_CHECKED_AT = "取得日時"


def _today_jst() -> str:
    """Today's date in JST as YYYY-MM-DD."""
    return datetime.now(JST).strftime("%Y-%m-%d")


def _rich_text(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value}}]}


def build_notion_properties(post: dict, date_jst: str, checked_at: str) -> dict:
    """Pure mapping from an engagement post dict to a Notion `properties` payload.

    No network calls — unit-testable. Shapes follow the Notion API for each type:
    title, date, rich_text, number, url.
    """
    property_id = str(post.get("property_id", ""))
    group = str(post.get("group", ""))
    return {
        PROP_TITLE: {"title": [{"text": {"content": f"{property_id} / {group}"}}]},
        PROP_DATE: {"date": {"start": date_jst}},
        PROP_PROPERTY_ID: _rich_text(property_id),
        PROP_GROUP: _rich_text(group),
        PROP_REACTIONS: {"number": int(post.get("reactions", 0) or 0)},
        PROP_COMMENTS: {"number": int(post.get("comments", 0) or 0)},
        PROP_SHARES: {"number": int(post.get("shares", 0) or 0)},
        PROP_SCORE: {"number": int(post.get("score", 0) or 0)},
        PROP_PERMALINK: {"url": post.get("permalink") or None},
        PROP_CHECKED_AT: _rich_text(checked_at),
    }


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def find_existing_page(
    settings: Settings, date_jst: str, property_id: str, group: str
) -> str | None:
    """Return the page id of an existing row for (日付, 物件ID, グループ), else None."""
    url = f"{NOTION_BASE}/databases/{settings.notion_database_id}/query"
    payload = {
        "filter": {
            "and": [
                {"property": PROP_DATE, "date": {"equals": date_jst}},
                {"property": PROP_PROPERTY_ID, "rich_text": {"equals": property_id}},
                {"property": PROP_GROUP, "rich_text": {"equals": group}},
            ]
        },
        "page_size": 1,
    }
    resp = requests.post(url, headers=_headers(settings.notion_token), json=payload, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


def create_page(settings: Settings, properties: dict) -> None:
    url = f"{NOTION_BASE}/pages"
    payload = {
        "parent": {"database_id": settings.notion_database_id},
        "properties": properties,
    }
    resp = requests.post(url, headers=_headers(settings.notion_token), json=payload, timeout=30)
    resp.raise_for_status()


def update_page(settings: Settings, page_id: str, properties: dict) -> None:
    url = f"{NOTION_BASE}/pages/{page_id}"
    resp = requests.patch(
        url, headers=_headers(settings.notion_token), json={"properties": properties}, timeout=30
    )
    resp.raise_for_status()


def upsert_post(settings: Settings, post: dict, date_jst: str, checked_at: str) -> str:
    """UPSERT one post. Returns 'created' or 'updated'."""
    property_id = str(post.get("property_id", ""))
    group = str(post.get("group", ""))
    properties = build_notion_properties(post, date_jst, checked_at)
    page_id = find_existing_page(settings, date_jst, property_id, group)
    if page_id:
        update_page(settings, page_id, properties)
        return "updated"
    create_page(settings, properties)
    return "created"


def _load_snapshot() -> dict | None:
    if not SNAPSHOT.exists():
        log.warning("engagement snapshot not found, nothing to sync: %s", SNAPSHOT)
        return None
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - never crash on a malformed snapshot
        log.warning("could not read engagement snapshot: %s: %s", type(exc).__name__, exc)
        return None


def main() -> None:
    setup_logging()
    settings = Settings.load()

    summary: dict[str, Any] = {"created": 0, "updated": 0, "skipped": False}

    if not settings.notion_token or not settings.notion_database_id:
        log.info("Notion not configured (NOTION_TOKEN / NOTION_DATABASE_ID empty); skipping")
        summary["skipped"] = True
        print(json.dumps(summary, ensure_ascii=False))
        return

    snapshot = _load_snapshot()
    if snapshot is None:
        summary["skipped"] = True
        print(json.dumps(summary, ensure_ascii=False))
        return

    date_jst = _today_jst()
    checked_at = str(snapshot.get("checked_at", ""))
    posts = snapshot.get("posts", []) or []

    for post in posts:
        try:
            outcome = upsert_post(settings, post, date_jst, checked_at)
            summary[outcome] += 1
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the rest
            log.warning(
                "notion upsert failed for %s / %s: %s: %s",
                post.get("property_id"), post.get("group"), type(exc).__name__, exc,
            )

    log.info(
        "notion engagement sync done: created=%d updated=%d (of %d posts)",
        summary["created"], summary["updated"], len(posts),
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
