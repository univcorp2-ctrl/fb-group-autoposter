"""Attach Messenger to the externally owned authenticated Chrome session.

This module never launches a browser and never closes the external browser,
context, or page. The central Executor is the single Chrome process owner.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

MAX_ENDPOINT_FILE_BYTES = 4096
MAX_VERSION_RESPONSE_BYTES = 64 * 1024
CONNECT_TIMEOUT_MS = 15_000


class AuthenticatedProfileUnavailable(RuntimeError):
    """The required authenticated Default profile cannot be attached."""


class AuthenticatedProfileModeMismatch(AuthenticatedProfileUnavailable):
    """The existing authenticated Chrome is not in the requested display mode."""


@dataclass(frozen=True)
class BrowserAttachment:
    context: Any
    actual_mode: str


def read_loopback_endpoint(user_data_dir: Path) -> str:
    """Return a loopback HTTP endpoint without retaining the private WS path."""
    endpoint_file = Path(user_data_dir) / "DevToolsActivePort"
    try:
        raw = endpoint_file.read_bytes()
    except OSError as exc:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable") from exc
    if not raw or len(raw) > MAX_ENDPOINT_FILE_BYTES:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    try:
        lines = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip()]
        port = int(lines[0])
        socket_path = lines[1]
    except (UnicodeDecodeError, ValueError, IndexError) as exc:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable") from exc
    if not 1 <= port <= 65_535 or not socket_path.startswith("/devtools/browser/"):
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    return f"http://127.0.0.1:{port}"


def browser_mode_from_version(payload: dict[str, Any]) -> str:
    product = f"{payload.get('Browser', '')} {payload.get('User-Agent', '')}"
    if "Chrome" not in product:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    return "headless" if "HeadlessChrome" in product else "visible"


def probe_browser_mode(endpoint: str, timeout_seconds: float = 2.0) -> str:
    request = Request(f"{endpoint}/json/version", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - loopback only
            raw = response.read(MAX_VERSION_RESPONSE_BYTES + 1)
    except OSError as exc:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable") from exc
    if len(raw) > MAX_VERSION_RESPONSE_BYTES:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable") from exc
    if not isinstance(payload, dict):
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    return browser_mode_from_version(payload)


async def attach_authenticated_context(
    playwright: Any,
    settings: Any,
    *,
    mode_probe: Callable[[str], str] = probe_browser_mode,
) -> BrowserAttachment:
    if str(settings.chrome_profile_directory) != "Default":
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    profile_dir = Path(settings.profile_dir)
    if not profile_dir.is_dir():
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")

    endpoint = read_loopback_endpoint(profile_dir)
    actual_mode = mode_probe(endpoint)
    requested_mode = str(settings.browser_display_mode)
    if requested_mode not in {"auto", "headless", "visible"}:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")
    if requested_mode != "auto" and actual_mode != requested_mode:
        raise AuthenticatedProfileModeMismatch("authenticated_profile_mode_mismatch")

    try:
        external_browser = await playwright.chromium.connect_over_cdp(
            endpoint, timeout=CONNECT_TIMEOUT_MS
        )
    except Exception as exc:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable") from exc
    contexts = list(external_browser.contexts)
    if not contexts:
        raise AuthenticatedProfileUnavailable("authenticated_profile_unavailable")

    # Do not call external_browser.close(), context.close(), or page.close().
    # Stopping the Playwright client disconnects transport without terminating
    # the Chrome process that belongs to the central Executor.
    return BrowserAttachment(context=contexts[0], actual_mode=actual_mode)


async def select_messenger_page(context: Any) -> Any:
    """Reuse a Messenger tab without navigating unrelated user tabs away."""
    for page in context.pages:
        try:
            host = (urlparse(str(page.url)).hostname or "").lower()
        except ValueError:
            continue
        if host == "messenger.com" or host.endswith(".messenger.com"):
            return page
    return await context.new_page()
