from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.group_rules import validate_group_policy

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
    return int(raw)


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    claude_model: str
    claude_vision_model: str
    telegram_bot_token: str
    telegram_chat_id: str
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
        )
        settings.ensure_dirs()
        return settings

    def ensure_dirs(self) -> None:
        for path in [self.profile_dir, self.inbox_dir, self.db_path.parent, Path("logs"), Path("screenshots")]:
            path.mkdir(parents=True, exist_ok=True)

    def validate_runtime(self, *, require_external: bool = True) -> None:
        missing: list[str] = []
        if require_external:
            if not self.anthropic_api_key:
                missing.append("ANTHROPIC_API_KEY")
            if not self.telegram_bot_token:
                missing.append("TELEGRAM_BOT_TOKEN")
            if not self.telegram_chat_id:
                missing.append("TELEGRAM_CHAT_ID")
        if self.min_interval_min > self.max_interval_min:
            raise ValueError("MIN_INTERVAL_MIN must be <= MAX_INTERVAL_MIN")
        if self.max_posts_per_day < 1:
            raise ValueError("MAX_POSTS_PER_DAY must be positive")
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
        validate_group_policy(group)
    return enabled
