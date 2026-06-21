"""Retroactive meta-noise purge — apply the durable-fact extraction criteria to
the EXISTING corpus (4.B.2 step 2b).

Extraction-scoping (JARVIS_EXTRACTION_INSTRUCTIONS) fixed NEW writes, but the
corpus still holds pre-scoping junk that outranks real answers in recall — e.g.
"User asked about their girlfriend's name" ranks #1 for "who is my girlfriend",
plus assistant-statements and task-status rows. This pass runs a batched LLM
classifier over every stored memory, labels each durable-user-fact vs noise
(recorded_question / assistant_statement / task_status / transient), and drops
the noise.

Safety mirrors consolidation: DRY-RUN by default (returns the plan, mutates
nothing), confidence-gated, every drop logged, conservative (keep when unsure).
The apply path is meant to run only after a backup + a master-reviewed dry-run —
it is NEVER auto-applied.
"""
import asyncio
import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import settings
from app.db.engine import async_session
from app.llm.gateway import llm_gateway
from app.memory.manager import get_memory
from app.utils.logging import get_logger

logger = get_logger(__name__)

_NOISE_CATEGORIES = ("recorded_question", "assistant_statement", "task_status", "transient")


class _Classification(BaseModel):
    mem_id: str
    label: str = "durable"          # "durable" | "noise"
    category: str = ""              # one of _NOISE_CATEGORIES when label == "noise"
    confidence: float = 0.0


class _BatchResult(BaseModel):
    items: list[_Classification] = Field(default_factory=list)


@dataclass
class NoisePurgeReport:
    corpus_before: int
    classified: int
    dry_run: bool
    min_confidence: float
    drops: list[dict] = field(default_factory=list)  # {mem_id, category, confidence, text}
    applied: int = 0
    errors: int = 0

    @property
    def planned(self) -> int:
        return len(self.drops)

    @property
    def corpus_after(self) -> int:
        return self.corpus_before - (self.applied if not self.dry_run else self.planned)

    def by_category(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.drops:
            out[d["category"]] = out.get(d["category"], 0) + 1
        return out

    def summary(self) -> dict:
        return {
            "corpus_before": self.corpus_before,
            "corpus_after": self.corpus_after,
            "classified": self.classified,
            "planned_drops": self.planned,
            "by_category": self.by_category(),
            "min_confidence": self.min_confidence,
            "dry_run": self.dry_run,
            "applied": self.applied,
            "errors": self.errors,
        }


_CLASSIFY_PROMPT = """You are auditing a personal AI assistant's long-term memory. For EACH memory below, decide whether it is a DURABLE FACT ABOUT THE USER worth keeping, or NOISE to remove.

KEEP (label "durable") — a lasting fact about the user:
- Stable preferences (likes/dislikes, communication style, food, tools, brands).
- Durable personal details (name, relationships, important recurring dates, home location, profession).
- Health & dietary facts (allergies, restrictions, routines).
- Lasting goals and standing commitments.

REMOVE (label "noise") — categorize as exactly one of:
- "recorded_question": a record that the user ASKED or INQUIRED something ("User asked about their girlfriend's name", "User inquired about events on Saturday"). A question is not a fact.
- "assistant_statement": something the ASSISTANT said, did, or can do ("Assistant can manage the calendar", "Assistant confirmed the meeting", "Assistant drafted an email").
- "task_status": the status or outcome of a one-off task ("the email was sent", "both tools completed", "reminder was set").
- "transient": a one-off request or ephemeral detail with no lasting value about the user.

DURABLE-FACT OVERRIDE (highest priority): if a memory STATES a concrete durable fact about the user — their birthday, an allergy or dietary fact, their name, a partner/relationship name, where they live, their profession — label it "durable" EVEN when wrapped in assistant or question framing. "Assistant noted the user's birthday is August 27, 1998" STATES the birthday → durable. "User stated he has no allergies" STATES a health fact → durable. Only label noise when the memory records a QUESTION, an ASSISTANT capability/action/story, or a one-off TASK with NO durable user fact stated in it.

Be CONSERVATIVE: when unsure, KEEP it (label "durable"). Only label "noise" when it clearly fits a category. A specific durable fact (a date, a name, a place) is NOT noise just because it is event-related.

Memories:
{rows}

Return ONLY a JSON object classifying EVERY id listed:
{{"items": [{{"mem_id": "<id>", "label": "durable" or "noise", "category": "<a noise category, or empty if durable>", "confidence": <0.0-1.0 confidence in THIS label>}}]}}"""


async def _load_texts() -> list[tuple[str, str]]:
    """(id, text) for every master memory. No vectors — classification is textual."""
    async with async_session() as session:
        rows = (await session.execute(text(
            "SELECT id, payload->>'data' FROM mem0_memories WHERE payload->>'user_id' = :u"
        ), {"u": get_memory().mem0.USER_ID})).all()
    return [(str(r[0]), r[1]) for r in rows if r[1]]


async def _classify_batch(batch: list[tuple[str, str]]) -> list[_Classification]:
    rows_blob = "\n".join(f'- id={mid} | "{txt}"' for mid, txt in batch)
    valid = {mid for mid, _ in batch}
    try:
        resp = await llm_gateway.complete(
            messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(rows=rows_blob)}],
            force_model=settings.MEM0_CONSOLIDATION_MODEL_SLOT,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp["choices"][0]["message"].get("content") or "{}"
        result = _BatchResult.model_validate(json.loads(content))
    except Exception as exc:  # noqa: BLE001 — a bad classification must never drop a memory
        logger.warning("noise_purge_batch_failed", size=len(batch), error=f"{type(exc).__name__}: {exc}")
        return []
    # Only honor classifications for ids we actually sent (guard against hallucinated ids).
    return [c for c in result.items if c.mem_id in valid]


def _states_durable_fact(text: str) -> bool:
    """Deterministic durable-fact protector — True when the text STATES a
    high-value durable fact (so it must not be purged as noise, regardless of the
    LLM's label — the LLM is non-deterministic and wraps these in question /
    assistant framing). Matches STATEMENTS, not topic mentions: "birthday is X" /
    "name is Mahesh" / "no allergies" are protected; "asked about her name" /
    "name is not recorded" still purge. Keyword anchors are case-insensitive;
    identity/relationship/place facts additionally require a Capitalized
    name/place in the ORIGINAL text (the proper-noun signal of a real value)."""
    t = text or ""
    low = t.lower()
    # health / dietary / birth facts — keyword statements
    if re.search(r"\bbirthday\s+(?:is|as|on|:)|\bborn\s+(?:on|in)\b", low):
        return True
    if re.search(r"\ballergic\s+to\b|\b(?:no|any)\s+allergies\b|\bnot\s+have\s+any\s+allergies\b", low):
        return True
    if re.search(r"\bdietary\b|\bvegetarian\b|\bvegan\b", low):
        return True
    # identity / relationship / location — require a Capitalized name/place
    if re.search(r"\bname\s+is\s+[A-Z][a-z]+", t):
        return True
    if re.search(r"\b(?:girlfriend|partner|wife|husband|fianc\w+)(?:'s)?\s+(?:name\s+is\s+)?[A-Z][a-z]+", t):
        return True
    return bool(re.search(r"\blives?\s+in\s+[A-Z][a-z]+|\bworks?\s+(?:as|at)\s+[A-Z][a-z]+", t))


def _should_drop(c: _Classification, min_confidence: float, text: str = "") -> bool:
    """Delete-path gate: drop ONLY a confident, validly-categorized noise label —
    AND never a memory that STATES a durable fact (deterministic veto over the
    LLM). Durable / low-confidence / unknown-category / durable-fact-stating are
    all kept. Conservative by construction."""
    if _states_durable_fact(text):
        return False
    return (
        c.label == "noise"
        and c.category in _NOISE_CATEGORIES
        and c.confidence >= min_confidence
    )


async def run_noise_purge(
    *,
    dry_run: bool = True,
    min_confidence: float | None = None,
    batch_size: int | None = None,
    concurrency: int | None = None,
) -> NoisePurgeReport:
    """Classify the whole corpus durable vs noise and (optionally) drop the noise.
    DRY-RUN by default. NEVER auto-applied — backup + review first."""
    min_confidence = settings.MEM0_NOISE_PURGE_MIN_CONFIDENCE if min_confidence is None else min_confidence
    batch_size = settings.MEM0_NOISE_PURGE_BATCH_SIZE if batch_size is None else batch_size
    concurrency = settings.MEM0_NOISE_PURGE_CONCURRENCY if concurrency is None else concurrency

    corpus = await _load_texts()
    text_by_id = dict(corpus)
    batches = [corpus[i:i + batch_size] for i in range(0, len(corpus), batch_size)]
    logger.info("noise_purge_start", corpus=len(corpus), batches=len(batches),
                min_confidence=min_confidence, dry_run=dry_run)

    sem = asyncio.Semaphore(concurrency)

    async def _run_batch(b):
        async with sem:
            return await _classify_batch(b)

    results = await asyncio.gather(*[_run_batch(b) for b in batches])

    report = NoisePurgeReport(
        corpus_before=len(corpus), classified=0, dry_run=dry_run, min_confidence=min_confidence,
    )
    for batch_result in results:
        for c in batch_result:
            report.classified += 1
            if _should_drop(c, min_confidence, text_by_id.get(c.mem_id, "")):
                report.drops.append({
                    "mem_id": c.mem_id,
                    "category": c.category,
                    "confidence": round(float(c.confidence), 3),
                    "text": text_by_id.get(c.mem_id, ""),
                })

    if not dry_run:
        mem = get_memory().mem0
        for d in report.drops:
            try:
                await mem.delete(d["mem_id"])
                report.applied += 1
                logger.info("noise_purge_dropped", mem_id=d["mem_id"], category=d["category"],
                            confidence=d["confidence"], text=d["text"][:80])
            except Exception as exc:  # noqa: BLE001 — one failed delete shouldn't abort the batch
                report.errors += 1
                logger.error("noise_purge_drop_failed", mem_id=d["mem_id"], error=str(exc))

    logger.info("noise_purge_done", **report.summary())
    return report
