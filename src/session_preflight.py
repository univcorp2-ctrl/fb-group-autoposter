"""Read-only Facebook session preflight used to clear recoverable safety circuits.

The preflight never posts, types into a composer, joins a group, or changes
Facebook state. It only opens the production persistent profile, loads the
Facebook home page, checks for login/challenge markers, and clears circuits
whose policy explicitly requires a successful preflight.
"""

from __future__ import annotations

from typing import Any

from src.browser_runtime import BrowserContract, build_launch_kwargs
from src.circuits import CircuitManager
from src.queue_db import QueueDB
from src.session import classify_challenge, is_logged_in


async def run_session_preflight(settings: Any, db: QueueDB | None = None) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    database = db or QueueDB(settings.db_path)
    circuits = CircuitManager(database)
    environment = str(getattr(settings, "runtime_environment", "default") or "default")

    async with async_playwright() as playwright:
        contract = BrowserContract.from_settings(settings)
        launch_kwargs = build_launch_kwargs(contract)
        launch_kwargs["timeout"] = int(getattr(settings, "page_hard_timeout", 60)) * 1000
        context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                "https://www.facebook.com/",
                wait_until="domcontentloaded",
                timeout=int(getattr(settings, "page_hard_timeout", 60)) * 1000,
            )
            await page.wait_for_timeout(2500)

            challenge = await classify_challenge(page)
            logged_in = await is_logged_in(page)
            if challenge:
                return {
                    "ok": False,
                    "reason": "challenge",
                    "challenge": challenge,
                    "cleared": 0,
                }
            if not logged_in:
                return {
                    "ok": False,
                    "reason": "not_logged_in",
                    "challenge": None,
                    "cleared": 0,
                }

            cleared = circuits.record_successful_preflight(
                environment,
                actor="preflight",
            )
            return {
                "ok": True,
                "reason": "healthy",
                "challenge": None,
                "cleared": cleared,
            }
        finally:
            await context.close()
