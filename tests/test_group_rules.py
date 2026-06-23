import pytest

from src.group_rules import apply_group_rules, append_signature_once, strip_links, validate_group


def group(**overrides):
    base = {
        "id": "123",
        "name": "Group",
        "post_url": "https://www.facebook.com/groups/123/",
        "tone": "丁寧",
        "max_chars": 120,
        "active_hours": [9, 22],
        "allow_links": False,
        "allow_images": True,
        "signature": "署名",
        "forbidden": ["絶対", "保証"],
    }
    base.update(overrides)
    return base


def test_strip_links_removes_http_and_https():
    out, removed = strip_links("詳細 https://example.com と http://example.jp")
    assert removed is True
    assert "http" not in out


def test_apply_group_rules_is_idempotent_and_keeps_signature_urls():
    # Regression: applying the rules twice must NOT duplicate the signature nor
    # strip the signature's own URLs (LINE / community invite), even when
    # allow_links is false. This was the cause of the duplicated, URL-stripped
    # signature seen in real posts.
    sig = (
        "━━━\n"
        "📲 未公開物件を配信中\n"
        "👉 https://lin.ee/8u8OJTSL\n"
        "👥 コミュニティ\n"
        "👉 https://www.facebook.com/groups/2217518449046952/\n"
        "━━━"
    )
    g = group(signature=sig, max_chars=1200)
    once = apply_group_rules("物件本文 https://example.com/listing", g).body
    twice = apply_group_rules(once, g).body
    assert once == twice, "apply_group_rules must be idempotent"
    # Signature URLs survive (appended after link-stripping); each appears once.
    assert once.count("https://lin.ee/8u8OJTSL") == 1
    assert once.count("https://www.facebook.com/groups/2217518449046952/") == 1
    # The property's own external link is still stripped (allow_links false).
    assert "https://example.com/listing" not in once


def test_apply_group_rules_link_forbidden_signature_and_limit():
    result = apply_group_rules("絶対おすすめ 保証 https://example.com " + "あ" * 200, group())
    assert result.removed_links is True
    assert set(result.removed_forbidden) == {"絶対", "保証"}
    assert len(result.body) <= 120
    assert "署名" in result.body
    assert "http" not in result.body
    assert "絶対" not in result.body
    assert "保証" not in result.body


def test_invite_link_in_signature_survives_allow_links_false():
    # The community-invite link lives in `signature`, which is appended AFTER
    # link-stripping — so it must survive even when allow_links is false, while
    # the property's own URL in the body is still removed.
    invite = "👥 ご参加ください\nhttps://www.facebook.com/groups/2217518449046952/"
    body = "物件 https://example.com/detail/1 のご紹介"
    result = apply_group_rules(body, group(signature=invite, max_chars=300))
    assert "https://www.facebook.com/groups/2217518449046952/" in result.body
    assert "example.com" not in result.body  # body URL stripped
    assert result.removed_links is True


def test_append_signature_once_is_idempotent():
    once = append_signature_once("本文", "署名")
    twice = append_signature_once(once, "署名")
    assert once == twice


def test_validate_group_rejects_bad_url():
    with pytest.raises(ValueError):
        validate_group(group(post_url="https://example.com/groups/123/"))


def test_validate_group_rejects_short_max_chars():
    with pytest.raises(ValueError):
        validate_group(group(max_chars=99))


def test_validate_group_accepts_cross_midnight_hours():
    validate_group(group(active_hours=[22, 7]))
