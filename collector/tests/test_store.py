"""Tests for the collected-property store (役割3)."""

from src.store import PropertyStore, signature


def _record(text="神奈川県の一棟アパート 4980万円 利回り8%"):
    return {
        "group_id": "g1", "group_name": "投資家グループ", "permalink": "https://fb/p/1",
        "author": "山田", "price_yen": 49_800_000, "yield_pct": 8.0,
        "prefecture": "神奈川県", "location": "神奈川県横浜市", "property_type": "一棟アパート",
        "areas": {"建物": 180.5}, "raw_text": text,
    }


def test_signature_is_stable_and_scoped_by_group():
    assert signature("g1", "abc") == signature("g1", "abc")
    assert signature("g1", "abc") != signature("g2", "abc")


def test_upsert_creates_then_updates(tmp_path):
    store = PropertyStore(tmp_path / "c.db")
    assert store.upsert(_record(), collected_at="2026-06-29") == "created"
    # Same group + same text -> same signature -> update, not duplicate.
    assert store.upsert(_record(), collected_at="2026-06-29") == "updated"
    assert store.count() == 1


def test_distinct_posts_create_distinct_rows(tmp_path):
    store = PropertyStore(tmp_path / "c.db")
    store.upsert(_record("物件A 5000万円 利回り7%"), collected_at="d")
    store.upsert(_record("物件B 6000万円 利回り9%"), collected_at="d")
    assert store.count() == 2


def test_export_json(tmp_path):
    store = PropertyStore(tmp_path / "c.db")
    store.upsert(_record(), collected_at="d")
    n = store.export_json(tmp_path / "out.json")
    assert n == 1
    assert (tmp_path / "out.json").exists()
