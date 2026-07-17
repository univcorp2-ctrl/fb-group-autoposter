from src.codex_provider import build_codex_prompt


def test_prompt_contains_property_and_group_rules() -> None:
    prompt = build_codex_prompt(
        {"property_id": "eb-1", "price": "8,800万円"},
        {"id": "group-1", "allow_links": False},
    )
    assert "8,800万円" in prompt
    assert '"allow_links": false' in prompt
    assert "誇大表現" in prompt
