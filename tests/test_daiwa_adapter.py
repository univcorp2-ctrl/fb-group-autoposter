"""Tests for Daiwa House adapter + brand masking."""
from src.daiwa_adapter import BRAND_POSITION, daiwa_to_property
from src.group_rules import BRAND_MASK, mask_brands


def test_mask_brands_replaces_all_aliases():
    for alias in ("大和ハウス", "ダイワハウス", "大和ハウス工業", "Daiwa House"):
        assert mask_brands(f"{alias}の物件です") == f"{BRAND_MASK}の物件です"
    assert "大和ハウス" not in mask_brands("提供元: 大和ハウス工業株式会社")


def test_daiwa_to_property_maps_fields_and_positions_brand():
    item = {
        "ID": "DH-7", "物件名": "BASE池袋", "種別": "新築一棟", "価格(万円)": 74000,
        "表面利回り(%)": 4.21, "構造": "RC", "築年数": 0, "手残り(万円/年)": 520,
        "仕入れ判定": "D", "所在地": "", "最寄駅": "",
    }
    p = daiwa_to_property(item)
    assert p["property_id"] == "daiwa-DH-7"
    assert p["title"] == "BASE池袋"
    assert p["price"] == "7億4,000万円"
    assert p["yield_pct"] == "4.21%"
    assert p["structure"] == "RC造 新築"  # 築0年 -> 新築
    assert BRAND_POSITION in p["highlights"]  # positioned as the major brand
    assert "手残り年520万円" in p["highlights"]  # positive CF surfaced
    assert p["_grade"] == "D"


def test_daiwa_to_property_never_leaks_brand():
    item = {"ID": "DH-X", "物件名": "大和ハウス施工 テスト物件", "提供元": "ダイワハウス",
            "種別": "中古一棟", "価格(万円)": 10000, "表面利回り(%)": 8, "構造": "RC", "築年数": 5}
    p = daiwa_to_property(item)
    blob = p["title"] + " ".join(p["highlights"])
    assert "大和ハウス" not in blob and "ダイワハウス" not in blob
    assert BRAND_MASK in p["title"]  # 大和ハウス施工 -> 超大手有名企業ブランド施工


def test_daiwa_to_property_handles_missing_price_yield():
    item = {"ID": "DH-9", "物件名": "Hearty亀戸", "種別": "区分マンション",
            "価格(万円)": "", "表面利回り(%)": 7.85, "構造": "", "築年数": ""}
    p = daiwa_to_property(item)
    assert p["price"] == "記載なし"
    assert p["yield_pct"] == "7.85%"
