"""Daily posting entry point: ingest one fresh broker-OK property, then post.

Designed to be scheduled (e.g. twice a day). Each run:
  1. selects the newest broker-OK (仲介回しOK) EstateBoard property that has
     not been posted yet, and writes it to the inbox,
  2. runs the posting pipeline, which posts only when within the group's
     active hours and the same-group interval guard allows it.

Safe by design: MAX_POSTS_PER_DAY and MIN_SAME_GROUP_HOURS cap the cadence,
so running this more often than needed never over-posts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.estateboard_adapter import select_postable
from src.logging_setup import setup_logging
from src.orchestrator import run_cycle
from src.queue_db import QueueDB

log = logging.getLogger("run_daily")

DEFAULT_SOURCE = Path(
    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json"
)


def _load_items(source: Path) -> list[dict]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("items", [])
    return data if isinstance(data, list) else []


def refresh_inbox(settings: Settings, *, source: Path, count: int) -> int:
    """Replace inbox with `count` fresh (unposted) broker-OK properties."""
    inbox = Path(settings.inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    for old in inbox.glob("eb-*.json"):
        old.unlink()

    posted = QueueDB(settings.db_path).posted_property_ids()
    try:
        items = _load_items(source)
    except FileNotFoundError:
        log.warning("EstateBoard source not found: %s", source)
        return 0
    properties = select_postable(items, limit=count, exclude_ids=posted)
    for prop in properties:
        (inbox / f"{prop['property_id']}.json").write_text(
            json.dumps(prop, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    log.info("inbox refreshed: %d fresh properties (excluded %d posted)", len(properties), len(posted))
    return len(properties)


def main() -> None:
    setup_logging()
    settings = Settings.load()
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    fresh = refresh_inbox(settings, source=source, count=1)
    if fresh == 0:
        log.warning("no fresh properties to post; nothing queued")
    summary = asyncio.run(run_cycle(settings))
    log.info("run_daily summary: %s", json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
