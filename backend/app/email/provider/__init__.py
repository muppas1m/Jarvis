"""Provider-agnostic email layer. Import the contract + ``get_email_provider``
from here; the concrete adapter is selected by the ``EMAIL_PROVIDER`` setting, so
switching providers is a config change, not a code change."""
from app.email.provider.base import (
    EmailProvider,
    EmailSendUncertain,
    InboundMessage,
    ReplyRef,
    SendResult,
)
from app.email.provider.gmail import GmailProvider
from app.email.provider.outlook import OutlookProvider

__all__ = [
    "EmailProvider",
    "EmailSendUncertain",
    "GmailProvider",
    "InboundMessage",
    "OutlookProvider",
    "ReplyRef",
    "SendResult",
    "get_email_provider",
]

# Registry of adapters by config name. A new provider is one entry + its module
# — no caller changes anywhere in the agent/approval/send/inbound layers.
_REGISTRY: dict[str, type[EmailProvider]] = {
    "gmail": GmailProvider,
    "outlook": OutlookProvider,  # skeleton (Graph-mapped) — proves the seam is real
}

# Adapters are stateless across calls (each builds a fresh underlying client), so
# a process-wide singleton per provider is safe — including across event loops
# (unlike the SQLAlchemy engine; see project_async_state_rebind_pattern). Cache
# is keyed by provider name so a (test) config flip still resolves correctly.
_instances: dict[str, EmailProvider] = {}


def get_email_provider(name: str | None = None) -> EmailProvider:
    """The configured email adapter (cached). ``name`` overrides the
    ``EMAIL_PROVIDER`` setting — used by the approval handler to resolve the SAME
    provider that received a message (the approval payload carries its tag)."""
    from app.config import settings

    key = (name or settings.EMAIL_PROVIDER or "gmail").strip().lower()
    if key not in _instances:
        adapter_cls = _REGISTRY.get(key)
        if adapter_cls is None:
            raise ValueError(
                f"Unknown EMAIL_PROVIDER {key!r}; registered: {sorted(_REGISTRY)}"
            )
        _instances[key] = adapter_cls()
    return _instances[key]
