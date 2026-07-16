from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_groups


def check_playwright_browser() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)
            return executable.exists(), str(executable)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def check_sqlite(path: Path) -> tuple[bool, str]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA quick_check")
        return True, str(path)
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    settings = Settings.load()
    groups = load_groups()
    browser_ok, browser_detail = check_playwright_browser()
    db_ok, db_detail = check_sqlite(settings.db_path)
    source_ok = settings.estateboard_source.is_file()
    profile_on_drive = str(settings.profile_dir).lower().startswith("g:\\")

    result = {
        "python": sys.executable,
        "playwright_browser": {"ok": browser_ok, "detail": browser_detail},
        "estateboard_source": {"ok": source_ok, "path": str(settings.estateboard_source)},
        "estateboard_drive_root": {
            "ok": settings.estateboard_drive_root.is_dir(),
            "path": str(settings.estateboard_drive_root),
        },
        "profile": {
            "ok": settings.profile_dir.is_dir() and not profile_on_drive,
            "path": str(settings.profile_dir),
            "inside_google_drive": profile_on_drive,
        },
        "sqlite": {"ok": db_ok, "detail": db_detail},
        "enabled_groups": len(groups),
        "mode": {"dry_run": settings.dry_run, "auto_approve": settings.auto_approve},
        "secrets": {
            "anthropic_configured": bool(settings.anthropic_api_key),
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    failures: list[str] = []
    if not browser_ok:
        failures.append("Playwright Chromium is missing")
    if not source_ok:
        failures.append("EstateBoard JSON source is missing")
    if profile_on_drive:
        failures.append("Facebook profile is still inside Google Drive; move it to LOCALAPPDATA")
    if not db_ok:
        failures.append("SQLite posting history is not writable")
    if not groups:
        failures.append("No enabled Facebook groups")

    if failures:
        print("\nPRECHECK FAILED:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nPRECHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
