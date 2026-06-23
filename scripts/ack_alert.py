"""Acknowledge a persistent alert from the command line (stops re-notification).

The ✅ inline button in Telegram only works when the bot is polled via
getUpdates. When the bot instead has a webhook (its updates go to an external
service), the button tap never reaches this app, so this CLI provides a reliable
acknowledge path that works regardless of the bot's update mode.

Usage:
    python scripts/ack_alert.py                # list open alerts
    python scripts/ack_alert.py session_dead   # acknowledge one (stops re-notify)
    python scripts/ack_alert.py --all          # acknowledge every open alert

Acknowledging only stops the re-notification; it does NOT fix the underlying
problem. A dead login still needs scripts/login_once.py. A later healthy run
clears the alert automatically and sends a recovery notice.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.alerts import AlertStore  # noqa: E402


def main() -> int:
    store = AlertStore()
    args = [a for a in sys.argv[1:]]

    if not args:
        alerts = store.all()
        if not alerts:
            print("No open alerts.")
            return 0
        print("Open alerts:")
        for a in alerts:
            state = "acknowledged" if a.get("acknowledged") else "PENDING"
            print(f"  {a['kind']:16} [{state}] notify_count={a.get('notify_count', 0)}  {a.get('message', '')[:80]}")
        print("\nAcknowledge with: python scripts/ack_alert.py <kind>   (or --all)")
        return 0

    targets = [a["kind"] for a in store.all()] if args == ["--all"] else args
    acked = 0
    for kind in targets:
        if store.acknowledge(kind):
            print(f"acknowledged: {kind} (re-notification stopped)")
            acked += 1
        else:
            print(f"no open alert named: {kind}")
    return 0 if acked or args == ["--all"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
