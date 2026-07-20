"""The harness ↔ manual-plan ledger map: which B1-N behavior classes are executable,
on which tier, by which tests. `python -m tests.harness.ledger_map` prints coverage.
The map is the honest record — an uncovered class says so out loud."""
CLASS_MAP: dict[str, dict] = {
    "B1-1":  {"name": "resolve-by-word, single card",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_1_resolve_by_word_single_card"],
              "live": []},
    "B1-2":  {"name": "non-committal → re-ask",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_2_noncommittal_reasks_then_committed_sends"],
              "live": ["tests/live_behavior/test_consent_rates.py::test_b1_2_noncommittal_zero_sends_live",
                        "tests/live_behavior/test_consent_rates.py::test_b1_2_committed_always_resolves_live"]},
    "B1-3":  {"name": "multi-card disambiguation",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_3_multi_card_asks_then_kind_resolves"],
              "live": []},
    "B1-4":  {"name": "both / reject both (+ every card flips)",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_4_both_dispatches_both_and_flips_both"],
              "live": []},
    "B1-5":  {"name": "stateful follow-up",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_5_followup_resolves_the_question_that_asked"],
              "live": []},
    "B1-6":  {"name": "hedged selector → re-confirm",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_6_hedged_all_reconfirms"],
              "live": []},
    "B1-7":  {"name": "no false all-selector / no wrong recipient",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_7_idiom_and_auxiliary_never_dispatch"],
              "live": []},
    "B1-8":  {"name": "briefing delivers on yes",
              "regression": ["tests/regression/test_consent_journeys.py::test_b1_8_offer_yes_delivers_by_code"],
              "live": []},
    "B1-9":  {"name": "wall-clock + first-run capture",
              "regression": [],   # unit-covered (test_b1_tz_render); harness journey PENDING
              "live": []},
    "B1-10": {"name": "long chat keeps pending",
              "regression": [],   # PENDING — compaction journey
              "live": []},
}


def coverage() -> str:
    lines = ["HARNESS COVERAGE (ledger map → manual_verification_plan.md)"]
    for k, v in CLASS_MAP.items():
        reg, live = len(v["regression"]), len(v["live"])
        mark = "✓" if (reg or live) else "✗ PENDING"
        lines.append(f"  {k:6} {mark:10} regression={reg} live={live}  — {v['name']}")
    done = sum(1 for v in CLASS_MAP.values() if v["regression"] or v["live"])
    lines.append(f"  covered {done}/{len(CLASS_MAP)} classes")
    return "\n".join(lines)


if __name__ == "__main__":
    print(coverage())
