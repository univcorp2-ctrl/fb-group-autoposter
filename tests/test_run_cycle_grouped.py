"""Dry-run tests for per-group property selection (run_cycle_grouped).

Proves each group independently picks its OWN next property by its OWN
selection_order, with NO real browser/network (DRY_RUN + AUTO_APPROVE).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from config import Settings
from src.orchestrator import run_cycle_grouped


async def _no_sleep(_seconds):
    """No-op sleeper so the block-avoidance interval doesn't stall tests."""
    return None

_GROUPS_YAML = """
groups:
  - id: "g_newest"
    name: "Newest Group"
    post_url: "https://www.facebook.com/groups/g_newest/"
    selection_order: "newest"
    enabled: true
    tone: "プロフェッショナル"
    max_chars: 1200
    active_hours: [0, 24]
    allow_links: false
    allow_images: true
    signature: ""
    forbidden: ["保証", "絶対", "確実"]
    contact: "📩 お問い合わせ"
  - id: "g_cheap"
    name: "Cheapest Group"
    post_url: "https://www.facebook.com/groups/g_cheap/"
    selection_order: "price_asc"
    enabled: true
    tone: "プロフェッショナル"
    max_chars: 1200
    active_hours: [0, 24]
    allow_links: false
    allow_images: true
    signature: ""
    forbidden: ["保証", "絶対", "確実"]
    contact: "📩 お問い合わせ"
"""


def _eb_item(pid, *, price, created):
    return {
        "id": pid,
        "propertyId": pid,
        "detail_url": f"https://estate-board.com/x/{pid}",
        "publicationStatus": "PUBLISHED",
        "deletedAt": "",
        "createdAt": created,
        "property.allowBrokerSharing": "TRUE",
        "property.label": f"物件{pid}",
        "property.price": price,
        "property.yieldAssumedFullOccupancy": "7.0",
        "property.prefectureLabel": "東京都",
        "property.cityLabel": "新宿区",
        "property.propertyType": "WHOLE_BUILDING_MANSION",
        "property.buildingStructureType": "REINFORCED_CONCRETE",
        "property.floorsAboveGround": "4",
    }


def _write_source(tmp_path) -> Path:
    # Newest = highest createdAt (pid 3). Cheapest = lowest price (pid 1).
    items = [
        _eb_item("1", price="30000000", created="2026-06-13T01:00:00Z"),  # cheapest
        _eb_item("2", price="90000000", created="2026-06-13T03:00:00Z"),
        _eb_item("3", price="60000000", created="2026-06-13T09:00:00Z"),  # newest
    ]
    src = tmp_path / "properties.json"
    src.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
    return src


def test_grouped_cycle_each_group_picks_own_property(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("groups.yaml").write_text(_GROUPS_YAML, encoding="utf-8")
    source = _write_source(tmp_path)

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    monkeypatch.setenv("AUTO_APPROVE_SKIP_DEGRADED", "false")  # auto-approve template bodies
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "jobs.db"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "data" / "inbox"))
    monkeypatch.setenv("PROFILE_DIR", str(tmp_path / "profiles" / "main"))
    settings = Settings.load(env_file=tmp_path / ".env")

    summary = asyncio.run(run_cycle_grouped(settings, source=source, sleeper=_no_sleep))

    assert summary["created"] == 2  # one job per group
    assert summary["approved_processed"] == 2

    # Inspect the queued jobs to confirm WHICH property each group selected.
    from src.queue_db import QueueDB

    db = QueueDB(settings.db_path)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT t.group_id, j.property_id FROM job_targets t JOIN jobs j ON j.job_id=t.job_id"
        ).fetchall()
    by_group = {r["group_id"]: r["property_id"] for r in rows}

    assert by_group["g_newest"] == "eb-3"  # newest createdAt
    assert by_group["g_cheap"] == "eb-1"   # cheapest price
    assert by_group["g_newest"] != by_group["g_cheap"]  # DIFFERENT properties


def test_grouped_cycle_skips_group_posted_today(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("groups.yaml").write_text(_GROUPS_YAML, encoding="utf-8")
    source = _write_source(tmp_path)

    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("AUTO_APPROVE", "true")
    monkeypatch.setenv("AUTO_APPROVE_SKIP_DEGRADED", "false")  # auto-approve template bodies
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "jobs.db"))
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "data" / "inbox"))
    monkeypatch.setenv("PROFILE_DIR", str(tmp_path / "profiles" / "main"))
    settings = Settings.load(env_file=tmp_path / ".env")

    # First run posts to both groups.
    asyncio.run(run_cycle_grouped(settings, source=source, sleeper=_no_sleep))
    # Second run on the SAME JST day: both groups already posted -> all skipped.
    summary2 = asyncio.run(run_cycle_grouped(settings, source=source, sleeper=_no_sleep))
    assert summary2["created"] == 0
    assert summary2["skipped_groups"] == 2
