"""CRM support layer for the Facebook Messenger and multi-channel assistant.

The package prepares CRM records, reply DRAFTS, next-action alerts, and
analytics payloads. It is designed for human approval before customer-facing
messages are sent.
"""

from .actions import build_next_actions, infer_customer_status
from .analytics import build_kpi_summary, calculate_reaction_rate
from .channels import CustomerStatus, ResponseChannel, get_channel_capabilities
from .dashboard_payload import build_dashboard_payload
from .drafts import DraftContext, ReplyDraftService
from .models import CRMEvent, ConversationSnapshot, MessengerMessage, ReplyDraft
from .repository import MessengerCRMRepository

__all__ = [
    "CRMEvent",
    "ConversationSnapshot",
    "CustomerStatus",
    "DraftContext",
    "MessengerCRMRepository",
    "MessengerMessage",
    "ReplyDraft",
    "ReplyDraftService",
    "ResponseChannel",
    "build_dashboard_payload",
    "build_kpi_summary",
    "build_next_actions",
    "calculate_reaction_rate",
    "get_channel_capabilities",
    "infer_customer_status",
]
