from __future__ import annotations

import pytest

from scripts.open_analytics_dashboard import (
    DEFAULT_DASHBOARD_URL,
    DashboardLinks,
    load_links,
)


def test_default_dashboard_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ANALYTICS_DASHBOARD_URL",
        "ESTATEBOARD_URL",
        "ANALYTICS_HEALTH_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    links = load_links()
    assert links.dashboard == DEFAULT_DASHBOARD_URL
    assert links.dashboard.endswith("/facebook-analytics/")


def test_custom_dashboard_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ANALYTICS_DASHBOARD_URL",
        "https://example.test/analytics/",
    )
    links = load_links()
    assert isinstance(links, DashboardLinks)
    assert links.dashboard == "https://example.test/analytics/"


def test_rejects_insecure_remote_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ANALYTICS_DASHBOARD_URL",
        "http://example.test/analytics/",
    )
    with pytest.raises(ValueError):
        load_links()


def test_allows_localhost_for_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "ANALYTICS_DASHBOARD_URL",
        "http://localhost:8788/facebook-analytics/",
    )
    links = load_links()
    assert links.dashboard == "http://localhost:8788/facebook-analytics/"


def test_readme_links_shared_analytics_surfaces() -> None:
    readme = (
        __import__("pathlib")
        .Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("README.md")
        .read_text(encoding="utf-8")
    )
    for required in (
        "Facebook投稿分析",
        "https://estateboard.pages.dev/facebook-analytics/",
        "https://github.com/univcorp2-ctrl/EstateBoard",
        "https://github.com/univcorp2-ctrl/fb-group-autoposter",
        "ANALYTICS_SYNC_ENABLED=true",
        "open-facebook-analytics.cmd",
    ):
        assert required in readme
