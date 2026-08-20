from pathlib import Path

from scripts import run_draft_daemon

MESSENGER_ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (MESSENGER_ROOT / relative).read_text(encoding="utf-8")


def test_scan_uses_authenticated_attachment_not_owned_browser() -> None:
    source = _source("scripts/run_once.py")
    assert "attach_authenticated_context" in source
    assert "launch_persistent_context" not in source
    assert "viewport=" not in source
    assert "user_agent=" not in source
    assert "ctx.close()" not in source


def test_daemon_does_not_open_or_hold_a_separate_visible_browser() -> None:
    source = _source("scripts/run_draft_daemon.py")
    assert "launch_persistent_context" not in source
    assert "viewport=" not in source
    assert "user_agent=" not in source
    assert "ctx.close()" not in source
    assert "_hold_reply_screen" not in source
    assert "headless=False" not in source


def test_retry_delay_is_bounded_and_increases() -> None:
    assert run_draft_daemon._retry_delay_seconds(1, 1800) == 30
    assert run_draft_daemon._retry_delay_seconds(2, 1800) == 60
    assert run_draft_daemon._retry_delay_seconds(5, 1800) == 300
    assert run_draft_daemon._retry_delay_seconds(99, 120) == 120


def test_all_messenger_entrypoints_reject_owned_or_guest_like_browser_launches() -> None:
    entrypoints = (
        "scripts/login.py",
        "scripts/run_once.py",
        "scripts/run_draft_daemon.py",
        "scripts/run_visible_drafts.py",
        "scripts/send_one_reply.py",
        "scripts/send_one_playwright_reply.py",
    )
    forbidden = (
        "launch_persistent_context",
        "viewport=",
        "user_agent=",
        "Profile 1",
        "profiles/messenger",
        "context.close()",
        "ctx.close()",
    )
    for relative in entrypoints:
        source = _source(relative)
        for value in forbidden:
            assert value not in source, f"{relative} contains unsafe browser route: {value}"


def test_sendkeys_profile_helper_is_removed() -> None:
    assert not (MESSENGER_ROOT / "scripts" / "place_work_profile_drafts.ps1").exists()


def test_example_config_documents_only_authenticated_default_profile() -> None:
    source = _source(".env.example")
    assert r"MESSENGER_PROFILE_DIR=C:\AI-Agent\chrome-profile-authenticated" in source
    assert "CHROME_PROFILE_DIRECTORY=Default" in source
    assert "MESSENGER_DISPLAY_MODE=auto" in source
    assert "profiles/messenger" not in source
    assert "BROWSER_USER_AGENT=" not in source


def test_readme_has_no_legacy_local_profile_login_instructions() -> None:
    source = _source("README_ja.md")
    assert "profiles/messenger" not in source
    assert "専用 Playwright" not in source
    assert "C:\\AI-Agent\\chrome-profile-authenticated" in source

