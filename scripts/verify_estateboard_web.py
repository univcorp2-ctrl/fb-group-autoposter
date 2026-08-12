"""Verify today's confirmed Facebook permalinks are visible on EstateBoard."""

from __future__ import annotations

import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from config import Settings
from scripts.sync_estateboard_status import sync_estateboard_status
from src.queue_db import QueueDB

PUBLIC_DATA_URL = "https://estateboard.pages.dev/data.json"
STATUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "logs"
    / "estateboard_web_sync_status.json"
)


def _today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


def _today_permalinks(db: QueueDB) -> list[str]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT t.permalink
            FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
            WHERE t.status='posted'
              AND t.permalink IS NOT NULL AND t.permalink!=''
              AND date(datetime(COALESCE(t.posted_at,j.updated_at), '+9 hours'))=date('now','+9 hours')
            ORDER BY t.permalink
            """
        ).fetchall()
    return [str(row["permalink"]) for row in rows]


def _fetch_public() -> str:
    req = urllib.request.Request(
        PUBLIC_DATA_URL, headers={"User-Agent": "estateboard-web-slo/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def missing_permalinks(public_text: str, permalinks: list[str]) -> list[str]:
    return [permalink for permalink in permalinks if permalink not in public_text]


def _write_status(payload: dict[str, Any]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _alert(db: QueueDB, text: str, suffix: str) -> None:
    db.enqueue_outbox_event(
        event_key=f"telegram:web-slo:{_today()}:{suffix}",
        event_type="environment",
        origin_run_id=f"estateboard-web-slo-{_today()}",
        subject_id="estateboard",
        payload={"text": text},
    )


def main() -> int:
    settings = Settings.load()
    db = QueueDB(settings.db_path)
    permalinks = _today_permalinks(db)
    status: dict[str, Any] = {
        "date": _today(),
        "checked_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "confirmed_posts": len(permalinks),
    }

    if not permalinks:
        status.update(
            {"ok": False, "reason": "no permalink-confirmed Facebook post today"}
        )
        _write_status(status)
        _alert(
            db,
            "⚠️ 本日のFacebook確認済み投稿が0件です。安全回路/セッション/PC稼働状況を確認してください。",
            "no-post",
        )
        print(json.dumps(status, ensure_ascii=False))
        return 1

    status["sync"] = sync_estateboard_status(settings.db_path)
    last_error = ""
    for attempt in range(1, 5):
        try:
            missing = missing_permalinks(_fetch_public(), permalinks)
            if not missing:
                status.update({"ok": True, "attempt": attempt, "missing": []})
                _write_status(status)
                print(json.dumps(status, ensure_ascii=False))
                return 0
            status["missing"] = missing
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < 4:
            time.sleep(15)

    status.update(
        {
            "ok": False,
            "error": last_error,
            "missing": status.get("missing", permalinks),
        }
    )
    _write_status(status)
    _alert(
        db,
        "⚠️ Facebook投稿は確認済みですがEstateBoard公開Webへの反映を確認できませんでした。Bridge/Pages deployを確認してください。",
        "not-reflected",
    )
    print(json.dumps(status, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
