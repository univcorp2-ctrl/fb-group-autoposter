"""Tests for the property extractor (役割3 core, pure functions)."""

from src.property_extractor import (
    extract_property,
    looks_like_property,
    parse_location,
    parse_price_yen,
    parse_property_type,
    parse_station,
    parse_year_built,
    parse_yield_pct,
)


def test_parse_price_oku_man():
    assert parse_price_yen("価格 1億2000万円") == 120_000_000


def test_parse_price_oku_only():
    assert parse_price_yen("総額 3億円") == 300_000_000


def test_parse_price_man_with_comma():
    assert parse_price_yen("お値段 3,980万円です") == 39_800_000


def test_parse_price_man_no_yen_suffix():
    assert parse_price_yen("4500万 で売り出し") == 45_000_000


def test_parse_price_none_when_absent():
    assert parse_price_yen("駅徒歩5分の好立地") is None


def test_parse_yield_explicit():
    assert parse_yield_pct("表面利回り 8.5%") == 8.5


def test_parse_yield_fullwidth_percent():
    assert parse_yield_pct("利回り：7％") == 7.0


def test_parse_yield_none_without_context():
    assert parse_yield_pct("消費税10%込み") is None


def test_parse_location_prefecture_and_city():
    pref, loc = parse_location("所在地：神奈川県横浜市神奈川区大口通")
    assert pref == "神奈川県"
    assert loc.startswith("神奈川県横浜市")


def test_parse_location_none():
    assert parse_location("駅近の好物件") == (None, None)


def test_parse_property_type():
    assert parse_property_type("一棟マンション 投資用") == "一棟マンション"
    assert parse_property_type("区分マンションです") == "区分マンション"
    assert parse_property_type("更地の土地") == "土地"


def test_parse_station():
    # The rail-line prefix is kept (useful context for the property DB).
    assert parse_station("JR大口駅 徒歩7分") == "JR大口駅 徒歩7分"
    assert parse_station("大口駅徒歩5分") == "大口駅 徒歩5分"


def test_parse_year_built_variants():
    assert parse_year_built("築20年") == "築20年"
    assert parse_year_built("1998年築") == "1998年築"
    assert parse_year_built("新築一棟") == "新築"


def test_looks_like_property_gate():
    assert looks_like_property("一棟アパート 利回り8% 4500万円") is True
    assert looks_like_property("おはようございます！") is False


def test_extract_full_listing():
    text = (
        "【売り物件】神奈川県横浜市の一棟アパート\n"
        "価格 4,980万円 表面利回り 8.20%\n"
        "JR横浜駅 徒歩10分 築15年 建物 180.5㎡"
    )
    p = extract_property(text)
    assert p is not None
    assert p.price_yen == 49_800_000
    assert p.yield_pct == 8.2
    assert p.prefecture == "神奈川県"
    assert p.property_type == "一棟アパート"
    assert p.station_access == "JR横浜駅 徒歩10分"
    assert p.year_built == "築15年"
    assert p.areas.get("建物") == 180.5


def test_extract_returns_none_for_non_listing():
    assert extract_property("今日の勉強会ありがとうございました！次回もよろしく") is None


def test_extract_returns_none_when_no_price_or_yield():
    # Mentions 物件/一棟 but has no number -> not stored.
    assert extract_property("一棟物件を探しています。良い物件あれば紹介ください。") is None
