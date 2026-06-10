"""Turn 20.5 task u — golden-query eval harness (LLM-as-judge).

Runs `evals/golden_queries.yaml` against the real agent stack and writes a JSON
report. Design decisions, per the turn's constraints:

- **Cost isolation (footgun):** sets `eval_mode` so every LLM call routes to the
  eval cost counter, never the production daily cap — an eval run can't halt the
  master's agent. Per-run spend is read from that eval counter and reported.
- **Contamination-safety (footgun):** `eval_mode` also makes `persist_node` skip
  Mem0 extraction, so eval turns don't pollute master memory. Seeded RAG corpus
  + audit rows are torn down in a finally.
- **Hard rule is the gate (item #4):** the pass/fail exit code is driven by the
  DETERMINISTIC rule `set(expected_tools) ⊆ set(tools the agent emitted)`. The
  GPT-4o-mini judge runs at temp=0 and its 1-5 scores are reported as a NOISY
  TREND signal — never the gate (a 0.5 drop is indistinguishable from judge noise).
- **Deferred-trigger instruments (the keystone, item #1):** `rag_probe` entries
  capture document_search's `rag_search_complete` kept/dropped audit so HyDE's
  phrasing-mismatch trigger and reranker leak-through are measurable; a
  `capture_audit` entry reads `audit_trail.latency_ms` + the turn `stop_reason`.
- **Honest runtime (item #5):** general queries run concurrently (cap), and the
  wall-clock + per-run cost are reported. Real multi-tool LLM turns take minutes,
  not the plan's optimistic "<60s" — the report states the real number.

Run: `make evals` (or `python -m evals.runner`). Flags: `--limit N`,
`--no-rag`, `--break-tool NAME` (regression demo), `--baseline` (write baseline.json).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
import yaml  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.agent.graph import init_checkpointer  # noqa: E402
from app.agent.runner import run_turn  # noqa: E402
from app.agent.tools import register_all_tools, tool_registry  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.engine import async_session  # noqa: E402
from app.db.models import AuditTrail, DocumentChunk  # noqa: E402
from app.documents.ingestion import ingest_document  # noqa: E402
from app.documents.search import search_documents  # noqa: E402
from app.llm.cost_tracker import CostTracker  # noqa: E402
from app.llm.eval_mode import eval_mode  # noqa: E402
from app.llm.gateway import llm_gateway  # noqa: E402
from app.utils.logging import configure_logging  # noqa: E402

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"
GOLDEN = EVALS_DIR / "golden_queries.yaml"
JUDGE_THRESHOLD = 4.0          # reported trend bar, NOT the gate
CONCURRENCY = 4
_TRAITS = ("relevance", "accuracy", "tone", "completeness")

JUDGE_PROMPT = """You grade an AI personal-assistant's response. Score each axis 1-5
(5 best) and respond with a JSON object ONLY: {{"relevance": n, "accuracy": n, "tone": n, "completeness": n}}.

accuracy especially penalizes fabrication (claiming actions/facts not supported).

User query:
{query}

Criteria the response should satisfy:
{traits}

The assistant's response:
{response}
"""


# --------------------------------------------------------------------------- #
# Capture helpers                                                             #
# --------------------------------------------------------------------------- #
def _tools_called(envelope: dict) -> list[str]:
    """Tool names the agent EMITTED (from AIMessage tool_calls) — selection
    signal, independent of whether they executed or paused for approval."""
    out: list[str] = []
    for m in envelope.get("messages", []):
        if m.get("role") == "ai":
            for tc in m.get("tool_calls") or []:
                if tc.get("name"):
                    out.append(tc["name"])
    return out


def _parse_judge(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    data = json.loads(text)
    return {k: float(data.get(k, 0) or 0) for k in _TRAITS}


async def _judge(query: str, traits: list[str], response: str) -> dict:
    prompt = JUDGE_PROMPT.format(
        query=query,
        traits="\n".join(f"- {t}" for t in traits) or "- (none)",
        response=response or "(empty response)",
    )
    try:
        resp = await llm_gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            task_type="reasoning",
            force_model="fallback",  # GPT-4o-mini
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        return _parse_judge(resp["choices"][0]["message"].get("content") or "")
    except Exception as exc:  # noqa: BLE001 — judge failure must not fail the gate
        return {**{k: 0.0 for k in _TRAITS}, "judge_error": str(exc)[:160]}


# --------------------------------------------------------------------------- #
# Per-entry runners                                                           #
# --------------------------------------------------------------------------- #
async def _run_general(entry: dict, sem: asyncio.Semaphore) -> dict:
    async with sem:
        thread_id = f"eval-{uuid.uuid4().hex[:10]}"
        expected = set(entry.get("expected_tools", []))
        try:
            envelope = await run_turn(entry["query"], thread_id, "eval", "eval-runner")
        except Exception as exc:  # noqa: BLE001
            return {
                "id": entry["id"], "category": entry.get("category"), "kind": "general",
                "error": str(exc)[:200], "hard_rule_pass": not expected, "thread_id": thread_id,
            }
        actual = _tools_called(envelope)
        record = {
            "id": entry["id"],
            "category": entry.get("category"),
            "kind": "general",
            "query": entry["query"],
            "expected_tools": sorted(expected),
            "actual_tools": actual,
            "hard_rule_pass": expected.issubset(set(actual)),
            "stop_reason": envelope.get("stop_reason"),
            "thread_id": thread_id,
        }
        if "expect_stop_reason" in entry:
            record["stop_reason_match"] = envelope.get("stop_reason") == entry["expect_stop_reason"]
        if entry.get("capture_audit"):
            async with async_session() as session:
                rows = (await session.execute(
                    select(AuditTrail.tool_name, AuditTrail.latency_ms)
                    .where(AuditTrail.thread_id == thread_id)
                )).all()
            record["audit_latency_ms"] = {r.tool_name: r.latency_ms for r in rows}
        record["scores"] = await _judge(
            entry["query"], entry.get("traits", []), envelope.get("response", "")
        )
        return record


async def _run_rag_probe(entry: dict) -> dict:
    """Capture the rag_search_complete kept/dropped audit for the deferred-lift
    triggers. Run serially (capture_logs is process-global, not task-safe)."""
    query = entry["query"]
    expect = entry.get("expect_hit_filename")
    with structlog.testing.capture_logs() as captured:
        await search_documents(query=query)
    events = [e for e in captured if e.get("event") == "rag_search_complete"]
    ev = events[-1] if events else {}
    kept = ev.get("kept_candidates") or []
    dropped = ev.get("dropped_candidates") or []
    kept_files = [k["filename"] for k in kept]
    dropped_for_expect = [d for d in dropped if d.get("filename") == expect]
    return {
        "id": entry["id"],
        "category": entry.get("category"),
        "kind": "rag_probe",
        "query": query,
        "expect_hit_filename": expect,
        "kept_files": kept_files,
        "kept_scores": [{"file": k["filename"], "rerank": k["rerank_score"]} for k in kept],
        # HyDE trigger: the on-topic doc exists but the vocabulary-mismatched query
        # failed to KEEP it → a phrasing-mismatch recall failure worth a HyDE lift.
        "hyde_candidate": expect not in kept_files,
        # leak-through visibility: the dropped on-topic chunk's rerank score (if any).
        "expect_dropped_scores": [
            {"rerank": round(d["rerank_score"], 4), "reason": d.get("drop_reason")}
            for d in dropped_for_expect
        ],
        "corpus_size": ev.get("corpus_size"),
    }


# --------------------------------------------------------------------------- #
# Seed / teardown                                                             #
# --------------------------------------------------------------------------- #
async def _seed_corpus(rag_entries: list[dict], tmpdir: Path) -> list[str]:
    filenames: list[str] = []
    for entry in rag_entries:
        corpus = entry["corpus"]
        path = tmpdir / corpus["filename"]
        path.write_text(corpus["content"], encoding="utf-8")
        await ingest_document(str(path), corpus["filename"])
        filenames.append(corpus["filename"])
    return filenames


async def _teardown(corpus_filenames: list[str]) -> None:
    async with async_session() as session:
        if corpus_filenames:
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.filename.in_(corpus_filenames))
            )
        await session.execute(
            delete(AuditTrail).where(AuditTrail.thread_id.like("eval-%"))
        )
        await session.commit()


# --------------------------------------------------------------------------- #
# Main                                                                        #
# --------------------------------------------------------------------------- #
async def _bootstrap() -> None:
    configure_logging()
    await init_checkpointer()
    register_all_tools()
    await tool_registry.index_all_tools()


def _summarize(records: list[dict]) -> dict:
    general = [r for r in records if r.get("kind") == "general"]
    rag = [r for r in records if r.get("kind") == "rag_probe"]
    hard_fail = [r["id"] for r in general if not r.get("hard_rule_pass")]
    score_vals = [r["scores"] for r in general if isinstance(r.get("scores"), dict)]
    avg = {}
    for k in _TRAITS:
        nums = [s[k] for s in score_vals if isinstance(s.get(k), (int, float)) and s.get(k)]
        avg[k] = round(sum(nums) / len(nums), 2) if nums else 0.0
    overall = round(sum(avg.values()) / len(avg), 2) if avg else 0.0
    return {
        "general_count": len(general),
        "rag_probe_count": len(rag),
        "hard_rule_failures": hard_fail,
        "hard_rule_pass_rate": round(1 - len(hard_fail) / len(general), 3) if general else 1.0,
        "avg_scores": avg,
        "avg_overall": overall,
        "judge_threshold": JUDGE_THRESHOLD,
        "hyde_candidates": [r["id"] for r in rag if r.get("hyde_candidate")],
    }


async def run_eval(limit: int | None, no_rag: bool, break_tool: str | None, baseline: bool) -> int:
    eval_mode.set(True)  # isolate cost-cap + Mem0 for the whole run (inherited by gather tasks)
    await _bootstrap()
    if break_tool:
        removed = tool_registry._entries.pop(break_tool, None)
        print(f"[regression-demo] removed tool {break_tool!r} from registry: {'ok' if removed else 'not found'}")

    entries = yaml.safe_load(GOLDEN.read_text())
    general_entries = [e for e in entries if not e.get("rag_probe")]
    rag_entries = [e for e in entries if e.get("rag_probe")]
    if limit is not None:
        general_entries = general_entries[:limit]
    if no_rag:
        rag_entries = []

    tracker = CostTracker(daily_cap=settings.DAILY_LLM_SPEND_CAP_USD, soft_cap_pct=settings.DAILY_LLM_SOFT_CAP_PCT)
    cost_before = await tracker.get_today_spend()  # reads the EVAL counter (eval_mode set)
    started = time.monotonic()
    records: list[dict] = []
    corpus_filenames: list[str] = []

    with tempfile.TemporaryDirectory(prefix="jarvis-evals-") as tmp:
        try:
            if rag_entries:
                corpus_filenames = await _seed_corpus(rag_entries, Path(tmp))

            sem = asyncio.Semaphore(CONCURRENCY)
            general_results = await asyncio.gather(*(_run_general(e, sem) for e in general_entries))
            records.extend(general_results)
            for e in rag_entries:  # serial — capture_logs is global
                records.append(await _run_rag_probe(e))
        finally:
            await _teardown(corpus_filenames)

    runtime_s = round(time.monotonic() - started, 1)
    cost_after = await tracker.get_today_spend()
    summary = _summarize(records)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": runtime_s,
        "eval_cost_usd": round(max(0.0, cost_after - cost_before), 6),
        "break_tool": break_tool,
        "summary": summary,
        "records": records,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / ("baseline.json" if baseline else f"{int(started)}.json")
    out.write_text(json.dumps(report, indent=2))

    # ---- console summary ----
    print(f"\n=== eval report ({out.name}) ===")
    print(f"runtime: {runtime_s}s   eval_cost: ${report['eval_cost_usd']}  (isolated counter — production cap untouched)")
    print(f"hard-rule pass rate: {summary['hard_rule_pass_rate']}  failures: {summary['hard_rule_failures'] or 'none'}")
    print(f"judge avg (NOISY TREND, not the gate): {summary['avg_overall']}  threshold {JUDGE_THRESHOLD}  per-axis {summary['avg_scores']}")
    if summary["hyde_candidates"]:
        print(f"HyDE candidates (phrasing-mismatch recall misses): {summary['hyde_candidates']}")
    if summary["avg_overall"] and summary["avg_overall"] < JUDGE_THRESHOLD:
        print(f"NOTE: judge avg {summary['avg_overall']} < {JUDGE_THRESHOLD} — trend signal only, NOT a failure.")

    # GATE = deterministic hard rule only (judge is too noisy to gate on).
    gate_failed = bool(summary["hard_rule_failures"])
    print("RESULT:", "FAIL (hard-rule regression)" if gate_failed else "PASS (no hard-rule failures)")
    return 1 if gate_failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Golden-query eval harness")
    ap.add_argument("--limit", type=int, default=None, help="run only the first N general queries")
    ap.add_argument("--no-rag", action="store_true", help="skip rag_probe entries")
    ap.add_argument("--break-tool", default=None, help="remove a tool to demo regression detection")
    ap.add_argument("--baseline", action="store_true", help="write results/baseline.json")
    args = ap.parse_args()
    return asyncio.run(run_eval(args.limit, args.no_rag, args.break_tool, args.baseline))


if __name__ == "__main__":
    sys.exit(main())
