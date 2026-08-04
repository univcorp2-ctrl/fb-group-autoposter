"""Offline acceptance contract for the Facebook posting-recovery boundary."""

from __future__ import annotations

import asyncio
import ast
import inspect
import json
import ntpath
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from src.poster import FacebookPoster, PostNotVerified, SessionExpired
from src.queue_db import QueueDB, normalized_body_hash
from src.run_result import OUTCOME_EXIT_CODES, RunResultStore, SCHEMA


ROOT = Path(__file__).resolve().parents[1]
POSTING_TASK_NAMES = frozenset(
    {
        "FBAutoposter-Morning",
        "FBAutoposter-Midday",
        "FBAutoposter-Afternoon",
        "FBAutoposter-Evening",
    }
)
ALLOWED_DAILY_OPERATIONAL_COMMANDS = frozenset({"daily-post"})


def _reachable_posting_modules(
    *, root: Path = ROOT, entry_module: str = "scripts.run_daily"
) -> dict[str, ast.Module]:
    pending = [entry_module]
    discovered: dict[str, ast.Module] = {}
    while pending:
        module = pending.pop()
        if module in discovered:
            continue
        path = root.joinpath(*module.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        discovered[module] = tree
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
            for imported in names:
                if imported.startswith(("src.", "scripts.")):
                    candidate = root.joinpath(*imported.split(".")).with_suffix(".py")
                    if candidate.exists():
                        pending.append(imported)
    return discovered


def _explicit_group_join_findings(modules: dict[str, ast.Module]) -> list[str]:
    findings: list[str] = []
    for tree in modules.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called_name = node.func.id if isinstance(node.func, ast.Name) else ""
                if isinstance(node.func, ast.Attribute) and node.func.attr in {
                    "join_group",
                    "join_facebook_group",
                }:
                    findings.append(node.func.attr)
                if called_name in {"join_group", "join_facebook_group"}:
                    findings.append(called_name)
                locator = _locator_call_clicked_by(node)
                if locator:
                    locator_name, label = locator
                    if _is_join_label(label):
                        findings.append(f"{locator_name}:{label}")
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if _is_group_join_url(node.value):
                    findings.append(node.value)
    return findings


def _locator_call_clicked_by(node: ast.Call) -> tuple[str, str] | None:
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "click":
        return None
    locator = node.func.value
    while isinstance(locator, ast.Attribute) and locator.attr in {"first", "last"}:
        locator = locator.value
    if not isinstance(locator, ast.Call) or not isinstance(locator.func, ast.Attribute):
        return None
    locator_name = locator.func.attr
    if locator_name == "get_by_text" and locator.args:
        label = locator.args[0]
    elif locator_name == "get_by_role":
        label = next((keyword.value for keyword in locator.keywords if keyword.arg == "name"), None)
        if label is None and len(locator.args) > 1:
            label = locator.args[1]
    else:
        return None
    if isinstance(label, ast.Constant) and isinstance(label.value, str):
        return locator_name, label.value
    return None


def _is_join_label(label: str) -> bool:
    normalized = re.sub(r"[\s\-_/]+", "", label).casefold()
    return normalized.startswith("join") or normalized.startswith(("参加", "グループに参加"))


def _is_group_join_url(value: str) -> bool:
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme or parsed.netloc else (value if value.startswith("/") else "")
    return bool(re.fullmatch(r"/groups/(?:[^/?#]+/)?join/?", path, flags=re.IGNORECASE))


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("def run(page):\n    page.get_by_text('参加する').click()\n", "get_by_text:参加する"),
        (
            "def run(page):\n    page.get_by_role('button', name='Join Group').first.click()\n",
            "get_by_role:Join Group",
        ),
    ),
)
def test_reachable_module_closure_finds_normalized_join_locator_clicks(tmp_path, source, expected):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_daily.py").write_text(source, encoding="utf-8")

    with pytest.raises(AssertionError, match=expected):
        assert _explicit_group_join_findings(_reachable_posting_modules(root=tmp_path)) == []


def test_reachable_module_closure_finds_group_id_join_url(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_daily.py").write_text(
        "def run(page):\n    page.goto('https://www.facebook.com/groups/group-1/join')\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="groups/group-1/join"):
        assert _explicit_group_join_findings(_reachable_posting_modules(root=tmp_path)) == []


def _assert_pending_delivery(db: QueueDB, *, event: str) -> None:
    events = db.list_outbox_events()
    assert any(item["event"] == event and item["status"] == "pending" for item in events)


def _installed_daily_actions() -> list[dict[str, str]]:
    installer = ROOT / "scripts" / "install_windows_tasks.ps1"
    escaped_installer = str(installer).replace("'", "''")
    harness = f"""
$ErrorActionPreference = 'Stop'
$captured = @()
function Test-Path {{ param($Path) return $false }}
function python {{ param([Parameter(ValueFromRemainingArguments=$true)]$Remaining) }}
function New-ScheduledTaskAction {{ param($Execute, $Argument, $WorkingDirectory) [pscustomobject]@{{Execute=$Execute; Argument=$Argument; WorkingDirectory=$WorkingDirectory}} }}
function New-ScheduledTaskTrigger {{ param([Parameter(ValueFromRemainingArguments=$true)]$Remaining) [pscustomobject]@{{Delay=''; Repetition=$null}} }}
function New-ScheduledTaskSettingsSet {{ param([Parameter(ValueFromRemainingArguments=$true)]$Remaining) [pscustomobject]@{{}} }}
function Register-ScheduledTask {{ param($TaskName, $Action, $Trigger, $Settings, $Description, [switch]$Force) $script:captured += [pscustomobject]@{{TaskName=$TaskName; Execute=$Action.Execute; Argument=$Action.Argument; WorkingDirectory=$Action.WorkingDirectory; Disabled=$false}} }}
function Disable-ScheduledTask {{ param($TaskName) foreach ($task in $script:captured) {{ if ($task.TaskName -eq $TaskName) {{ $task.Disabled = $true }} }} }}
function Get-ScheduledTask {{ @() }}
. '{escaped_installer}'
$captured | ConvertTo-Json -Compress
"""
    installed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", harness],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    payload = installed.stdout[installed.stdout.index("[") :]
    return json.loads(payload)


def _posting_task_actions(actions: list[dict[str, str]]) -> list[dict[str, str]]:
    return [action for action in actions if action["TaskName"] in POSTING_TASK_NAMES]


def _clicked_attempt(db: QueueDB) -> str:
    db.create_job(
        {"job_id": "job-1", "property_id": "property-1"},
        [{"group_id": "group-1", "body": "body", "source_hash": "source", "generation_fingerprint": "fingerprint"}],
    )
    approval = db.approve_target("job-1", "group-1", source="operator")
    attempt = db.begin_submission(
        "job-1",
        "group-1",
        approval_id=approval["approval_id"],
        source_hash="source",
        body_hash=approval["body_hash"],
        generation_fingerprint="fingerprint",
    )
    db.mark_click_started(attempt["attempt_id"])
    return attempt["attempt_id"]


def _make_verified_poster(tmp_path, monkeypatch, *, notifier, permalink):
    import src.poster as poster_module

    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job(
        {"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}]
    )
    target = db.get_targets(job_id)[0]
    poster = FacebookPoster(
        SimpleNamespace(page_hard_timeout=1),
        db,
        [{"id": "group-1", "post_url": "https://www.facebook.com/groups/group-1"}],
        notifier=notifier,
    )
    poster._user_id = "user-1"

    class FakePage:
        async def goto(self, *_args, **_kwargs):
            return None

        async def wait_for_timeout(self, *_args, **_kwargs):
            return None

    async def noop(*_args, **_kwargs):
        return None

    async def returned_permalink(*_args, **_kwargs):
        return permalink

    monkeypatch.setattr(poster, "_detect_blocking_markers", noop)
    monkeypatch.setattr(poster, "_human_pause", noop)
    monkeypatch.setattr(poster, "_click_first", noop)
    monkeypatch.setattr(poster, "_wait_first", noop)
    monkeypatch.setattr(poster, "_enter_body", noop)
    monkeypatch.setattr(poster, "_attach_images", noop)
    monkeypatch.setattr(poster, "_verify_composer_contains", noop)
    monkeypatch.setattr(poster, "_open_permalink", noop)
    monkeypatch.setattr(poster_module, "is_logged_in", lambda _page: _true())
    monkeypatch.setattr(poster_module, "verify_post_visible", noop)
    monkeypatch.setattr(poster_module, "find_my_post", returned_permalink)
    monkeypatch.setattr(
        poster_module, "save_screenshot", lambda *_args, **_kwargs: _value("shot.png")
    )
    return db, job_id, target, poster, FakePage


@pytest.mark.parametrize(
    "permalink",
    ("", "http://www.facebook.com/groups/group-1/posts/1", "https://example.invalid/post"),
)
def test_invalid_permalink_cannot_confirm_a_submission_attempt(tmp_path, permalink):
    db = QueueDB(tmp_path / "jobs.db")
    attempt_id = _clicked_attempt(db)

    with pytest.raises(ValueError, match="Facebook permalink"):
        db.resolve_submission(attempt_id, outcome="confirmed", permalink=permalink)

    assert db.get_submission_attempt(attempt_id)["state"] == "reconcile_only"
    assert db.get_targets("job-1")[0]["status"] == "uncertain"


def test_submission_attempt_record_accepts_a_captured_https_facebook_permalink(tmp_path):
    db = QueueDB(tmp_path / "jobs.db")
    attempt_id = _clicked_attempt(db)
    permalink = "https://www.facebook.com/groups/group-1/posts/1"

    confirmed = db.resolve_submission(attempt_id, outcome="confirmed", permalink=permalink)

    assert confirmed["state"] == "posted"
    assert db.get_targets("job-1")[0]["permalink"] == permalink

    post_source = inspect.getsource(FacebookPoster._post_one)
    assert "permalink = await find_my_post(" in post_source
    assert "await self._open_permalink(page, permalink)" in post_source


@pytest.mark.parametrize("permalink", ("http://www.facebook.com/groups/group-1/posts/1", "https://example.invalid/post"))
def test_poster_runtime_invalid_permalink_never_records_posted(tmp_path, monkeypatch, permalink):
    import src.poster as poster_module

    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    target = db.get_targets(job_id)[0]
    poster = FacebookPoster(SimpleNamespace(page_hard_timeout=1), db, [{"id": "group-1", "post_url": "https://www.facebook.com/groups/group-1"}])
    poster._user_id = "user-1"

    class FakePage:
        async def goto(self, *_args, **_kwargs):
            return None

        async def wait_for_timeout(self, *_args, **_kwargs):
            return None

    async def noop(*_args, **_kwargs):
        return None

    async def invalid_permalink(*_args, **_kwargs):
        return permalink

    monkeypatch.setattr(poster, "_detect_blocking_markers", noop)
    monkeypatch.setattr(poster, "_human_pause", noop)
    monkeypatch.setattr(poster, "_click_first", noop)
    monkeypatch.setattr(poster, "_wait_first", noop)
    monkeypatch.setattr(poster, "_enter_body", noop)
    monkeypatch.setattr(poster, "_attach_images", noop)
    monkeypatch.setattr(poster, "_verify_composer_contains", noop)
    monkeypatch.setattr(poster, "_open_permalink", noop)
    monkeypatch.setattr(poster_module, "is_logged_in", lambda _page: _true())
    monkeypatch.setattr(poster_module, "verify_post_visible", noop)
    monkeypatch.setattr(poster_module, "find_my_post", invalid_permalink)
    monkeypatch.setattr(poster_module, "save_screenshot", lambda *_args, **_kwargs: _value("shot.png"))

    with pytest.raises(PostNotVerified):
        asyncio.run(
            poster._post_one(
                FakePage(),
                {"job_id": job_id, "property_id": "property-1"},
                target,
                {"id": "group-1", "post_url": "https://www.facebook.com/groups/group-1"},
            )
        )

    assert db.get_targets(job_id)[0]["status"] != "posted"


@pytest.mark.xfail(
    strict=True,
    reason="Task 2 must add named interruption recovery so each state quarantines the existing attempt.",
)
@pytest.mark.parametrize("interruption_state", ("write_started", "clicked_unverified", "unknown"))
def test_named_interruption_states_quarantine_attempts_without_retry(tmp_path, interruption_state):
    db = QueueDB(tmp_path / "jobs.db")
    attempt_id = _clicked_attempt(db)
    before = db.get_submission_attempt(attempt_id)
    assert before["state"] == "submitting"

    recovered = db.recover_interrupted_attempt(attempt_id, state=interruption_state)

    assert recovered["state"] == "reconcile_only"
    assert db.get_targets("job-1")[0]["status"] == "uncertain"
    with pytest.raises(ValueError, match="click boundary permanently prevents a new attempt"):
        db.begin_submission(
            "job-1",
            "group-1",
            approval_id=before["approval_id"],
            source_hash="source",
            body_hash=normalized_body_hash("body"),
            generation_fingerprint="fingerprint",
        )


def test_telegram_and_estateboard_failures_preserve_attempt_truth_and_retry_budget(
    tmp_path, monkeypatch
):
    from scripts import build_group_registry, run_daily, sync_estateboard_status, sync_groups_web
    from src import approval, status_report

    settings = SimpleNamespace(
        db_path=tmp_path / "jobs.db",
        profile_dir=tmp_path / "profile",
        telegram_bot_token="token",
        telegram_chat_id="chat",
    )
    db = QueueDB(settings.db_path)
    attempt_id = _clicked_attempt(db)
    db.resolve_submission(
        attempt_id,
        outcome="confirmed",
        permalink="https://www.facebook.com/groups/group-1/posts/1",
    )
    before = db.get_submission_attempt(attempt_id)
    calls = {"facebook": 0}

    class FailingNotifier:
        enabled = True

        def __init__(self, *_args, **_kwargs):
            pass

        def send_message(self, _message):
            raise RuntimeError("telegram unavailable")

    async def run_once():
        calls["facebook"] += 1

    async def fake_ensure(_settings, _groups, _db, *, run_once, **_kwargs):
        await run_once()
        return {"reason": "completed"}

    monkeypatch.setattr(run_daily.Settings, "load", lambda: settings)
    monkeypatch.setattr(run_daily, "load_groups", lambda: [])
    monkeypatch.setattr(run_daily, "ensure_posted_today", fake_ensure)
    monkeypatch.setattr(run_daily, "run_cycle_grouped", lambda *_args, **_kwargs: run_once())
    monkeypatch.setattr(run_daily, "_clear_session_alert", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(approval, "TelegramApproval", FailingNotifier)
    monkeypatch.setattr(status_report, "build_status_files", lambda *_args, **_kwargs: {"counts": {}})
    monkeypatch.setattr(build_group_registry, "build_registry", lambda: {"summary": {}})
    monkeypatch.setattr(sync_groups_web, "sync_groups_web", lambda: {})
    monkeypatch.setattr(
        sync_estateboard_status,
        "sync_estateboard_status",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("estateboard unavailable")),
    )
    monkeypatch.setattr(run_daily.sys, "argv", ["run_daily.py"])

    run_daily.main()

    after = QueueDB(settings.db_path).get_submission_attempt(attempt_id)
    assert calls["facebook"] == 1
    assert (after["state"], after["reopen_count"]) == (before["state"], before["reopen_count"])
    assert QueueDB(settings.db_path).get_targets("job-1")[0]["status"] == "posted"


def test_verified_post_notification_failure_preserves_posted_truth_and_queues_delivery(
    tmp_path, monkeypatch
):
    class FailingNotifier:
        attempts = 0

        def send_message(self, _message):
            self.attempts += 1
            raise RuntimeError("telegram unavailable")

    notifier = FailingNotifier()
    db, job_id, target, poster, page_type = _make_verified_poster(
        tmp_path,
        monkeypatch,
        notifier=notifier,
        permalink="https://www.facebook.com/groups/group-1/posts/1",
    )

    asyncio.run(
        poster._post_one.__wrapped__(
            poster,
            page_type(),
            {"job_id": job_id, "property_id": "property-1"},
            target,
            {"id": "group-1", "post_url": "https://www.facebook.com/groups/group-1"},
        )
    )

    after = db.get_targets(job_id)[0]
    assert (after["status"], after["attempts"]) == ("posted", 0)
    assert notifier.attempts == 0
    _assert_pending_delivery(db, event="verified_post")


def test_preview_notification_failure_preserves_approval_truth_and_queues_delivery(tmp_path, monkeypatch):
    from src.approval import TelegramApproval

    monkeypatch.chdir(tmp_path)
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    settings = SimpleNamespace(
        telegram_bot_token="token",
        telegram_chat_id="chat",
        auto_approve=False,
        auto_approve_skip_degraded=True,
    )
    notifier = TelegramApproval(settings, db)
    attempts = {"preview": 0}

    def fail_preview(_job_id):
        attempts["preview"] += 1
        raise RuntimeError("telegram unavailable")

    monkeypatch.setattr(notifier, "send_preview", fail_preview)
    notifier.auto_or_send_preview(job_id)

    target = db.get_targets(job_id)[0]
    assert (target["status"], target["attempts"]) == ("pending_approval", 0)
    assert attempts["preview"] == 0
    _assert_pending_delivery(db, event="approval_preview")


def test_challenge_notification_failure_preserves_challenge_stop_and_queues_delivery(
    tmp_path, monkeypatch
):
    from playwright import async_api
    import src.poster as poster_module

    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    job = db.get_job(job_id)
    calls = {"post": 0, "alert": 0}

    class FailingNotifier:
        def alert(self, _message):
            calls["alert"] += 1
            raise RuntimeError("telegram unavailable")

    class FakeContext:
        pages = [object()]

        async def close(self):
            return None

    class FakeChromium:
        async def launch_persistent_context(self, **_kwargs):
            return FakeContext()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakePlaywrightManager:
        async def __aenter__(self):
            return FakePlaywright()

        async def __aexit__(self, *_args):
            return None

    async def stopped_by_challenge(*_args, **_kwargs):
        calls["post"] += 1
        raise SessionExpired("challenge")

    settings = SimpleNamespace(
        browser_backend="playwright",
        profile_dir=tmp_path / "profile",
        browser_user_agent="ua",
        page_hard_timeout=1,
        max_posts_per_day=5,
        max_groups_per_browser=5,
        group_fail_threshold=3,
    )
    poster = FacebookPoster(
        settings,
        db,
        [{"id": "group-1", "post_url": "https://www.facebook.com/groups/group-1", "active_hours": [0, 24]}],
        notifier=FailingNotifier(),
    )
    monkeypatch.setattr(async_api, "async_playwright", FakePlaywrightManager)
    monkeypatch.setattr(poster_module, "cookie_user_id", lambda _context: _value("user-1"))
    monkeypatch.setattr(poster, "_post_one", stopped_by_challenge)

    with pytest.raises(SessionExpired, match="challenge"):
        asyncio.run(poster._post_job_real(job))

    target = db.get_targets(job_id)[0]
    assert (target["status"], target["attempts"]) == ("pending", 0)
    assert calls == {"post": 1, "alert": 0}
    _assert_pending_delivery(db, event="challenge")


def test_summary_notification_failure_preserves_existing_targets_and_queues_delivery(
    tmp_path, monkeypatch
):
    from src import orchestrator

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "items.json"
    source.write_text("[]", encoding="utf-8")
    db = QueueDB(tmp_path / "jobs.db")
    job_id = db.create_job({"property_id": "property-1"}, [{"group_id": "group-1", "body": "body"}])
    before = db.get_targets(job_id)[0]
    sends = {"summary": 0}

    class FailingNotifier:
        enabled = True

        def __init__(self, *_args, **_kwargs):
            pass

        def auto_or_send_preview(self, _job_id):
            return None

        def send_message(self, _message):
            sends["summary"] += 1
            raise RuntimeError("telegram unavailable")

    settings = SimpleNamespace(
        db_path=tmp_path / "jobs.db",
        dry_run=True,
        telegram_notify_pipeline_summary=True,
        validate_runtime=lambda **_kwargs: None,
    )
    monkeypatch.setattr(orchestrator, "setup_logging", lambda: None)
    monkeypatch.setattr(orchestrator, "load_groups", lambda: [])
    monkeypatch.setattr(orchestrator, "TelegramApproval", FailingNotifier)

    summary = asyncio.run(orchestrator.run_cycle_grouped(settings, source=source))

    after = db.get_targets(job_id)[0]
    assert summary["created"] == 0
    assert (after["status"], after["attempts"]) == (before["status"], before["attempts"])
    assert sends["summary"] == 0
    _assert_pending_delivery(db, event="pipeline_summary")


def test_daily_posting_reachable_modules_have_no_explicit_group_join_action():
    modules = _reachable_posting_modules()
    assert {"scripts.run_daily", "src.orchestrator", "src.poster"} <= modules.keys()

    assert _explicit_group_join_findings(modules) == []


def test_reachable_module_closure_finds_nested_attribute_group_join(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "scripts" / "run_daily.py").write_text(
        "from src import orchestrator\norchestrator.run()\n", encoding="utf-8"
    )
    (tmp_path / "src" / "orchestrator.py").write_text(
        "from src import poster\ndef run():\n    poster.post()\n", encoding="utf-8"
    )
    (tmp_path / "src" / "poster.py").write_text(
        "def post():\n    facebook.join_group('group-1')\n", encoding="utf-8"
    )

    modules = _reachable_posting_modules(root=tmp_path)

    assert {"scripts.run_daily", "src.orchestrator", "src.poster"} <= modules.keys()
    with pytest.raises(AssertionError, match="join_group"):
        assert _explicit_group_join_findings(modules) == []


def test_reachable_module_closure_finds_join_label_button(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "run_daily.py").write_text(
        "def run(page):\n    page.get_by_role('button', name='参加').click()\n", encoding="utf-8"
    )

    with pytest.raises(AssertionError, match="get_by_role:参加"):
        assert _explicit_group_join_findings(_reachable_posting_modules(root=tmp_path)) == []


@pytest.mark.xfail(
    strict=True,
    reason="Task 3 must block generic healer coordinate clicks unless the action is a reviewed composer action.",
)
def test_unreviewed_write_action_never_uses_healer_coordinate_click(monkeypatch):
    import src.poster as poster_module

    clicks = []

    class EmptyLocator:
        first = None

        def __init__(self):
            self.first = self

        async def count(self):
            return 0

    class FakeMouse:
        async def click(self, x, y):
            clicks.append((x, y))

    class FakePage:
        mouse = FakeMouse()

        @staticmethod
        def locator(_selector):
            return EmptyLocator()

        @staticmethod
        def get_by_text(_text, **_kwargs):
            return EmptyLocator()

    poster = FacebookPoster(SimpleNamespace(), QueueDB(":memory:"), [])

    async def healed(*_args, **_kwargs):
        return SimpleNamespace(x=10, y=20)

    monkeypatch.setitem(poster_module.SELECTORS, "unreviewed_action", (".missing",))
    monkeypatch.setattr(poster_module, "heal_locate", healed)
    asyncio.run(poster._click_first(FakePage(), "unreviewed_action", "unreviewed"))

    assert clicks == []


def test_terminal_outcomes_have_the_canonical_exit_code_contract(tmp_path):
    assert SCHEMA == "fb-autoposter-run/v1"
    assert set(OUTCOME_EXIT_CODES.values()) == {0, 20, 30, 40, 50, 60}

    reasons = {
        "success": "success",
        "no_action": "already_posted_today",
        "preflight_blocked": "browser_missing",
        "risk_stopped": "facebook_challenge",
        "submission_ambiguous": "submission_uncertain",
        "posted_delivery_pending": "telegram_failed",
        "internal_error": "launcher_failed",
    }
    store = RunResultStore(tmp_path)
    for index, (outcome, exit_code) in enumerate(OUTCOME_EXIT_CODES.items()):
        run = store.start("daily-post", run_id=f"run-{index}")
        terminal = store.finish(run, outcome=outcome, reason=reasons[outcome])

        assert terminal["schema"] == SCHEMA
        assert terminal["terminal"] is True
        assert terminal["exit_code"] == exit_code


@pytest.mark.xfail(
    strict=True,
    reason="Installer currently registers all daily posting tasks enabled before runtime gates pass.",
)
def test_installer_keeps_daily_posting_tasks_disabled_until_runtime_gates_pass():
    daily_actions = _posting_task_actions(_installed_daily_actions())

    assert len(daily_actions) == 4
    assert all(action["Disabled"] is True for action in daily_actions)


@pytest.mark.xfail(
    strict=True,
    reason="The installer schedules direct Python instead of the hidden VBS-PowerShell launcher that must propagate canonical child results.",
)
def test_scheduled_daily_child_propagates_canonical_terminal_result(tmp_path):
    daily_actions = _posting_task_actions(_installed_daily_actions())
    assert {action["TaskName"] for action in daily_actions} == POSTING_TASK_NAMES
    assert all(
        ntpath.isabs(action["Execute"])
        and action["Execute"].lower().endswith(r"\wscript.exe")
        for action in daily_actions
    )
    for action in daily_actions:
        vbs = re.search(r'(?i)([A-Z]:[\\/][^"\s]*[\\/]launch_hidden\.vbs)', action["Argument"])
        command = re.search(r"(?:^|\s)--command\s+([a-z-]+)(?:\s|$)", action["Argument"])
        assert vbs and ntpath.isabs(vbs.group(1))
        assert command and command.group(1) in ALLOWED_DAILY_OPERATIONAL_COMMANDS

    result_dir = tmp_path / "run-results"
    bootstrap = """
import asyncio
from pathlib import Path
from types import SimpleNamespace
from scripts import build_group_registry, run_daily, sync_estateboard_status, sync_groups_web
from src import status_report

settings = SimpleNamespace(db_path=Path('jobs.db'), profile_dir=Path('profile'))
async def fake_cycle(*_args, **_kwargs):
    return {'statuses': []}
async def fake_ensure(_settings, _groups, _db, *, run_once, **_kwargs):
    await run_once()
    return {'reason': 'session_unrecoverable'}
run_daily.Settings.load = lambda: settings
run_daily.load_groups = lambda: []
run_daily.ensure_posted_today = fake_ensure
run_daily.run_cycle_grouped = fake_cycle
run_daily._alert_session_dead = lambda *_args, **_kwargs: None
run_daily._send_completion_report = lambda *_args, **_kwargs: None
status_report.build_status_files = lambda *_args, **_kwargs: {'counts': {}}
build_group_registry.build_registry = lambda: {'summary': {}}
sync_groups_web.sync_groups_web = lambda: {}
sync_estateboard_status.sync_estateboard_status = lambda *_args, **_kwargs: {}
run_daily.main()
"""
    env = {**os.environ, "FBAUTOP_RUN_RESULT_DIR": str(result_dir)}

    child = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=tmp_path,
        env={**env, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert child.returncode == 30
    terminal = json.loads((result_dir / "latest.json").read_text(encoding="utf-8"))
    assert terminal["exit_code"] == child.returncode
    assert terminal["schema"] == SCHEMA


async def _true():
    return True


async def _value(value):
    return value
