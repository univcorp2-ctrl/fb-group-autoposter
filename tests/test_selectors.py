from src.selectors import SELECTORS


def test_selector_groups_not_empty():
    required = ["logged_in_markers", "open_composer", "composer_textbox", "post_button", "file_input"]
    for key in required:
        assert key in SELECTORS
        assert len(SELECTORS[key]) >= 2
