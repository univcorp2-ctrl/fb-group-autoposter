from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.selectors import SELECTORS


async def is_logged_in(page: Any) -> bool:
    url = page.url.lower()
    if "login" in url or "checkpoint" in url or "/recover" in url:
        return False
    for selector in SELECTORS["logged_in_markers"]:
        try:
            if await page.query_selector(selector):
                return True
        except Exception:
            continue
    return False


def backup_profile(profile_dir: str | Path, keep: int = 7) -> Path | None:
    src = Path(profile_dir)
    if not src.exists():
        return None
    backup_root = src.parent
    stamp = datetime.now(UTC).strftime("backup_%Y%m%d_%H%M%S")
    dst = backup_root / stamp
    shutil.copytree(src, dst, dirs_exist_ok=True)
    backups = sorted(backup_root.glob("backup_*"), key=lambda p: p.name, reverse=True)
    for old in backups[keep:]:
        shutil.rmtree(old, ignore_errors=True)
    return dst


def login_required_message() -> str:
    return "Facebookセッション切れまたはcheckpoint検知。scripts/login_once.pyで手動再ログインしてください。"
