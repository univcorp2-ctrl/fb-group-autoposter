"""Guaranteed-completion posting loop.

Goal: never miss a day's post. While at least one group is still postable today
(within its active hours and not yet posted), keep retrying with backoff until
the post lands. On a session expiry, restore the profile from the latest backup
and retry. If the day's post still cannot be completed within this run's time
budget, exit cleanly — the next scheduled/logon trigger picks up where this left
off. The calendar-day guard makes every retry idempotent (never double-posts).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


def next_backoff(attempt: int, base: int = 60, cap: int = 900) -> int:
    """Exponential backoff seconds for a 0-based attempt index, capped."""
    if attempt < 0:
        attempt = 0
    return min(cap, base * (2**attempt))


def jst_hour() -> int:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Tokyo")).hour
    except Exception:
        from datetime import timedelta, timezone

        return datetime.now(timezone(timedelta(hours=9))).hour


def is_active_hour(active_hours: Any, now_hour: int) -> bool:
    start, end = int(active_hours[0]), int(active_hours[1])
    if start <= end:
        return start <= now_hour < end
    return now_hour >= start or now_hour < end


def all_groups_done_today(db: Any, groups: list[dict[str, Any]]) -> bool:
    if not groups:
        return True
    return all(db.posted_same_group_today(g["id"]) for g in groups)


def any_group_postable_now(db: Any, groups: list[dict[str, Any]], now_hour: int) -> bool:
    for g in groups:
        if is_active_hour(g.get("active_hours", [0, 24]), now_hour) and not db.posted_same_group_today(g["id"]):
            return True
    return False


async def ensure_posted_today(
    settings: Any,
    groups: list[dict[str, Any]],
    db: Any,
    *,
    run_once: Callable[[], Awaitable[Any]],
    restore_session: Callable[[], bool],
    sleeper: Callable[[int], Awaitable[None]] = asyncio.sleep,
    now_hour_fn: Callable[[], int] = jst_hour,
    time_fn: Callable[[], float] = time.monotonic,
    max_seconds: int = 3000,
    base_backoff: int = 60,
    backoff_cap: int = 900,
) -> dict[str, Any]:
    """Retry posting until today's post lands or this run is out of budget.

    `run_once` performs one full cycle (refresh inbox + post). `restore_session`
    recovers an expired login (returns True if a backup was restored). Both the
    sleeper and clock are injectable for tests.
    """
    from src.poster import SessionExpired

    start = time_fn()
    attempt = 0
    result: dict[str, Any] = {"attempts": 0, "posted": False, "reason": None, "restored": False}

    while True:
        if all_groups_done_today(db, groups):
            result.update(posted=True, reason="already_done")
            return result

        now_hour = now_hour_fn()
        if not any_group_postable_now(db, groups, now_hour):
            # Nothing postable right now (outside active hours). A later trigger
            # within active hours will complete it — do not burn the budget here.
            result["reason"] = "outside_active_hours"
            return result

        attempt += 1
        result["attempts"] = attempt
        try:
            await run_once()
        except SessionExpired:
            restored = restore_session()
            result["restored"] = result["restored"] or restored
            log.warning("session expired; profile restored=%s, will retry", restored)
        except Exception as exc:  # noqa: BLE001 - keep going no matter what
            log.warning("post attempt %d failed: %s: %s", attempt, type(exc).__name__, exc)

        if all_groups_done_today(db, groups):
            result.update(posted=True, reason="posted")
            return result

        if time_fn() - start >= max_seconds:
            # Out of time for this run; the next trigger continues the mission.
            result["reason"] = "budget_exhausted"
            return result

        await sleeper(next_backoff(attempt - 1, base_backoff, backoff_cap))
