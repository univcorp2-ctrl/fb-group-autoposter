"""Configuration for the Group Property Collector role (役割3).

A self-contained role inside the parent project: reads posts from the Facebook
groups the account belongs to and builds a property database. READ-ONLY — it
never posts. Its own profile/.env, anchored to THIS package so it works from any
working directory. No dependency on the other roles.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _anchor(path: Path) -> Path:
    return path if path.is_absolute() else (ROOT / path)


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name!r} must be an integer, got: {raw!r}") from None


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    headless: bool
    profile_dir: Path
    browser_user_agent: str
    max_posts_per_group: int
    telegram_bot_token: str
    telegram_chat_id: str
    notion_token: str
    notion_database_id: str
    data_dir: Path
    db_path: Path
    sources: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> Settings:
        if env_file is None:
            env_file = ROOT / ".env"
        load_dotenv(env_file)
        settings = cls(
            headless=_bool("HEADLESS", False),
            profile_dir=_anchor(Path(os.getenv("COLLECTOR_PROFILE_DIR", "profiles/collector"))),
            browser_user_agent=os.getenv("BROWSER_USER_AGENT", DEFAULT_UA),
            max_posts_per_group=_int("MAX_POSTS_PER_GROUP", 30),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            notion_token=os.getenv("NOTION_TOKEN", ""),
            notion_database_id=os.getenv("NOTION_COLLECTED_DATABASE_ID", ""),
            data_dir=_anchor(Path(os.getenv("DATA_DIR", "data"))),
            db_path=_anchor(Path(os.getenv("DB_PATH", "data/collected.db"))),
            sources=load_sources(),
        )
        settings = replace(settings, data_dir=_anchor(settings.data_dir), db_path=_anchor(settings.db_path))
        settings.ensure_dirs()
        return settings

    def ensure_dirs(self) -> None:
        for path in [self.profile_dir, self.data_dir, self.db_path.parent, ROOT / "logs"]:
            path.mkdir(parents=True, exist_ok=True)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def notion_enabled(self) -> bool:
        return bool(self.notion_token and self.notion_database_id)


def load_sources(path: str | Path | None = None) -> list[dict]:
    """Load the list of FB groups to collect from (collector/sources.yaml).

    Each entry: {id, name, feed_url}. Returns [] when the file is absent so the
    role degrades gracefully instead of crashing.
    """
    p = _anchor(Path(path)) if path else (ROOT / "sources.yaml")
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    groups = data.get("groups", [])
    return [g for g in groups if isinstance(g, dict) and g.get("enabled", True)]
