"""Final-click attempt boundary tests with a synthetic Playwright page."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.approval import TelegramApproval
from src.poster import FacebookPoster, SubmissionAmbiguous
from src.queue_db import QueueDB


def _prepared(db: QueueDB):
    db.create_job(
        {"job_id": "job", "property_id": "property"},
        [{"group_id": "group", "body": "body", "source_hash": "source", "generation_fingerprint": "fingerprint"}],
    )
    return db.approve_target("job", "group", source="operator")


def test_final_click_commits_attempt_before_the_fake_click(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = _prepared(db)
    poster = FacebookPoster(SimpleNamespace(), db, [])
    observed: list[str] = []

    class Locator:
        first = None
        def __init__(self): self.first = self
        async def count(self): return 1
        async def is_visible(self): return True
        async def click(self, **_kwargs):
            observed.append(db.list_submission_attempts()[0]["click_started_at"])

    class Page:
        def locator(self, _selector): return Locator()

    target = db.get_targets("job")[0]
    attempt = db.begin_submission(
        "job", "group", approval_id=approval["approval_id"], source_hash="source",
        body_hash=approval["body_hash"], generation_fingerprint="fingerprint",
    )
    asyncio.run(poster._click_first(Page(), "post_button", "post", before_click=lambda: db.mark_click_started(attempt["attempt_id"])))

    assert observed and observed[0]
    assert db.get_submission_attempt(attempt["attempt_id"])["click_started_at"]
    assert target["group_id"] == "group"


def test_missing_final_selector_aborts_preclick_attempt_without_retry(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = _prepared(db)
    poster = FacebookPoster(SimpleNamespace(), db, [])

    class Missing:
        first = None
        def __init__(self): self.first = self
        async def count(self): return 0

    class Page:
        def locator(self, _selector): return Missing()

    attempt = db.begin_submission(
        "job", "group", approval_id=approval["approval_id"], source_hash="source",
        body_hash=approval["body_hash"], generation_fingerprint="fingerprint",
    )
    try:
        asyncio.run(poster._click_first(Page(), "post_button", "post", before_click=lambda: db.mark_click_started(attempt["attempt_id"])))
    except RuntimeError:
        db.abort_submission_preclick(attempt["attempt_id"], reason="selector_missing")

    assert db.get_submission_attempt(attempt["attempt_id"])["state"] == "aborted_preclick"
    assert db.get_targets("job")[0]["status"] == "approved"


def test_auto_approval_binds_target_before_final_fake_click(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    db.create_job(
        {"job_id": "job", "property_id": "property"},
        [{"group_id": "group", "body": "body", "source_hash": "source", "generation_fingerprint": "fingerprint"}],
    )
    approval = TelegramApproval(
        SimpleNamespace(
            auto_approve=True, auto_approve_skip_degraded=False,
            telegram_bot_token="", telegram_chat_id="",
        ), db
    )
    approval.auto_or_send_preview("job")
    target = db.get_targets("job")[0]
    poster = FacebookPoster(SimpleNamespace(), db, [])
    click_started: list[str] = []

    class Locator:
        first = None
        def __init__(self): self.first = self
        async def count(self): return 1
        async def is_visible(self): return True
        async def click(self, **_kwargs):
            click_started.append(db.list_submission_attempts()[0]["click_started_at"])

    class Page:
        def locator(self, _selector): return Locator()

    attempt_id = poster._begin_submission_if_bound({"job_id": "job"}, target)
    asyncio.run(
        poster._click_first(
            Page(), "post_button", "post",
            before_click=lambda: db.mark_click_started(attempt_id),
        )
    )

    assert target["approval_id"]
    assert attempt_id
    assert click_started == [db.get_submission_attempt(attempt_id)["click_started_at"]]


def test_unbound_approved_job_stops_before_browser_activity(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    db.create_job({"job_id": "legacy", "property_id": "property"}, [{"group_id": "group", "body": "body"}])
    db.approve_job("legacy")
    poster = FacebookPoster(
        SimpleNamespace(
            browser_backend="playwright", profile_dir=tmp_path / "profile",
            browser_user_agent="ua", page_hard_timeout=1,
        ), db, [],
    )

    with pytest.raises(RuntimeError, match="manual_reapproval_required"):
        asyncio.run(poster._post_job_real({"job_id": "legacy", "property_id": "property"}))


def test_click_error_after_boundary_is_ambiguous_and_never_retried(tmp_path, monkeypatch):
    import src.poster as poster_module

    db = QueueDB(tmp_path / "jobs.db")
    _prepared(db)
    target = db.get_targets("job")[0]
    poster = FacebookPoster(SimpleNamespace(page_hard_timeout=1), db, [])
    clicks = []

    class Page:
        async def goto(self, *_args, **_kwargs): return None
        async def wait_for_timeout(self, *_args, **_kwargs): return None

    async def noop(*_args, **_kwargs): return None

    async def click_then_raise(_page, action, _intent, *, before_click=None, **_kwargs):
        if action != "post_button":
            return None
        before_click()
        clicks.append("final")
        raise TimeoutError("click response lost")

    monkeypatch.setattr(poster_module, "is_logged_in", lambda _page: _true())
    monkeypatch.setattr(poster, "_detect_blocking_markers", noop)
    monkeypatch.setattr(poster, "_human_pause", noop)
    monkeypatch.setattr(poster, "_click_first", click_then_raise)
    monkeypatch.setattr(poster, "_wait_first", noop)
    monkeypatch.setattr(poster, "_enter_body", noop)
    monkeypatch.setattr(poster, "_attach_images", noop)
    monkeypatch.setattr(poster, "_verify_composer_contains", noop)

    with pytest.raises(SubmissionAmbiguous):
        asyncio.run(poster._post_one(Page(), {"job_id": "job", "property_id": "property"}, target, {"id": "group", "post_url": "https://example.invalid/group"}))

    assert clicks == ["final"]
    assert db.list_submission_attempts()[0]["state"] == "reconcile_only"
    assert db.get_targets("job")[0]["status"] == "uncertain"


def test_disabled_final_control_aborts_before_click_timestamp(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    approval = _prepared(db)
    poster = FacebookPoster(SimpleNamespace(), db, [])
    attempt = db.begin_submission(
        "job", "group", approval_id=approval["approval_id"], source_hash="source",
        body_hash=approval["body_hash"], generation_fingerprint="fingerprint",
    )

    class Locator:
        first = None
        def __init__(self): self.first = self
        async def count(self): return 1
        async def is_visible(self): return True
        async def is_enabled(self): return False
        async def click(self, **_kwargs): raise AssertionError("disabled control must not click")

    class Page:
        def locator(self, _selector): return Locator()

    with pytest.raises(RuntimeError, match="not_actionable"):
        asyncio.run(
            poster._click_first(
                Page(), "post_button", "post",
                before_click=lambda: db.mark_click_started(attempt["attempt_id"]),
            )
        )
    db.abort_submission_preclick(attempt["attempt_id"], reason="not_actionable")
    assert db.get_submission_attempt(attempt["attempt_id"])["click_started_at"] is None


async def _true():
    return True
