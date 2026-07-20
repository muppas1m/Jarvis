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
