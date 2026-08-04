"""Read-only Telegram credential-role check; it never calls Telegram or writes files."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.telegram_config_probe import probe_telegram_config

DEFAULT_WORKBOOK = Path(r"G:\マイドライブ\AI_Agents\Private\API_AWS_DB.xlsx")


def main(
    *,
    env_path: Path = ROOT / ".env",
    workbook_path: Path = DEFAULT_WORKBOOK,
) -> int:
    print(json.dumps(probe_telegram_config(env_path, workbook_path), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-path", type=Path, default=ROOT / ".env")
    parser.add_argument("--workbook-path", type=Path, default=DEFAULT_WORKBOOK)
    args = parser.parse_args()
    raise SystemExit(main(env_path=args.env_path, workbook_path=args.workbook_path))
