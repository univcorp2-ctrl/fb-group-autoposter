"""Export local posting history to the EstateBoard analytics API.

This module is deliberately additive: it reads the existing jobs.db without
changing the posting pipeline or its safety guards. The server-side API is
idempotent, so the whole history can be resent safely on every scheduled run.
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests
import yaml
from dotenv import load_dotenv


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AnalyticsConfig:
    enabled: bool
    base_url: str
    token: str
    db_path: Path
    groups_path: Path
    timeout_seconds: float = 30.0

    @property
    def posts_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/analytics/posts"

    @property
    def metrics_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/analytics/metrics"


def load_config(env_file: str | Path = ".env") -> AnalyticsConfig:
    load_dotenv(env_file)
    return AnalyticsConfig(
        enabled=os.getenv("ANALYTICS_SYNC_ENABLED", "false").lower() in TRUE_VALUES,
        base_url=os.getenv("ANALYTICS_BASE_URL", "https://estateboard.pages.dev").strip(),
        token=os.getenv("ANALYTICS_INGEST_TOKEN", "").strip(),
        db_path=Path(os.getenv("DB_PATH", "data/jobs.db")),
        groups_path=Path(os.getenv("GROUPS_PATH", "groups.yaml")),
        timeout_seconds=float(os.getenv("ANALYTICS_HTTP_TIMEOUT", "30")),
    )


def validate_config(config: AnalyticsConfig) -> None:
    if not config.enabled:
        raise RuntimeError("analytics sync is disabled (ANALYTICS_SYNC_ENABLED=false)")
    if not config.token:
        raise RuntimeError("ANALYTICS_INGEST_TOKEN is required")
    if not config.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise RuntimeError("ANALYTICS_BASE_URL must use HTTPS outside local development")
    if not config.db_path.exists():
        raise FileNotFoundError(config.db_path)


def load_group_catalog(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(item["id"]): item for item in raw.get("groups", []) if item.get("id")}


def read_posting_history(db_path: Path) -> list[dict[str, Any]]:
    query = """
        SELECT
          j.job_id, j.property_id, j.payload_json, j.created_at AS job_created_at,
          j.updated_at AS job_updated_at, j.status AS job_status,
          t.group_id, t.body, t.status, t.attempts, t.last_error,
          t.posted_at, t.permalink
        FROM jobs j
        JOIN job_targets t ON t.job_id = j.job_id
        ORDER BY COALESCE(t.posted_at, j.updated_at), t.id
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query).fetchall()]


def _property_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(row.get("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {
        "external_id": str(row["property_id"]),
        "title": str(payload.get("title") or payload.get("label") or row["property_id"]),
        "source_url": str(payload.get("url") or payload.get("detail_url") or ""),
        "raw": payload,
    }


def build_post_payload(
    row: dict[str, Any], group_catalog: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    group_id = str(row["group_id"])
    group = group_catalog.get(group_id, {})
    event_time = row.get("posted_at") or row.get("job_updated_at") or row.get("job_created_at")
    return {
        "idempotency_key": f"post:{row['job_id']}:{group_id}",
        "job_id": str(row["job_id"]),
        "run_id": f"job:{row['job_id']}",
        "run_status": str(row.get("job_status") or "completed"),
        "property": _property_payload(row),
        "group": {
            "external_id": group_id,
            "name": str(group.get("name") or group_id),
            "url": str(group.get("post_url") or f"https://www.facebook.com/groups/{group_id}"),
        },
        "status": str(row["status"]),
        "posted_at": event_time,
        "post_url": str(row.get("permalink") or ""),
        "body_excerpt": str(row.get("body") or "")[:2000],
        "attempts": int(row.get("attempts") or 0),
        "error_detail": str(row.get("last_error") or "")[:2000],
    }


class AnalyticsClient:
    def __init__(self, config: AnalyticsConfig, session: requests.Session | None = None):
        self.config = config
        self.session = session or requests.Session()

    def send_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self.config.posts_url, payload)

    def send_metrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(self.config.metrics_url, payload)

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Idempotency-Key": str(payload.get("idempotency_key") or ""),
                "User-Agent": "fb-group-autoposter/analytics-sync",
            },
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("error") or "analytics API rejected the event")
        return data


def sync_history(
    config: AnalyticsConfig,
    *,
    rows: Iterable[dict[str, Any]] | None = None,
    client: AnalyticsClient | None = None,
) -> dict[str, int]:
    validate_config(config)
    catalog = load_group_catalog(config.groups_path)
    records = list(rows) if rows is not None else read_posting_history(config.db_path)
    api = client or AnalyticsClient(config)
    summary = {"total": len(records), "sent": 0, "failed": 0}
    for row in records:
        try:
            api.send_post(build_post_payload(row, catalog))
            summary["sent"] += 1
        except Exception:  # noqa: BLE001 - keep syncing independent rows
            summary["failed"] += 1
    return summary
