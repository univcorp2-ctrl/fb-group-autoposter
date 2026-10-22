"""Read-only Facebook session preflight for the configured browser backend."""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from urllib.request import urlopen
from pathlib import Path
from typing import Any

from config import load_groups
from src.browser_runtime import BrowserContract, build_launch_kwargs
from src.circuits import CircuitManager
from src.queue_db import QueueDB
from src.session import classify_challenge, is_logged_in

ROOT = Path(__file__).resolve().parents[1]


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


async def _extension_preflight(settings: Any, database: QueueDB, circuits: CircuitManager, environment: str) -> dict[str, Any]:
    groups = load_groups()
    if not groups:
        return {"ok": False, "reason": "no_enabled_groups", "challenge": None, "cleared": 0}
    if os.getenv('FB_POST_TRANSPORT') == 'authenticated_cdp':
        from src.authenticated_post_transport import run_authenticated_task
        task_id = 'session-cdp-' + uuid.uuid4().hex[:12]
        task = {'task_id':task_id, 'group_url':groups[0]['post_url'], 'body':'',
                'images':[], 'allow_images':False, 'action':'probe'}
        result = await run_authenticated_task(task, ROOT/'data'/'extension_tasks'/(task_id+'.json'), timeout=60)
        healthy = result.get('status') == 'session_ok'
        cleared = circuits.record_successful_preflight(environment, actor='preflight') if healthy else 0
        return {'ok':healthy, 'reason':'healthy' if healthy else 'not_logged_in',
                'challenge':None, 'cleared':cleared, 'backend':'authenticated_cdp', 'detail':result}
    # Transport health is not login health. Do not create a doomed probe or
    # claim the Facebook session is expired when the MV3 worker is silent.
    try:
        bridge_port = int(os.getenv("FB_EXTENSION_BRIDGE_PORT", "8766"))
        with urlopen(f"http://127.0.0.1:{bridge_port}/health", timeout=3) as response:
            bridge = json.load(response)
        if not bridge.get("extension_polling"):
            return {"ok": False, "reason": "extension_not_polling", "challenge": None,
                    "cleared": 0, "backend": "extension",
                    "poll_age_seconds": bridge.get("extension_poll_age_seconds")}
    except (OSError, ValueError, TimeoutError) as error:
        return {"ok": False, "reason": "extension_bridge_unreachable",
                "challenge": None, "cleared": 0, "backend": "extension",
                "error": type(error).__name__}
    task_dir = Path(os.getenv("FB_EXTENSION_TASK_DIR", str(ROOT / "data" / "extension_tasks")))
    task_dir.mkdir(parents=True, exist_ok=True)
    task_id = f"session-probe-{uuid.uuid4().hex[:12]}"
    task_path = task_dir / f"{task_id}.json"
    group = groups[0]
    timeout = max(90, int(getattr(settings, "page_hard_timeout", 60)) + 30)
    _atomic_json(task_path, {
        "task_id": task_id,
        "status": "pending",
        "created_at_epoch": time.time(),
        "expires_at_epoch": time.time() + timeout,
        "group_id": str(group["id"]),
        "group_url": str(group["post_url"]),
        "body": "",
        "images": [],
        "image_root": "",
        "allow_images": False,
        "action": "probe",
    })
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            current = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            await asyncio.sleep(1)
            continue
        if current.get("status") == "finished":
            result = current.get("result") or {}
            status = str(result.get("status") or "")
            if status == "session_ok":
                cleared = circuits.record_successful_preflight(environment, actor="preflight")
                return {"ok": True, "reason": "healthy", "challenge": None, "cleared": cleared, "backend": "extension"}
            if status == "session_expired":
                return {"ok": False, "reason": "not_logged_in", "challenge": None, "cleared": 0, "backend": "extension"}
            return {"ok": False, "reason": "extension_probe_failed", "challenge": None, "cleared": 0, "backend": "extension", "error": str(result.get("error") or status)}
        await asyncio.sleep(1)
    return {"ok": False, "reason": "extension_probe_timeout", "challenge": None, "cleared": 0, "backend": "extension"}


async def run_session_preflight(settings: Any, db: QueueDB | None = None) -> dict[str, Any]:
    database = db or QueueDB(settings.db_path)
    circuits = CircuitManager(database)
    environment = str(getattr(settings, "runtime_environment", "default") or "default")

    if getattr(settings, "browser_backend", "playwright") == "extension":
        return await _extension_preflight(settings, database, circuits, environment)

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        contract = BrowserContract.from_settings(settings)
        launch_kwargs = build_launch_kwargs(contract)
        launch_kwargs["timeout"] = int(getattr(settings, "page_hard_timeout", 60)) * 1000
        context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(
                "https://www.facebook.com/",
                wait_until="domcontentloaded",
                timeout=int(getattr(settings, "page_hard_timeout", 60)) * 1000,
            )
            await page.wait_for_timeout(2500)

            challenge = await classify_challenge(page)
            logged_in = await is_logged_in(page)
            if challenge:
                return {"ok": False, "reason": "challenge", "challenge": challenge, "cleared": 0}
            if not logged_in:
                return {"ok": False, "reason": "not_logged_in", "challenge": None, "cleared": 0}

            cleared = circuits.record_successful_preflight(environment, actor="preflight")
            return {"ok": True, "reason": "healthy", "challenge": None, "cleared": cleared}
        finally:
            await context.close()
