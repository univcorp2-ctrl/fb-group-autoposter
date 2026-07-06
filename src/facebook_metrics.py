"""Collect visible engagement counters from confirmed Facebook post URLs."""
from __future__ import annotations

import asyncio
import os
import random
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.analytics_export import AnalyticsClient, AnalyticsConfig, load_config, validate_config


_NUMBER = r"([0-9][0-9,.]*(?:万|千|[kKmM])?)"
_PATTERNS = {
    "reactions": [
        rf"(?:リアクション|いいね[！!]?|reactions?|likes?)\s*[:：]?\s*{_NUMBER}",
        rf"{_NUMBER}\s*(?:件の|件)\s*(?:リアクション|いいね[！!]?)",
        rf"{_NUMBER}\s*(?:reactions?|likes?)",
    ],
    "comments": [
        rf"(?:コメント|comments?)\s*[:：]?\s*{_NUMBER}",
        rf"{_NUMBER}\s*(?:件の|件)\s*コメント",
        rf"{_NUMBER}\s*comments?",
    ],
    "shares": [
        rf"(?:シェア|shares?)\s*[:：]?\s*{_NUMBER}",
        rf"{_NUMBER}\s*(?:件の|件)\s*シェア",
        rf"{_NUMBER}\s*shares?",
    ],
    "views": [
        rf"(?:表示|再生|views?)\s*[:：]?\s*{_NUMBER}",
        rf"{_NUMBER}\s*(?:回の|回)\s*(?:表示|再生)",
        rf"{_NUMBER}\s*views?",
    ],
}


def parse_compact_number(value: str) -> int:
    cleaned = value.replace(",", "").strip()
    multiplier = 1
    if cleaned.lower().endswith("k"):
        multiplier, cleaned = 1_000, cleaned[:-1]
    elif cleaned.lower().endswith("m"):
        multiplier, cleaned = 1_000_000, cleaned[:-1]
    elif cleaned.endswith("万"):
        multiplier, cleaned = 10_000, cleaned[:-1]
    elif cleaned.endswith("千"):
        multiplier, cleaned = 1_000, cleaned[:-1]
    try:
        return max(0, int(float(cleaned) * multiplier))
    except ValueError:
        return 0


def extract_metric_counts(text: str) -> dict[str, int]:
    normalized = " ".join((text or "").split())
    result: dict[str, int] = {}
    for metric, patterns in _PATTERNS.items():
        values: list[int] = []
        for pattern in patterns:
            values.extend(
                parse_compact_number(match)
                for match in re.findall(pattern, normalized, re.IGNORECASE)
            )
        result[metric] = max(values, default=0)
    return result


def metric_targets(db_path: Path, max_age_days: int, limit: int) -> list[dict[str, Any]]:
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
    query = """
        SELECT j.job_id, t.group_id, t.permalink, t.posted_at
        FROM job_targets t
        JOIN jobs j ON j.job_id=t.job_id
        WHERE t.status='posted' AND t.permalink IS NOT NULL AND t.permalink != ''
          AND COALESCE(t.posted_at, j.updated_at) >= ?
        ORDER BY COALESCE(t.posted_at, j.updated_at) DESC
        LIMIT ?
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, (cutoff, limit)).fetchall()]


async def read_visible_metrics(page: Any, url: str) -> tuple[dict[str, int], str]:
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3500)
    if "login" in page.url.lower() or "checkpoint" in page.url.lower():
        raise RuntimeError("Facebook login/checkpoint required")
    article = page.locator('div[role="article"]').first
    text = (
        await article.inner_text(timeout=15_000)
        if await article.count()
        else await page.inner_text("body")
    )
    labels = await page.locator("[aria-label]").evaluate_all(
        "els => els.slice(0, 500).map(el => el.getAttribute('aria-label') || '').filter(Boolean)"
    )
    combined = f"{text}\n" + "\n".join(labels)
    return extract_metric_counts(combined), combined[:4000]


async def collect_and_send_metrics(
    config: AnalyticsConfig,
    *,
    profile_dir: Path,
    max_posts: int = 30,
    max_age_days: int = 180,
    headless: bool = False,
    client: AnalyticsClient | None = None,
) -> dict[str, int]:
    validate_config(config)
    targets = metric_targets(config.db_path, max_age_days, max_posts)
    api = client or AnalyticsClient(config)
    summary = {"targets": len(targets), "sent": 0, "failed": 0}
    if not targets:
        return summary

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=headless,
            viewport={"width": 1366, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            for target in targets:
                try:
                    counts, raw = await read_visible_metrics(page, target["permalink"])
                    observed_at = datetime.now(UTC).isoformat()
                    payload = {
                        "idempotency_key": (
                            f"metrics:{target['job_id']}:{target['group_id']}:{observed_at[:13]}"
                        ),
                        "post_key": f"{target['job_id']}:{target['group_id']}",
                        "post_url": target["permalink"],
                        "observed_at": observed_at,
                        **counts,
                        "raw": {"visible_text": raw},
                    }
                    api.send_metrics(payload)
                    summary["sent"] += 1
                except Exception:  # noqa: BLE001 - one inaccessible post must not stop the sweep
                    summary["failed"] += 1
                await asyncio.sleep(random.uniform(3.0, 7.0))
        finally:
            await context.close()
    return summary


def metrics_runtime_options() -> tuple[Path, int, int, bool]:
    load_dotenv()
    profile = Path(os.getenv("PROFILE_DIR", "profiles/main"))
    max_posts = max(1, int(os.getenv("ANALYTICS_METRICS_MAX_POSTS", "30")))
    max_age = max(1, int(os.getenv("ANALYTICS_METRICS_MAX_AGE_DAYS", "180")))
    headless = os.getenv("ANALYTICS_METRICS_HEADLESS", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return profile, max_posts, max_age, headless


async def run_from_environment() -> dict[str, int]:
    config = load_config()
    profile, max_posts, max_age, headless = metrics_runtime_options()
    return await collect_and_send_metrics(
        config,
        profile_dir=profile,
        max_posts=max_posts,
        max_age_days=max_age,
        headless=headless,
    )
