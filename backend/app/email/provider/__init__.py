"""Provider-agnostic email layer. Import the contract from here; the concrete
adapter is selected by ``get_email_provider`` (added with the Gmail adapter)."""
from app.email.provider.base import (
    EmailProvider,
    InboundMessage,
    ReplyRef,
    SendResult,
)

__all__ = [
    "EmailProvider",
    "InboundMessage",
    "ReplyRef",
    "SendResult",
]
