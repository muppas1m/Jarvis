"""The agent-direct email_send tool surfaces maybe-delivered honestly too.

A timeout/5xx (EmailSendUncertain) on a "send an email to X" turn RE-RAISES carrying the
honest, DETERMINISTIC "couldn't confirm — may have gone out" wording, so execute_tool_guarded
records the 3rd outcome (success=False + uncertain=True → ⚠️ unconfirmed) instead of a clean ✅
(#5). A DEFINITE failure still propagates (the standard [ERROR]/success=False path).
"""
import pytest

from app.agent.tools.email_send import email_send
from app.email.provider import EmailSendUncertain, SendResult


async def test_tool_reraises_uncertain_with_honest_wording(monkeypatch):
    async def fake_send(*a, **k):
        raise EmailSendUncertain("timeout — may have gone out")

    monkeypatch.setattr("app.agent.tools.email_send.send_email", fake_send)
    with pytest.raises(EmailSendUncertain) as exc:
        await email_send("bob@example.com", "Hi", "body")
    msg = str(exc.value)
    assert "couldn't confirm" in msg.lower()  # the honest signal
    assert "sent folder" in msg.lower()
    assert "bob@example.com" in msg  # names the recipient
    assert "❌" not in msg  # NOT a flat failure


async def test_tool_definite_failure_propagates(monkeypatch):
    """Consistency with every other tool: a definite failure RAISES → the
    tool_executor's standard [ERROR]/success=False path, not a clean string."""
    async def fake_send(*a, **k):
        raise RuntimeError("permanent 403")

    monkeypatch.setattr("app.agent.tools.email_send.send_email", fake_send)
    with pytest.raises(RuntimeError):
        await email_send("bob@example.com", "Hi", "body")


async def test_tool_success_returns_sent_string(monkeypatch):
    async def fake_send(*a, **k):
        return SendResult(provider="gmail", sent_message_id="m1")

    monkeypatch.setattr("app.agent.tools.email_send.send_email", fake_send)
    result = await email_send("bob@example.com", "Hi", "body")
    assert "Email sent to bob@example.com" in result and "m1" in result
