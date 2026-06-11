from src.property_schema import normalize_property, property_id_from_payload, validate_property


def test_normalize_property_fills_defaults_and_lists():
    prop = normalize_property({"title": "A", "highlights": "駅近,RC", "images": "a.jpg"})
    validate_property(prop)
    assert prop["title"] == "A"
    assert prop["price"] == "記載なし"
    assert prop["highlights"] == ["駅近", "RC"]
    assert prop["images"] == ["a.jpg"]


def test_property_id_is_stable_for_same_payload():
    payload = {"title": "A", "price": "1000万円"}
    assert property_id_from_payload(payload) == property_id_from_payload(payload)


def test_normalize_keeps_existing_property_id():
    prop = normalize_property({"property_id": "fixed", "title": "A"})
    assert prop["property_id"] == "fixed"
