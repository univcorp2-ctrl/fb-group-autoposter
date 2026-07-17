"""Build a browser-safe runtime snapshot from the local SQLite queue."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SECRET_PATTERN = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|authorization|cookie|password|secret)\s*[:=]\s*\S+"
)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _safe_error(value: str | None) -> str | None:
    if not value:
        return None
    redacted = _SECRET_PATTERN.sub(r"\1=[REDACTED]", str(value))
    return redacted[:500]


def build_runtime_status(db_path: str | Path, *, limit: int = 50) -> dict[str, Any]:
    now = datetime.now(UTC)
    path = Path(db_path)
    base: dict[str, Any] = {
        "generated_at": now.isoformat(),
        "health": "not_initialized",
        "message": "投稿履歴DBがまだ作成されていません。",
        "counts": {},
        "last_post_at": None,
        "heartbeat": {},
        "recent": [],
    }
    if not path.exists():
        return base
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT j.property_id, t.group_id, t.status, t.attempts, t.last_error,
                   t.posted_at, t.permalink, j.updated_at
            FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
            ORDER BY COALESCE(t.posted_at, j.updated_at) DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        heartbeat_rows = conn.execute(
            "SELECT component, last_seen FROM heartbeat ORDER BY component"
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        return {**base, "health": "error", "message": f"SQLite読込エラー: {exc}"}

    recent: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["last_error"] = _safe_error(item.get("last_error"))
        recent.append(item)

    counts = Counter(str(row["status"]) for row in rows)
    published_times = [
        _parse(row["posted_at"] or row["updated_at"])
        for row in rows
        if row["status"] in {"posted", "uncertain"}
    ]
    published_times = [value for value in published_times if value]
    last_post = max(published_times) if published_times else None
    age_hours = (now - last_post).total_seconds() / 3600 if last_post else None
    if last_post is None:
        health, message = "stalled", "確認済み投稿がありません。"
    elif age_hours is not None and age_hours > 36:
        health, message = "stalled", f"最終投稿から{age_hours:.1f}時間経過しています。"
    elif counts.get("failed", 0) > counts.get("posted", 0) + counts.get("uncertain", 0):
        health, message = "warning", "直近履歴で失敗が成功を上回っています。"
    else:
        health, message = "healthy", "投稿ランタイムは正常範囲です。"
    return {
        **base,
        "health": health,
        "message": message,
        "counts": dict(counts),
        "last_post_at": last_post.isoformat() if last_post else None,
        "heartbeat": {row["component"]: row["last_seen"] for row in heartbeat_rows},
        "recent": recent,
    }


def write_runtime_status(db_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    status = build_runtime_status(db_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status
