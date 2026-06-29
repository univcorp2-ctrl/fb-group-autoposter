"""Tests for the reply drafter (template path; Claude path is best-effort)."""

from src.drafter import build_draft, build_template_draft


def test_template_includes_name_and_links():
    d = build_template_draft(
        "山田太郎",
        "物件について",
        line_url="https://lin.ee/abc",
        community_url="https://facebook.com/groups/x",
    )
    assert "山田太郎さん" in d
    assert "https://lin.ee/abc" in d
    assert "https://facebook.com/groups/x" in d


def test_template_without_links_omits_link_section():
    d = build_template_draft("佐藤", "こんにちは")
    assert "公式LINE" not in d
    assert "佐藤さん" in d


def test_template_handles_empty_name():
    d = build_template_draft("", "問い合わせ")
    assert "お問い合わせさん" in d


def test_build_draft_falls_back_to_template_without_api_key():
    d = build_draft("田中", "空き家ありますか", line_url="https://lin.ee/z", api_key="")
    assert "田中さん" in d
    assert "下書き" in d  # disclaimer appended
    assert "https://lin.ee/z" in d


def test_build_draft_appends_disclaimer():
    d = build_draft("鈴木", "内見できますか", api_key="")
    assert d.strip().endswith("ご確認ください）")
