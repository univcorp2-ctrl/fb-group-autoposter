import json

import pytest

from src.property_evidence import lookup_property


def catalog(tmp_path, extra=()):
    path = tmp_path / 'properties.json'
    rows = [{'propertyId': '2866', 'property.label': '池袋 Marietta',
             'property.cityLabel': '東京都豊島区', 'property.price': 215000000,
             'publicationScope': 'USER'}, *extra]
    path.write_text(json.dumps({'items': rows}, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.mark.parametrize('incoming', [
    '池袋Mariettaの資料をください',
    '池袋 Ｍａｒｉｅｔｔａの概要書を送ってください',
    '物件ID: 2866 の資料をください',
    '物件ＩＤ：２８６６の資料をください',
])
def test_explicit_identity_outside_legacy_regions(tmp_path, incoming):
    result = lookup_property(incoming, catalog(tmp_path))
    assert result.matched
    assert result.property_id == '2866'
    assert result.price_jpy == 215000000
    assert result.sharing_cleared is False


def test_duplicate_names_are_ambiguous(tmp_path):
    duplicate = {'propertyId': '999', 'property.label': '池袋 Marietta',
                 'property.price': 215000000}
    result = lookup_property('池袋Mariettaの資料をください', catalog(tmp_path, [duplicate]))
    assert not result.matched
    assert result.ambiguous


@pytest.mark.parametrize('incoming', [
    '池袋Marietta 32億円の資料をください',
    '物件ID: 28660 の資料をください',
    '2866万円の物件資料をください',
    '池袋の資料をください',
])
def test_conflicting_or_insufficient_identity_does_not_match(tmp_path, incoming):
    assert not lookup_property(incoming, catalog(tmp_path)).matched


def test_conflicting_id_and_name_are_not_silently_resolved(tmp_path):
    other = {'propertyId': '999', 'property.label': '仙台グリーンハイツ',
             'property.price': 100000000}
    result = lookup_property('物件ID: 999 池袋Mariettaの資料をください', catalog(tmp_path, [other]))
    assert not result.matched

