from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.group_rules import validate_group

ROOT = Path(__file__).resolve().parent


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
    anthropic_api_key: str
    claude_model: str
    claude_vision_model: str
    telegram_bot_token: str
    telegram_chat_id: str
    notion_token: str
    notion_database_id: str
    dry_run: bool
    auto_approve: bool
    auto_approve_skip_degraded: bool
    humanize: bool
    min_interval_min: int
    max_interval_min: int
    max_posts_per_day: int
    min_same_group_hours: int
    max_groups_per_browser: int
    retry_max: int
    page_hard_timeout: int
    approval_timeout_hours: int
    heartbeat_timeout_min: int
    group_fail_threshold: int
    cooldown_hours: int
    profile_dir: Path
    inbox_dir: Path
    db_path: Path
    profile_backup_keep: int
    browser_backend: str
    browser_user_agent: str
    estateboard_source: Path

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> "Settings":
        if env_file is None:
            env_file = ROOT / ".env"
        load_dotenv(env_file)
        settings = cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6"),
            claude_vision_model=os.getenv("CLAUDE_VISION_MODEL", "claude-sonnet-4-6"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            notion_token=os.getenv("NOTION_TOKEN", ""),
            notion_database_id=os.getenv("NOTION_DATABASE_ID", ""),
            dry_run=_bool("DRY_RUN", True),
            auto_approve=_bool("AUTO_APPROVE", False),
            auto_approve_skip_degraded=_bool("AUTO_APPROVE_SKIP_DEGRADED", True),
            humanize=_bool("HUMANIZE", True),
            min_interval_min=_int("MIN_INTERVAL_MIN", 15),
            max_interval_min=_int("MAX_INTERVAL_MIN", 35),
            max_posts_per_day=_int("MAX_POSTS_PER_DAY", 10),
            min_same_group_hours=_int("MIN_SAME_GROUP_HOURS", 20),
            max_groups_per_browser=_int("MAX_GROUPS_PER_BROWSER", 5),
            retry_max=_int("RETRY_MAX", 3),
            page_hard_timeout=_int("PAGE_HARD_TIMEOUT", 120),
            approval_timeout_hours=_int("APPROVAL_TIMEOUT_HOURS", 24),
            heartbeat_timeout_min=_int("HEARTBEAT_TIMEOUT_MIN", 30),
            group_fail_threshold=_int("GROUP_FAIL_THRESHOLD", 3),
            cooldown_hours=_int("COOLDOWN_HOURS", 24),
            profile_dir=Path(os.getenv("PROFILE_DIR", "profiles/main")),
            inbox_dir=Path(os.getenv("INBOX_DIR", "data/inbox")),
            db_path=Path(os.getenv("DB_PATH", "data/jobs.db")),
            profile_backup_keep=_int("PROFILE_BACKUP_KEEP", 7),
            browser_backend=os.getenv("BROWSER_BACKEND", "playwright"),
            # A stable, realistic UA reduces checkpoint triggers. A CHANGING UA is
            # a top trigger, so this must stay constant across runs (see .env.example).
            browser_user_agent=os.getenv(
                "BROWSER_USER_AGENT",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            ),
            # Latest EstateBoard broker-OK export; re-read at post time by the
            # freshness gate to confirm a property is still live before posting.
            estateboard_source=Path(
                os.getenv(
                    "ESTATEBOARD_SOURCE",
                    r"G:\マイドライブ\AI_Agents\github\repos\EstateBoard\output\received\properties.json",
                )
            ),
        )
        settings.ensure_dirs()
        return settings

    def ensure_dirs(self) -> None:
        for path in [self.profile_dir, self.inbox_dir, self.db_path.parent, Path("logs"), Path("screenshots")]:
            path.mkdir(parents=True, exist_ok=True)

    def validate_runtime(self, *, require_external: bool = True) -> None:
        missing: list[str] = []
        if require_external:
            # ANTHROPIC_API_KEY is optional: the generator falls back to template
            # (degraded) bodies when it is absent. Telegram is only required when
            # manual approval is in use (i.e. AUTO_APPROVE is disabled).
            if not self.auto_approve:
                if not self.telegram_bot_token:
                    missing.append("TELEGRAM_BOT_TOKEN")
                if not self.telegram_chat_id:
                    missing.append("TELEGRAM_CHAT_ID")
        if self.min_interval_min > self.max_interval_min:
            raise ValueError("MIN_INTERVAL_MIN must be <= MAX_INTERVAL_MIN")
        numeric_positive = {
            "MAX_POSTS_PER_DAY": self.max_posts_per_day,
            "MIN_SAME_GROUP_HOURS": self.min_same_group_hours,
            "MAX_GROUPS_PER_BROWSER": self.max_groups_per_browser,
            "RETRY_MAX": self.retry_max,
            "PAGE_HARD_TIMEOUT": self.page_hard_timeout,
            "APPROVAL_TIMEOUT_HOURS": self.approval_timeout_hours,
            "HEARTBEAT_TIMEOUT_MIN": self.heartbeat_timeout_min,
            "GROUP_FAIL_THRESHOLD": self.group_fail_threshold,
            "COOLDOWN_HOURS": self.cooldown_hours,
            "PROFILE_BACKUP_KEEP": self.profile_backup_keep,
        }
        for key, value in numeric_positive.items():
            if value <= 0:
                raise ValueError(f"{key} must be positive")
        if self.browser_backend not in {"playwright", "adspower"}:
            raise ValueError("BROWSER_BACKEND must be playwright or adspower")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variables: {joined}")


def load_groups(path: str | Path = "groups.yaml") -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    groups = data.get("groups", [])
    if not isinstance(groups, list):
        raise ValueError("groups.yaml must contain a top-level 'groups' list")
    enabled = [g for g in groups if g.get("enabled", True)]
    for group in enabled:
        validate_group(group)
    return enabled
