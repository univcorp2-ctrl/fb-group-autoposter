"""Drive-aware production entrypoint for the existing daily pipeline."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import src.estateboard_adapter as adapter
import src.orchestrator as orchestrator
from src.drive_assets import attach_drive_images
from src.multi_source import build_posting_source

_ORIGINAL_SELECT = adapter.select_postable
DEFAULT_DRIVE_ROOT = Path(r"G:\マイドライブ\0.物件資料_お客様紹介用\Estateboard")

DEFAULT_GMAIL_SOURCE = Path("G:/\u30de\u30a4\u30c9\u30e9\u30a4\u30d6/AI_Agents/github/repos/Bukken-DB/data/fb_postable.json")
COMBINED_SOURCE = ROOT / "data" / "posting_source.json"


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
    orchestrator.select_postable = _drive_aware_select
    if os.getenv("POST_TEXT_PROVIDER", "").strip().casefold() == "codex":
        from src.codex_provider import generate_variants_with_codex

        orchestrator.generate_variants = generate_variants_with_codex
    from scripts.run_daily import main as existing_main

    original_argv = sys.argv[:]
    source = os.getenv("ESTATEBOARD_SOURCE", "").strip()
    if len(sys.argv) == 1:
        estateboard_source = Path(source) if source else Path(
            "G:/\u30de\u30a4\u30c9\u30e9\u30a4\u30d6/AI_Agents/github/repos/EstateBoard/output/received/properties.json"
        )
        gmail_source = Path(os.getenv("GMAIL_POSTABLE_SOURCE", str(DEFAULT_GMAIL_SOURCE)))
        built = build_posting_source(estateboard_source, gmail_source, COMBINED_SOURCE)
        print(f"posting source: EB={built['estateboard']} Gmail={built['gmail']} combined={built['combined']}")
        sys.argv.append(str(COMBINED_SOURCE))
    try:
        existing_main()
    finally:
        sys.argv[:] = original_argv
        try:
            from scripts.publish_runtime_status import publish_runtime_status

            publish_runtime_status(push=os.getenv("PUBLISH_STATUS_GIT", "0") == "1")
        except Exception as exc:  # noqa: BLE001 - status publishing must not mask posting result
            print(f"runtime status publish skipped: {type(exc).__name__}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
