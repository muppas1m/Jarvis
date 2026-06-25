"""POST /voice/announce-approval — Jarvis reads a freshly-surfaced card aloud.

Now origin-agnostic (3C): an inbound email reply names sender + subject; a
chat-queued TOOL action speaks its description. Tests the spoken-intro wording
per kind, the "another" variant, and the endpoint wiring (synthesizes, maps to
{text, audio, mime}, 404s on a stale/missing approval). synth_line is mocked —
TTS itself is the voice layer's concern, not this endpoint's.
"""
import pytest
from fastapi import HTTPException

import app.api.voice as voice


class _EmailRow:
    def __init__(self, sender="Priya Rao <priya@x.com>", subject="Q3 numbers"):
        self.thread_id = "email:gmail:m1"
        self.description = "Reply to 'Q3 numbers'"
        self.payload = {"sender": sender, "subject": subject, "draft": "On it."}


class _ToolRow:
    def __init__(self, description="Create event 'Standup'"):
        self.thread_id = "web:master"
        self.description = description
        self.payload = {"tool_name": "calendar_create", "tool_args": {"title": "Standup"}}


def test_announce_text_email_names_sender_and_subject():
    text = voice._announce_text(_EmailRow(), first=True)
    assert "Priya Rao" in text  # display name, not the raw address
    assert "Q3 numbers" in text
    assert text.strip().endswith("Shall I send it?")
    assert "another" not in text.lower()  # first card


def test_announce_text_email_second_card_says_another():
    assert "another" in voice._announce_text(_EmailRow(), first=False).lower()


def test_announce_text_email_falls_back_to_address_then_someone():
    assert "bob@x.com" in voice._announce_text(_EmailRow(sender="bob@x.com"), first=True)
    t = voice._announce_text(_EmailRow(sender="", subject=""), first=True)
    assert "someone" in t and "your message" in t


def test_announce_text_tool_speaks_description_not_reply_copy():
    """A tool card must NOT say 'I've drafted a reply' — it speaks its action."""
    text = voice._announce_text(_ToolRow(), first=True)
    assert "Create event 'Standup'" in text
    assert "reply" not in text.lower()  # not the email copy
    assert text.strip().endswith("Shall I go ahead?")
    assert "another" not in text.lower()


def test_announce_text_tool_second_card_says_another():
    assert "another" in voice._announce_text(_ToolRow(), first=False).lower()


async def test_endpoint_synthesizes_and_maps(monkeypatch):
    async def fake_load(_id):
        return _EmailRow()

    async def fake_synth(text):
        return {"text": text, "audio": "QURJTw==", "mime": "audio/wav", "filler": False}

    monkeypatch.setattr(voice, "_load_pending_approval", fake_load)
    monkeypatch.setattr(voice, "synth_line", fake_synth)

    resp = await voice.announce_approval(
        voice.AnnounceApprovalRequest(approval_id="uuid-1"), user=None
    )
    assert "Priya Rao" in resp.text
    assert resp.audio == "QURJTw=="
    assert resp.mime == "audio/wav"


async def test_endpoint_404_on_missing(monkeypatch):
    async def fake_load(_id):
        return None

    monkeypatch.setattr(voice, "_load_pending_approval", fake_load)
    with pytest.raises(HTTPException) as ei:
        await voice.announce_approval(
            voice.AnnounceApprovalRequest(approval_id="gone"), user=None
        )
    assert ei.value.status_code == 404


async def test_endpoint_returns_text_when_tts_empty(monkeypatch):
    async def fake_load(_id):
        return _ToolRow()

    async def fake_synth(text):
        return None  # TTS yielded nothing

    monkeypatch.setattr(voice, "_load_pending_approval", fake_load)
    monkeypatch.setattr(voice, "synth_line", fake_synth)
    resp = await voice.announce_approval(
        voice.AnnounceApprovalRequest(approval_id="uuid-1"), user=None
    )
    assert resp.text and resp.audio == ""  # caption still returned for the card
