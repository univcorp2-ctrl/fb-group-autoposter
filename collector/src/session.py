"""Login-state helpers for the collector role.

Ground truth for being logged in is the c_user cookie (the FB user id), not DOM
markers — the same lesson learned in the messenger role.
"""

from __future__ import annotations

from typing import Any


async def c_user(ctx: Any) -> str | None:
    for c in await ctx.cookies():
        if c.get("name") == "c_user" and c.get("value"):
            return c["value"]
    return None


async def is_logged_in(ctx: Any) -> bool:
    return await c_user(ctx) is not None


def login_required_message() -> str:
    return (
        "コレクター用のFacebookセッションが未ログインです。"
        "`python collector/scripts/login.py` を実行してログインしてください。"
    )
