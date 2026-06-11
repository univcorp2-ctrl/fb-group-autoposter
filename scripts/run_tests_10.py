from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_once(index: int) -> None:
    print(f"\n===== test pass {index}/10: ruff =====", flush=True)
    subprocess.run([sys.executable, "-m", "ruff", "check", "."], cwd=ROOT, check=True)
    print(f"\n===== test pass {index}/10: pytest =====", flush=True)
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)


def main() -> int:
    for i in range(1, 11):
        run_once(i)
    print("\nALL 10 TEST PASSES COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
