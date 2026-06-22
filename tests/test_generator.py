from types import SimpleNamespace

from src.generator import build_pitch, generate_variants

_FORBIDDEN = ("保証", "絶対", "確実")


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


def _sample_prop(**overrides):
    base = {
        "property_id": "p1",
        "title": "テスト物件",
        "price": "3,480万円",
        "yield_pct": "8.5%",
        "location": "横浜市神奈川区",
        "access": "JR大口駅 徒歩7分",
        "structure": "RC造 4階建",
        "land_area": "120.5㎡",
        "building_area": "210.3㎡",
        "year_built": "2008年",
        "highlights": ["駅近", "RC造", "所有権"],
        "url": "https://example.com",
        "images": [],
    }
    base.update(overrides)
    return base


def test_build_pitch_is_factual_and_safe():
    pitch = build_pitch(_sample_prop())
    assert pitch.startswith("🔑 推しポイント：")
    assert pitch.strip() != "🔑 推しポイント："
    assert "高利回り8.5%" in pitch  # yield >= 8 -> 高利回り label
    assert "駅徒歩7分" in pitch
    for word in _FORBIDDEN:
        assert word not in pitch
    assert len(pitch) <= 70  # short one-liner


def test_build_pitch_handles_sparse_property():
    pitch = build_pitch({"property_id": "x", "title": "無情報物件"})
    assert pitch.startswith("🔑 推しポイント：")
    for word in _FORBIDDEN:
        assert word not in pitch


def test_generate_variants_always_contains_pitch():
    settings = SimpleNamespace(anthropic_api_key="", claude_model="unused")
    groups = [
        {"id": "g1", "name": "A", "tone": "プロフェッショナル", "max_chars": 1200,
         "allow_links": False, "signature": "", "forbidden": list(_FORBIDDEN),
         "active_hours": [7, 23], "contact": "📩 お問い合わせ"},
        # A tight max_chars to prove the pitch survives truncation.
        {"id": "g2", "name": "B", "tone": "カジュアル", "max_chars": 300,
         "allow_links": False, "signature": "DMへ", "forbidden": list(_FORBIDDEN),
         "active_hours": [7, 23], "contact": "📩 お問い合わせ"},
    ]
    batch = generate_variants(_sample_prop(), groups, settings)
    for v in batch.variants:
        assert "推しポイント" in v["body"]
        for word in _FORBIDDEN:
            assert word not in v["body"]
