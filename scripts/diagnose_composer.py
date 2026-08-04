"""One-group, read-only Facebook composer diagnostic.

This is deliberately separate from the posting runner.  It navigates only to a
caller-supplied Facebook *group feed*, reads the DOM/accessibility tree, and
prints a sanitized JSON result.  It never opens a composer, types, uploads, or
submits a post.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

# ``python scripts/diagnose_composer.py`` sets sys.path to scripts/, not the
# repository root.  Keep the command explicitly runnable from the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Settings
from src.browser_runtime import BrowserContract, build_launch_kwargs
from src.composer_diagnostic import diagnose_composer


def _joined_group_url(value: str) -> str:
    parsed = urlparse(value)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"facebook.com", "www.facebook.com", "m.facebook.com"}
        or len(parts) < 2
        or parts[0] != "groups"
        or "messenger" in parsed.path.casefold()
    ):
        raise argparse.ArgumentTypeError("--group-url must be one configured Facebook group feed URL")
    return value


async def _run(group_url: str, *, screenshot: bool) -> dict[str, object]:
    from playwright.async_api import async_playwright

    settings = Settings.load()
    contract = BrowserContract.from_settings(settings)
    kwargs = build_launch_kwargs(contract)
    kwargs["timeout"] = settings.page_hard_timeout * 1000
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(**kwargs)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(group_url, wait_until="domcontentloaded", timeout=kwargs["timeout"])
            result = await diagnose_composer(page)
            # A diagnostic image is never created on auth/challenge pages.  The
            # current minimal CLI reports the opt-in state only; operational image
            # capture must use a separately reviewed redaction implementation.
            result["screenshot"] = "redaction_required" if screenshot and result["reason"] not in {"login_required", "checkpoint_required"} else "not_captured"
            return result
        finally:
            await context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Facebook group composer diagnostic")
    parser.add_argument("--group-url", required=True, type=_joined_group_url)
    parser.add_argument("--screenshot", action="store_true", help="request only a separately redacted diagnostic image")
    args = parser.parse_args()
    result = asyncio.run(_run(args.group_url, screenshot=args.screenshot))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["reason"] == "composer_ready" else 20


if __name__ == "__main__":
    raise SystemExit(main())
