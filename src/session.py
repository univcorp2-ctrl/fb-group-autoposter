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


async def classify_challenge(page: Any) -> str | None:
    """Identify the kind of login challenge on the current page.

    A profile restore can recover a plain expired cookie, but it can NEVER clear
    a checkpoint / captcha / 2FA challenge — only a human re-login does. Knowing
    the kind lets the caller alert with the right operator action instead of a
    generic "session dead" message. Returns one of "checkpoint", "captcha",
    "two_factor", "login", or None (page looks logged in / no challenge).
    """
    url = page.url.lower()
    if "checkpoint" in url:
        return "checkpoint"
    if "/two_step_verification" in url or "/two_factor" in url or "approvals_code" in url:
        return "two_factor"
    if "/recover" in url or "/login" in url or url.rstrip("/").endswith("facebook.com/login"):
        return "login"
    # DOM markers (page may be on a normal URL but show an inline challenge).
    for kind, key in (("captcha", "captcha_markers"), ("two_factor", "two_factor_markers"), ("checkpoint", "checkpoint_markers")):
        for selector in SELECTORS.get(key, []):
            try:
                if await page.query_selector(selector):
                    return kind
            except Exception:
                continue
    return None


def login_required_message() -> str:
    return "Facebookセッション切れまたはcheckpoint検知。scripts/login_once.pyで手動再ログインしてください。"


# Per-kind operator guidance. A checkpoint/captcha/2FA needs a different human
# action than a plain cookie expiry, so we spell out the cause; all kinds end
# with the same re-login instruction reused from login_required_message().
_CHALLENGE_CAUSE = {
    "checkpoint": "Facebook本人確認 checkpoint を検知しました。",
    "captcha": "Facebook画像認証（captcha）を検知しました。",
    "two_factor": "Facebook2段階認証コードの入力を求められています。",
    "login": "Facebookログイン切れを検知しました。",
}


def challenge_message(kind: str) -> str:
    cause = _CHALLENGE_CAUSE.get(kind, "Facebookセッション要再ログイン。")
    return f"{cause} scripts/login_once.pyで手動再ログインしてください。"
