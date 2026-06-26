"""The Telegram approval-callback flow: instant feedback BEFORE the (possibly
multi-second) dispatch, an ACCURATE final edit from the outcome, and — the regression
this locks — a guaranteed confirmation on ANY failure (never a silent dead-end with
live buttons). Covers every kind (fast tool card + the heads-up draft)."""
import json
from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest

from app.agent.approval_dispatch import ApprovalDispatchOutcome
from app.messaging.channels.telegram import TelegramChannel

_AID = "00000000-0000-0000-0000-000000000001"


def _make_channel() -> TelegramChannel:
    ch = TelegramChannel.__new__(TelegramChannel)  # bypass the TELEGRAM_BOT_TOKEN check
    ch.bot = AsyncMock()
    ch._bg_tasks = set()
    ch.send_alert = AsyncMock()  # isolate from the real bot send
    return ch


def _fake_query(action: str = "approve") -> MagicMock:
    q = MagicMock()
    q.data = json.dumps({"a": action, "id": _AID})
    q.answer = AsyncMock()
    q.edit_message_text = AsyncMock()
    return q


def _edit_texts(q: MagicMock) -> list[str]:
    return [c.kwargs.get("text") for c in q.edit_message_text.call_args_list]


async def test_working_feedback_before_dispatch_then_accurate_outcome(monkeypatch):
    # The exact ordering: answer → instant "⏳ Working…" (buttons cleared) → dispatch →
    # accurate outcome. Proves feedback lands BEFORE the slow dispatch, not after.
    ch, q = _make_channel(), _fake_query("approve")
    events: list = []
    q.answer = AsyncMock(side_effect=lambda *a, **k: events.append("answer"))
    q.edit_message_text = AsyncMock(side_effect=lambda *a, **k: events.append(("edit", k.get("text"))))
    outcome = ApprovalDispatchOutcome(kind="tool", status="executed", detail="📅 Done.", success=True)

    async def _dispatch(*a, **k):
        events.append("dispatch")
        return outcome

    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", AsyncMock(side_effect=_dispatch))
    monkeypatch.setattr("app.agent.approval_dispatch.alert_text_for", lambda o: "📅 Done.")

    await ch._handle_approval_callback(q)

    assert events == ["answer", ("edit", "⏳ Working…"), "dispatch", ("edit", "✅ Approved.")]
    ch.send_alert.assert_awaited_once_with("📅 Done.")


async def test_buttons_cleared_no_stale_markup(monkeypatch):
    # A fast send/calendar card benefits too: every edit drops the keyboard (no
    # reply_markup re-attached) so the master can't double-press a stale button.
    ch, q = _make_channel(), _fake_query("approve")
    outcome = ApprovalDispatchOutcome(kind="tool", status="executed", detail="ok", success=True)
    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", AsyncMock(return_value=outcome))
    monkeypatch.setattr("app.agent.approval_dispatch.alert_text_for", lambda o: None)

    await ch._handle_approval_callback(q)

    assert q.edit_message_text.await_count >= 1
    assert all("reply_markup" not in c.kwargs for c in q.edit_message_text.call_args_list)


async def test_dispatch_exception_still_confirms(monkeypatch):
    # The regression lived exactly here: a raised dispatch must STILL leave a clear
    # message (never silence), and must not propagate out of the handler.
    ch, q = _make_channel(), _fake_query("approve")
    monkeypatch.setattr(
        "app.agent.approval_dispatch.resolve_and_dispatch", AsyncMock(side_effect=RuntimeError("boom"))
    )

    await ch._handle_approval_callback(q)  # must NOT raise

    texts = _edit_texts(q)
    assert texts[0] == "⏳ Working…"               # instant feedback fired first
    assert "went wrong" in texts[-1].lower()        # then a clear fallback, not silence
    ch.send_alert.assert_not_awaited()              # the edit landed → no last-ditch alert


async def test_dispatch_and_edit_fail_falls_back_to_alert(monkeypatch):
    # Worst case: dispatch raises AND the fallback edit also fails (message gone). The
    # master is STILL not left in silence — a fresh alert is the last-ditch.
    ch, q = _make_channel(), _fake_query("reject")
    monkeypatch.setattr(
        "app.agent.approval_dispatch.resolve_and_dispatch", AsyncMock(side_effect=RuntimeError("boom"))
    )
    # 1st edit ("⏳ Working…") succeeds; 2nd edit (the ⚠ fallback) raises → last-ditch alert.
    q.edit_message_text = AsyncMock(side_effect=[None, BadRequest("message to edit not found")])

    await ch._handle_approval_callback(q)  # must NOT raise

    ch.send_alert.assert_awaited_once()
    assert "went wrong" in ch.send_alert.await_args.args[0].lower()


async def test_headsup_renders_drafted_not_approved(monkeypatch):
    # The kill-the-lie fix stays: approving a needs_drafting heads-up DRAFTS (not sends),
    # so the final edit reads "Drafted", never "Approved".
    ch, q = _make_channel(), _fake_query("approve")
    outcome = ApprovalDispatchOutcome(
        kind="draft_request", status="drafted", success=True, detail="I've drafted it — queued."
    )
    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", AsyncMock(return_value=outcome))
    monkeypatch.setattr("app.agent.approval_dispatch.alert_text_for", lambda o: o.detail)

    await ch._handle_approval_callback(q)

    final = _edit_texts(q)[-1]
    assert "Drafted" in final and "Approved" not in final


async def test_malformed_callback_is_ignored_no_edit(monkeypatch):
    # A bad/foreign callback (no valid action) never dispatches and never edits.
    ch, q = _make_channel(), _fake_query("approve")
    q.data = json.dumps({"a": "frobnicate", "id": _AID})
    spy = AsyncMock()
    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", spy)

    await ch._handle_approval_callback(q)

    spy.assert_not_awaited()
    q.edit_message_text.assert_not_awaited()
