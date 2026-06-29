"""Tests for the pre-post freshness gate (src/freshness.py) and the poster's
freshness skip wiring (src/poster.py)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from src.freshness import FRESH, STALE, UNKNOWN, FreshnessChecker, FreshnessResult, build_checker
from src.poster import FacebookPoster

POSTABLE = {
    "propertyId": "ALIVE1",
    "publicationStatus": "PUBLISHED",
    "property.allowBrokerSharing": "TRUE",
    "property.price": 35000000,
}
DELETED = {**POSTABLE, "propertyId": "DEAD1", "deletedAt": "2026-06-20T00:00:00Z"}
UNPUBLISHED = {**POSTABLE, "propertyId": "DRAFT1", "publicationStatus": "DRAFT"}
NO_PRICE = {"propertyId": "NOYEN1", "publicationStatus": "PUBLISHED",
            "property.allowBrokerSharing": "TRUE", "property.price": ""}
BROKER_OFF = {**POSTABLE, "propertyId": "NOSHARE1", "property.allowBrokerSharing": "FALSE"}


def _write(path, items):
    path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return path


# ---- checker: EstateBoard listings -----------------------------------------

def test_eb_postable_is_fresh(tmp_path):
    src = _write(tmp_path / "p.json", [POSTABLE])
    assert FreshnessChecker(src).check("eb-ALIVE1") == FreshnessResult(FRESH, "postable")


def test_eb_deleted_is_stale(tmp_path):
    src = _write(tmp_path / "p.json", [DELETED])
    res = FreshnessChecker(src).check("eb-DEAD1")
    assert res.is_stale and res.reason == "deleted"


def test_eb_unpublished_is_stale(tmp_path):
    src = _write(tmp_path / "p.json", [UNPUBLISHED])
    assert FreshnessChecker(src).check("eb-DRAFT1").reason == "unpublished"


def test_eb_no_price_is_stale(tmp_path):
    src = _write(tmp_path / "p.json", [NO_PRICE])
    assert FreshnessChecker(src).check("eb-NOYEN1").reason == "no_price"


def test_eb_broker_sharing_off_is_stale(tmp_path):
    src = _write(tmp_path / "p.json", [BROKER_OFF])
    assert FreshnessChecker(src).check("eb-NOSHARE1").reason == "broker_sharing_off"


def test_eb_absent_listing_is_stale(tmp_path):
    """The core case: a property that has vanished from EstateBoard."""
    src = _write(tmp_path / "p.json", [POSTABLE])
    res = FreshnessChecker(src).check("eb-GONE999")
    assert res.is_stale and res.reason == "not_in_estateboard"


def test_eb_source_missing_is_unknown_and_fails_open(tmp_path):
    res = FreshnessChecker(tmp_path / "does_not_exist.json").check("eb-ALIVE1")
    assert res.state == UNKNOWN
    assert res.allow_post is True
    assert res.source_missing is True


# ---- checker: Daiwa + unverifiable -----------------------------------------

def test_daiwa_present_is_fresh(tmp_path):
    src = (tmp_path / "d.json")
    src.write_text(json.dumps([{"ID": "DH-7"}]), encoding="utf-8")
    assert FreshnessChecker(None, src).check("daiwa-DH-7").state == FRESH


def test_daiwa_absent_is_stale(tmp_path):
    src = (tmp_path / "d.json")
    src.write_text(json.dumps([{"ID": "DH-7"}]), encoding="utf-8")
    assert FreshnessChecker(None, src).check("daiwa-DH-99").reason == "not_in_daiwa"


def test_unverifiable_origin_is_unknown(tmp_path):
    res = FreshnessChecker(_write(tmp_path / "p.json", [POSTABLE])).check("sample-001")
    assert res.state == UNKNOWN and res.allow_post is True


def test_build_checker_derives_daiwa_path(tmp_path):
    eb = tmp_path / "EstateBoard" / "output" / "received" / "properties.json"
    eb.parent.mkdir(parents=True)
    _write(eb, [POSTABLE])
    daiwa = tmp_path / "EstateBoard" / "docs" / "data_daiwa.json"
    daiwa.parent.mkdir(parents=True)
    daiwa.write_text(json.dumps([{"ID": "DH-1"}]), encoding="utf-8")
    checker = build_checker(eb)
    assert checker.check("daiwa-DH-1").state == FRESH


# ---- poster wiring ---------------------------------------------------------

class _FakeDB:
    def __init__(self):
        self.targets = [{"group_id": "g1"}, {"group_id": "g2"}]
        self.updates: list[tuple] = []
        self.job_status: list[tuple] = []

    def update_job_status(self, job_id, status):
        self.job_status.append((job_id, status))

    def unposted_targets(self, job_id):
        return list(self.targets)

    def update_target_status(self, job_id, group_id, status, **kw):
        self.updates.append((group_id, status, kw.get("error")))

    def finalize_job_from_targets(self, job_id):
        return "skipped"


class _FakeChecker:
    def __init__(self, result):
        self.result = result

    def check(self, _pid):
        return self.result


class _RecordingNotifier:
    def __init__(self):
        self.alerts: list[str] = []

    def alert(self, text):
        self.alerts.append(text)


def _poster(db, checker, notifier=None):
    settings = SimpleNamespace(dry_run=True, max_posts_per_day=10)
    return FacebookPoster(settings, db, groups=[{"id": "g1"}, {"id": "g2"}],
                          notifier=notifier, freshness_checker=checker)


def test_post_job_skips_stale_property_without_posting():
    db, notifier = _FakeDB(), _RecordingNotifier()
    poster = _poster(db, _FakeChecker(FreshnessResult(STALE, "deleted")), notifier)
    status = asyncio.run(poster.post_job({"job_id": "j1", "property_id": "eb-DEAD1"}))
    assert status == "skipped"
    assert all(u[1] == "skipped" for u in db.updates)
    assert all("stale_property:deleted" == u[2] for u in db.updates)
    assert notifier.alerts and "スキップ" in notifier.alerts[0]


def test_post_job_alerts_but_allows_when_source_missing():
    db, notifier = _FakeDB(), _RecordingNotifier()
    poster = _poster(db, _FakeChecker(FreshnessResult(UNKNOWN, "eb_source_unavailable")), notifier)
    reason = poster._freshness_skip_reason({"job_id": "j1", "property_id": "eb-X"})
    assert reason is None  # fails open
    assert notifier.alerts and "確認できませんでした" in notifier.alerts[0]


def test_no_checker_means_no_skip():
    db = _FakeDB()
    poster = _poster(db, checker=None)
    assert poster._freshness_skip_reason({"job_id": "j1", "property_id": "eb-X"}) is None
