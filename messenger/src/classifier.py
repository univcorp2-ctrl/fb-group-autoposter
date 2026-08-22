"""Decide which Messenger threads need a human reply.

Pure functions, no I/O — fully unit-testable. The scraper produces thread dicts;
this module classifies each one. Drafts are NEVER auto-sent. Thread type is
fail-closed: only an explicitly verified 1:1 thread can produce a draft.

Rule of thumb ("要返信" = needs reply):
  - positively verified 1:1 only (skip group and ambiguous threads)
  - the OTHER person sent the last message (skip if I replied last)
  - skip obvious automated / page / marketplace system threads
"""

from __future__ import annotations

from dataclasses import dataclass

_SELF_PREFIXES = ("あなた:", "あなた：", "自分:", "自分：", "You:", "You sent", "Vous :")

_AUTOMATED_HINTS = (
    "facebook",
    "meta",
    "マーケットプレイス",
    "marketplace",
    "ページ",
    "page",
    "自動応答",
    "ボット",
    "no-reply",
    "noreply",
)

_SYSTEM_PREVIEW_HINTS = (
    "エンドツーエンド暗号化",
    "end-to-end encrypted",
    "グループに追加しました",
    "さんが参加しました",
    "が退出しました",
    "さんが退出しました",
    "通話履歴",
    "不在着信",
    "missed call",
    "you added",
    "added you to the group",
)

_NO_REPLY_ACKS = (
    "承知しました",
    "承知いたしました",
    "了解しました",
    "了解いたしました",
    "わかりました",
    "分かりました",
    "かしこまりました",
)


def _is_system_preview(preview: str) -> bool:
    p = preview or ""
    return any(hint in p for hint in _SYSTEM_PREVIEW_HINTS)


def _is_closing_ack(preview: str) -> bool:
    normalized = (preview or "").strip().rstrip("。.!！?？ ")
    return normalized in _NO_REPLY_ACKS


@dataclass(frozen=True)
class Classification:
    needs_reply: bool
    reason: str
    priority: str


def _looks_self_sent(preview: str) -> bool:
    p = (preview or "").lstrip()
    return any(p.startswith(prefix) for prefix in _SELF_PREFIXES)


def _looks_automated(name: str, preview: str) -> bool:
    blob = f"{name} {preview}".lower()
    return any(hint in blob for hint in _AUTOMATED_HINTS)


def classify_thread(thread: dict) -> Classification:
    """Classify one scraped thread dict conservatively."""
    name = str(thread.get("name", "") or "")
    preview = str(thread.get("preview", "") or "")

    if thread.get("is_group") is True:
        return Classification(False, "group_thread", "none")

    participant_count = thread.get("participant_count")
    if isinstance(participant_count, int) and participant_count > 1:
        return Classification(False, "group_thread", "none")

    # A missing/weak group signal is NOT proof of 1:1.  Require the scraper's
    # positive one-to-one evidence and an explicit single counterpart count.
    if thread.get("one_to_one_verified") is not True or participant_count != 1:
        return Classification(False, "ambiguous_thread_type", "none")

    last_from_me = thread.get("last_from_me")
    if last_from_me is None:
        last_from_me = _looks_self_sent(preview)
    if last_from_me:
        return Classification(False, "already_replied", "none")

    if _looks_automated(name, preview):
        return Classification(False, "automated_thread", "none")

    if _is_system_preview(preview):
        return Classification(False, "no_message", "none")

    if _is_closing_ack(preview):
        return Classification(False, "closing_ack", "none")

    if not preview.strip():
        return Classification(False, "empty_preview_no_draft", "none")

    priority = "high" if thread.get("is_unread") else "normal"
    return Classification(True, "inbound_1to1", priority)


def select_threads_needing_reply(threads: list[dict]) -> list[dict]:
    """Return reply-needed threads annotated with priority/reason."""
    out: list[dict] = []
    for thread in threads:
        classification = classify_thread(thread)
        if classification.needs_reply:
            out.append(
                {
                    **thread,
                    "classification": {
                        "reason": classification.reason,
                        "priority": classification.priority,
                    },
                }
            )
    out.sort(key=lambda item: 0 if item["classification"]["priority"] == "high" else 1)
    return out
