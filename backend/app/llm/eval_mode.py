"""Eval-mode flag — isolates eval runs from the PRODUCTION cost-cap and Mem0.

The eval framework drives `run_turn` 20-30× plus judge calls. Without isolation
those calls (a) increment the production daily cost counter
(`jarvis:llm_cost:<UTC_DATE>`) and can trip the hard cap, which would then halt
the MASTER's real agent for the rest of the day, and (b) run `persist_node`,
polluting the master's Mem0 with eval turns.

The eval runner sets this contextvar before driving turns; it propagates through
the async call chain (asyncio.gather copies the context per task). Consulted by:
  - `cost_tracker.record()` — routes spend to a SEPARATE eval counter
    (`jarvis:eval_cost:<UTC_DATE>`), never the production counter.
  - `gateway.complete()` — skips hard/soft-cap enforcement (an eval must not be
    halted by, or contribute to, production cap state).
  - `persist_node` — skips Mem0 extraction so eval turns don't pollute memory.

Per-run cost is still surfaced: the eval runner sums each turn's reported usage
(and reads the eval counter), so the run's spend is visible, not hidden.
"""
from contextvars import ContextVar

eval_mode: ContextVar[bool] = ContextVar("jarvis_eval_mode", default=False)
