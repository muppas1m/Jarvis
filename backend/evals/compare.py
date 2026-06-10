"""Turn 20.5 task x — compare an eval result against the committed baseline.

Regression is judged on the DETERMINISTIC hard rule (tool-selection), not the
noisy judge average (item #4): a hard-rule pass-rate drop or a NEW hard-rule
failure is a regression (exit 1); a judge-average drop is reported as a TREND
warning only, never a gate.

Usage:
    python evals/compare.py [path/to/result.json]   # defaults to newest result
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVALS_DIR / "results"
BASELINE = RESULTS_DIR / "baseline.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def main() -> int:
    if not BASELINE.exists():
        print("no baseline.json — run `python evals/runner.py --baseline` first")
        return 1

    if len(sys.argv) > 1:
        latest_path = Path(sys.argv[1])
    else:
        candidates = sorted(p for p in RESULTS_DIR.glob("*.json") if p.name != "baseline.json")
        if not candidates:
            print("no eval result to compare (only baseline.json present)")
            return 1
        latest_path = candidates[-1]

    base = _load(BASELINE)["summary"]
    latest = _load(latest_path)["summary"]
    print(f"baseline vs {latest_path.name}\n")
    print(f"  hard-rule pass rate:  {base['hard_rule_pass_rate']:>6}  ->  {latest['hard_rule_pass_rate']:>6}")
    print(f"  judge avg (trend):    {base['avg_overall']:>6}  ->  {latest['avg_overall']:>6}")

    regressions: list[str] = []
    if latest["hard_rule_pass_rate"] < base["hard_rule_pass_rate"]:
        regressions.append("hard-rule pass rate dropped")
    new_fail = sorted(set(latest["hard_rule_failures"]) - set(base["hard_rule_failures"]))
    if new_fail:
        regressions.append(f"new hard-rule failures: {new_fail}")

    judge_drop = round(base["avg_overall"] - latest["avg_overall"], 2)
    if judge_drop >= 0.5:
        print(f"\n  TREND WARNING: judge avg dropped {judge_drop} (noisy — investigate, do NOT treat as a gate)")

    print()
    if regressions:
        print("REGRESSION:")
        for r in regressions:
            print(f"  - {r}")
        return 1
    print("OK — no hard-rule regression vs baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
