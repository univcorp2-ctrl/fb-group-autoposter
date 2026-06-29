"""Upsert reply drafts into a Notion database (one row per thread, kept current).

Best-effort: if NOTION_TOKEN / NOTION_REPLIES_DATABASE_ID are unset, callers skip
this entirely. Idempotent by スレッドID — a re-run UPDATES the same row (refreshed
draft / latest message) instead of duplicating it.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Exact Notion property names (must match the database created separately).
PROP_TITLE = "相手"
PROP_THREAD_ID = "スレッドID"
PROP_LAST_MESSAGE = "最新メッセージ"
PROP_DRAFT = "返信下書き"
PROP_PRIORITY = "優先度"
PROP_STATUS = "ステータス"
PROP_URL = "スレッドURL"
PROP_CHECKED_AT = "取得日時"

DEFAULT_STATUS = "要返信"
_PRIORITY_LABEL = {"high": "高", "normal": "中", "none": "低"}


def _rich_text(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": (value or "")[:1900]}}]}


def build_properties(draft_row: dict, checked_at: str) -> dict:
    """Pure mapping from a draft row to a Notion `properties` payload."""
    name = str(draft_row.get("name", "") or "(名称不明)")
    priority = str(draft_row.get("priority", "normal"))
    return {
        PROP_TITLE: {"title": [{"text": {"content": name[:200]}}]},
        PROP_THREAD_ID: _rich_text(str(draft_row.get("thread_id", ""))),
        PROP_LAST_MESSAGE: _rich_text(str(draft_row.get("last_message", ""))),
        PROP_DRAFT: _rich_text(str(draft_row.get("draft", ""))),
        PROP_PRIORITY: {"select": {"name": _PRIORITY_LABEL.get(priority, "中")}},
        PROP_STATUS: {"select": {"name": DEFAULT_STATUS}},
        PROP_URL: {"url": draft_row.get("url") or None},
        PROP_CHECKED_AT: _rich_text(checked_at),
    }


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _find_existing_page(token: str, database_id: str, thread_id: str) -> str | None:
    url = f"{NOTION_BASE}/databases/{database_id}/query"
    payload = {
        "filter": {"property": PROP_THREAD_ID, "rich_text": {"equals": thread_id}},
        "page_size": 1,
    }
    resp = requests.post(url, headers=_headers(token), json=payload, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    return results[0]["id"] if results else None


def upsert_draft(token: str, database_id: str, draft_row: dict, checked_at: str) -> str:
    """UPSERT one draft row. Returns 'created' or 'updated'.

    On update we refresh the message/draft but DO NOT touch ステータス, so a human
    who already moved a row to 返信済 keeps that state.
    """
    properties = build_properties(draft_row, checked_at)
    page_id = _find_existing_page(token, database_id, str(draft_row.get("thread_id", "")))
    if page_id:
        update_props = {k: v for k, v in properties.items() if k != PROP_STATUS}
        resp = requests.patch(
            f"{NOTION_BASE}/pages/{page_id}",
            headers=_headers(token),
            json={"properties": update_props},
            timeout=30,
        )
        resp.raise_for_status()
        return "updated"
    resp = requests.post(
        f"{NOTION_BASE}/pages",
        headers=_headers(token),
        json={"parent": {"database_id": database_id}, "properties": properties},
        timeout=30,
    )
    resp.raise_for_status()
    return "created"
