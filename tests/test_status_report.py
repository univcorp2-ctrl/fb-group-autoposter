"""Tests for posting-status aggregation (src/status_report.py)."""
from src.status_report import (
    STATUS_FAILED,
    STATUS_POSTED,
    STATUS_UNCERTAIN,
    STATUS_UNPOSTED,
    PostRecord,
    build_rows,
    classify,
    summarize,
)


def _item(pid, label, *, broker="TRUE", published="PUBLISHED", price="100000000", created="2026-06-01"):
    return {
        "propertyId": pid,
        "publicationStatus": published,
        "deletedAt": "",
        "createdAt": created,
        "detail_url": f"https://estate-board.com/x/{pid}",
        "property.allowBrokerSharing": broker,
        "property.label": label,
        "property.price": price,
        "property.propertyType": "WHOLE_BUILDING_MANSION",
        "property.prefectureLabel": "東京都",
    }


def test_classify_maps_status():
    assert classify(PostRecord("posted")) == STATUS_POSTED
    # 'uncertain' is submitted-but-unverified — must NOT be counted as 投稿済.
    assert classify(PostRecord("uncertain")) == STATUS_UNCERTAIN
    assert classify(PostRecord("failed")) == STATUS_FAILED
    assert classify(PostRecord("skipped")) == STATUS_UNPOSTED
    assert classify(None) == STATUS_UNPOSTED


def test_build_rows_excludes_non_broker_and_joins_status():
    items = [
        _item("1", "投稿済物件"),
        _item("2", "未投稿物件"),
        _item("3", "対象外", broker="FALSE"),  # not broker-OK -> excluded
    ]
    records = {
        "eb-1": PostRecord("posted", posted_at="2026-06-10T00:00:00+00:00", screenshot="screenshots/p.png", body="本文プレビュー"),
    }
    rows = build_rows(items, records)
    assert len(rows) == 2  # the non-broker item is filtered out
    by_id = {r.property_id: r for r in rows}
    assert by_id["eb-1"].status == STATUS_POSTED
    assert by_id["eb-1"].posted_at_jst.startswith("2026-06-10")
    assert by_id["eb-1"].body_preview == "本文プレビュー"
    assert by_id["eb-2"].status == STATUS_UNPOSTED
    # posted sorts before unposted
    assert rows[0].property_id == "eb-1"


def test_summarize_counts():
    items = [_item("1", "a"), _item("2", "b"), _item("3", "c")]
    records = {"eb-1": PostRecord("posted"), "eb-2": PostRecord("failed")}
    counts = summarize(build_rows(items, records))
    assert counts[STATUS_POSTED] == 1
    assert counts[STATUS_FAILED] == 1
    assert counts[STATUS_UNPOSTED] == 1
    assert counts["total"] == 3
