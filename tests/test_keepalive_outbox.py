from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_keepalive_unhealthy_path_uses_persistent_outbox_alert_not_network_alert():
    tree = ast.parse((ROOT / "scripts" / "keepalive.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]

    assert any(call.func.attr == "raise_persistent_alert" for call in calls)
    assert not any(call.func.attr == "alert" for call in calls)
