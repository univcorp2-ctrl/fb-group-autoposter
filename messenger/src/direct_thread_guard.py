"""Second independent group-chat barrier on the *opened* Messenger thread.

An inbox avatar heuristic is insufficient to approve sends. A real one-to-one
thread must have an exact per-recipient conversation accessibility label.
Ambiguity/group signals always fail closed, both for text and PDF delivery.
"""
from __future__ import annotations
from typing import Any

GROUP_MARKERS=("グループチャット","グループのメンバー","グループの詳細",
               "group chat","group members","members in this chat",
               "group information")

def direct_thread_evidence(evidence: dict, counterpart: str, inbox: dict) -> bool:
    if (inbox.get("is_group") is not False
            or inbox.get("one_to_one_verified") is not True
            or type(inbox.get("participant_count")) is not int
            or inbox["participant_count"] != 1
            or not counterpart or str(inbox.get("name")) != counterpart):
        return False
    labels=[str(label) for label in evidence.get("labels",[])]
    title=str(evidence.get("title","")).strip()
    if not title.startswith(f"スレッド: {counterpart}") and not title.startswith(f"Thread: {counterpart}"):
        return False
    if any(marker in label.lower() for label in labels for marker in GROUP_MARKERS):
        return False
    positive=(f"{counterpart}とのスレッドのメッセージ" in labels
              or f"Messages in conversation with {counterpart}" in labels)
    return positive

async def assert_one_to_one_thread(page: Any, counterpart: str, inbox: dict) -> None:
    evidence=await page.evaluate("""() => {
        const root=document.querySelector('[role="main"]');
        if (!root) return {title:'',labels:[]};
        const title=(root.innerText||'').split('\\n')[0].trim();
        const labels=[...root.querySelectorAll('[aria-label]')]
            .map(n=>n.getAttribute('aria-label')||'').filter(Boolean);
        return {title,labels:labels.slice(0,250)};
    }""")
    if not direct_thread_evidence(evidence,counterpart,inbox):
        raise RuntimeError("group_or_ambiguous_thread_send_forbidden")