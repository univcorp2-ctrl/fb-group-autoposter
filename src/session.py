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
    # Skip Chromium lock/socket files that can't be copied and aren't needed.
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore_volatile)
    backups = sorted(backup_root.glob("backup_*"), key=lambda p: p.name, reverse=True)
    for old in backups[keep:]:
        shutil.rmtree(old, ignore_errors=True)
    return dst


# Chromium runtime files that lock or are recreated on launch — never copy them.
_VOLATILE = {"SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"}


def _ignore_volatile(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in _VOLATILE}


def latest_backup(profile_dir: str | Path) -> Path | None:
    """Most recent healthy profile backup, or None if there are none."""
    root = Path(profile_dir).parent
    if not root.exists():
        return None
    backups = sorted(root.glob("backup_*"), key=lambda p: p.name, reverse=True)
    return backups[0] if backups else None


def restore_profile(profile_dir: str | Path, backup: str | Path | None = None) -> Path | None:
    """Restore the profile from a backup (latest if not given).

    Recovery fallback for an expired/corrupted session: copy a known-good
    profile snapshot back over the live profile dir. Must be called when no
    browser is using the profile (between posting attempts). Returns the backup
    used, or None when there is nothing to restore from.
    """
    dst = Path(profile_dir)
    src = Path(backup) if backup is not None else latest_backup(profile_dir)
    if src is None or not src.exists():
        return None
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore_volatile)
    return src


def login_required_message() -> str:
    return "Facebookセッション切れまたはcheckpoint検知。scripts/login_once.pyで手動再ログインしてください。"
