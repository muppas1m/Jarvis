# The two-tier harness (ledger item #2)

**Tier `tests/regression/`** — real graph (`run_turn`), agent scripted + judges pinned →
**deterministic guarantees**. A red here is a broken invariant, never model noise.

**Tier `tests/live_behavior/`** — real graph + the REAL `DECISION_MODEL`, phrasings sampled →
**behavior-class rates**. Consent classes assert **zero leaks** across the sample; capability
classes assert rates. `HARNESS_N` scales the sample (default 3 so the tier rides the normal suite).

**Evidence is loss-proof:** every live sample appends to `tests/.harness_artifacts/<date>.jsonl`
(git-ignored) — a red run's evidence survives the terminal.

**The ledger map** (`tests/harness/ledger_map.py`, `make harness-report`) records which
`manual_verification_plan.md` behavior classes are executable, by tier — an uncovered class says
`PENDING` out loud.

## When to run what (the sweep triggers)
- Any consent-adjacent diff (`nodes.py` resolution arm, `answer_consumption`, `decision_resolver`,
  the judges' prompts): `make harness` before commit, **`make harness-sweep` before certification/push**.
- A judge-prompt change additionally re-runs `tests/test_decision_judge_live.py` in full (the boundary lock).
- Adding a behavior class: implement on BOTH tiers where meaningful, register it in `ledger_map.py`
  (the map is the honest record), and wire its capture calls.

## Commands
- `make harness` — both tiers at default N (fast; rides CI/the suite anyway).
- `make harness-sweep` — both tiers at `HARNESS_N=6` + the full live judge boundary.
- `make harness-report` — coverage vs the manual plan.

## Enforcement + operations (item #2 completion pass)
- **`make sweep-check`** FAILS (with the exact command) when any `SWEEP_TRIGGERS` surface
  changed since the last GREEN sweep — the receipt is written only by a green
  `make harness-sweep`. Manual discipline is not the mechanism anymore; this is.
- **Tier split:** the default suite / `make test` runs regression-only (`norecursedirs`
  excludes `tests/live_behavior`); the live tier runs ONLY via the harness targets
  (explicit paths bypass the exclusion). `test_decision_judge_live.py` stays in the suite
  deliberately — it is the certified judge boundary lock, not the sampled tier.
- **Capture scope (declared):** loss-proof capture covers BOTH tiers — live samples record
  every run; a `pytest_runtest_makereport` hook records every harness FAILURE (both tiers)
  to the same artifacts.
- **Minting journeys (reviewer watch-item, on the record):** before ANY journey that mints
  through the agent, run with `HARNESS_INDEX_TOOLS=1` so `ensure_graph` mirrors
  production's `index_all_tools()` tool-ranking — without it a mint journey can pass for
  the wrong reason (the empty-registry class). Consume-path journeys don't need it.
- **Absorbed by reference:** the scattered graph-level journeys (step-2 consume, brief HWM,
  edit fixes) are indexed in `ledger_map.ABSORBED_BY_REFERENCE` where they live — declared,
  not silently migrated.
