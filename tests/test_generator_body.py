from __future__ import annotations

from src.generator import build_hashtags, fallback_body

GROUP = {
    "id": "g1",
    "name": "g",
    "post_url": "https://www.facebook.com/groups/g1/",
    "tone": "プロフェッショナル",
    "max_chars": 1200,
    "active_hours": [7, 23],
    "allow_links": False,
    "forbidden": ["保証", "絶対", "確実"],
    "signature": "",
    "contact": "📩 お問い合わせ\nbukken511+ag@gmail.com",
}

PROP = {
    "property_id": "eb-1",
    "title": "新宿区一棟収益マンション",
    "price": "1億2,000万円",
    "yield_pct": "6.50%",
    "location": "東京都新宿区高田馬場3-24-4",
    "access": "JR山手線 高田馬場駅 徒歩9分",
    "structure": "RC造 14階建",
    "land_area": "131㎡",
    "building_area": "635㎡",
    "year_built": "2026年2月",
    "highlights": ["一棟マンション", "RC造", "駅近", "所有権", "分かれ"],
    "url": "https://estate-board.com/x/1",
    "images": [],
    "raw_text": "",
}


def test_build_hashtags_includes_type_and_area():
    tags = build_hashtags(PROP)
    assert "#不動産投資" in tags
    assert "#一棟マンション" in tags
    assert "#東京都" in tags
    assert "#新宿区" in tags
    assert len(tags) <= 6


def test_fallback_body_has_contact_and_hashtags_and_no_link():
    body = fallback_body(PROP, GROUP)
    assert "bukken511+ag@gmail.com" in body  # contact appended
    assert "#不動産投資" in body  # hashtags appended
    assert "https://" not in body  # allow_links=False strips URLs
    assert "🏢" in body and "💰" in body  # emoji formatting
    assert len(body) <= GROUP["max_chars"]


def test_fallback_body_removes_forbidden_words():
    prop = dict(PROP, title="絶対に儲かる物件")
    body = fallback_body(prop, GROUP)
    assert "絶対" not in body
