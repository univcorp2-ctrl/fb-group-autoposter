import random
from types import SimpleNamespace

from src.generator import generate_variants
from src.group_rules import apply_group_rules
from src.property_schema import normalize_property, validate_property


def make_group(i: int, *, allow_links: bool) -> dict:
    return {
        "id": f"g{i}",
        "name": f"Group {i}",
        "post_url": f"https://www.facebook.com/groups/g{i}/",
        "enabled": True,
        "tone": "カジュアル" if i % 2 else "丁寧・硬め",
        "max_chars": 300 + (i % 5) * 50,
        "active_hours": [0, 24],
        "allow_links": allow_links,
        "allow_images": True,
        "signature": f"署名{i}",
        "forbidden": ["絶対", "必ず儲かる", "保証", f"NG{i}"],
    }


def make_property(i: int) -> dict:
    return normalize_property(
        {
            "property_id": f"p{i}",
            "title": f"テスト物件{i}",
            "price": f"{3000 + i:,}万円",
            "yield_pct": f"{5 + (i % 7)}.{i % 10}%",
            "location": "横浜市神奈川区",
            "access": f"駅徒歩{1 + i % 15}分",
            "structure": "RC造",
            "land_area": f"{100 + i}.5㎡",
            "building_area": f"{200 + i}.3㎡",
            "year_built": f"20{(i % 20):02d}年",
            "highlights": ["駅近", "RC造", "満室稼働中"],
            "url": f"https://example.com/property/{i}",
            "raw_text": "絶対 必ず儲かる 保証 " * 3,
        }
    )


def test_randomized_group_rules_invariants():
    rng = random.Random(20260611)
    for i in range(200):
        group = make_group(i, allow_links=bool(i % 2))
        body = f"本文{i} https://example.com/{i} 絶対 保証 NG{i} " + "あ" * rng.randint(0, 900)
        result = apply_group_rules(body, group)
        assert len(result.body) <= group["max_chars"]
        assert group["signature"] in result.body
        for word in group["forbidden"]:
            assert word not in result.body
        if not group["allow_links"]:
            assert "https://" not in result.body


def test_randomized_generator_preserves_numeric_facts_without_api():
    settings = SimpleNamespace(anthropic_api_key="", claude_model="unused")
    for i in range(100):
        prop = make_property(i)
        validate_property(prop)
        groups = [make_group(i, allow_links=False), make_group(i + 1000, allow_links=True)]
        batch = generate_variants(prop, groups, settings)
        assert batch.degraded is True
        assert len(batch.variants) == 2
        for variant, group in zip(batch.variants, groups, strict=True):
            body = variant["body"]
            assert prop["price"] in body
            assert prop["yield_pct"] in body
            assert prop["land_area"] in body
            assert prop["building_area"] in body
            assert len(body) <= group["max_chars"]
            for word in group["forbidden"]:
                assert word not in body
            if not group["allow_links"]:
                assert "https://" not in body


def test_generation_variation_seed_is_stable_and_distinct():
    settings = SimpleNamespace(anthropic_api_key="", claude_model="unused")
    prop = make_property(777)
    groups = [make_group(1, allow_links=True), make_group(2, allow_links=True), make_group(3, allow_links=True)]
    first = generate_variants(prop, groups, settings)
    second = generate_variants(prop, groups, settings)
    assert [v["variation_seed"] for v in first.variants] == [v["variation_seed"] for v in second.variants]
    assert len({v["variation_seed"] for v in first.variants}) == 3
