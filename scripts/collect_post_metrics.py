from __future__ import annotations

import asyncio
import json
import sys

from src.facebook_metrics import run_from_environment


def main() -> int:
    try:
        result = asyncio.run(run_from_environment())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": result["failed"] == 0, **result}, ensure_ascii=False))
    return 0 if result["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
