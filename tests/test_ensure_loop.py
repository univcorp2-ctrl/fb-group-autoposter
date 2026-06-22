"""Tests for the guaranteed-completion posting loop (src/ensure.py)."""
import asyncio

import pytest

from src.ensure import (
    all_groups_done_today,
    any_group_postable_now,
    ensure_posted_today,
    is_active_hour,
    next_backoff,
)
from src.poster import SessionExpired

GROUPS = [{"id": "g1", "active_hours": [0, 24]}]


class FakeDB:
    def __init__(self):
        self.posted: set[str] = set()

    def posted_same_group_today(self, gid: str) -> bool:
        return gid in self.posted


async def _noop_sleep(_seconds):
    return None


def _run(db, **kw):
    kw.setdefault("sleeper", _noop_sleep)
    kw.setdefault("now_hour_fn", lambda: 12)
    kw.setdefault("time_fn", lambda: 0.0)
    kw.setdefault("restore_session", lambda: False)
    return asyncio.run(ensure_posted_today(None, kw.pop("groups", GROUPS), db, **kw))


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def test_next_backoff_grows_and_caps():
    assert next_backoff(0, base=60) == 60
    assert next_backoff(1, base=60) == 120
    assert next_backoff(2, base=60) == 240
    assert next_backoff(99, base=60, cap=900) == 900
    assert next_backoff(-5, base=60) == 60


def test_is_active_hour_normal_and_wraparound():
    assert is_active_hour([7, 23], 12) is True
    assert is_active_hour([7, 23], 3) is False
    assert is_active_hour([7, 23], 23) is False
    # overnight window 22:00-06:00
    assert is_active_hour([22, 6], 23) is True
    assert is_active_hour([22, 6], 3) is True
    assert is_active_hour([22, 6], 12) is False


def test_group_state_helpers():
    db = FakeDB()
    assert all_groups_done_today(db, []) is True
    assert all_groups_done_today(db, GROUPS) is False
    assert any_group_postable_now(db, GROUPS, 12) is True
    db.posted.add("g1")
    assert all_groups_done_today(db, GROUPS) is True
    assert any_group_postable_now(db, GROUPS, 12) is False


# --------------------------------------------------------------------------- #
# the loop
# --------------------------------------------------------------------------- #
def test_already_done_does_not_post():
    db = FakeDB()
    db.posted.add("g1")
    called = {"n": 0}

    async def run_once():
        called["n"] += 1

    res = _run(db, run_once=run_once)
    assert res["posted"] is True
    assert res["reason"] == "already_done"
    assert called["n"] == 0


def test_outside_active_hours_returns_without_posting():
    db = FakeDB()
    called = {"n": 0}

    async def run_once():
        called["n"] += 1
        db.posted.add("g1")

    res = _run(db, run_once=run_once, groups=[{"id": "g1", "active_hours": [7, 23]}], now_hour_fn=lambda: 3)
    assert res["posted"] is False
    assert res["reason"] == "outside_active_hours"
    assert called["n"] == 0


def test_retries_until_posted():
    db = FakeDB()
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        if calls["n"] >= 3:  # succeeds on the third attempt
            db.posted.add("g1")

    res = _run(db, run_once=run_once)
    assert res["posted"] is True
    assert res["attempts"] == 3
    assert calls["n"] == 3


def test_session_expiry_triggers_restore_then_succeeds():
    db = FakeDB()
    calls = {"n": 0}
    restored = {"n": 0}

    async def run_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise SessionExpired("expired")
        db.posted.add("g1")

    def restore():
        restored["n"] += 1
        return True

    res = _run(db, run_once=run_once, restore_session=restore)
    assert res["posted"] is True
    assert res["restored"] is True
    assert restored["n"] == 1


def test_session_unrecoverable_stops_after_one_restore():
    # A stale backup that restores "successfully" but is itself expired must NOT
    # loop forever: restore once, and if the login is still expired, give up so
    # the operator is alerted (the real production failure mode).
    db = FakeDB()
    calls = {"n": 0}
    restored = {"n": 0}

    async def run_once():
        calls["n"] += 1
        raise SessionExpired("still expired")

    def restore():
        restored["n"] += 1
        return True

    res = _run(db, run_once=run_once, restore_session=restore)
    assert res["posted"] is False
    assert res["reason"] == "session_unrecoverable"
    assert restored["n"] == 1  # restored exactly once, then stopped
    assert calls["n"] == 2


def test_no_backup_to_restore_stops_immediately():
    db = FakeDB()
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        raise SessionExpired("expired")

    res = _run(db, run_once=run_once, restore_session=lambda: False)
    assert res["posted"] is False
    assert res["reason"] == "no_backup_to_restore"
    assert res["restored"] is False
    assert calls["n"] == 1


def test_budget_exhausted_stops_for_next_trigger():
    db = FakeDB()

    async def run_once():
        return None  # never posts

    times = iter([0.0, 5000.0])

    res = _run(db, run_once=run_once, time_fn=lambda: next(times))
    assert res["posted"] is False
    assert res["reason"] == "budget_exhausted"
    assert res["attempts"] == 1


def test_keeps_going_after_generic_error():
    db = FakeDB()
    calls = {"n": 0}

    async def run_once():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        db.posted.add("g1")

    res = _run(db, run_once=run_once)
    assert res["posted"] is True
    assert calls["n"] == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
