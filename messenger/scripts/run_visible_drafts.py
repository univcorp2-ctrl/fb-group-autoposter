"""Place unsent drafts in the central authenticated visible Chrome session."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings  # noqa: E402
from scripts.run_once import _scan  # noqa: E402


async def main_async() -> dict:
    settings = replace(Settings.load(), browser_display_mode="visible")
    scan = await _scan(settings, use_telegram=True)
    result = {
        "scan": scan,
        "browser_profile_directory": settings.chrome_profile_directory,
        "display_mode": "visible",
        "sent": False,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    asyncio.run(main_async())

