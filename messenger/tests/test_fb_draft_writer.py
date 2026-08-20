import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src import fb_draft_writer


def test_find_composer_scrolls_real_editor_into_view_before_use() -> None:
    composer = SimpleNamespace(
        count=AsyncMock(return_value=1),
        scroll_into_view_if_needed=AsyncMock(),
        is_visible=AsyncMock(return_value=True),
    )
    page = SimpleNamespace(locator=lambda _selector: SimpleNamespace(first=composer))

    selected = asyncio.run(fb_draft_writer._find_composer(page))

    assert selected is composer
    composer.scroll_into_view_if_needed.assert_awaited_once_with(timeout=10_000)
    composer.is_visible.assert_awaited_once_with()


def test_draft_writer_has_no_send_or_enter_path() -> None:
    source = inspect.getsource(fb_draft_writer.write_draft_no_send)
    assert "keyboard.press" not in source
    assert "send_button" not in source
    assert ".press(" not in source
