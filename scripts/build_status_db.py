"""Build the posting-status database as an Excel workbook (+ CSV).

Leftmost column = 投稿状況, color-coded so posted/unposted is obvious at a glance.
Every broker-OK (中間マージンの足OK) postable property appears exactly once, joined
with jobs.db so 投稿済 rows show when/where (screenshot path) the post was saved.

Usage:
    python scripts/build_status_db.py [path/to/properties.json]

Regenerate any time; it is idempotent and reflects the current jobs.db state.
Also runs automatically after each posting run and at monitor time.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from src.logging_setup import setup_logging  # noqa: E402
from src.status_report import build_status_files  # noqa: E402

log = logging.getLogger("build_status_db")

DEFAULT_SOURCE = Path(
    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json"
)
OUT_DIR = ROOT / "output"


def main() -> None:
    setup_logging()
    settings = Settings.load()
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    result = build_status_files(source, str(settings.db_path), OUT_DIR, root=ROOT)
    log.info("status DB built: %s", json.dumps(result["counts"], ensure_ascii=False))
    log.info("excel: %s", result["excel"])

    # Keep EstateBoard (master store + live dashboard) in sync on the scheduled
    # StatusDB rebuild too. Best-effort: never crash the status build.
    try:
        from scripts.sync_estateboard_status import sync_estateboard_status

        eb = sync_estateboard_status(settings.db_path)
        log.info("EstateBoard status synced: %s", json.dumps(eb, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - EstateBoard sync is best-effort
        log.warning("EstateBoard status sync skipped: %s: %s", type(exc).__name__, exc)

    print(json.dumps({"counts": result["counts"], "excel": result["excel"], "csv": result["csv"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
