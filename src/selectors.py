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
        'div[role="button"]:has-text("Write something")',
        'div[role="button"]:has-text("Create post")',
        'div[role="button"]:has-text("Start discussion")',
        'div[aria-label*="作成"]',
        'div[aria-label*="Create"]',
    ],
    "composer_textbox": [
        'div[role="dialog"] div[role="textbox"][contenteditable="true"]',
        'div[role="dialog"] div[contenteditable="true"]',
        'div[aria-label="投稿を作成"] div[role="textbox"][contenteditable="true"]',
        'div[role="textbox"][contenteditable="true"]',
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
    ],
}


def selectors_for(action: str) -> list[str]:
    values = SELECTORS.get(action, [])
    if not values:
        raise KeyError(f"no selectors registered for {action}")
    return values
