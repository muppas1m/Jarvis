"""
Action Safety Classifier — every tool call is intercepted before execution.

Four levels:
  SAFE     -> execute silently (read-only operations).
  NOTIFY   -> execute, then inform master (low-risk writes).
  APPROVE  -> pause via LangGraph interrupt(), ask master, resume only on yes.
  BLOCKED  -> never execute, regardless of context.

Default for unknown tools is APPROVE — this is fail-safe. Anything not in the
allowlist is treated as a write that needs human review.

Args-aware overrides:
  Some tools start at NOTIFY but escalate to APPROVE based on their args.
  Example: `telegram_send` to the master's own chat is NOTIFY, but to any
  other chat ID it's APPROVE. The classifier consults TOOL_SAFETY_MAP first
  and then runs `_args_overrides()` to bump up the level when needed.

The classifier never bumps levels DOWN. APPROVE never becomes NOTIFY based on
args; if you want auto-approval rules they belong in a separate trust-
accumulation layer (Phase 2).
"""
from enum import Enum
from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)


class SafetyLevel(str, Enum):
    SAFE = "safe"
    NOTIFY = "notify"
    APPROVE = "approve"
    BLOCKED = "blocked"


# Tool name → default classification.
# Add a row here every time a new tool gets registered. Unknown tools default
# to APPROVE (see SafetyClassifier.classify).
TOOL_SAFETY_MAP: dict[str, SafetyLevel] = {
    # --- read-only / information ---------------------------------------------
    "brave_search":     SafetyLevel.SAFE,
    "tavily_search":    SafetyLevel.SAFE,
    "firecrawl_crawl":  SafetyLevel.SAFE,
    "gmail_read":       SafetyLevel.SAFE,
    "gmail_list":       SafetyLevel.SAFE,
    "calendar_read":    SafetyLevel.SAFE,
    "memory_search":    SafetyLevel.SAFE,
    "email_history_search": SafetyLevel.SAFE,
    "document_search":  SafetyLevel.SAFE,
    "web_research":     SafetyLevel.SAFE,

    # --- low-risk writes -----------------------------------------------------
    "telegram_send":    SafetyLevel.NOTIFY,
    "email_archive":    SafetyLevel.NOTIFY,
    "email_label":      SafetyLevel.NOTIFY,

    # --- high-risk writes (master must explicitly approve) -------------------
    "email_send":           SafetyLevel.APPROVE,
    "email_reply":          SafetyLevel.APPROVE,
    "whatsapp_send":        SafetyLevel.APPROVE,
    "calendar_create":      SafetyLevel.APPROVE,
    "calendar_update":      SafetyLevel.APPROVE,
    "calendar_delete":      SafetyLevel.APPROVE,
    "booking_reserve":      SafetyLevel.APPROVE,
    "book_restaurant":      SafetyLevel.APPROVE,
    "search_flights":       SafetyLevel.APPROVE,
    "browser_form_submit":  SafetyLevel.APPROVE,

    # --- never executed ------------------------------------------------------
    "delete_account":       SafetyLevel.BLOCKED,
    "share_credentials":    SafetyLevel.BLOCKED,
}


class SafetyClassifier:
    """Returns the SafetyLevel for a tool call. Default is APPROVE for unknowns."""

    def classify(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
    ) -> SafetyLevel:
        base = TOOL_SAFETY_MAP.get(tool_name, SafetyLevel.APPROVE)

        # BLOCKED is terminal — no override path can downgrade it.
        if base is SafetyLevel.BLOCKED:
            return SafetyLevel.BLOCKED

        # Args-aware escalation. Never downgrades; only bumps up.
        return self._args_overrides(tool_name, tool_args or {}, base)

    @staticmethod
    def _args_overrides(
        tool_name: str,
        tool_args: dict[str, Any],
        base: SafetyLevel,
    ) -> SafetyLevel:
        """Per-tool rules that bump severity up. Add overrides here as new
        tools onboard. Always: never downgrade, only escalate."""
        # Imported lazily so a unit test can patch settings.TELEGRAM_MASTER_CHAT_ID
        # without forcing a global config reload.
        from app.config import settings

        if tool_name == "telegram_send":
            # Sending to the master's own chat is the expected NOTIFY path;
            # sending to any other chat (e.g. a contact, a group) requires
            # explicit approval to avoid accidental outbound messages.
            chat_id = str(tool_args.get("chat_id", ""))
            if chat_id and chat_id != settings.TELEGRAM_MASTER_CHAT_ID:
                # Surface the escalation: reading audit_trail alone can't tell a
                # default-APPROVE from an args-escalated one (Phase-4 dashboard
                # wants "how often does args-escalation fire?"). q2 / Step 6 F2.
                logger.warning(
                    "safety_args_override_escalated",
                    tool=tool_name,
                    from_level=base.value,
                    to_level=SafetyLevel.APPROVE.value,
                    override_reason="telegram_send_to_non_master",
                )
                return SafetyLevel.APPROVE

        # Add future args-based escalations here. e.g. gmail_archive of a
        # large bulk could escalate; calendar_read with a non-primary calendar
        # could escalate; etc.

        return base
