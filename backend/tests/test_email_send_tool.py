"""The agent-direct email_send tool surfaces maybe-delivered honestly too.

A timeout/5xx (EmailSendUncertain) on a "send an email to X" turn must return the
same honest, DETERMINISTIC "couldn't confirm — may have gone out" wording the
approval transports use — not propagate as a generic tool failure. A DEFINITE
failure still propagates (tool_executor's standard [ERROR]/success=False path),
consistent with every other tool.
"""
import pytest

from app.agent.tools.email_send import email_send
from app.email.provider import EmailSendUncertain, SendResult


async def test_tool_returns_uncertain_wording_on_maybe_delivered(monkeypatch):
    async def fake_send(*a, **k):
        raise EmailSendUncertain("timeout — may have gone out")

    monkeypatch.setattr("app.agent.tools.email_send.send_email", fake_send)
    result = await email_send("bob@example.com", "Hi", "body")
    assert "couldn't confirm" in result.lower()  # the honest signal
    assert "sent folder" in result.lower()
    assert "bob@example.com" in result  # names the recipient
    assert "❌" not in result  # NOT a flat failure


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
