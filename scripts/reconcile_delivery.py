"""Reconcile durable downstream delivery obligations without touching Facebook."""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings
from src.outbox import DeliveryOutbox
from src.queue_db import QueueDB
from src.run_result import RunResultStore
from src.telegram_transport import TelegramTransport

MAX_EVENTS_PER_RUN = 20
LEASE_SECONDS = 60
MAX_RETRYABLE_ATTEMPTS = 3


def _telegram_handler(event: dict[str, Any], transport: TelegramTransport) -> dict[str, Any]:
    """Render the approved, schema-validated outbox payload for Telegram only."""
    payload = event["payload"]
    reply_markup = payload.get("reply_markup")
    return transport.send_message(
        payload["text"],
        reply_markup=reply_markup if isinstance(reply_markup, dict) else None,
        disable_web_page_preview=True,
    )


DESTINATION_HANDLERS = {"telegram": _telegram_handler}


def reconcile_delivery(
    outbox: DeliveryOutbox,
    transport: TelegramTransport,
    *,
    owner: str,
    limit: int = MAX_EVENTS_PER_RUN,
) -> dict[str, int]:
    """Claim at most one bounded batch and record only delivery outcomes.

    A timeout or any failure after request submission is terminally ambiguous: a
    later operator may resolve it explicitly, but this worker will never reset
    it or retry it automatically.
    """
    claimed = outbox.claim_oldest_origin(
        owner, limit=min(max(1, limit), MAX_EVENTS_PER_RUN), lease_seconds=LEASE_SECONDS
    )
    origin_run_id = claimed[0]["origin_run_id"] if claimed else None
    summary = {
        "claimed": len(claimed),
        "delivered": 0,
        "failed": 0,
        "delivery_ambiguous": 0,
        "skipped": 0,
        "retry_pending": 0,
        "origin_run_id": origin_run_id,
    }
    for index, event in enumerate(claimed):
        remaining_ids = [item["event_id"] for item in claimed[index:]]
        renewed = outbox.renew_leases(remaining_ids, owner, lease_seconds=LEASE_SECONDS)
        if event["event_id"] not in renewed:
            summary["skipped"] += 1
            continue
        if event["origin_run_id"] != origin_run_id:
            raise RuntimeError("outbox claim mixed origin_run_id values")
        if not origin_run_id:
            outbox.mark_failed(event["event_id"], owner, "missing origin_run_id")
            summary["failed"] += 1
            continue
        handler = DESTINATION_HANDLERS.get(event["destination"])
        if handler is None:
            outbox.mark_failed(event["event_id"], owner, "no registered delivery handler")
            summary["failed"] += 1
            continue
        try:
            result = handler(event, transport)
        except Exception:  # A handler exception may have occurred after submit.
            outbox.mark_ambiguous(event["event_id"], owner, "delivery handler exception")
            summary["delivery_ambiguous"] += 1
            continue
        if result.get("ok") is True:
            message_id = result.get("message_id")
            outbox.mark_delivered(
                event["event_id"], owner, remote_message_id=str(message_id) if message_id is not None else None
            )
            summary["delivered"] += 1
        elif result.get("code") == "retryable_pre_submit":
            retried = outbox.retry_or_fail(
                event["event_id"], owner, "retryable_pre_submit", max_attempts=MAX_RETRYABLE_ATTEMPTS
            )
            summary["retry_pending" if retried["state"] == "pending" else "failed"] += 1
        elif result.get("code") in {"disabled", "telegram_api_error"}:
            outbox.mark_failed(event["event_id"], owner, str(result.get("code")))
            summary["failed"] += 1
        else:
            outbox.mark_ambiguous(event["event_id"], owner, str(result.get("code", "delivery_unknown")))
            summary["delivery_ambiguous"] += 1
    return summary


def run_reconciliation(
    settings: Settings,
    *,
    run_id: str | None = None,
    store: RunResultStore | None = None,
    transport: TelegramTransport | None = None,
) -> dict[str, Any]:
    """Execute one downstream-only batch and record its reconciliation linkage."""
    store = store or RunResultStore(ROOT / "output" / "run-results")
    run = store.start("reconcile-delivery", run_id=run_id or f"delivery-{uuid.uuid4().hex}")
    outbox = DeliveryOutbox(QueueDB(settings.db_path))
    summary = reconcile_delivery(
        outbox,
        transport or TelegramTransport(settings.telegram_bot_token, settings.telegram_chat_id),
        owner=f"reconcile:{run['run_id']}",
    )
    return store.finish(
        run,
        outcome="success",
        reason="success",
        extra_fields={"delivery": summary, "origin_run_id": summary["origin_run_id"]},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile queued Telegram delivery without Facebook access.")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    result = run_reconciliation(Settings.load(), run_id=args.run_id)
    print(f"claimed={result['delivery']['claimed']} delivered={result['delivery']['delivered']}")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
