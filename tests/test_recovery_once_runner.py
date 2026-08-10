from __future__ import annotations

import sys

from scripts.recovery_once import run_checked


def test_run_checked_tolerates_non_utf8_subprocess_output() -> None:
    result = run_checked(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\x83')"],
        timeout=10,
    )

    assert result["returncode"] == 0
    assert isinstance(result["stdout"], str)
