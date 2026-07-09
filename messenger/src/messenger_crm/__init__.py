"""CRM support layer for the Facebook Messenger assistant.

The package is intentionally side-effect free. It prepares CRM records, reply
DRAFTS, and analytics payloads; it never sends a Messenger message.
"""

from .analytics import build_kpi_summary, calculate_reaction_rate
from .drafts import DraftContext, ReplyDraftService
from .models import CRMEvent, ConversationSnapshot, MessengerMessage, ReplyDraft
from .repository import MessengerCRMRepository

__all__ = [
    "CRMEvent",
    "ConversationSnapshot",
    "DraftContext",
    "MessengerCRMRepository",
    "MessengerMessage",
    "ReplyDraft",
    "ReplyDraftService",
    "build_kpi_summary",
    "calculate_reaction_rate",
]
