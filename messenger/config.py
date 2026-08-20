"""Configuration for the Messenger role (役割2).

A self-contained role inside the parent project. Completely independent of the
posting role (役割1): its own profile dir, its own .env, anchored to THIS package
so it works no matter the current working directory. Nothing here touches the
autoposter's files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
AUTHENTICATED_CHROME_USER_DATA_DIR = Path(r"C:\AI-Agent\chrome-profile-authenticated")
AUTHENTICATED_CHROME_PROFILE_DIRECTORY = "Default"
ALLOWED_BROWSER_DISPLAY_MODES = {"auto", "headless", "visible"}


def _anchor(path: Path) -> Path:
    """Resolve a relative path against THIS package dir (not the CWD), so the role
    behaves the same whether launched from the repo root or its own folder."""
    return path if path.is_absolute() else (ROOT / path)

def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name!r} must be an integer, got: {raw!r}") from None


@dataclass(frozen=True)
class Settings:
    read_only: bool
    write_draft_to_fb: bool
    headless: bool
    profile_dir: Path
    chrome_profile_directory: str
    browser_display_mode: str
    max_threads_per_run: int
    telegram_bot_token: str
    telegram_chat_id: str
    notion_token: str
    notion_replies_database_id: str
    line_url: str
    community_url: str
    anthropic_api_key: str
    claude_model: str
    data_dir: Path

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> Settings:
        if env_file is None:
            env_file = ROOT / ".env"
        load_dotenv(env_file)
        settings = cls(
            read_only=_bool("READ_ONLY", True),
            write_draft_to_fb=_bool("WRITE_DRAFT_TO_FB", False),
            headless=_bool("HEADLESS", False),
            profile_dir=Path(
                os.getenv("MESSENGER_PROFILE_DIR", str(AUTHENTICATED_CHROME_USER_DATA_DIR))
            ),
            chrome_profile_directory=os.getenv(
                "CHROME_PROFILE_DIRECTORY", AUTHENTICATED_CHROME_PROFILE_DIRECTORY
            ).strip(),
            browser_display_mode=os.getenv("MESSENGER_DISPLAY_MODE", "auto").strip().lower(),
            max_threads_per_run=_int("MAX_THREADS_PER_RUN", 20),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            notion_token=os.getenv("NOTION_TOKEN", ""),
            notion_replies_database_id=os.getenv("NOTION_REPLIES_DATABASE_ID", ""),
            line_url=os.getenv("LINE_URL", ""),
            community_url=os.getenv("COMMUNITY_URL", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
            data_dir=_anchor(Path(os.getenv("DATA_DIR", "data"))),
        )
        # Anchor the profile dir to THIS package so the role works regardless of
        # the current working directory (it lives under the parent project now).
        settings = replace(settings, profile_dir=_anchor(settings.profile_dir))
        settings.validate_browser_policy()
        settings.ensure_dirs()
        return settings

    def validate_browser_policy(self) -> None:
        configured = os.path.normcase(os.path.abspath(self.profile_dir))
        required = os.path.normcase(os.path.abspath(AUTHENTICATED_CHROME_USER_DATA_DIR))
        if configured != required or self.chrome_profile_directory != AUTHENTICATED_CHROME_PROFILE_DIRECTORY:
            raise ValueError("authenticated_profile_unavailable")
        if self.browser_display_mode not in ALLOWED_BROWSER_DISPLAY_MODES:
            raise ValueError(
                "MESSENGER_DISPLAY_MODE must be one of: auto, headless, visible"
            )

    def ensure_dirs(self) -> None:
        # The browser profile is externally owned by the central Executor. Never
        # create, copy, or mutate it as a side effect of loading Messenger config.
        for path in [self.data_dir, ROOT / "logs"]:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_token and self.notion_replies_database_id)
