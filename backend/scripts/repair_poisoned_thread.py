"""Repair a committed thread poisoned by malformed tool-call residue (D22).

A thread bricks when a committed AIMessage carries an unanswerable tool call in a
field the `.tool_calls` audits can't see (`invalid_tool_calls` + the raw mirror in
`additional_kwargs["tool_calls"]` — the trpv0ek1t shape that bricked web:master):
ChatLiteLLM's serializer resurrects the raw mirror on the wire → OpenAI 400s every
turn. This tool applies the SAME normalize logic the runtime uses
(`app.agent.message_repair`) to the committed head, durably:

  - divergent residue → same-id sanitized replace (position + history preserved);
  - truly-unanswered PARSED tool_calls → synthetic placeholder ToolMessage appended
    durably (wire adjacency is normalized per-call by `repair_orphaned_tool_calls`).

Safety: a RAW-SQL dump of the thread's checkpoints / checkpoint_blobs /
checkpoint_writes rows is written to backups/ BEFORE any write. Idempotent — a
second run finds nothing and writes nothing. The repair is an `aupdate_state`
(a NEW child checkpoint) — no history rewrite, the conversation survives intact.

Usage (inside the backend container — imports the app):
    python scripts/repair_poisoned_thread.py web:master
    python scripts/repair_poisoned_thread.py web:master --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage


async def _dump_thread_rows(thread_id: str, dump_dir: Path) -> Path:
    """Raw-SQL dump of every checkpointer row for the thread — the pre-write safety
    net. bytea → base64 so the JSON round-trips losslessly."""
    from sqlalchemy import text

    from app.db.engine import async_session

    def _enc(v):
        if isinstance(v, (bytes, memoryview)):
            return {"__bytea_b64__": base64.b64encode(bytes(v)).decode()}
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    dump: dict[str, list] = {}
    async with async_session() as s:
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            rows = (await s.execute(
                text(f"SELECT * FROM {table} WHERE thread_id = :t"), {"t": thread_id}
            )).mappings().all()
            dump[table] = [{k: _enc(v) for k, v in dict(r).items()} for r in rows]

    dump_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe = thread_id.replace(":", "_").replace("/", "_")
    path = dump_dir / f"thread_dump_{safe}_{ts}.json"
    path.write_text(json.dumps(dump, default=str))
    counts = {t: len(r) for t, r in dump.items()}
    print(f"[dump] {path}  rows={counts}")
    return path


def _find_repairs(messages: list) -> tuple[list, list]:
    """(same-id sanitized replacements, synthetic ToolMessages for unanswered
    PARSED calls) — the durable half of the runtime normalize logic."""
    from app.agent.message_repair import (
        ORPHAN_PLACEHOLDER,
        strip_divergent_tool_call_residue,
    )

    replacements = [
        fixed for m in messages
        if (fixed := strip_divergent_tool_call_residue(m)) is not None
    ]
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    synthetics = [
        ToolMessage(content=ORPHAN_PLACEHOLDER, tool_call_id=tc_id)
        for m in messages if isinstance(m, AIMessage)
        for tc in (m.tool_calls or [])
        if (tc_id := (tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)))
        and tc_id not in answered
    ]
    return replacements, synthetics


def _wire_audit(messages: list) -> list[str]:
    """Round-trip proof: serialize every message through ChatLiteLLM's ACTUAL
    outbound converter and verify no assistant tool_call is left unanswered by
    the immediately-following tool messages — under BOTH branches of the elif."""
    from langchain_litellm.chat_models.litellm import _convert_message_to_dict

    wire = [_convert_message_to_dict(m) for m in messages]
    problems: list[str] = []
    for i, d in enumerate(wire):
        if d.get("role") != "assistant" or not d.get("tool_calls"):
            continue
        ids = {c.get("id") for c in d["tool_calls"]}
        j = i + 1
        while j < len(wire) and wire[j].get("role") == "tool":
            ids.discard(wire[j].get("tool_call_id"))
            j += 1
        if ids:
            problems.append(f"message[{i}] unanswered on the wire: {sorted(ids)}")
    return problems


async def repair_thread(thread_id: str, dry_run: bool = False,
                        dump_dir: Path = Path("backups")) -> dict:
    """Heal a committed thread. Returns a result dict (used by the tests)."""
    from app.agent.graph import init_checkpointer
    from app.agent import runner

    await init_checkpointer()
    runner._graph = None
    g = runner.graph()
    cfg = {"configurable": {"thread_id": thread_id}}

    snap = await g.aget_state(cfg)
    messages = (snap.values or {}).get("messages") or []
    if not messages:
        print(f"[scan] {thread_id}: no messages — nothing to do")
        return {"healed": 0, "synthesized": 0, "n_before": 0, "n_after": 0}

    replacements, synthetics = _find_repairs(messages)
    print(f"[scan] {thread_id}: n={len(messages)} divergent={len(replacements)} "
          f"unanswered_parsed={len(synthetics)}")
    for m in replacements:
        print(f"  - strip residue: message id={m.id}")
    for t in synthetics:
        print(f"  - synthesize answer: tool_call_id={t.tool_call_id}")

    if not replacements and not synthetics:
        print("[done] thread is clean — no write (idempotent no-op)")
        return {"healed": 0, "synthesized": 0,
                "n_before": len(messages), "n_after": len(messages)}
    if dry_run:
        print("[dry-run] no write performed")
        return {"healed": len(replacements), "synthesized": len(synthetics),
                "n_before": len(messages), "n_after": len(messages), "dry_run": True}

    # Raw-SQL dump BEFORE any write.
    await _dump_thread_rows(thread_id, dump_dir)

    # Durable heal: same-id replace (position preserved) + synthetic answers.
    await g.aupdate_state(cfg, {"messages": [*replacements, *synthetics]},
                          as_node="memory_load")

    # Post-verify: re-read, re-scan, and wire-audit through the REAL converter.
    after = await g.aget_state(cfg)
    healed_msgs = (after.values or {}).get("messages") or []
    re_repl, re_synth = _find_repairs(healed_msgs)
    problems = _wire_audit(healed_msgs)
    print(f"[verify] n_before={len(messages)} n_after={len(healed_msgs)} "
          f"residual_divergent={len(re_repl)} residual_unanswered={len(re_synth)} "
          f"wire_problems={problems or 'NONE'}")
    if re_repl or re_synth or problems:
        raise SystemExit("POST-VERIFY FAILED — restore from the dump and investigate")
    print(f"[done] {thread_id} healed — history intact "
          f"({len(messages)} → {len(healed_msgs)} messages)")
    return {"healed": len(replacements), "synthesized": len(synthetics),
            "n_before": len(messages), "n_after": len(healed_msgs)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("thread_id")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(repair_thread(args.thread_id, dry_run=args.dry_run))
