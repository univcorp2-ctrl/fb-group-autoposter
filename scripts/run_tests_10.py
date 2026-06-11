from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], round_no: int) -> None:
    print(f"\n=== round {round_no}: {' '.join(cmd)} ===", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    rounds = 10
    for i in range(1, rounds + 1):
        run([sys.executable, "-m", "ruff", "check", "."], i)
        run([sys.executable, "-m", "pytest", "-q"], i)
    print(f"\nOK: lint + pytest passed {rounds} consecutive rounds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
