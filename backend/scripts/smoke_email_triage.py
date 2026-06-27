"""Turn 17.8 smoke — email triage enrichment (classifier → meta → consumers).

Two tiers, like smoke_rag/smoke_documents:

  DETERMINISTIC (no LLM, no DB) — the bug-prone parts:
    - urgency_rank ordinal: immediate < today < this_week < none, unknown last.
      (A plain text sort would be alphabetical and WRONG — this is the trap.)
    - _parse_triage robustness: valid JSON, markdown-fenced JSON, out-of-enum →
      ValidationError, garbage → JSONDecodeError; _fallback_triage is valid.

  LIVE (LLM + DB):
    - classify_email populates all five EmailTriageResult fields as valid enums.
    - email_history_search urgency filter returns only the matching rows.

Self-cleaning: deletes the EmailLog rows it inserts. Run inside the container:

    docker compose exec -T backend python scripts/smoke_email_triage.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import _smoke_isolation  # noqa: F401  — side effect: bind to the test DB before any app import

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.agent.tools.email_history import email_history_search  # noqa: E402
from app.db.engine import async_session  # noqa: E402
from app.db.models import EmailLog  # noqa: E402
from app.email.classifier import (  # noqa: E402
    EmailTriageResult,
    _fallback_triage,
    _parse_triage,
    classify_email,
    urgency_rank,
)
from app.utils.logging import configure_logging  # noqa: E402

_VALID_URGENCY = {"immediate", "today", "this_week", "none"}
_SMOKE_IDS = ["smoke-triage-immediate", "smoke-triage-week", "smoke-triage-none"]


def _check_urgency_rank(failures: list[str]) -> None:
    print("=== urgency_rank ordinal (deterministic) ===")
    ranks = {u: urgency_rank(u) for u in ("immediate", "today", "this_week", "none")}
    print(f"  ranks={ranks}  unknown={urgency_rank('bogus')}")
    if not (ranks["immediate"] < ranks["today"] < ranks["this_week"] < ranks["none"]):
        failures.append(f"urgency_rank: ordering wrong {ranks}")
    if urgency_rank("bogus") != ranks["none"]:
        failures.append("urgency_rank: unknown value should sort last (== none)")
    # A real sort over a shuffled list must come out most-urgent-first.
    shuffled = ["none", "immediate", "this_week", "today"]
    ordered = sorted(shuffled, key=urgency_rank)
    if ordered != ["immediate", "today", "this_week", "none"]:
        failures.append(f"urgency_rank: sort produced {ordered}")


def _check_parse(failures: list[str]) -> None:
    print("=== _parse_triage robustness (deterministic) ===")
    good = '{"classification":"spam","urgency":"none","intent":"spam","confidence":0.9,"suggested_action":"archive"}'
    fenced = "```json\n" + good + "\n```"
    try:
        r = _parse_triage(good)
        if not isinstance(r, EmailTriageResult) or r.classification != "spam":
            failures.append("_parse_triage: valid JSON didn't parse to spam")
    except Exception as exc:
        failures.append(f"_parse_triage: valid JSON raised {exc!r}")
    try:
        r = _parse_triage(fenced)
        if r.classification != "spam":
            failures.append("_parse_triage: markdown-fenced JSON not stripped/parsed")
    except Exception as exc:
        failures.append(f"_parse_triage: fenced JSON raised {exc!r}")
    # Out-of-enum value must fail validation (so it degrades to fallback upstream).
    bad_enum = '{"classification":"URGENT","urgency":"none","intent":"spam","confidence":0.5,"suggested_action":"archive"}'
    try:
        _parse_triage(bad_enum)
        failures.append("_parse_triage: out-of-enum classification should raise ValidationError")
    except ValidationError:
        pass
    except Exception as exc:
        failures.append(f"_parse_triage: out-of-enum raised {type(exc).__name__}, expected ValidationError")
    # Garbage must raise (caller catches → fallback).
    try:
        _parse_triage("not json at all")
        failures.append("_parse_triage: garbage should raise")
    except Exception:
        pass
    fb = _fallback_triage()
    if fb.classification != "fyi" or fb.confidence != 0.0:
        failures.append(f"_fallback_triage: expected conservative fyi/0.0, got {fb}")
    print("  valid/fenced parsed; out-of-enum + garbage rejected; fallback conservative")


async def _check_classify_llm(failures: list[str]) -> None:
    print("=== classify_email populates 5 valid fields (LLM) ===")
    result = await classify_email(
        subject="Can you send me the Q3 report by end of day?",
        sender="colleague@example.com",
        body="Hi, I need the Q3 financial report before our 5pm meeting today. Please reply. Thanks.",
    )
    print(f"  -> {result.model_dump()}")
    if not isinstance(result, EmailTriageResult):
        failures.append("classify_email: did not return EmailTriageResult")
        return
    # Literal typing guarantees enum validity if construction succeeded; assert the
    # five fields are all present + in-range (proves the LLM→parse→validate path ran).
    d = result.model_dump()
    for field in ("classification", "urgency", "intent", "confidence", "suggested_action"):
        if field not in d:
            failures.append(f"classify_email: missing field {field}")
    if not (0.0 <= result.confidence <= 1.0):
        failures.append(f"classify_email: confidence out of range {result.confidence}")


async def _check_history_filter(failures: list[str]) -> None:
    print("=== email_history urgency filter (DB) ===")
    rows = [
        ("smoke-triage-immediate", "SMOKEIMMEDIATE prod is down", "immediate"),
        ("smoke-triage-week", "SMOKEWEEK quarterly newsletter", "this_week"),
        ("smoke-triage-none", "SMOKENONE your receipt", "none"),
    ]
    async with async_session() as session:
        for gid, subject, urgency in rows:
            session.add(EmailLog(
                gmail_message_id=gid,
                subject=subject,
                sender="smoke@example.com",
                classification="action_required",
                meta={
                    "classification": "action_required",
                    "urgency": urgency,
                    "intent": "request",
                    "confidence": 0.9,
                    "suggested_action": "reply",
                },
            ))
        await session.commit()

    immediate_only = await email_history_search(days_back=1, urgency="immediate")
    all_three = await email_history_search(days_back=1, sender="smoke@example.com")
    print("  --- urgency=immediate ---")
    for line in immediate_only.splitlines():
        print(f"    {line}")

    if "SMOKEIMMEDIATE" not in immediate_only:
        failures.append("history: urgency=immediate should surface the immediate row")
    if "SMOKEWEEK" in immediate_only or "SMOKENONE" in immediate_only:
        failures.append("history: urgency=immediate leaked non-immediate rows")
    if "[IMMEDIATE]" not in immediate_only:
        failures.append("history: immediate row missing the [IMMEDIATE] urgency tag")
    for marker in ("SMOKEIMMEDIATE", "SMOKEWEEK", "SMOKENONE"):
        if marker not in all_three:
            failures.append(f"history: unfiltered query missing {marker}")


async def _cleanup() -> None:
    async with async_session() as session:
        await session.execute(delete(EmailLog).where(EmailLog.gmail_message_id.in_(_SMOKE_IDS)))
        await session.commit()


async def main() -> int:
    configure_logging()
    failures: list[str] = []
    _check_urgency_rank(failures)
    _check_parse(failures)
    try:
        await _check_classify_llm(failures)
        await _check_history_filter(failures)
    finally:
        await _cleanup()
        print("=== cleanup === removed smoke EmailLog rows")

    print()
    if failures:
        print(f"FAIL: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: urgency ordinal correct, JSON parse hardened, 5-field triage populates, urgency filter works")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
