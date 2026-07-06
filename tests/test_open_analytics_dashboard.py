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
