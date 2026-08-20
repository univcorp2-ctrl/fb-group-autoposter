"""Pure helpers for an explicit, exact-target Messenger reply.

This module deliberately contains no browser or send operation.  It keeps the
recipient selection and draft sanitisation testable before a consequential UI
action is attempted.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

_INTERNAL_NOTE_RE = re.compile(
    r"^\s*[（(]\s*※?\s*(?:この返信は下書きです|送信前に内容をご確認)",
)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Collapse whitespace for comparisons while preserving the source text."""

    return _WHITESPACE_RE.sub(" ", value or "").strip()


def sanitize_draft(value: str) -> str:
    """Remove internal review notes that must never be sent to a recipient."""

    kept = [line for line in (value or "").splitlines() if not _INTERNAL_NOTE_RE.match(line)]
    return "\n".join(kept).strip()


def select_exact_draft(
    payload: Mapping[str, Any], *, target_name: str, thread_id: str
) -> dict[str, Any]:
    """Return exactly one draft matching both recipient name and thread id.

    Matching both fields prevents a same-name collision and prevents a stale URL
    from being used for a different recipient.  Any ambiguity is a hard failure.
    """

    drafts = payload.get("drafts", [])
    if not isinstance(drafts, Sequence) or isinstance(drafts, (str, bytes)):
        raise ValueError("drafts payload must contain a sequence")

    matches = [
        row
        for row in drafts
        if isinstance(row, Mapping)
        and str(row.get("name", "")) == target_name
        and str(row.get("thread_id", "")) == thread_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one draft for "
            f"{target_name!r} / {thread_id!r}; found {len(matches)}"
        )
    return dict(matches[0])


def message_fingerprint(value: str) -> str:
    """Stable SHA-256 fingerprint used to block accidental duplicate sends."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
