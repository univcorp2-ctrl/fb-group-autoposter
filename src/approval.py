from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

from src.queue_db import QueueDB

log = logging.getLogger(__name__)


class TelegramApproval:
    def __init__(self, settings: Any, db: QueueDB):
        self.settings = settings
        self.db = db
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}" if settings.telegram_bot_token else ""
        self.offset_path = Path("data/telegram_offset.txt")
        self.offset_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not self.enabled:
            log.info("telegram disabled: %s", method)
            return None
        try:
            resp = requests.post(f"{self.base_url}/{method}", json=payload, timeout=20)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(
                f"Telegram API error on {method}: {exc.response.status_code}"
            ) from None
        return resp.json()

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
            self.send_preview(job_id)
            self.db.approve_job(job_id)
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
        msg_chat_id = str((callback.get("message") or {}).get("chat", {}).get("id", ""))
        expected = str(self.settings.telegram_chat_id)
        return sender_id == expected or msg_chat_id == expected

    def poll_once(self) -> int:
        if not self.enabled:
            return 0
        params: dict[str, Any] = {"timeout": 0}
        offset = self._read_offset()
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("telegram poll failed: %s", exc)
            return 0
        updates = resp.json().get("result", [])
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
            handled += 1
        return handled

    def alert(self, text: str) -> None:
        self.send_message(f"🔴 {text}")
