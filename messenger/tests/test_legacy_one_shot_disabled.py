"""Offline tests: deprecated Messenger sender cannot dispatch any customer message."""
import asyncio
from types import SimpleNamespace

import pytest
from scripts import send_one_reply as legacy


@pytest.mark.parametrize("force", [False, True])
def test_legacy_sender_send_is_rejected_before_loading_draft(monkeypatch, force):
    def unexpected_load(_args):
        raise AssertionError("must fail before customer draft or browser interaction")
    monkeypatch.setattr(legacy, "load_target", unexpected_load)
    args=SimpleNamespace(send=True,force=force,thread_id="synthetic")
    with pytest.raises(RuntimeError, match="legacy_one_shot_sender_disabled_fail_closed"):
        asyncio.run(legacy.run(args))


def test_legacy_guard_is_not_an_authorization_path():
    import ast
    tree=ast.parse((legacy.MESSENGER_ROOT/"scripts"/"send_one_reply.py").read_text(encoding="utf-8"))
    run=next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=="run")
    assert isinstance(run.body[0],ast.If)
    assert ast.unparse(run.body[0].test)=="args.send"
    assert "legacy_one_shot_sender_disabled_fail_closed" in ast.unparse(run.body[0])
