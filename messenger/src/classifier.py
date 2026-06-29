"""Decide which Messenger threads need a human reply.

Pure functions, no I/O — fully unit-testable. The scraper produces thread dicts;
this module classifies each one. Drafts are NEVER auto-sent, so a wrong call is
harmless (a human reviews every draft) — but we still bias toward only flagging
genuine 1:1 inbound messages to keep the operator's queue clean.

Rule of thumb ("要返信" = needs reply):
  - 1:1 only (skip group threads)
  - the OTHER person sent the last message (skip if I replied last)
  - skip obvious automated / page / marketplace system threads
"""

from __future__ import annotations

from dataclasses import dataclass

# Preview prefixes Facebook uses when *I* sent the last message.
_SELF_PREFIXES = ("あなた:", "あなた：", "自分:", "自分：", "You:", "You sent", "Vous :")

# Names / preview fragments that indicate a non-personal, automated thread.
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

# Preview fragments that mean there is NO real inbound message to reply to:
# the end-to-end-encryption banner (empty/new conversation) or a system event.
# A thread whose latest preview is one of these has nothing to answer.
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


def _is_system_preview(preview: str) -> bool:
    p = (preview or "")
    return any(hint in p for hint in _SYSTEM_PREVIEW_HINTS)


@dataclass(frozen=True)
class Classification:
    needs_reply: bool
    reason: str
    priority: str  # "high" | "normal" | "none"


def _looks_self_sent(preview: str) -> bool:
    p = (preview or "").lstrip()
    return any(p.startswith(prefix) for prefix in _SELF_PREFIXES)


def _looks_automated(name: str, preview: str) -> bool:
    blob = f"{name} {preview}".lower()
    return any(hint in blob for hint in _AUTOMATED_HINTS)


def classify_thread(thread: dict) -> Classification:
    """Classify one scraped thread dict.

    Expected keys (all best-effort; missing ones are treated conservatively):
      name: str           — the other party / thread title
      preview: str        — last message preview text
      is_unread: bool     — thread shows an unread indicator
      last_from_me: bool  — I sent the last message (overrides preview parsing)
      is_group: bool      — known group thread
      participant_count: int | None — number of *other* participants if known
    """
    name = str(thread.get("name", "") or "")
    preview = str(thread.get("preview", "") or "")

    if thread.get("is_group"):
        return Classification(False, "group_thread", "none")

    pc = thread.get("participant_count")
    if isinstance(pc, int) and pc > 1:
        return Classification(False, "group_thread", "none")

    # Explicit signal wins; otherwise infer from the preview prefix.
    last_from_me = thread.get("last_from_me")
    if last_from_me is None:
        last_from_me = _looks_self_sent(preview)
    if last_from_me:
        return Classification(False, "already_replied", "none")

    if _looks_automated(name, preview):
        return Classification(False, "automated_thread", "none")

    if _is_system_preview(preview):
        # E2E banner / system event — there is no actual message to reply to.
        return Classification(False, "no_message", "none")

    if not preview.strip():
        # No readable last message — flag for human eyes but low priority.
        return Classification(True, "needs_review_empty_preview", "normal")

    priority = "high" if thread.get("is_unread") else "normal"
    return Classification(True, "inbound_1to1", priority)


def select_threads_needing_reply(threads: list[dict]) -> list[dict]:
    """Return the subset of threads that need a reply, each annotated with its
    classification under the 'classification' key (priority/reason)."""
    out: list[dict] = []
    for thread in threads:
        c = classify_thread(thread)
        if c.needs_reply:
            out.append({**thread, "classification": {"reason": c.reason, "priority": c.priority}})
    # High-priority (unread) first, stable otherwise.
    out.sort(key=lambda t: 0 if t["classification"]["priority"] == "high" else 1)
    return out
