"""Verify 10 NEW Facebook group-thread posts on the existing EstateBoard Web.

Repo/Windows Task Scheduler owns this monitor. It neither creates posts nor
counts uncertain attempts, and never calls the ChatGPT scheduling service.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from config import Settings

BASELINE_JST = "2026-10-10"
TARGET = 10
SITE = "https://estateboard.pages.dev"
PRIVATE_TOKENS = Path(r"G:\マイドライブ\AI_Agents\Private\estateboard_analytics_tokens.json")
OUTPUT = Path(r"G:\マイドライブ\AI_Agents\Private\FBGroupAutoposter\post10_status.json")
THREAD = re.compile(r"https://(?:www\.)?facebook\.com/groups/(\d+)/posts/(\d+)(?:[/?#]|$)")


def get_json(url: str, token: str = "") -> dict:
    headers = {"User-Agent": "fb-post10-web-monitor/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def safe_write(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def load_local(db_path: Path) -> dict[str, dict]:
    baseline = datetime.fromisoformat(BASELINE_JST).replace(tzinfo=ZoneInfo("Asia/Tokyo")).astimezone(timezone.utc)
    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT j.property_id,t.group_id,t.status,t.posted_at,t.permalink
               FROM job_targets t JOIN jobs j ON j.job_id=t.job_id
               WHERE t.status='posted' AND t.permalink IS NOT NULL AND t.permalink != ''
               ORDER BY t.posted_at"""
        ).fetchall()
    verified = {}
    for row in rows:
        link = str(row["permalink"] or "")
        match = THREAD.match(link)
        if not match or match[1] != str(row["group_id"]) or "comment_id=" in link:
            continue
        try:
            stamped = datetime.fromisoformat(str(row["posted_at"] or "").replace("Z", "+00:00"))
            if stamped.tzinfo is None:
                stamped = stamped.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamped < baseline:
            continue
        verified[link] = {
            "property_id": row["property_id"],
            "group_id": row["group_id"],
            "posted_at": str(row["posted_at"]),
        }
    return verified


def main() -> int:
    settings = Settings.load()
    local = load_local(settings.db_path)
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "baseline_jst": BASELINE_JST,
        "target": TARGET,
        "confirmed_new_threads": len(local),
        "analytics_reflected": 0,
        "property_web_reflected": 0,
        "complete": False,
        "links": [{"url": url, **info} for url, info in sorted(local.items())],
        "analytics_url": SITE + "/facebook-analytics/",
        "property_web_url": SITE + "/data.json",
    }
    try:
        health = get_json(SITE + "/api/analytics/health")
        payload["analytics_healthy"] = bool(health.get("ok"))
        token = str(json.loads(PRIVATE_TOKENS.read_text(encoding="utf-8"))["ANALYTICS_DASHBOARD_TOKEN"])
        api = get_json(SITE + f"/api/analytics/posts?status=posted&start={BASELINE_JST}&limit=500", token)
        api_urls = {str(row.get("post_url")) for row in api.get("posts", []) if row.get("post_url")}
        payload["analytics_reflected"] = len(set(local) & api_urls)
        with urllib.request.urlopen(SITE + "/data.json", timeout=20) as response:
            published = response.read().decode("utf-8")
        payload["property_web_reflected"] = sum(url in published for url in local)
        with urllib.request.urlopen(SITE + "/facebook-analytics/", timeout=20) as response:
            payload["dashboard_http_status"] = response.status
        payload["complete"] = bool(
            len(local) >= TARGET
            and payload["analytics_reflected"] >= TARGET
            and payload["property_web_reflected"] >= TARGET
            and payload["analytics_healthy"]
            and payload["dashboard_http_status"] == 200
        )
    except Exception as exc:
        payload["web_error"] = f"{type(exc).__name__}: {exc}"
    safe_write(OUTPUT, payload)
    print(json.dumps(
        {k: payload.get(k) for k in
         ("confirmed_new_threads", "analytics_reflected", "property_web_reflected",
          "analytics_healthy", "dashboard_http_status", "complete", "web_error")},
        ensure_ascii=False,
    ))
    return 0 if payload["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
