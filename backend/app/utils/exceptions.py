"""
Custom exception hierarchy.

App code raises these instead of bare Exception so the FastAPI exception
handler in main.py can map them to specific HTTP responses, and so the
LangGraph tool_executor node can catch each one and produce a clean,
machine-readable tool-result message back to the LLM.
"""


class JarvisError(Exception):
    """Base for everything Jarvis raises. Catch this to swallow expected
    domain failures without masking unrelated bugs."""


class ToolExecutionError(JarvisError):
    """A tool handler raised, exceeded its timeout, or returned malformed output."""


class SafetyBlockedError(JarvisError):
    """The safety classifier rejected an action."""


class ApprovalExpiredError(JarvisError):
    """Master did not respond to an approval request within APPROVAL_EXPIRY_HOURS."""


class RateLimitedError(JarvisError):
    """Per-tool or per-conversation rate limit hit."""


class CostCapExceededError(JarvisError):
    """DAILY_LLM_SPEND_CAP_USD reached; agent halted for the rest of the day."""
