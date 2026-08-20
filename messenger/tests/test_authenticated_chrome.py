import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config import Settings

AUTHENTICATED_ROOT = Path(r"C:\AI-Agent\chrome-profile-authenticated")


def _clear_browser_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MESSENGER_PROFILE_DIR",
        "CHROME_PROFILE_DIRECTORY",
        "MESSENGER_DISPLAY_MODE",
        "BROWSER_USER_AGENT",
        "DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_default_to_authenticated_default_without_creating_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_browser_env(monkeypatch)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    settings = Settings.load(empty_env)

    assert settings.profile_dir == AUTHENTICATED_ROOT
    assert settings.chrome_profile_directory == "Default"
    assert settings.browser_display_mode == "auto"
    assert not hasattr(settings, "browser_user_agent")
    assert not (tmp_path / "profiles" / "messenger").exists()


@pytest.mark.parametrize(
    ("profile_dir", "profile_directory"),
    [
        ("profiles/messenger", "Default"),
        (r"C:\AI-Agent\chrome-profile-authenticated", "Profile 1"),
        (r"C:\Users\Public\Temp\Chrome", "Default"),
    ],
)
def test_settings_reject_guest_like_or_non_default_profiles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    profile_dir: str,
    profile_directory: str,
) -> None:
    _clear_browser_env(monkeypatch)
    monkeypatch.setenv("MESSENGER_PROFILE_DIR", profile_dir)
    monkeypatch.setenv("CHROME_PROFILE_DIRECTORY", profile_directory)
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="authenticated_profile_unavailable"):
        Settings.load(empty_env)


def test_settings_reject_unknown_display_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_browser_env(monkeypatch)
    monkeypatch.setenv("MESSENGER_DISPLAY_MODE", "guest")
    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="MESSENGER_DISPLAY_MODE"):
        Settings.load(empty_env)


def _browser_module():
    return importlib.import_module("src.authenticated_chrome")


def test_reads_only_a_loopback_endpoint_from_devtools_active_port(tmp_path: Path) -> None:
    browser = _browser_module()
    (tmp_path / "DevToolsActivePort").write_text(
        "53123\n/devtools/browser/private-endpoint\n", encoding="ascii"
    )

    assert browser.read_loopback_endpoint(tmp_path) == "http://127.0.0.1:53123"


@pytest.mark.parametrize(
    "contents",
    [
        "",
        "not-a-port\n/devtools/browser/x\n",
        "70000\n/devtools/browser/x\n",
        "53123\n/not-a-browser-endpoint\n",
        "53123\n",
    ],
)
def test_rejects_stale_or_malformed_devtools_endpoint(
    tmp_path: Path, contents: str
) -> None:
    browser = _browser_module()
    (tmp_path / "DevToolsActivePort").write_text(contents, encoding="ascii")

    with pytest.raises(browser.AuthenticatedProfileUnavailable):
        browser.read_loopback_endpoint(tmp_path)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"Browser": "Chrome/151.0", "User-Agent": "Mozilla/5.0 Chrome/151.0"}, "visible"),
        (
            {"Browser": "Chrome/151.0", "User-Agent": "Mozilla/5.0 HeadlessChrome/151.0"},
            "headless",
        ),
    ],
)
def test_detects_existing_authenticated_browser_mode(payload: dict, expected: str) -> None:
    browser = _browser_module()
    assert browser.browser_mode_from_version(payload) == expected


def test_attach_reuses_external_context_without_closing_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    browser = _browser_module()
    settings = SimpleNamespace(
        profile_dir=tmp_path,
        chrome_profile_directory="Default",
        browser_display_mode="auto",
    )
    (tmp_path / "DevToolsActivePort").write_text(
        "53123\n/devtools/browser/private-endpoint\n", encoding="ascii"
    )
    external_context = object()
    external_browser = SimpleNamespace(contexts=[external_context], close=AsyncMock())
    connect = AsyncMock(return_value=external_browser)
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))

    attachment = asyncio.run(
        browser.attach_authenticated_context(
            playwright,
            settings,
            mode_probe=lambda _endpoint: "headless",
        )
    )

    assert attachment.context is external_context
    assert attachment.actual_mode == "headless"
    connect.assert_awaited_once_with("http://127.0.0.1:53123", timeout=15_000)
    external_browser.close.assert_not_awaited()


def test_attach_fails_closed_on_display_mode_mismatch(tmp_path: Path) -> None:
    browser = _browser_module()
    settings = SimpleNamespace(
        profile_dir=tmp_path,
        chrome_profile_directory="Default",
        browser_display_mode="visible",
    )
    (tmp_path / "DevToolsActivePort").write_text(
        "53123\n/devtools/browser/private-endpoint\n", encoding="ascii"
    )
    connect = AsyncMock()
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))

    with pytest.raises(browser.AuthenticatedProfileModeMismatch):
        asyncio.run(
            browser.attach_authenticated_context(
                playwright,
                settings,
                mode_probe=lambda _endpoint: "headless",
            )
        )

    connect.assert_not_awaited()


def test_select_messenger_page_reuses_matching_tab() -> None:
    browser = _browser_module()
    other = SimpleNamespace(url="https://example.com/")
    messenger = SimpleNamespace(url="https://www.messenger.com/t/123")
    context = SimpleNamespace(pages=[other, messenger], new_page=AsyncMock())

    selected = asyncio.run(browser.select_messenger_page(context))

    assert selected is messenger
    context.new_page.assert_not_awaited()


def test_select_messenger_page_creates_tab_without_replacing_user_page() -> None:
    browser = _browser_module()
    created = SimpleNamespace(url="about:blank")
    context = SimpleNamespace(
        pages=[SimpleNamespace(url="https://example.com/")],
        new_page=AsyncMock(return_value=created),
    )

    selected = asyncio.run(browser.select_messenger_page(context))

    assert selected is created
    context.new_page.assert_awaited_once_with()

