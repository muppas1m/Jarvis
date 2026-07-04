"""Approval-message essentials (A2 s1b — the Essentials-registry standard).

An approval message may stand on the MODEL's prose only when that prose NAMES the action's
essentials — the payload fields the master must recognize before consenting. Each APPROVE-tier
tool DECLARES its essentials at registration (`tool_registry.register(approval_essentials=…)`);
this module owns the matching. The check is STRUCTURAL: field values come from the row payload,
matching is case-insensitive, whitespace-normalized PRESENCE in the prose — never tokenization,
never stop-lists, never sentence surgery (the D25 lesson).

Match kinds:
  - "recipient": the address itself OR its local-part ("bob@x.com" or "bob").
  - "text":      the value as a normalized substring ("Site Visit").
  - "time":      TOLERANT — any human form of the ISO instant (24h "17:00", 12h "5 pm"/"5pm",
                 weekday "Friday", month-day "July 4"/"4 July"). One hit = named (the floor
                 covers precision; the goal is recognizability, not parsing prose).

Fallback ladder (the silent-erosion guard): a tool with NO declaration → essentials cannot be
verified → the deterministic floor ALWAYS fires and a WARNING is logged (the weak path stays
visible, never the quiet norm). A CONSCIOUS empty declaration ([]) → floor always fires, no
warning (a decision, not an omission). Declared fields whose payload value is empty (e.g. a
calendar_update that only moved the location) are skipped; if NOTHING checkable remains, the
floor fires (safe default).
"""
from __future__ import annotations

import re
from datetime import datetime
from email.utils import parseaddr
from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)


def _norm(text: str) -> str:
    """Case-folded, whitespace-collapsed — the ONE normalization both sides get."""
    return " ".join((text or "").lower().split())


def _present(prose_norm: str, value: str) -> bool:
    """Word-boundary presence — 'hi' must not match inside 'this' (presence-only, no surgery)."""
    v = _norm(value)
    return bool(v) and re.search(rf"(?<![a-z0-9]){re.escape(v)}(?![a-z0-9])", prose_norm) is not None


def _named_recipient(prose_norm: str, value: str) -> bool:
    addr = parseaddr(value or "")[1].strip().lower() or _norm(value)
    if not addr:
        return False
    if addr in prose_norm:                     # full addresses are unambiguous as substrings
        return True
    local = addr.split("@")[0]
    return len(local) >= 3 and _present(prose_norm, local)  # "bob" names bob@x.com; 2-char too weak


def _named_text(prose_norm: str, value: str) -> bool:
    return _present(prose_norm, value)


def _time_forms(iso_value: str) -> list[str]:
    """Human forms of an ISO instant a prose sentence might use. Deterministic generation from
    the VALUE (never parsing the prose): 24h, 12h with/without space, weekday, month-day both
    orders. Unparseable value → no forms → not named → the floor fires (safe)."""
    raw = (iso_value or "").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return []
    hour24 = f"{dt.hour:02d}:{dt.minute:02d}"                      # 17:00
    h12 = dt.hour % 12 or 12
    ampm = "am" if dt.hour < 12 else "pm"
    forms = [hour24, f"{h12}:{dt.minute:02d} {ampm}", f"{h12} {ampm}", f"{h12}{ampm}"]
    if dt.minute == 0:
        forms.append(f"{h12} o'clock")
    month = dt.strftime("%B").lower()
    forms += [dt.strftime("%A").lower(),                            # friday
              f"{month} {dt.day}", f"{dt.day} {month}"]             # july 4 / 4 july
    return forms


def _named_time(prose_norm: str, value: str) -> bool:
    return any(_present(prose_norm, f) for f in _time_forms(value))


_MATCHERS = {"recipient": _named_recipient, "text": _named_text, "time": _named_time}


def card_essentials_named(prose: str, tool_name: str, tool_args: dict[str, Any]) -> bool:
    """Does the prose name THIS card's declared essentials? (One card; the caller ANDs cards.)
    Undeclared tool → False + WARN (the registry standard). Conscious [] → False, silent.
    Declared: every field with a non-empty payload value must be named; nothing checkable →
    False (the floor is the safe default)."""
    from app.agent.tools.registry import tool_registry

    declared = tool_registry.approval_essentials(tool_name)
    if declared is None:
        logger.warning("approval_essentials_undeclared", tool=tool_name)
        return False
    prose_norm = _norm(prose)
    if not prose_norm:
        return False
    checkable = 0
    for spec in declared:
        value = str((tool_args or {}).get(spec.get("field"), "") or "")
        if not value.strip():
            continue                       # unset aspect (e.g. update left title unchanged)
        checkable += 1
        matcher = _MATCHERS.get(spec.get("kind"), _named_text)
        if not matcher(prose_norm, value):
            return False
    return checkable > 0


def essentials_named(prose: str, cards: list) -> bool:
    """The turn-level gate: the prose names EVERY queued card's essentials (UnifiedApprovalCard
    shapes — tool_name + tool_args). Empty card list → False (nothing to verify → floor)."""
    if not cards:
        return False
    return all(card_essentials_named(prose, c.tool_name, c.tool_args or {}) for c in cards)


def normalize_field(kind: str, value: str) -> str:
    """The ONE kind-normalizer the dedup signature + supersede key share (s4): recipient →
    parseaddr'd address; text → case-folded, whitespace-collapsed; raw/other → stripped."""
    v = str(value or "")
    if kind == "recipient":
        return parseaddr(v)[1].strip().lower() or _norm(v)
    if kind == "text":
        return _norm(v)
    return v.strip()
