from types import SimpleNamespace

from src.generator import generate_variants


def test_generator_fallback_preserves_numbers_and_rules():
    settings = SimpleNamespace(anthropic_api_key="", claude_model="unused")
    prop = {
        "property_id": "p1",
        "title": "テスト物件",
        "price": "3,480万円",
        "yield_pct": "8.5%",
        "location": "横浜市",
        "access": "駅徒歩7分",
        "structure": "RC造",
        "land_area": "120.5㎡",
        "building_area": "210.3㎡",
        "year_built": "2008年",
        "highlights": ["駅近"],
        "url": "https://example.com",
        "images": [],
    }
    groups = [
        {"id": "g1", "name": "A", "tone": "丁寧", "max_chars": 1500, "allow_links": True, "signature": "署名", "forbidden": ["保証"], "active_hours": [0, 24]},
        {"id": "g2", "name": "B", "tone": "カジュアル", "max_chars": 800, "allow_links": False, "signature": "DMへ", "forbidden": ["保証"], "active_hours": [0, 24]},
    ]
    batch = generate_variants(prop, groups, settings)
    assert batch.degraded is True
    assert len(batch.variants) == 2
    for v in batch.variants:
        assert "3,480万円" in v["body"]
        assert "8.5%" in v["body"]
        assert "保証" not in v["body"]
    assert "https://" not in batch.variants[1]["body"]
    assert batch.variants[0]["body"] != batch.variants[1]["body"]
