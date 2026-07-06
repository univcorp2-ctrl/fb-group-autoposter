"""Open the shared EstateBoard Facebook analytics dashboard.

This is the canonical entry point from the Facebook posting repository. It
keeps the live dashboard URL configurable without duplicating the dashboard
implementation in this repository.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass

from dotenv import load_dotenv


DEFAULT_DASHBOARD_URL = "https://estateboard.pages.dev/facebook-analytics/"
DEFAULT_ESTATEBOARD_URL = "https://estateboard.pages.dev/"
DEFAULT_HEALTH_URL = "https://estateboard.pages.dev/api/analytics/health"


@dataclass(frozen=True)
class DashboardLinks:
    dashboard: str
    estateboard: str
    health: str


def load_links() -> DashboardLinks:
    load_dotenv()
    dashboard = os.getenv("ANALYTICS_DASHBOARD_URL", DEFAULT_DASHBOARD_URL).strip()
    estateboard = os.getenv("ESTATEBOARD_URL", DEFAULT_ESTATEBOARD_URL).strip()
    health = os.getenv("ANALYTICS_HEALTH_URL", DEFAULT_HEALTH_URL).strip()
    for name, value in {
        "ANALYTICS_DASHBOARD_URL": dashboard,
        "ESTATEBOARD_URL": estateboard,
        "ANALYTICS_HEALTH_URL": health,
    }.items():
        if not value.startswith(
            ("https://", "http://localhost", "http://127.0.0.1")
        ):
            raise ValueError(
                f"{name} must be an HTTPS URL outside local development"
            )
    return DashboardLinks(
        dashboard=dashboard,
        estateboard=estateboard,
        health=health,
    )


def check_url(url: str, timeout: float = 10.0) -> tuple[bool, int | None, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "fb-group-autoposter/dashboard-launcher",
            "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return True, response.status, response.geturl()
    except urllib.error.HTTPError as error:
        # The health endpoint may intentionally return 503 until D1 is configured.
        return error.code in {401, 503}, error.code, error.geturl()
    except (urllib.error.URLError, TimeoutError) as error:
        return False, None, str(error)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EstateBoard Facebook投稿分析を開きます"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="URLを開かず接続状態だけ確認",
    )
    parser.add_argument(
        "--target",
        choices=("dashboard", "estateboard", "health"),
        default="dashboard",
        help="開く画面",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        links = load_links()
    except ValueError as error:
        print(f"設定エラー: {error}", file=sys.stderr)
        return 2

    url = getattr(links, args.target)
    reachable, status, _detail = check_url(url)
    status_text = str(status) if status is not None else "接続不可"
    print(f"{args.target}: {url}")
    print(f"status: {status_text}")

    if args.status:
        return 0 if reachable else 1

    if not webbrowser.open(url, new=2):
        print(
            "ブラウザを自動起動できませんでした。"
            f"次のURLを開いてください: {url}"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
