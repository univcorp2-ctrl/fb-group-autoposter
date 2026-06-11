SELECTORS: dict[str, list[str]] = {
    "logged_in_markers": [
        'a[aria-label="Home"]',
        'a[aria-label="ホーム"]',
        'div[role="navigation"]',
        'div[aria-label="Account"]',
        'div[aria-label="アカウント"]',
    ],
    "open_composer": [
        'div[role="button"]:has-text("投稿を作成")',
        'div[role="button"]:has-text("Write something")',
        'div[role="button"]:has-text("Create post")',
        'div[aria-label*="作成"]',
        'div[aria-label*="Create"]',
        'div[role="main"] div[role="button"] >> nth=0',
    ],
    "composer_textbox": [
        'div[role="textbox"][contenteditable="true"]',
        'div[aria-label*="投稿"][contenteditable="true"]',
        'div[aria-label*="Write"][contenteditable="true"]',
        'div[aria-label*="作成"][contenteditable="true"]',
    ],
    "post_button": [
        'div[aria-label="投稿"][role="button"]',
        'div[aria-label="Post"][role="button"]',
        'button:has-text("投稿")',
        'button:has-text("Post")',
        'div[role="button"]:has-text("投稿")',
        'div[role="button"]:has-text("Post")',
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
    ],
}


def selectors_for(action: str) -> list[str]:
    values = SELECTORS.get(action, [])
    if not values:
        raise KeyError(f"no selectors registered for {action}")
    return values
