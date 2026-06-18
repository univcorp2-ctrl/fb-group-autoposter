"""Extended coverage tests for fb-group-autoposter.

Covers edge cases missed by the base test suite across config, group_rules,
property_schema, queue_db, ingest, generator, approval, and orchestrator.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from config import Settings, _bool, _int
from src.approval import TelegramApproval
from src.generator import fallback_body, generate_variants
from src.group_rules import (
    apply_group_rules,
    enforce_max_chars,
    remove_forbidden_words,
    strip_links,
)
from src.ingest import ingest_manual, scan_inbox
from src.orchestrator import pipeline_lock, sample_property
from src.property_schema import normalize_property, validate_property
from src.queue_db import QueueDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_group(**overrides) -> dict:
    base = {
        "id": "test-group",
        "name": "Test Group",
        "post_url": "https://www.facebook.com/groups/test-group/",
        "tone": "丁寧",
        "max_chars": 1500,
        "active_hours": [9, 22],
        "allow_links": True,
        "allow_images": True,
        "signature": "",
        "forbidden": [],
    }
    base.update(overrides)
    return base


def _make_settings(**overrides) -> SimpleNamespace:
    base = {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "auto_approve": False,
        "auto_approve_skip_degraded": True,
        "anthropic_api_key": "",
        "claude_model": "unused",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ===========================================================================
# 1. Config edge cases
# ===========================================================================


class TestBoolHelper:
    @pytest.mark.parametrize("value", ["1", "true", "yes", "y", "on", "True", "YES"])
    def test_bool_helper_various_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("TEST_FLAG", value)
        assert _bool("TEST_FLAG", False) is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "n", "off", "anything", "nope", "disabled"])
    def test_bool_helper_various_falsy_values(self, monkeypatch, value):
        monkeypatch.setenv("TEST_FLAG", value)
        assert _bool("TEST_FLAG", True) is False


def test_int_helper_default_on_empty(monkeypatch):
    monkeypatch.setenv("TEST_INT", "")
    assert _int("TEST_INT", 42) == 42


def test_settings_validate_rejects_negative_values(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAX_POSTS_PER_DAY", "-1")
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(ValueError, match="MAX_POSTS_PER_DAY must be positive"):
        settings.validate_runtime(require_external=False)


def test_settings_validate_rejects_bad_browser_backend(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BROWSER_BACKEND", "selenium")
    settings = Settings.load(env_file=tmp_path / ".env")
    with pytest.raises(ValueError, match="BROWSER_BACKEND must be playwright or adspower"):
        settings.validate_runtime(require_external=False)


# ===========================================================================
# 2. Group rules edge cases
# ===========================================================================


def test_enforce_max_chars_exactly_at_limit():
    body = "x" * 500
    result, truncated = enforce_max_chars(body, 500)
    assert truncated is False
    assert result == body


def test_enforce_max_chars_one_over():
    body = "x" * 501
    result, truncated = enforce_max_chars(body, 500)
    assert truncated is True
    assert len(result) <= 500


def test_enforce_max_chars_raises_on_zero():
    with pytest.raises(ValueError, match="max_chars must be positive"):
        enforce_max_chars("hello", 0)


def test_strip_links_preserves_non_urls():
    text = "これはテストです。メール: user@example.com"
    result, removed = strip_links(text)
    assert removed is False
    assert result == text


def test_remove_forbidden_words_empty_list():
    body = "普通の文章です"
    result, removed = remove_forbidden_words(body, [])
    assert result == body
    assert removed == ()


def test_apply_group_rules_preserves_links_when_allowed():
    group = _make_group(allow_links=True, forbidden=[])
    body = "物件情報 https://example.com/property/1"
    result = apply_group_rules(body, group)
    assert "https://example.com/property/1" in result.body
    assert result.removed_links is False


# ===========================================================================
# 3. Property schema edge cases
# ===========================================================================


def test_validate_property_rejects_missing_fields():
    incomplete = {"property_id": "x", "title": "A"}
    with pytest.raises(ValueError, match="missing normalized fields"):
        validate_property(incomplete)


def test_validate_property_rejects_non_list_highlights():
    prop = normalize_property({"title": "A"})
    prop["highlights"] = "not a list"
    with pytest.raises(ValueError, match="highlights must be a list"):
        validate_property(prop)


def test_normalize_handles_string_highlights_with_commas():
    prop = normalize_property({"title": "A", "highlights": "駅近, RC造, 満室"})
    assert prop["highlights"] == ["駅近", "RC造", "満室"]
    assert isinstance(prop["highlights"], list)


def test_normalize_handles_string_images():
    prop = normalize_property({"title": "A", "images": "photo.jpg"})
    assert prop["images"] == ["photo.jpg"]
    assert isinstance(prop["images"], list)


# ===========================================================================
# 4. Queue DB edge cases
# ===========================================================================


def test_create_job_ignores_duplicate_insert(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    prop = {"property_id": "p1", "title": "A", "job_id": "fixed-id"}
    variants = [{"group_id": "g1", "body": "body1"}]
    first_id = db.create_job(prop, variants)
    second_id = db.create_job(prop, variants)
    assert first_id == second_id
    targets = db.get_targets(first_id)
    assert len(targets) == 1


def test_heartbeat_round_trip(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    db.mark_heartbeat("test-component")
    age = db.heartbeat_age_minutes("test-component")
    assert age is not None
    assert age < 1.0


def test_posted_same_group_recently_false_when_old(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    prop = {"property_id": "p1", "title": "A"}
    variants = [{"group_id": "g1", "body": "body"}]
    job_id = db.create_job(prop, variants)
    db.update_target_status(job_id, "g1", "posted")

    # Manually backdate the posted_at to 48 hours ago
    old_ts = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_targets SET posted_at=? WHERE job_id=? AND group_id=?",
            (old_ts, job_id, "g1"),
        )

    assert db.posted_same_group_recently("g1", hours=24) is False


def test_finalize_all_skipped_is_done(tmp_path):
    # A guard-skip (daily cap, same-group spacing, duplicate, outside hours) is
    # "correctly did nothing", not a failure — it must not surface as `failed`.
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "p1"},
        [{"group_id": "g1", "body": "a"}, {"group_id": "g2", "body": "b"}],
    )
    db.update_target_status(job_id, "g1", "skipped")
    db.update_target_status(job_id, "g2", "skipped")
    status = db.finalize_job_from_targets(job_id)
    assert status == "done"


def test_finalize_failed_target_still_reports_failure(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "p1"},
        [{"group_id": "g1", "body": "a"}, {"group_id": "g2", "body": "b"}],
    )
    db.update_target_status(job_id, "g1", "failed", error="boom")
    db.update_target_status(job_id, "g2", "skipped")
    assert db.finalize_job_from_targets(job_id) == "failed"


def test_posted_same_group_today_blocks_then_allows_next_day(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "p1"}, [{"group_id": "g1", "body": "b"}])
    db.update_target_status(job_id, "g1", "posted")
    # Posted just now -> same JST day -> blocked.
    assert db.posted_same_group_today("g1") is True
    assert db.posted_same_group_today("other") is False

    # Backdate the post to 30h ago -> a previous JST day -> the next day's run
    # is allowed (this is exactly what the hours-based guard wrongly blocked).
    old_ts = (datetime.now(UTC) - timedelta(hours=30)).isoformat()
    with db.connect() as conn:
        conn.execute(
            "UPDATE job_targets SET posted_at=? WHERE job_id=? AND group_id=?",
            (old_ts, job_id, "g1"),
        )
    assert db.posted_same_group_today("g1") is False


# ===========================================================================
# 5. Ingest edge cases
# ===========================================================================


def test_scan_inbox_empty_directory(tmp_path):
    empty_inbox = tmp_path / "empty_inbox"
    empty_inbox.mkdir()
    result = scan_inbox(empty_inbox)
    assert result == []


def test_ingest_manual_minimal_input():
    prop = ingest_manual({})
    assert prop["title"] == "記載なし"
    assert prop["price"] == "記載なし"
    assert prop["yield_pct"] == "記載なし"
    assert prop["location"] == "記載なし"
    assert isinstance(prop["highlights"], list)
    assert isinstance(prop["images"], list)
    assert prop["property_id"]  # must not be empty


# ===========================================================================
# 6. Generator edge cases
# ===========================================================================


def test_fallback_body_casual_tone_adds_emoji_option():
    group = _make_group(tone="カジュアル", max_chars=2000, allow_links=True)
    prop = {
        "property_id": "p1",
        "title": "テスト物件",
        "price": "3,480万円",
        "yield_pct": "8.5%",
        "location": "横浜市",
        "access": "駅徒歩7分",
        "structure": "RC造",
        "land_area": "120㎡",
        "building_area": "200㎡",
        "year_built": "2008年",
        "highlights": ["駅近"],
        "url": "https://example.com",
    }
    body = fallback_body(prop, group)
    # The casual tone path adds openings that may include emoji.
    # The body must still contain the factual property data.
    assert "3,480万円" in body
    assert "8.5%" in body
    assert isinstance(body, str)
    assert len(body) > 0


def test_generate_variants_without_api_key_is_degraded():
    settings = _make_settings(anthropic_api_key="")
    prop = normalize_property({
        "property_id": "p-test",
        "title": "物件X",
        "price": "5,000万円",
        "yield_pct": "6.0%",
    })
    groups = [_make_group(id="g1"), _make_group(id="g2")]
    batch = generate_variants(prop, groups, settings)
    assert batch.degraded is True
    assert len(batch.variants) == 2
    for v in batch.variants:
        assert v["body"]
        assert "5,000万円" in v["body"]


# ===========================================================================
# 7. Approval edge cases
# ===========================================================================


def test_telegram_disabled_when_no_token(tmp_path):
    settings = _make_settings(telegram_bot_token="", telegram_chat_id="")
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(settings, db)
    assert approval.enabled is False


def test_poll_once_returns_zero_when_disabled(tmp_path):
    settings = _make_settings(telegram_bot_token="", telegram_chat_id="")
    db = QueueDB(tmp_path / "jobs.db")
    approval = TelegramApproval(settings, db)
    result = approval.poll_once()
    assert result == 0


# ===========================================================================
# 8. Orchestrator
# ===========================================================================


def test_pipeline_lock_prevents_concurrent_runs(tmp_path, monkeypatch):
    lock_file = tmp_path / "pipeline.lock"
    # Write a lock with a different PID
    lock_file.write_text("999999999", encoding="utf-8")
    monkeypatch.setattr("src.orchestrator._pid_is_running", lambda pid: True)
    with pytest.raises(RuntimeError, match="pipeline lock exists"):
        with pipeline_lock(lock_file):
            pass  # pragma: no cover


def test_sample_property_has_required_fields():
    prop = sample_property()
    required = ["property_id", "title", "price", "yield_pct", "location",
                "access", "structure", "land_area", "building_area",
                "year_built", "highlights", "url", "images", "raw_text"]
    for field in required:
        assert field in prop, f"sample_property missing field: {field}"
    assert isinstance(prop["highlights"], list)
    assert isinstance(prop["images"], list)
