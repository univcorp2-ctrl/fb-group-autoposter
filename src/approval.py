from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

from src.alerts import AlertStore
from src.queue_db import QueueDB
from src.secret_redaction import redact
from src.telegram_transport import TelegramTransport

log = logging.getLogger(__name__)


class DeliveryAmbiguousError(requests.RequestException):
    """Telegram may have accepted the request; automatic resend is unsafe."""


class TelegramApproval:
    def __init__(
        self,
        settings: Any,
        db: QueueDB,
        alert_store: AlertStore | None = None,
        transport: TelegramTransport | None = None,
    ):
        self.settings = settings
        self.db = db
        self.alert_store = alert_store or AlertStore()
        self.transport = transport or TelegramTransport(settings.telegram_bot_token, settings.telegram_chat_id)
        self.offset_path = Path("data/telegram_offset.txt")
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return self.transport.enabled

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            log.info("telegram disabled: %s", method)
            return None
        if method != "sendMessage":
            raise ValueError("unsupported Telegram operation")
        result = self.transport.send_message(
            str(payload.get("text", "")), reply_markup=payload.get("reply_markup")
        )
        if not result.get("ok"):
            if result.get("code") == "delivery_ambiguous":
                raise DeliveryAmbiguousError("Telegram send outcome is delivery_ambiguous")
            raise requests.RequestException(f"Telegram {method} failed: {result.get('code', 'unknown')}")
        return {"ok": True, "result": {"message_id": result.get("message_id")}}

    def _sanitize_error(self, exc: BaseException) -> str:
        return str(
            redact(
                exc,
                secrets=(self.settings.telegram_bot_token, self.settings.telegram_chat_id),
            )
        )[:500]

    def send_message(self, text: str, *, reply_markup: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": self.settings.telegram_chat_id, "text": text[:4096]}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self._post("sendMessage", payload)

    def send_preview(self, job_id: str) -> None:
        job = self.db.get_job(job_id)
        if not job:
            return
        payload = json.loads(job["payload_json"])
        targets = self.db.get_targets(job_id)
        degraded = "⚠️簡易生成" if job.get("degraded") else ""
        first = targets[:2]
        body_preview = "\n\n".join(f"[{t['group_id']}]\n{t['body'][:900]}" for t in first)
        text = (
            f"📣 配信ジョブ確認 {degraded}\n"
            f"job_id: {job_id}\n"
            f"物件: {payload.get('title')} / {payload.get('price')} / {payload.get('yield_pct')}\n"
            f"対象: {len(targets)}グループ\n\n{body_preview}"
        )
        buttons = {
            "inline_keyboard": [
                [
                    {"text": "✅承認", "callback_data": f"approve:{job_id}"},
                    {"text": "✏️修正", "callback_data": f"revise:{job_id}"},
                    {"text": "❌却下", "callback_data": f"reject:{job_id}"},
                ],
                [{"text": "👁️全文", "callback_data": f"full:{job_id}"}],
            ]
        }
        self.send_message(text, reply_markup=buttons)

    def auto_or_send_preview(self, job_id: str) -> None:
        job = self.db.get_job(job_id)
        degraded = bool(job and job.get("degraded"))
        if self.settings.auto_approve and not (degraded and self.settings.auto_approve_skip_degraded):
            self.db.approve_job(job_id)
            if getattr(self.settings, "telegram_notify_auto_approval", False):
                self.send_preview(job_id)
                self.send_message(f"✅ AUTO_APPROVEにより承認済み: {job_id}")
        else:
            self.send_preview(job_id)

    def _read_offset(self) -> int | None:
        if not self.offset_path.exists():
            return None
        raw = self.offset_path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None

    def _write_offset(self, offset: int) -> None:
        self.offset_path.write_text(str(offset), encoding="utf-8")

    def _is_authorized_sender(self, callback: dict[str, Any]) -> bool:
        sender_id = str(callback.get("from", {}).get("id", ""))
        authorized_user_id = str(getattr(self.settings, "telegram_authorized_user_id", "")).strip()
        if authorized_user_id:
            return sender_id == authorized_user_id
        configured_chat_id = str(self.settings.telegram_chat_id).strip()
        is_private_user_chat = configured_chat_id.isdigit() and int(configured_chat_id) > 0
        return is_private_user_chat and sender_id in {configured_chat_id, "<telegram-chat-id>"}

    def poll_once(self) -> int:
        if not self.enabled:
            return 0
        offset = self._read_offset()
        result = self.transport.get_updates(offset=offset)
        if not result.get("ok"):
            log.warning("telegram poll failed: code=%s", result.get("code", "unknown"))
            return 0
        updates = result.get("result", [])
        handled = 0
        for update in updates:
            self._write_offset(update["update_id"] + 1)
            callback = update.get("callback_query")
            if not callback:
                continue
            if not self._is_authorized_sender(callback):
                log.warning("ignoring callback from unauthorized sender")
                continue
            data = callback.get("data", "")
            action, _, job_id = data.partition(":")
            if not job_id:
                continue
            if action == "approve":
                self.db.approve_job(job_id)
                self.send_message(f"✅ 承認しました: {job_id}")
            elif action == "reject":
                self.db.reject_job(job_id, "telegram rejected")
                self.send_message(f"❌ 却下しました: {job_id}")
            elif action == "full":
                for target in self.db.get_targets(job_id):
                    self.send_message(f"[{target['group_id']}]\n{target['body']}")
            elif action == "revise":
                self.send_message(f"✏️ 修正指示を通常メッセージで返信してください。job_id={job_id}")
            elif action == "ack":
                # `job_id` here carries the alert kind (e.g. "session_dead").
                if self.alert_store.acknowledge(job_id):
                    self.send_message(
                        f"🆗 確認を受け付けました（{job_id}）。このセッション復旧アラートの再通知を停止します。"
                    )
                else:
                    self.send_message(f"（{job_id} の未確認アラートは見つかりませんでした）")
            handled += 1
        return handled

    def alert(self, text: str) -> None:
        self.send_message(f"🔴 {text}")

    def raise_persistent_alert(self, kind: str, message: str) -> None:
        """Record an acknowledge-until-cleared alert and send it once now.

        The store keeps the obligation alive across process exits; the scheduled
        re-notifier (`scripts/renotify_alerts.py`) keeps re-sending it until the
        operator taps ✅ or a healthy run clears it. Recording always happens even
        when Telegram is disabled, so nothing is silently dropped."""
        self.alert_store.raise_alert(kind, message)
        self.send_persistent_alert(kind, message)

    def send_persistent_alert(self, kind: str, message: str) -> None:
        """(Re)send a persistent alert with an inline ✅ acknowledge button."""
        buttons = {
            "inline_keyboard": [
                [{"text": "✅ 確認した（対応します）", "callback_data": f"ack:{kind}"}]
            ]
        }
        try:
            self.send_message(
                f"🔴🔁 {message}\n\n"
                "※ 復旧（再ログイン）まで通知し続けます。\n"
                f"　止めるには ✅ ボタン、または PCで `python scripts/ack_alert.py {kind}` を実行してください。",
                reply_markup=buttons,
            )
            self.alert_store.mark_notified(kind)
        except DeliveryAmbiguousError:
            self.alert_store.quarantine_delivery(kind)
            log.warning("persistent alert delivery quarantined (%s): code=delivery_ambiguous", kind)
        except Exception as exc:  # noqa: BLE001 - never let notification crash the caller
            log.warning("persistent alert send failed (%s): %s", kind, self._sanitize_error(exc))

    def clear_persistent_alert(self, kind: str, *, notify_recovery: bool = True) -> None:
        """Clear an open alert (condition resolved) and optionally announce it."""
        if self.alert_store.clear(kind) and notify_recovery:
            try:
                self.send_message(f"✅ 復旧を確認しました（{kind}）。再通知を停止します。")
            except Exception as exc:  # noqa: BLE001
                log.warning("recovery notice send failed (%s): %s", kind, self._sanitize_error(exc))

    def renotify_pending(self) -> int:
        """Re-send every unacknowledged open alert. Returns how many were sent."""
        sent = 0
        for alert in self.alert_store.pending_unacknowledged():
            self.send_persistent_alert(alert["kind"], alert.get("message", ""))
            sent += 1
        return sent

    def has_pending_alerts(self) -> bool:
        return bool(self.alert_store.pending_unacknowledged())
