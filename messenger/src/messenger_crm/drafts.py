from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import ConversationSnapshot, ReplyDraft, stable_hash


@dataclass(frozen=True)
class DraftContext:
    operator_name: str = "担当者"
    company_name: str = "物件紹介窓口"
    property_payload: dict[str, Any] = field(default_factory=dict)
    include_viewing_question: bool = True


def _safe_text(value: Any, default: str = "未設定") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def infer_intent(message_body: str) -> str:
    lowered = message_body.lower()
    if any(keyword in message_body for keyword in ["内見", "見学", "現地", "案内"]):
        return "viewing_request"
    if any(keyword in message_body for keyword in ["資料", "詳細", "図面", "pdf", "PDF"]):
        return "materials_request"
    if any(keyword in message_body for keyword in ["価格", "家賃", "費用", "初期費用", "値段"]):
        return "price_question"
    if any(keyword in lowered for keyword in ["available", "vacancy"]):
        return "availability_question"
    if any(keyword in message_body for keyword in ["空室", "空いて", "まだあります"]):
        return "availability_question"
    return "general_inquiry"


def property_summary(payload: dict[str, Any]) -> str:
    title = _safe_text(payload.get("title") or payload.get("name"), "該当物件")
    area = _safe_text(payload.get("area") or payload.get("station") or payload.get("address"), "エリア確認中")
    price = _safe_text(payload.get("price") or payload.get("rent") or payload.get("total_price"), "価格確認中")
    layout = _safe_text(payload.get("layout") or payload.get("size"), "間取り確認中")
    return f"{title}（{area} / {price} / {layout}）"


class ReplyDraftService:
    """Create human-review reply drafts from a Messenger conversation snapshot."""

    def create_draft(self, snapshot: ConversationSnapshot, context: DraftContext | None = None) -> ReplyDraft | None:
        if not snapshot.needs_reply():
            return None

        draft_context = context or DraftContext()
        latest_customer_message = snapshot.last_customer_message()
        if latest_customer_message is None:
            return None

        intent = infer_intent(latest_customer_message.body)
        summary = property_summary(draft_context.property_payload)
        confidence = 0.86 if intent != "general_inquiry" else 0.68
        body = self._render_body(snapshot, draft_context, summary, intent)
        draft_id = stable_hash(
            {
                "thread_id": snapshot.thread_id,
                "customer_external_id": snapshot.customer_external_id,
                "source_snapshot_hash": snapshot.snapshot_hash(),
                "body": body,
            }
        )
        return ReplyDraft(
            draft_id=draft_id,
            thread_id=snapshot.thread_id,
            customer_external_id=snapshot.customer_external_id,
            body=body,
            intent=intent,
            confidence=confidence,
            source_snapshot_hash=snapshot.snapshot_hash(),
        )

    def _render_body(
        self,
        snapshot: ConversationSnapshot,
        context: DraftContext,
        summary: str,
        intent: str,
    ) -> str:
        customer_name = _safe_text(snapshot.customer_name, "お客様")
        lines = [
            f"{customer_name}様",
            "お問い合わせありがとうございます。",
            f"ご連絡いただいた物件は {summary} です。",
        ]

        if intent == "materials_request":
            lines.append("物件資料・費用感・空室状況を確認し、すぐにご案内できる形でまとめます。")
        elif intent == "viewing_request":
            lines.append("内見候補日を確認しますので、ご希望の日程を2〜3つ教えてください。")
        elif intent == "price_question":
            lines.append("費用面の詳細を確認し、初期費用と月額費用が分かる形でお送りします。")
        elif intent == "availability_question":
            lines.append("最新の空室状況を確認し、募集中かどうかを折り返しご案内します。")
        else:
            lines.append("条件に合うか確認できるよう、物件情報を整理してご案内します。")

        if context.include_viewing_question and intent != "viewing_request":
            lines.append("内見希望・資料だけ希望・条件相談のどれが近いか教えていただけますか？")

        lines.append(f"{context.company_name} {context.operator_name}")
        return "\n".join(lines)
