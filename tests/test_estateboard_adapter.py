from __future__ import annotations

from src.estateboard_adapter import (
    build_access,
    build_location,
    build_structure,
    format_price_yen,
    format_yield,
    is_broker_ok,
    is_postable,
    select_postable,
    to_property,
)


def _item(**overrides):
    base = {
        "id": "1",
        "propertyId": "100",
        "detail_url": "https://estate-board.com/property-publication/received/1",
        "publicationStatus": "PUBLISHED",
        "deletedAt": "",
        "createdAt": "2026-06-13T08:00:00.000Z",
        "property.allowBrokerSharing": "TRUE",
        "property.label": "テスト一棟マンション",
        "property.price": "120000000",
        "property.yieldAssumedFullOccupancy": "6.5",
        "property.prefectureLabel": "東京都",
        "property.cityLabel": "新宿区",
        "property.restAddress": "高田馬場3-24-4",
        "property.nearestStation1": "JR山手線 高田馬場駅",
        "property.distanceFromNearestStation1": "9",
        "property.buildingStructureType": "REINFORCED_CONCRETE",
        "property.floorsAboveGround": "4",
        "property.propertyType": "WHOLE_BUILDING_MANSION",
        "property.ownershipType": "FREEHOLD",
        "property.commissionAllocation": "分かれ",
        "property.landAreaSqm": "131.89",
        "property.buildingAreaSqm": "635.26",
        "property.constructionDateYear": "2026",
        "property.constructionDateMonth": "3",
        "property.catchphrase": "駅近新築",
    }
    base.update(overrides)
    return base


def test_broker_ng_is_excluded():
    assert is_broker_ok(_item()) is True
    assert is_broker_ok(_item(**{"property.allowBrokerSharing": "FALSE"})) is False


def test_postable_requires_published_and_price():
    assert is_postable(_item()) is True
    assert is_postable(_item(publicationStatus="DRAFT")) is False
    assert is_postable(_item(deletedAt="2026-01-01")) is False
    assert is_postable(_item(**{"property.price": ""})) is False
    assert is_postable(_item(**{"property.allowBrokerSharing": "FALSE"})) is False


def test_price_formatting():
    assert format_price_yen("120000000") == "1億2,000万円"
    assert format_price_yen("59800000") == "5,980万円"
    assert format_price_yen("200000000") == "2億円"
    assert format_price_yen("0") == "記載なし"
    assert format_price_yen(None) == "記載なし"


def test_yield_formatting():
    assert format_yield("6.5") == "6.50%"
    assert format_yield("") == "記載なし"


def test_location_and_access_and_structure():
    item = _item()
    assert build_location(item) == "東京都新宿区高田馬場3-24-4"
    assert build_access(item) == "JR山手線 高田馬場駅 徒歩9分"
    assert build_structure(item) == "RC造 4階建"


def test_to_property_shape():
    prop = to_property(_item())
    assert prop["property_id"] == "eb-100"
    assert prop["title"] == "テスト一棟マンション"
    assert prop["price"] == "1億2,000万円"
    assert prop["yield_pct"] == "6.50%"
    assert prop["images"] == []
    assert "駅近" in prop["highlights"]
    assert "一棟マンション" in prop["highlights"]


def test_select_postable_filters_and_limits():
    items = [
        _item(id="a", propertyId="1", createdAt="2026-06-13T01:00:00Z"),
        _item(id="b", propertyId="2", createdAt="2026-06-13T05:00:00Z"),
        _item(id="c", propertyId="3", **{"property.allowBrokerSharing": "FALSE"}),
    ]
    out = select_postable(items, limit=10)
    ids = [p["property_id"] for p in out]
    assert ids == ["eb-2", "eb-1"]  # newest first, NG excluded
    assert select_postable(items, limit=1)[0]["property_id"] == "eb-2"


def test_select_postable_excludes_posted():
    items = [
        _item(id="a", propertyId="1", createdAt="2026-06-13T01:00:00Z"),
        _item(id="b", propertyId="2", createdAt="2026-06-13T05:00:00Z"),
    ]
    out = select_postable(items, limit=10, exclude_ids={"eb-2"})
    ids = [p["property_id"] for p in out]
    assert ids == ["eb-1"]  # eb-2 already posted -> skipped
    # limit applies after exclusion: still returns the next fresh one
    assert select_postable(items, limit=1, exclude_ids={"eb-2"})[0]["property_id"] == "eb-1"
