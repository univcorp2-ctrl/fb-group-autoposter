"""Pure offline safety regression tests: never touch Messenger or send anything."""
import ast
import json
from pathlib import Path

import pytest
from scripts.send_one_playwright_reply import _assert_global_send_guard

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "send_one_playwright_reply.py"


def ledger(path, attempts):
    (path / "auto_reply_ledger.json").write_text(
        json.dumps({"armed_after": "2026-10-21T00:00:00+09:00", "attempts": attempts}),
        encoding="utf-8",
    )


def test_pause_blocks_even_when_ledger_is_missing(tmp_path):
    (tmp_path / "send_pause.lock").write_text("maintenance", encoding="utf-8")
    with pytest.raises(RuntimeError, match="send_paused_fail_closed"):
        _assert_global_send_guard(tmp_path, "987654")


def test_missing_ledger_blocks_when_pause_not_present(tmp_path):
    with pytest.raises(RuntimeError, match="ledger_missing_fail_closed"):
        _assert_global_send_guard(tmp_path, "987654")


@pytest.mark.parametrize("content", ["not json", "[]", '{"attempts": null}', '{"attempts": [1]}'])
def test_corrupt_ledger_blocks(tmp_path, content):
    (tmp_path / "auto_reply_ledger.json").write_text(content, encoding="utf-8")
    with pytest.raises(RuntimeError, match="ledger_.*fail_closed"):
        _assert_global_send_guard(tmp_path, "987654")


@pytest.mark.parametrize("state", [
    "blocked_or_uncertain_no_replay", "attempted_unconfirmed", "waiting", None,
])
def test_any_ambiguous_prior_attempt_blocks_same_thread(tmp_path, state):
    ledger(tmp_path, {"old": {"thread_id": "987654", "state": state}})
    with pytest.raises(RuntimeError, match="uncertain_prior_delivery_no_replay"):
        _assert_global_send_guard(tmp_path, "987654")
    # Changing the thread is distinct; never change or clear the historical ledger.
    _assert_global_send_guard(tmp_path, "other-thread")


def test_malformed_unrelated_entry_fails_closed(tmp_path):
    ledger(tmp_path, {"malformed": None})
    with pytest.raises(RuntimeError, match="ledger_invalid_fail_closed"):
        _assert_global_send_guard(tmp_path, "987654")


def test_confirmed_only_history_does_not_trigger_ambiguous_guard(tmp_path):
    ledger(tmp_path, {"old": {"thread_id": "987654", "state": "confirmed_sent"}})
    _assert_global_send_guard(tmp_path, "987654")  # Other gates still apply.


def test_force_cannot_skip_global_guard_and_it_runs_immediately_before_click():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    main = ast.unparse(defs["main"])
    browser = ast.unparse(defs["_run_browser"])
    assert "if args.send:\n            _assert_global_send_guard(settings.data_dir, args.thread_id)" in main
    assert "await _set_editor_text(page, editor, reply)" in browser
    before_editor = browser.index("_assert_global_send_guard(settings.data_dir, args.thread_id)")
    editor = browser.index("await _set_editor_text(page, editor, reply)")
    assert before_editor < editor
    click = browser.index("await send_button.click(timeout=10000)")
    before_click = browser.rindex("_assert_global_send_guard(settings.data_dir, args.thread_id)", 0, click)
    assert before_click > editor
    assert "args.force" not in ast.unparse(defs["_assert_global_send_guard"])
