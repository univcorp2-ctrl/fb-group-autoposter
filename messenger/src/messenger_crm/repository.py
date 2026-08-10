from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import json
import sqlite3
from typing import Any

from .models import CRMEvent, ConversationSnapshot, ReplyDraft


class MessengerCRMRepository:
    """Small SQLite repository for Messenger CRM phase-1 records."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    customer_external_id TEXT PRIMARY KEY,
                    customer_name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    thread_id TEXT PRIMARY KEY,
                    customer_external_id TEXT NOT NULL,
                    property_id TEXT,
                    post_id TEXT,
                    snapshot_hash TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    FOREIGN KEY(customer_external_id) REFERENCES customers(customer_external_id)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    external_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    body TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    attachments_json TEXT NOT NULL,
                    FOREIGN KEY(thread_id) REFERENCES conversations(thread_id)
                );

                CREATE TABLE IF NOT EXISTS reply_drafts (
                    draft_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    customer_external_id TEXT NOT NULL,
                    body TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_snapshot_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS crm_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    customer_external_id TEXT NOT NULL,
                    thread_id TEXT,
                    property_id TEXT,
                    draft_id TEXT,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                """
            )

    def upsert_snapshot(self, snapshot: ConversationSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO customers (customer_external_id, customer_name, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(customer_external_id) DO UPDATE SET
                    customer_name=excluded.customer_name,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (snapshot.customer_external_id, snapshot.customer_name, snapshot.source, snapshot.captured_at),
            )
            connection.execute(
                """
                INSERT INTO conversations (
                    thread_id, customer_external_id, property_id, post_id, snapshot_hash, captured_at, tags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    customer_external_id=excluded.customer_external_id,
                    property_id=excluded.property_id,
                    post_id=excluded.post_id,
                    snapshot_hash=excluded.snapshot_hash,
                    captured_at=excluded.captured_at,
                    tags_json=excluded.tags_json
                """,
                (
                    snapshot.thread_id,
                    snapshot.customer_external_id,
                    snapshot.property_id,
                    snapshot.post_id,
                    snapshot.snapshot_hash(),
                    snapshot.captured_at,
                    json.dumps(snapshot.tags, ensure_ascii=False),
                ),
            )
            for message in snapshot.messages:
                connection.execute(
                    """
                    INSERT INTO messages (
                        external_id, thread_id, sender_name, direction, body, sent_at, attachments_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(external_id) DO UPDATE SET
                        sender_name=excluded.sender_name,
                        direction=excluded.direction,
                        body=excluded.body,
                        sent_at=excluded.sent_at,
                        attachments_json=excluded.attachments_json
                    """,
                    (
                        message.external_id,
                        message.thread_id,
                        message.sender_name,
                        message.direction,
                        message.body,
                        message.sent_at,
                        json.dumps(message.attachments, ensure_ascii=False),
                    ),
                )

    def save_draft(self, draft: ReplyDraft) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reply_drafts (
                    draft_id, thread_id, customer_external_id, body, intent, confidence,
                    source_snapshot_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    body=excluded.body,
                    intent=excluded.intent,
                    confidence=excluded.confidence,
                    status=excluded.status
                """,
                (
                    draft.draft_id,
                    draft.thread_id,
                    draft.customer_external_id,
                    draft.body,
                    draft.intent,
                    draft.confidence,
                    draft.source_snapshot_hash,
                    draft.status,
                    draft.created_at,
                ),
            )

    def record_event(self, event: CRMEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO crm_events (
                    event_id, event_type, customer_external_id, thread_id, property_id,
                    draft_id, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    payload_json=excluded.payload_json
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.customer_external_id,
                    event.thread_id,
                    event.property_id,
                    event.draft_id,
                    event.occurred_at,
                    json.dumps(event.payload, ensure_ascii=False, sort_keys=True),
                ),
            )

    def list_events(self) -> list[CRMEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, customer_external_id, thread_id, property_id,
                       draft_id, occurred_at, payload_json
                FROM crm_events
                ORDER BY occurred_at ASC, event_id ASC
                """
            ).fetchall()
        return [
            CRMEvent(
                event_id=row["event_id"],
                event_type=row["event_type"],
                customer_external_id=row["customer_external_id"],
                thread_id=row["thread_id"],
                property_id=row["property_id"],
                draft_id=row["draft_id"],
                occurred_at=row["occurred_at"],
                payload=json.loads(row["payload_json"]),
            )
            for row in rows
        ]

    def export_estateboard_payload(self) -> dict[str, Any]:
        with self._connect() as connection:
            customers = connection.execute("SELECT COUNT(*) AS count FROM customers").fetchone()["count"]
            conversations = connection.execute("SELECT COUNT(*) AS count FROM conversations").fetchone()["count"]
            drafts = connection.execute("SELECT COUNT(*) AS count FROM reply_drafts").fetchone()["count"]
            pending = connection.execute(
                "SELECT COUNT(*) AS count FROM reply_drafts WHERE status = 'pending_approval'"
            ).fetchone()["count"]
            events = [event.to_record() for event in self.list_events()]
        return {
            "schema_version": "messenger-crm-phase1/v1",
            "summary": {
                "customers": customers,
                "conversations": conversations,
                "reply_drafts": drafts,
                "pending_approval": pending,
            },
            "events": events,
        }

    def record_events(self, events: Iterable[CRMEvent]) -> None:
        for event in events:
            self.record_event(event)
