"""Memory consolidation — collapse the Mem0 corpus's near-duplicate and
superseded memories (4.B.2 steps 4/5).

The corpus accumulated heavy duplication while dedup-on-write was off (the same
fact re-extracted every session — "User's name is Mahesh" ×33) plus stale
superseded facts (an ex-partner's name still stored next to the current one).
4.B.1 restored the true cosine, so similar memories now actually cluster.

Pipeline:
  1. Load every memory (id, text, created_at, vector) — the FULL corpus
     (get_all's truncation was fixed in 4.B.2 step 1; here we read vectors too).
  2. Cluster by true cosine >= SIM_THRESHOLD (connected components).
  3. Adjudicate each multi-member cluster:
       - exact-text repeats          → auto-merge (keep newest, drop rest), no LLM.
       - varying text                → LLM decides duplicate / superseded / distinct,
                                        CONSERVATIVELY (keep both when unsure).
  4. Keep only drops at/above MIN_CONFIDENCE.

Safety (it deletes the master's real memories):
  - DRY-RUN by default — returns the plan, mutates nothing. The apply path is
    meant to run only after the master reviews a dry-run.
  - Conservative — a memory is dropped only when a confident decision folds it
    into a surviving sibling; distinct facts are never dropped.
  - Every drop is logged; the survivor is kept untouched (we delete the
    redundant/stale row, we don't rewrite the canonical).
  - Idempotent — a second run over a consolidated corpus produces an empty plan.
"""
import json
from dataclasses import dataclass, field

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.config import settings
from app.db.engine import async_session
from app.llm.gateway import llm_gateway
from app.memory.manager import get_memory
from app.utils.logging import get_logger

logger = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Data shapes
# --------------------------------------------------------------------------- #
@dataclass
class _Row:
    mem_id: str
    content: str
    created_at: str
    vector: np.ndarray


class _Drop(BaseModel):
    """One memory the adjudicator wants to remove, folded into a survivor.

    ``confidence`` is PER-DROP — a borderline drop must not ride in on a
    confident cluster's score. ``None`` from the LLM falls back to the cluster
    confidence in ``_llm_decision``."""
    drop_id: str
    folds_into_id: str
    reason: str = "duplicate"  # "duplicate" | "superseded"
    confidence: float | None = None


class _ClusterDecision(BaseModel):
    drops: list[_Drop] = Field(default_factory=list)
    confidence: float = 0.0   # cluster-level fallback when a drop omits its own
    note: str = ""


@dataclass
class ConsolidationReport:
    corpus_before: int
    clusters_examined: int
    auto_merge_clusters: int
    llm_clusters: int
    dry_run: bool
    # each drop: {drop_id, folds_into_id, reason, confidence, lossless, drop_text, keep_text}
    drops: list[dict] = field(default_factory=list)
    apply_reasons: list[str] | None = None     # apply filter actually used (None = all reasons)
    apply_lossless_only: bool = False
    applied: int = 0
    errors: int = 0

    def selected(self) -> list[dict]:
        """The drops that the apply filter would actually delete (the full
        ``drops`` list is the complete plan; this is the gated subset)."""
        return [
            d for d in self.drops
            if (self.apply_reasons is None or d["reason"] in self.apply_reasons)
            and (not self.apply_lossless_only or d["lossless"])
        ]

    @property
    def planned(self) -> int:
        return len(self.drops)

    @property
    def selected_count(self) -> int:
        return len(self.selected())

    @property
    def corpus_after(self) -> int:
        removed = self.applied if not self.dry_run else self.selected_count
        return self.corpus_before - removed

    def by_reason(self, drops: list[dict] | None = None) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in (self.drops if drops is None else drops):
            out[d["reason"]] = out.get(d["reason"], 0) + 1
        return out

    def summary(self) -> dict:
        return {
            "corpus_before": self.corpus_before,
            "corpus_after": self.corpus_after,
            "planned_drops": self.planned,
            "planned_by_reason": self.by_reason(),
            "selected_for_apply": self.selected_count,
            "selected_by_reason": self.by_reason(self.selected()),
            "apply_reasons": self.apply_reasons,
            "apply_lossless_only": self.apply_lossless_only,
            "clusters_examined": self.clusters_examined,
            "auto_merge_clusters": self.auto_merge_clusters,
            "llm_clusters": self.llm_clusters,
            "dry_run": self.dry_run,
            "applied": self.applied,
            "errors": self.errors,
        }


# --------------------------------------------------------------------------- #
# Corpus load + clustering
# --------------------------------------------------------------------------- #
def _parse_vector(raw) -> np.ndarray:
    if isinstance(raw, str):
        return np.array([float(x) for x in raw.strip("[]").split(",")], dtype=np.float32)
    return np.array(raw, dtype=np.float32)


async def _load_corpus() -> list[_Row]:
    """Every master memory with its stored vector. Reads pgvector directly — the
    vector isn't exposed through Mem0's get_all, and consolidation needs it for
    clustering (same true cosine the search uses)."""
    async with async_session() as session:
        rows = (await session.execute(text(
            "SELECT id, payload->>'data', payload->>'created_at', vector "
            "FROM mem0_memories WHERE payload->>'user_id' = :u"
        ), {"u": get_memory().mem0.USER_ID})).all()
    out: list[_Row] = []
    for r in rows:
        if r[1] is None or r[3] is None:
            continue
        out.append(_Row(mem_id=str(r[0]), content=r[1], created_at=r[2] or "", vector=_parse_vector(r[3])))
    return out


def _cluster(rows: list[_Row], threshold: float) -> list[list[int]]:
    """Connected components over edges where cosine >= threshold. Returns
    clusters of >= 2 row-indices (singletons are nothing to consolidate)."""
    n = len(rows)
    if n < 2:
        return []
    mat = np.vstack([r.vector for r in rows]).astype(np.float32)
    mat /= (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
    sim = mat @ mat.T

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = np.argwhere(np.triu(sim >= threshold, k=1))
    for i, j in pairs:
        ri, rj = find(int(i)), find(int(j))
        if ri != rj:
            parent[ri] = rj

    comp: dict[int, list[int]] = {}
    for i in range(n):
        comp.setdefault(find(i), []).append(i)
    return [c for c in comp.values() if len(c) > 1]


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split()).rstrip(".")


# --------------------------------------------------------------------------- #
# Adjudication
# --------------------------------------------------------------------------- #
_ADJUDICATION_PROMPT = """You are consolidating a personal AI assistant's long-term memory about its single user. Below is a cluster of memories that are textually similar. Decide which memories (if any) are REDUNDANT and should be removed, keeping the best survivor.

A memory may be removed only as:
- "duplicate": it states the SAME fact with the SAME specific values as another memory here → keep the most complete one, drop the other(s).
- "superseded": it is an OLDER memory whose fact a NEWER memory in this cluster updates → keep the NEWER, drop the older STALE one.

CRITICAL — do NOT lose information:
- If two memories differ in any SPECIFIC VALUE — a date, a name, a number, a place, a time — they are DIFFERENT FACTS. Do NOT drop either as a "duplicate" (e.g. "met on June 11" and "met on June 17" are two different events; "deadline is June 13" and "deadline was initially June 13" carry different status — keep both).
- Only mark "superseded" when the SAME attribute of the SAME subject has a NEW value AND created_at clearly shows which is newer AND the older is genuinely obsolete. Resolve by TRUTH + timestamp, never by which phrasing sounds more current.
- When in any doubt, keep BOTH and list no drop. A wrongly kept duplicate is harmless; a wrongly dropped distinct fact is permanent data loss.

Use created_at to tell newer from older.

Memories in this cluster:
{rows}

Respond with ONLY a JSON object:
{{"drops": [{{"drop_id": "<id to remove>", "folds_into_id": "<surviving id it is redundant with>", "reason": "duplicate" or "superseded", "confidence": <0.0-1.0 your confidence in THIS specific drop>}}], "note": "<one short sentence>"}}
List a drop only when confident. folds_into_id MUST be an id in this cluster that you are NOT dropping. If nothing should be dropped, return an empty drops list."""


def _auto_decision(cluster: list[_Row]) -> _ClusterDecision | None:
    """If every row in the cluster is the same normalized text, it's pure
    re-extraction: keep the newest, drop the rest. No LLM needed."""
    if len({_norm(r.content) for r in cluster}) != 1:
        return None
    survivor = max(cluster, key=lambda r: r.created_at)
    return _ClusterDecision(
        drops=[_Drop(drop_id=r.mem_id, folds_into_id=survivor.mem_id, reason="duplicate", confidence=1.0)
               for r in cluster if r.mem_id != survivor.mem_id],
        confidence=1.0,
        note="exact-text re-extraction",
    )


async def _llm_decision(cluster: list[_Row]) -> _ClusterDecision:
    rows_blob = "\n".join(
        f'- id={r.mem_id} | created_at={r.created_at or "?"} | "{r.content}"' for r in cluster
    )
    valid_ids = {r.mem_id for r in cluster}
    try:
        resp = await llm_gateway.complete(
            messages=[{"role": "user", "content": _ADJUDICATION_PROMPT.format(rows=rows_blob)}],
            force_model=settings.MEM0_CONSOLIDATION_MODEL_SLOT,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = resp["choices"][0]["message"].get("content") or "{}"
        decision = _ClusterDecision.model_validate(json.loads(content))
    except Exception as exc:  # noqa: BLE001 — a bad adjudication must never drop a memory
        logger.warning("consolidation_llm_decision_failed", error=f"{type(exc).__name__}: {exc}")
        return _ClusterDecision()

    # Defensive: only honor drops whose ids are real and whose survivor is in the
    # cluster AND not itself dropped. Protects against a hallucinated id.
    drop_ids = {d.drop_id for d in decision.drops}
    safe = [
        d for d in decision.drops
        if d.drop_id in valid_ids
        and d.folds_into_id in valid_ids
        and d.folds_into_id not in drop_ids
        and d.drop_id != d.folds_into_id
    ]
    # Per-drop confidence: fall back to the cluster score only when the model
    # omitted it, so one borderline drop can't ride in on a confident cluster.
    for d in safe:
        if d.confidence is None:
            d.confidence = decision.confidence
    decision.drops = safe
    return decision


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def _drop_dict(d: _Drop, drop_row: _Row, keep_row: _Row) -> dict:
    conf = d.confidence if d.confidence is not None else 0.0
    return {
        "drop_id": d.drop_id,
        "folds_into_id": d.folds_into_id,
        "reason": d.reason,
        "confidence": round(float(conf), 3),
        # provably lossless ⇔ the dropped row's text is identical to its survivor's,
        # so deleting it cannot lose information (an exact re-extraction).
        "lossless": _norm(drop_row.content) == _norm(keep_row.content),
        "drop_text": drop_row.content,
        "keep_text": keep_row.content,
    }


def _lossless_plan(rows: list[_Row]) -> list[dict]:
    """Provably-lossless plan — NO LLM, NO clustering. Group the corpus by
    normalized text; in any group with repeats keep the newest and drop the rest.
    Every dropped row is textually identical to its survivor, so nothing is lost.
    This is the safe core of consolidation (exact re-extractions like "User's
    name is Mahesh" ×33) and the right first apply."""
    groups: dict[str, list[_Row]] = {}
    for r in rows:
        groups.setdefault(_norm(r.content), []).append(r)
    plan: list[dict] = []
    for g in groups.values():
        if len(g) < 2:
            continue
        survivor = max(g, key=lambda r: r.created_at)
        for r in g:
            if r.mem_id != survivor.mem_id:
                plan.append(_drop_dict(
                    _Drop(drop_id=r.mem_id, folds_into_id=survivor.mem_id,
                          reason="duplicate", confidence=1.0),
                    r, survivor))
    return plan


async def run_consolidation(
    *,
    dry_run: bool = True,
    sim_threshold: float | None = None,
    min_confidence: float | None = None,
    max_clusters: int | None = None,
    reasons: set[str] | None = None,
    lossless_only: bool = False,
) -> ConsolidationReport:
    """Consolidate the Mem0 corpus. DRY-RUN by default.

    Apply-safety filters:
      - ``lossless_only=True`` → SKIP the LLM entirely and plan only
        provably-lossless exact-text duplicate collapses. Fast, deterministic,
        cannot lose information — the safe FIRST apply.
      - ``reasons={"duplicate"}`` → in a full run, only drops of these reasons are
        applied (e.g. hold ``"superseded"`` out until entity-attribute
        supersession lands and a human has reviewed it).

    The full ``report.drops`` is always the complete plan; ``report.selected()``
    is the gated subset that an apply would delete. ``max_clusters`` caps LLM
    adjudication (None = all); a cap is logged so a bounded run never reads as
    "covered everything."
    """
    sim_threshold = settings.MEM0_CONSOLIDATION_SIM_THRESHOLD if sim_threshold is None else sim_threshold
    min_confidence = settings.MEM0_CONSOLIDATION_MIN_CONFIDENCE if min_confidence is None else min_confidence

    rows = await _load_corpus()
    by_id = {r.mem_id: r for r in rows}
    report = ConsolidationReport(
        corpus_before=len(rows), clusters_examined=0, auto_merge_clusters=0,
        llm_clusters=0, dry_run=dry_run,
        apply_reasons=sorted(reasons) if reasons else None,
        apply_lossless_only=lossless_only,
    )

    if lossless_only:
        report.drops = _lossless_plan(rows)
        logger.info("consolidation_start", corpus=len(rows), mode="lossless_only",
                    dry_run=dry_run, planned=len(report.drops))
    else:
        clusters = _cluster(rows, sim_threshold)
        clusters.sort(key=len, reverse=True)
        logger.info(
            "consolidation_start",
            corpus=len(rows), clusters=len(clusters), sim_threshold=sim_threshold,
            min_confidence=min_confidence, dry_run=dry_run,
            cap=max_clusters if max_clusters is not None else "none",
        )
        to_examine = clusters if max_clusters is None else clusters[:max_clusters]
        if max_clusters is not None and len(clusters) > max_clusters:
            logger.warning(
                "consolidation_cluster_cap",
                examined=max_clusters, total=len(clusters),
                skipped=len(clusters) - max_clusters,
                message="capped this run — remaining clusters consolidate on a later run",
            )
        for cluster_idx in to_examine:
            cluster = [rows[i] for i in cluster_idx]
            report.clusters_examined += 1
            decision = _auto_decision(cluster)
            if decision is not None:
                report.auto_merge_clusters += 1
            else:
                decision = await _llm_decision(cluster)
                report.llm_clusters += 1
            for d in decision.drops:
                conf = d.confidence if d.confidence is not None else 0.0
                if conf < min_confidence:   # PER-DROP gate
                    continue
                keep = by_id.get(d.folds_into_id)
                drop = by_id.get(d.drop_id)
                if drop is None or keep is None:
                    continue
                report.drops.append(_drop_dict(d, drop, keep))

    # Apply only the SELECTED drops (reason + lossless filtered) — never the whole
    # plan when a safety filter is set.
    if not dry_run:
        mem = get_memory().mem0
        for d in report.selected():
            try:
                await mem.delete(d["drop_id"])
                report.applied += 1
                logger.info(
                    "consolidation_dropped",
                    drop_id=d["drop_id"], folds_into=d["folds_into_id"],
                    reason=d["reason"], confidence=d["confidence"], lossless=d["lossless"],
                    drop_text=d["drop_text"][:80], keep_text=d["keep_text"][:80],
                )
            except Exception as exc:  # noqa: BLE001 — one failed delete shouldn't abort the batch
                report.errors += 1
                logger.error("consolidation_drop_failed", drop_id=d["drop_id"], error=str(exc))

    logger.info("consolidation_done", **report.summary())
    return report
