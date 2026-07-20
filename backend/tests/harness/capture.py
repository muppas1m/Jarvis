"""Loss-proof capture — a live-behavior run's evidence must survive its own failure.

Every sampled run appends a JSONL record (class, phrase, run index, outcome, response
excerpt) under tests/.harness_artifacts/<UTC-date>.jsonl (git-ignored). A red run's
evidence is IN the artifact, never only in a lost terminal scroll — the lesson of the
unnamed-wobble incident (grep|tail discarded the FAILED line)."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / ".harness_artifacts"


def record(behavior_class: str, phrase: str, run: int, outcome: str, detail: str = "") -> None:
    try:
        _DIR.mkdir(exist_ok=True)
        day = datetime.now(UTC).strftime("%Y%m%d")
        with open(_DIR / f"{day}.jsonl", "a") as f:
            f.write(json.dumps({
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "class": behavior_class, "phrase": phrase, "run": run,
                "outcome": outcome, "detail": detail[:300],
                "n_env": os.environ.get("HARNESS_N", ""),
            }) + "\n")
    except Exception:  # noqa: BLE001 — capture must never fail a test
        pass
