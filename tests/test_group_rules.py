import pytest

from src.group_rules import apply_group_rules, strip_links, validate_group_policy


def test_strip_links_removes_urls():
    assert strip_links("詳細 https://example.com です") == "詳細  です"


def test_apply_group_rules_signature_forbidden_and_max_chars():
    group = {"allow_links": False, "forbidden": ["絶対"], "signature": "署名", "max_chars": 30}
    body = apply_group_rules("絶対おすすめ https://example.com 長い本文長い本文長い本文", group)
    assert "絶対" not in body
    assert "https://" not in body
    assert body.endswith("署名")
    assert len(body) <= 30


def test_validate_group_policy_rejects_bad_hours():
    with pytest.raises(ValueError):
        validate_group_policy({"id": "g", "name": "n", "post_url": "u", "tone": "t", "max_chars": 1, "active_hours": [25, 1]})
