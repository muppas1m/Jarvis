"""P5b — calendar update/delete + named conflict warning.

The Google client is mocked (the handlers call it synchronously inside the async
body — the existing pattern); these tests pin the behavior we added: partial
update body, delete-with-title, and the named overlap warning that feeds the
approval prompt.
"""
from unittest.mock import MagicMock, patch

import pytest

import app.agent.tools.calendar_tool as cal


def _mock_service(list_items=None, patch_result=None, get_result=None):
    svc = MagicMock()
    events = svc.events.return_value
    events.list.return_value.execute.return_value = {"items": list_items or []}
    events.patch.return_value.execute.return_value = patch_result or {"id": "E1", "summary": "Updated"}
    events.get.return_value.execute.return_value = get_result or {"summary": "Dentist"}
    events.delete.return_value.execute.return_value = {}
    events.insert.return_value.execute.return_value = {"id": "NEW", "htmlLink": "http://x"}
    return svc, events


def _ev(title, start, end):
    return {"summary": title, "start": {"dateTime": start}, "end": {"dateTime": end}}


# --------------------------------------------------------------------------- #
# conflict warning — names what it overlaps                                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_conflict_warning_none_when_slot_free():
    svc, _ = _mock_service(list_items=[])
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_conflict_warning(
            "2026-06-13T14:00:00-04:00", "2026-06-13T15:00:00-04:00"
        )
    assert out is None


@pytest.mark.asyncio
async def test_conflict_warning_names_the_event():
    svc, events = _mock_service(list_items=[
        _ev("Car Wash", "2026-06-13T14:00:00-04:00", "2026-06-13T15:00:00-04:00"),
    ])
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_conflict_warning(
            "2026-06-13T14:00:00-04:00", "2026-06-13T15:00:00-04:00"
        )
    assert out is not None and "Car Wash" in out and "⚠️" in out
    # events.list is the named-overlap source (not freebusy)
    assert events.list.called


@pytest.mark.asyncio
async def test_conflict_warning_empty_slot_no_api_call():
    svc, events = _mock_service()
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_conflict_warning("", "")
    assert out is None
    assert not events.list.called


@pytest.mark.asyncio
async def test_conflict_warning_fails_open_on_error():
    svc = MagicMock()
    svc.events.return_value.list.return_value.execute.side_effect = RuntimeError("api down")
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_conflict_warning(
            "2026-06-13T14:00:00-04:00", "2026-06-13T15:00:00-04:00"
        )
    assert out is None  # never block the approval on a check failure


# --------------------------------------------------------------------------- #
# update — partial body                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_update_only_sets_provided_fields():
    svc, events = _mock_service()
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_update(event_id="E1", title="Renamed Gym")
    body = events.patch.call_args.kwargs["body"]
    assert body == {"summary": "Renamed Gym"}  # only the title; nothing else
    assert events.patch.call_args.kwargs["eventId"] == "E1"
    assert "Updated" in out


@pytest.mark.asyncio
async def test_update_noop_when_nothing_provided():
    svc, events = _mock_service()
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_update(event_id="E1")
    assert "nothing to update" in out.lower()
    assert not events.patch.called


@pytest.mark.asyncio
async def test_update_sets_times():
    svc, events = _mock_service()
    with patch.object(cal, "_service", return_value=svc):
        await cal.calendar_update(
            event_id="E1",
            start_iso="2026-06-14T16:00:00-04:00",
            end_iso="2026-06-14T17:00:00-04:00",
        )
    body = events.patch.call_args.kwargs["body"]
    assert body["start"] == {"dateTime": "2026-06-14T16:00:00-04:00"}
    assert body["end"] == {"dateTime": "2026-06-14T17:00:00-04:00"}
    assert "summary" not in body


# --------------------------------------------------------------------------- #
# delete — names what it removed                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_delete_names_event():
    svc, events = _mock_service(get_result={"summary": "Duplicate Gym"})
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_delete("E9")
    assert "Duplicate Gym" in out
    assert events.delete.call_args.kwargs["eventId"] == "E9"


# --------------------------------------------------------------------------- #
# create — happy path (the write returns the new event_id + link)             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_create_happy_returns_event_id():
    svc, events = _mock_service()
    with patch.object(cal, "_service", return_value=svc):
        out = await cal.calendar_create(
            "Sync", "2026-06-14T14:00:00-04:00", "2026-06-14T15:00:00-04:00",
        )
    assert "NEW" in out and "http://x" in out
    assert events.insert.call_args.kwargs["calendarId"] == "primary"


# --------------------------------------------------------------------------- #
# writes are bounded — a hung Google call surfaces TimeoutError, never a wedge #
# --------------------------------------------------------------------------- #
async def _blocking_timeout(*_a, **_k):
    """Stand-in for _blocking when the Google round-trip exceeds CALENDAR_TIMEOUT_S."""
    raise TimeoutError("calendar round-trip exceeded")


@pytest.mark.asyncio
@pytest.mark.parametrize("call", [
    lambda: cal.calendar_create("S", "2026-06-14T14:00:00-04:00", "2026-06-14T15:00:00-04:00"),
    lambda: cal.calendar_update(event_id="E1", title="X"),
    lambda: cal.calendar_delete("E9"),
])
async def test_write_surfaces_timeout_not_hang(monkeypatch, call):
    # A hung write must raise TimeoutError out to the normal [ERROR] path — not block forever.
    monkeypatch.setattr(cal, "_blocking", _blocking_timeout)
    with patch.object(cal, "_service", return_value=MagicMock()), pytest.raises(TimeoutError):
        await call()


@pytest.mark.asyncio
async def test_conflict_warning_fails_open_on_timeout(monkeypatch):
    # The conflict check is a soft warning — a timeout returns None (never blocks the approval).
    monkeypatch.setattr(cal, "_blocking", _blocking_timeout)
    with patch.object(cal, "_service", return_value=MagicMock()):
        out = await cal.calendar_conflict_warning(
            "2026-06-13T14:00:00-04:00", "2026-06-13T15:00:00-04:00",
        )
    assert out is None


@pytest.mark.asyncio
async def test_real_blocking_times_out_a_hung_write(monkeypatch):
    # End-to-end through the REAL _blocking (to_thread + wait_for): a slow Google write
    # raises TimeoutError within the budget instead of blocking the event loop forever.
    import time
    monkeypatch.setattr(cal.settings, "CALENDAR_TIMEOUT_S", 0.05)
    svc = MagicMock()
    svc.events.return_value.insert.return_value.execute.side_effect = lambda: time.sleep(0.5)
    with patch.object(cal, "_service", return_value=svc), pytest.raises(TimeoutError):
        await cal.calendar_create("S", "2026-06-14T14:00:00-04:00", "2026-06-14T15:00:00-04:00")
