"""Login-state detection for messenger.com / facebook.com/messages."""

from __future__ import annotations

from typing import Any

# When logged in, the messenger inbox shows a conversation list grid and a
# "新しいメッセージ" / "Chats" navigation. When logged out, the URL contains
# login/checkpoint or a login form is shown.
_LOGGED_IN_MARKERS = (
    '[aria-label="チャット"]',
    '[aria-label="Chats"]',
    'div[role="grid"]',
    'a[href^="/t/"]',
)


async def is_logged_in(page: Any) -> bool:
    url = page.url.lower()
    if "login" in url or "checkpoint" in url or "/recover" in url:
        return False
    for selector in _LOGGED_IN_MARKERS:
        try:
            if await page.query_selector(selector):
                return True
        except Exception:
            continue
    return False


def login_required_message() -> str:
    return (
        "Messengerのセッション切れ/未ログインを検知しました。"
        "`python scripts/login.py` を実行してブラウザで手動ログインしてください。"
    )
