"""The synthesized card-context line (`_card_context_line`, reused by the in-graph card
resolver + the judge), that it actually REACHES the judge, and the Telegram heads-up label.

(Step A retired the old runner reminder/stale-ack orchestrators; their tests went with them.
The card-context line + the judge-context wiring they shared are live and tested here.)
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.agent.runner as runner


def _email_row(needs_drafting=False):
    return SimpleNamespace(
        thread_id="email:gmail:x", action_type="email_reply",
        description="Reply to 'Q3' from Priya",
        payload={"sender": "Priya <p@x.com>", "subject": "Q3", "body": "orig",
                 "draft": "d", "needs_drafting": needs_drafting},
    )


# --- the synthesized card-context line (pure, used by production AND the live test) ---
def test_card_context_line_email_send():
    line = runner._card_context_line(_email_row())
    assert line.startswith("Assistant:") and "Priya" in line and "send it" in line.lower()


def test_card_context_line_headsup():
    line = runner._card_context_line(_email_row(needs_drafting=True))
    assert "Priya" in line and "draft a reply" in line.lower()  # framed as "shall I draft?"


def test_card_context_line_tool():
    row = SimpleNamespace(thread_id="web:master", action_type="calendar_create",
                          description="Create event 'Standup'", payload={})
    line = runner._card_context_line(row)
    assert line.startswith("Assistant:") and "Standup" in line


# --- Telegram heads-up confirmation label (pure) -----------------------------
def test_telegram_decision_label():
    from app.messaging.channels.telegram import _telegram_decision_label

    def outcome(kind, status):
        return SimpleNamespace(kind=kind, status=status)

    assert "Drafted" in _telegram_decision_label("approve", outcome("draft_request", "drafted"))
    assert "inbox" in _telegram_decision_label("reject", outcome("draft_request", "left")).lower()
    assert "couldn't draft" in _telegram_decision_label("approve", outcome("draft_request", "draft_failed")).lower()
    assert _telegram_decision_label("approve", outcome("email", "sent")) == "✅ Approved."
    assert _telegram_decision_label("reject", outcome("email", "rejected")) == "❌ Rejected."
    assert "already handled" in _telegram_decision_label("approve", outcome("none", "not_claimed")).lower()


# --- the synthesized card-line actually REACHES the judge (deterministic, no live LLM) ------
async def test_card_context_line_reaches_the_judge(monkeypatch):
    # An inbound card has no conversation thread, so _judge_presented must feed
    # _card_context_line(row) into resolve_decision as "the assistant just raised this".
    row = SimpleNamespace(
        thread_id="email:gmail:x", action_type="email_reply", status="pending",
        description="Reply to 'Q3' from Priya",
        payload={"sender": "Priya <p@x.com>", "subject": "Q3", "body": "o", "draft": "d",
                 "needs_drafting": False},
    )
    captured = {}

    async def _fake_resolve(tool_name, tool_args, description, message, context):
        captured["context"] = context
        return SimpleNamespace(intent="unclear", change="")

    monkeypatch.setattr(runner, "_load_approval_by_id", AsyncMock(return_value=row))
    monkeypatch.setattr(runner, "resolve_decision", _fake_resolve)

    judged = await runner._judge_presented("approval-id", "did she say when?", recent_context="")

    assert judged is not None and judged.intent == "unclear"
    assert runner._card_context_line(row) in captured["context"]   # the synthesized line reached it
    assert "drafted a reply" in captured["context"].lower()         # inbound framing, despite no thread
