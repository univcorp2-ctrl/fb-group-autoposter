"""Build an anonymized CRM operational snapshot from local Messenger state.

Read-only source: no SAMPLE_EVENTS and no customer identifiers. This artifact
is suitable for review; it does not itself publish to EstateBoard.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


def _load(path: Path) -> dict:
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return obj if isinstance(obj, dict) else {}


def build_live_metrics(data_dir: Path) -> dict:
    status = _load(data_dir / "draft_daemon_status.json")
    # Durable ledger is authoritative; paused status omits historical totals.
    ledger_path = data_dir / "auto_reply_ledger.json"
    if not ledger_path.is_file():
        raise ValueError("send ledger missing; refuse inaccurate counts")
    ledger = _load(ledger_path)
    attempts = ledger.get("attempts")
    if not isinstance(attempts, dict) or any(not isinstance(v, dict) for v in attempts.values()):
        raise ValueError("invalid ledger; refuse inaccurate counts")
    confirmed = sum(v.get("state") == "confirmed_sent" for v in attempts.values())
    uncertain = sum(v.get("state") != "confirmed_sent" for v in attempts.values())
    threads = _load(data_dir / "threads_state.json")
    drafts = _load(data_dir / "drafts.json").get("drafts", [])
    if not isinstance(drafts, list):
        drafts = []
    drafts = [r for r in drafts if isinstance(r, dict)]
    scan = status.get("scan", {})
    if not isinstance(scan, dict):
        scan = {}
    return {
        "schema_version": "messenger-crm-private-aggregate/v1",
        "source": "live_local_json_not_demo",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "messenger_only",
        "contains_personal_data": False,
        "source_files": [
            "draft_daemon_status.json", "auto_reply_ledger.json",
            "threads_state.json", "drafts.json"
        ],
        "tracked_thread_count": len(threads),
        "latest_scan_count": int(scan.get("scanned") or 0),
        "latest_need_reply_count": int(scan.get("need_reply") or 0),
        "current_active_draft_count": len(drafts),
        "current_premium_approved_count": sum(
            r.get("review_status") == "approved" for r in drafts
        ),
        "confirmed_send_count": confirmed,
        "uncertain_send_count": uncertain,
        "estateboard_publication_confirmed": False,
        "remarks": "Scanned counts are cycle observations, not unique leads. No fake customers."
    }

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Privacy-safe live Messenger counters")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build_live_metrics(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pending = args.output.with_suffix(".tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(args.output)
    print(json.dumps({
        "scope": data["scope"],
        "tracked_threads": data["tracked_thread_count"],
        "latest_scan": data["latest_scan_count"],
        "uncertain": data["uncertain_send_count"],
        "public_deploy": False
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
