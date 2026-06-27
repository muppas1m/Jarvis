"""#5 — a chat-composed email_send that hits EmailSendUncertain is UNCONFIRMED, not sent.

Before: email_send swallowed EmailSendUncertain into a success string → execute_tool_guarded
saw success → recorded ✅ executed → "sent" when it was unconfirmed. Now: email_send re-raises,
execute_tool_guarded records the 3rd state (success=False + uncertain=True), and _terminal_outcome
maps tool+uncertain → 'unconfirmed' (⚠️) — chat path at parity with the inbound path.
"""

import pytest

from app.agent.approval_dispatch import (
    ApprovalDispatchOutcome,
    _terminal_outcome,
    alert_text_for,
)


def test_terminal_outcome_tool_uncertain_maps_to_unconfirmed():
    out = ApprovalDispatchOutcome(
        kind="tool", status="executed", detail="I couldn't confirm the email to x@y.com sent",
        success=False, uncertain=True, thread_id="web:t",
    )
    terminal = _terminal_outcome(out)
    assert terminal is not None
    status, detail = terminal
    assert status == "unconfirmed"  # NOT executed, NOT failed
    assert "couldn't confirm" in detail.lower()


def test_terminal_outcome_tool_success_still_executed():
    out = ApprovalDispatchOutcome(kind="tool", status="executed", detail="Email sent to x",
                                  success=True, uncertain=False, thread_id="web:t")
    assert _terminal_outcome(out)[0] == "executed"


def test_alert_text_uncertain_is_warning_not_cross():
    out = ApprovalDispatchOutcome(kind="tool", status="executed", detail="couldn't confirm",
                                  success=False, uncertain=True, thread_id="web:t")
    txt = alert_text_for(out)
    assert txt.startswith("⚠️") and "❌" not in txt


@pytest.mark.asyncio
async def test_execute_tool_guarded_sets_uncertain_on_emailsenduncertain(monkeypatch):
    # The real guarded executor: a tool that raises EmailSendUncertain → uncertain=True,
    # success=False, and the exception's honest wording becomes the content.
    from app.email.provider.base import EmailSendUncertain

    async def fake_execute(name, args):
        raise EmailSendUncertain("I couldn't confirm the email to bob@x.com sent, Sir — it may have gone out.")

    # tool_registry is imported lazily inside execute_tool_guarded; patch the singleton's
    # method (the lazy import resolves the same object).
    import app.agent.nodes as nodes
    from app.agent.tools.registry import tool_registry
    monkeypatch.setattr(tool_registry, "execute", fake_execute)

    from app.agent.safety import SafetyLevel
    res = await nodes.execute_tool_guarded("web:t", "email_send", {"to": "bob@x.com"},
                                           level=SafetyLevel.APPROVE, tool_call_id="c1")
    assert res.uncertain is True and res.success is False
    assert "couldn't confirm" in res.content.lower()
