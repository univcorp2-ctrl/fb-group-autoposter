"""Export privacy-safe, read-only live Messenger metrics (never send or publish)."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def build_snapshot(data_dir: Path) -> dict:
    daemon = _read_json(data_dir / "draft_daemon_status.json")
    reply = _read_json(data_dir / "auto_reply_status.json")
    watchdog = _read_json(data_dir / "messenger_watchdog_status.json")
    drafts = _read_json(data_dir / "drafts.json").get("drafts", [])
    if not isinstance(drafts, list):
        drafts = []
    safe_rows = [row for row in drafts if isinstance(row, dict)]
    scan = daemon.get("scan") if isinstance(daemon.get("scan"), dict) else {}
    approved = sum(row.get("review_status") == "approved" for row in safe_rows)
    return {
        "schema_version": "messenger-runtime-health/v1",
        "source": "local_runtime_read_only",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "includes_customer_identifiers": False,
        "estateboard_published_verified": False,
        "daemon_running": daemon.get("running") is True,
        "browser_authenticated": scan.get("logged_in") is True,
        "watchdog_decision": str(watchdog.get("decision", "unknown")),
        "auto_send_configured": daemon.get("send_enabled") is True,
        "scanned_count": int(scan.get("scanned", 0) or 0),
        "needs_reply_count": int(scan.get("need_reply", 0) or 0),
        "active_draft_count": len(safe_rows),
        "review_approved_count": approved,
        "material_approved_count": sum(
            isinstance(row.get("material"), dict)
            and row["material"].get("approved") is True for row in safe_rows
        ),
        "confirmed_sent_total": int(reply.get("confirmed_total", 0) or 0),
        "uncertain_send_total": int(reply.get("uncertain_total", 0) or 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = build_snapshot(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print("wrote privacy-safe runtime metrics (no customer data)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
