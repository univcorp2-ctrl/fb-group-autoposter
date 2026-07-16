"""Drive-aware compatibility entry point for the existing daily pipeline.

This keeps the proven queue/post/verify implementation unchanged and decorates
EstateBoard-selected properties with images downloaded under the user's Google
Drive archive before jobs are created.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.estateboard_adapter as adapter
import src.orchestrator as orchestrator
from src.drive_assets import attach_drive_images

_ORIGINAL_SELECT = adapter.select_postable
DEFAULT_DRIVE_ROOT = Path(r"G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard")


def _drive_aware_select(
    items: list[dict[str, Any]],
    *,
    limit: int | None = None,
    exclude_ids: set[str] | None = None,
    order: str = "newest",
) -> list[dict[str, Any]]:
    properties = _ORIGINAL_SELECT(items, limit=limit, exclude_ids=exclude_ids, order=order)
    drive_root = Path(os.getenv("ESTATEBOARD_DRIVE_ROOT", str(DEFAULT_DRIVE_ROOT)))
    return attach_drive_images(properties, items, drive_root)


def main() -> None:
    # run_cycle_grouped imported select_postable into the orchestrator module, so
    # replace that module-level reference before invoking the established entrypoint.
    orchestrator.select_postable = _drive_aware_select
    from scripts.run_daily import main as existing_main

    existing_main()


if __name__ == "__main__":
    main()
