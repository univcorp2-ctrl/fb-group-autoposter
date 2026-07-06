from __future__ import annotations

import json
import sys

from src.analytics_export import load_config, sync_history


def main() -> int:
    try:
        result = sync_history(load_config())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": result["failed"] == 0, **result}, ensure_ascii=False))
    return 0 if result["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
