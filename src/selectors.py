from __future__ import annotations

from typing import Any


class SelectorMissing(RuntimeError):
    """No reviewed, visible element was available for a write boundary."""


class SelectorAmbiguous(RuntimeError):
    """More than one reviewed, visible element was available for an action."""


SELECTORS: dict[str, list[str]] = {
    "logged_in_markers": [
        'a[aria-label="Home"]',
        'a[aria-label="ホーム"]',
        'div[role="navigation"]',
        'div[aria-label="Account"]',
        'div[aria-label="アカウント"]',
    ],
    "open_composer": [
        'div[role="button"]:has-text("テキストを入力")',
        'div[role="button"]:has-text("投稿を作成")',
        'div[role="button"]:has-text("ディスカッションを書く")',
        'div[role="button"]:has-text("Write something")',
        'div[role="button"]:has-text("Create post")',
        'div[role="button"]:has-text("Start discussion")',
    ],
    "composer_textbox": [
        'div[role="dialog"] div[role="textbox"][contenteditable="true"]',
        'div[role="dialog"] div[contenteditable="true"]',
        'div[aria-label="投稿を作成"] div[role="textbox"][contenteditable="true"]',
    ],
    "post_button": [
        'div[role="dialog"] div[aria-label="投稿"][role="button"]',
        'div[role="dialog"] div[aria-label="Post"][role="button"]',
        'div[role="dialog"] div[role="button"]:has-text("投稿")',
        'div[role="dialog"] div[role="button"]:has-text("Post")',
        'div[aria-label="投稿"][role="button"]',
        'div[aria-label="Post"][role="button"]',
    ],
    "file_input": [
        'input[type="file"][accept*="image"]',
        'input[type="file"]',
    ],
    "posting_block_markers": [
        ':text("投稿できません")',
        ':text("You can’t post")',
        ':text("temporarily blocked")',
        ':text("一時的にブロック")',
    ],
    "checkpoint_markers": [
        ':text("checkpoint")',
        ':text("本人確認")',
        ':text("security check")',
        ':text("アカウントを保護")',
        ':text("Confirm your identity")',
    ],
    "captcha_markers": [
        'iframe[src*="recaptcha"]',
        'iframe[title*="recaptcha"]',
        'iframe[src*="captcha"]',
        'div[class*="captcha"]',
        ':text("ロボットではありません")',
        ':text("セキュリティチェック")',
    ],
    "two_factor_markers": [
        'input[name="approvals_code"]',
        ':text("ログインコード")',
        ':text("認証コード")',
        ':text("two-factor")',
        ':text("2段階認証")',
    ],
}


def selectors_for(action: str) -> list[str]:
    values = SELECTORS.get(action, [])
    if not values:
        raise KeyError(f"no selectors registered for {action}")
    return values


async def exactly_one_visible(page: Any, action: str) -> Any:
    """Return the one reviewed visible action target, or fail closed.

    A CSS selector union makes the count a count of DOM elements rather than a
    count of selector matches, so one element matching two reviewed variants is
    still one candidate.  This helper only reads locator state; callers decide
    whether the returned locator may be clicked or typed into.
    """

    selectors = selectors_for(action)
    union = ", ".join(selectors)
    locator = page.locator(union)
    count = await locator.count()
    visible: list[Any] = []
    for index in range(count):
        candidate = locator.nth(index) if hasattr(locator, "nth") else locator.first
        is_visible = getattr(candidate, "is_visible", None)
        if is_visible is None or await is_visible():
            visible.append(candidate)
    if not visible:
        raise SelectorMissing(f"selector_missing:{action}")
    if len(visible) != 1:
        raise SelectorAmbiguous(f"selector_ambiguous:{action}")
    return visible[0]


async def is_actionable(locator: Any) -> bool:
    """Return whether a reviewed control can safely receive the final click."""
    enabled = getattr(locator, "is_enabled", None)
    if enabled is not None and not await enabled():
        return False
    attribute = getattr(locator, "get_attribute", None)
    if attribute is not None:
        disabled = await attribute("aria-disabled")
        if str(disabled).casefold() == "true":
            return False
    return True
