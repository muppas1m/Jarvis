"""
Action Safety Classifier — every tool call is intercepted before execution.

Four levels:
  SAFE     -> execute silently (read-only operations).
  NOTIFY   -> execute, then inform master (low-risk writes).
  APPROVE  -> QUEUE a PendingApproval (non-blocking; the turn completes), ask
              master, and execute OUT-OF-BAND only on yes — via the claim-gated
              dispatcher (app/agent/approval_dispatch.py). Phase 3 retired the old
              interrupt()/resume pause; nothing blocks the turn now.
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
    "task_list":        SafetyLevel.SAFE,
    "readiness_check":  SafetyLevel.SAFE,
    "briefing":         SafetyLevel.SAFE,  # read + an internal HWM advance; no external side effect

    # --- own-task management (no external side effect) -----------------------
    "task_add":         SafetyLevel.SAFE,
    "task_complete":    SafetyLevel.SAFE,
    "task_drop":        SafetyLevel.SAFE,

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


# Consent tier for an APPROVE-tier tool — consulted by the DECISION JUDGE
# (decision_resolver), NOT this classifier. The classifier decides WHETHER to ask;
# this decides HOW STRONG the master's confirmation must be once asked.
#
# SOFT-CONSENT-OK: a soft affirmation OF THE ACTION ("that works", "okay sure") in
# direct response to the surfaced card counts as consent → approve. Restricted to the
# reversible SENDS the master accepted (2026-06-25) plus the heads-up draft action
# (approving it only DRAFTS — nothing irreversible).
#
# Everything else — destructive / irreversible / money (calendar_create/update/delete,
# bookings, form-submit, flight search) AND every unlisted/unknown tool — is
# EXPLICIT-REQUIRED: a soft affirmation is NOT enough (the judge returns "unclear" and
# the caller re-asks); ONLY an explicit, unambiguous command ("delete it", "yes, book
# it") approves. Default-explicit is fail-safe: a tool is soft ONLY by being named here.
SOFT_CONSENT_TOOLS: frozenset[str] = frozenset({
    "email_send",
    "email_reply",
    "whatsapp_send",
    "draft_email_reply",   # heads-up synthetic action — approving only DRAFTS (reversible)
})


def consent_tier(tool_name: str) -> str:
    """'soft'  → a soft affirmation ("that works") is consent (reversible sends).
    'explicit' → only an explicit command approves (destructive / irreversible / money).
    Defaults to 'explicit' for any unlisted/unknown tool — fail-safe."""
    return "soft" if tool_name in SOFT_CONSENT_TOOLS else "explicit"


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
