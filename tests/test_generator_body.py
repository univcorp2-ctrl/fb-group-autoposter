from __future__ import annotations

from types import SimpleNamespace

from src.generator import (
    INVEST_PREFIX,
    build_hashtags,
    build_investment_pitch,
    fallback_body,
    generate_variants,
)

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


def test_investment_pitch_has_lender_cashflow_and_payoff():
    pitch = build_investment_pitch(PROP)  # 1.2億 / 6.5%
    assert INVEST_PREFIX in pitch
    assert "想定融資" in pitch and "想定キャッシュフロー" in pitch and "想定売却益" in pitch
    assert "万円" in pitch
    assert "想定・概算" in pitch  # clearly framed as an estimate, not a promise
    # No forbidden / guarantee wording.
    for w in ("保証", "絶対", "確実"):
        assert w not in pitch


def test_investment_pitch_empty_without_price_or_yield():
    assert build_investment_pitch(dict(PROP, price="", yield_pct="")) == ""


def test_fallback_body_includes_investment_simulation():
    body = fallback_body(PROP, GROUP)
    assert INVEST_PREFIX in body
    assert "想定融資" in body


def test_generated_post_always_includes_line_and_community_links():
    # Regression: every post MUST carry the LINE official-account link and the
    # community-invite link (they live in `signature`, appended after link
    # stripping). This guards against the duplication/strip bug ever silently
    # dropping them again, even when allow_links is false.
    signature = (
        "━━━\n"
        "📲 未公開物件をLINEで配信中\n"
        "👉 https://lin.ee/8u8OJTSL\n"
        "👥 コミュニティ\n"
        "👉 https://www.facebook.com/groups/2217518449046952/\n"
        "━━━"
    )
    group = dict(GROUP, signature=signature, allow_links=False)
    settings = SimpleNamespace(anthropic_api_key="")  # force fallback path
    batch = generate_variants(PROP, [group], settings)
    body = batch.variants[0]["body"]
    assert "https://lin.ee/8u8OJTSL" in body, "LINE link missing from post"
    assert "https://www.facebook.com/groups/2217518449046952/" in body, "community invite missing"
    # Property's own external URL is still stripped (allow_links false).
    assert "estate-board.com" not in body
    assert len(body) <= group["max_chars"]
