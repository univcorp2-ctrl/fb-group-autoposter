"""Tests for login-challenge detection and kind propagation.

Covers src/session.classify_challenge, the CheckpointRequired exception, and the
challenge kind being recorded by the ensure loop. No real browser/network — a
tiny async fake page mirrors the FakeDB/async style in test_ensure_loop.py.
"""
import asyncio

from src.ensure import ensure_posted_today
from src.poster import CheckpointRequired, SessionExpired
from src.session import challenge_message, classify_challenge, login_required_message

GROUPS = [{"id": "g1", "active_hours": [0, 24]}]


class FakePage:
    """Minimal async page stub: a `.url` and an async `query_selector`.

    `query_selector` returns None (no inline DOM markers) so URL-based detection
    is exercised in isolation.
    """

    def __init__(self, url: str):
        self.url = url

    async def query_selector(self, _selector):
        return None


# --------------------------------------------------------------------------- #
# classify_challenge — URL based
# --------------------------------------------------------------------------- #
def test_classify_checkpoint_url():
    assert asyncio.run(classify_challenge(FakePage("https://www.facebook.com/checkpoint/123"))) == "checkpoint"


def test_classify_two_factor_url():
    assert asyncio.run(classify_challenge(FakePage("https://www.facebook.com/two_factor/start"))) == "two_factor"


def test_classify_login_url():
    assert asyncio.run(classify_challenge(FakePage("https://www.facebook.com/login/"))) == "login"


def test_classify_recover_url_is_login():
    assert asyncio.run(classify_challenge(FakePage("https://www.facebook.com/recover/initiate"))) == "login"


def test_classify_normal_url_returns_none():
    assert asyncio.run(classify_challenge(FakePage("https://www.facebook.com/groups/12345"))) is None


class FakeMarkerPage:
    """Normal URL but an inline DOM challenge marker present."""

    def __init__(self, url: str, hit_selector: str):
        self.url = url
        self.hit = hit_selector

    async def query_selector(self, selector):
        return object() if selector == self.hit else None


def test_classify_inline_captcha_marker_on_normal_url():
    page = FakeMarkerPage("https://www.facebook.com/groups/12345", 'iframe[src*="recaptcha"]')
    assert asyncio.run(classify_challenge(page)) == "captcha"


# --------------------------------------------------------------------------- #
# challenge_message — per-kind guidance, always points to login_once.py
# --------------------------------------------------------------------------- #
def test_challenge_message_per_kind_and_fallback():
    assert "checkpoint" in challenge_message("checkpoint")
    assert "2段階認証" in challenge_message("two_factor")
    assert "captcha" in challenge_message("captcha")
    for kind in ("checkpoint", "captcha", "two_factor", "login", "unknown"):
        assert "login_once.py" in challenge_message(kind)
    assert "login_once.py" in login_required_message()


# --------------------------------------------------------------------------- #
# CheckpointRequired exception
# --------------------------------------------------------------------------- #
def test_checkpoint_required_is_session_expired_and_carries_kind():
    exc = CheckpointRequired("msg", kind="captcha")
    assert isinstance(exc, SessionExpired)
    assert exc.kind == "captcha"


def test_checkpoint_required_default_kind():
    assert CheckpointRequired("msg").kind == "checkpoint"


# --------------------------------------------------------------------------- #
# ensure.py records the challenge kind
# --------------------------------------------------------------------------- #
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


def test_ensure_records_challenge_when_unrecoverable():
    # Restore "succeeds" once but the login is still a checkpoint, so the run
    # stops as session_unrecoverable and records challenge="checkpoint".
    db = FakeDB()
    restored = {"n": 0}

    async def run_once():
        raise CheckpointRequired("checkpoint detected", kind="checkpoint")

    def restore():
        restored["n"] += 1
        return True

    res = _run(db, run_once=run_once, restore_session=restore)
    assert res["posted"] is False
    assert res["reason"] == "session_unrecoverable"
    assert res["challenge"] == "checkpoint"
    assert restored["n"] == 1


def test_ensure_records_challenge_when_no_backup():
    db = FakeDB()

    async def run_once():
        raise CheckpointRequired("two factor", kind="two_factor")

    res = _run(db, run_once=run_once, restore_session=lambda: False)
    assert res["reason"] == "no_backup_to_restore"
    assert res["challenge"] == "two_factor"


def test_ensure_plain_session_expiry_has_session_expired_challenge():
    # A bare SessionExpired (no kind) records the "session_expired" fallback.
    db = FakeDB()

    async def run_once():
        raise SessionExpired("plain expiry")

    res = _run(db, run_once=run_once, restore_session=lambda: False)
    assert res["reason"] == "no_backup_to_restore"
    assert res["challenge"] == "session_expired"
