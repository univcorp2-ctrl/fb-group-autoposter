"""Read-only browser compatibility contract for the existing posting runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrowserContract:
    """Identity and display settings that runtime recovery must preserve."""

    headless: bool
    user_data_dir: Path
    user_agent: str
    viewport: dict[str, int]

    @classmethod
    def from_settings(cls, settings: Any) -> "BrowserContract":
        return cls(
            headless=False,
            user_data_dir=Path(settings.profile_dir),
            user_agent=settings.browser_user_agent,
            viewport={"width": 1366, "height": 900},
        )
