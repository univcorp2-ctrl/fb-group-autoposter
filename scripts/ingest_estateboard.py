"""Ingest EstateBoard received properties into the autoposter inbox.

Filters to broker-OK (仲介回しOK = allowBrokerSharing TRUE) published properties,
maps them to the autoposter property schema, and writes one JSON file per
property into the inbox directory so the orchestrator can pick them up.

Usage:
    python scripts/ingest_estateboard.py --limit 10
    python scripts/ingest_estateboard.py --source <path/to/properties.json> --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.estateboard_adapter import select_postable
from src.queue_db import QueueDB

DEFAULT_SOURCE = Path(
    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json"
)


def load_items(source: Path) -> list[dict]:
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("items", [])
    if isinstance(data, list):
        return data
    raise ValueError(f"unexpected EstateBoard JSON shape: {type(data).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--clear-inbox", action="store_true", help="remove existing inbox JSON first")
    parser.add_argument("--dry", action="store_true", help="print selection without writing files")
    parser.add_argument(
        "--include-posted",
        action="store_true",
        help="do not skip properties already posted (default: skip them)",
    )
    args = parser.parse_args()

    settings = Settings.load()
    exclude: set[str] = set()
    if not args.include_posted:
        exclude = QueueDB(settings.db_path).posted_property_ids()

    items = load_items(args.source)
    properties = select_postable(items, limit=args.limit, exclude_ids=exclude)

    inbox = Path(settings.inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)

    if args.clear_inbox:
        for old in inbox.glob("eb-*.json"):
            old.unlink()

    print(f"source: {args.source}")
    print(f"total items: {len(items)}  selected (broker-OK, newest): {len(properties)}")
    written = 0
    for prop in properties:
        print(f"  - {prop['property_id']}  {prop['title']}  {prop['price']}  利回り{prop['yield_pct']}")
        if not args.dry:
            target = inbox / f"{prop['property_id']}.json"
            target.write_text(json.dumps(prop, ensure_ascii=False, indent=2), encoding="utf-8")
            written += 1
    if not args.dry:
        print(f"wrote {written} files to {inbox}")


if __name__ == "__main__":
    main()
