from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], round_no: int) -> None:
    print(f"\n=== deep verification round {round_no}: {' '.join(cmd)} ===", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=50)
    parser.add_argument("--skip-lint", action="store_true")
    args = parser.parse_args()
    if args.rounds <= 0:
        raise SystemExit("--rounds must be positive")
    for i in range(1, args.rounds + 1):
        if not args.skip_lint:
            run([sys.executable, "-m", "ruff", "check", "."], i)
        run([sys.executable, "-m", "pytest", "-q"], i)
    print(f"\nOK: verification passed {args.rounds} consecutive rounds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
