"""
Channel-routed system alerts — STUB.

Turn 11 builds the proper version: it looks up the master's primary channel
(Telegram by default) via the channel registry and pushes a system message
prefixed with `[🚨 SYSTEM]` for failures or `[ℹ NOTIFY]` for tool-executed
notifications. Approval requests get inline approve/reject buttons.

For now the agent graph (`app.agent.nodes.tool_executor_node`) imports two
helpers from here. We provide no-op implementations that just log so the
import works and the rest of the agent flow is testable end-to-end.

When Turn 11 lands:
  - `send_approval_request_to_master` should send a Telegram message with
    inline approve/reject buttons whose callback_data carries `approval_id`.
  - `notify_tool_executed` should send a brief Telegram notice ("✓ Sent
    email to Alice"), throttled so a burst of NOTIFY tools doesn't spam.
  - Add `send_system_alert(text)` for the @critical_task decorator's
    consumer (Phase 2 Task 2.7b) — referenced widely in the plan.
"""
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def send_approval_request_to_master(
    approval_id: str,
    tool_name: str,
    description: str,
) -> None:
    """STUB — Turn 11 wires real Telegram inline keyboard delivery."""
    logger.info(
        "approval_request_stub",
        approval_id=approval_id,
        tool_name=tool_name,
        description_len=len(description),
    )


async def notify_tool_executed(thread_id: str, tool_name: str) -> None:
    """STUB — Turn 11 wires the throttled Telegram notice."""
    logger.info(
        "notify_tool_executed_stub",
        thread_id=thread_id,
        tool_name=tool_name,
    )


async def send_system_alert(text: str) -> None:
    """STUB — Turn 11 wires this for @critical_task failure delivery."""
    logger.warning("system_alert_stub", text=text)
