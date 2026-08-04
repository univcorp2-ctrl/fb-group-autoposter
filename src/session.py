from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.selectors import SELECTORS


def restore_session_boundary(
    profile_dir: str | Path,
    *,
    run_id: str,
    challenge: str | None = None,
    probe_callable: Any | None = None,
    contract: Any | None = None,
) -> Any:
    """Prepare only clone-based ordinary-expiry recovery.

    Challenges are terminal for this boundary: they never copy, restore, probe,
    or promote a profile.  A plain expiry can be probed on a candidate, but the
    returned decision always keeps submission disabled until a later explicit
    preflight clears the relevant circuit.
    """

    from src.browser_runtime import BrowserContract, ProbeResult, prepare_candidate, probe_candidate

    if challenge:
        return ProbeResult(str(challenge), False, True, False)
    if probe_callable is None or contract is None:
        return ProbeResult("manual_profile_recovery_required", False, True, False)
    candidate = prepare_candidate(profile_dir, run_id)
    browser_contract = contract if isinstance(contract, BrowserContract) else BrowserContract.from_settings(contract)
    result = probe_candidate(candidate, probe_callable, contract=browser_contract)
    # An expiry-triggered candidate probe is diagnostic only.  It can never
    # clear the circuit or make this run eligible to submit/promote.
    reason = (
        "candidate_probe_healthy_manual_recovery_required"
        if result.healthy
        else "manual_profile_recovery_required"
    )
    return ProbeResult(reason, False, True, False, result.manifest, result.candidate_binding)


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
    """Deprecated fail-closed legacy API; it never overwrites a live profile."""

    del profile_dir, backup
    return None


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
