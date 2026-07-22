"""Sweep ENFORCEMENT (battle-requirement #1) — manual discipline proved insufficient.

`record` runs only at the end of a GREEN `make harness-sweep` and writes a receipt of the
exact content (sha256) of every sweep-trigger file. `check` re-hashes: any trigger file
changed (or no receipt) → EXIT 1 with the exact command to run. Certification wires
`make sweep-check`; a changed consent surface can no longer slide past un-swept.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent          # backend/
_RECEIPT = _ROOT / "tests" / ".harness_artifacts" / "sweep_receipt.json"

# The consent-adjacent / prompt-bearing surfaces: a diff here without a sweep is the
# incident class ("sure" → approve shipped on an unswept prompt edit).
SWEEP_TRIGGERS = [
    "app/agent/nodes.py",
    "app/agent/answer_consumption.py",
    "app/agent/decision_resolver.py",
    "app/agent/approval_essentials.py",
    "app/agent/runner.py",
    "app/agent/prompts.py",
]


def _sha(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "absent"


def trigger_state(root: Path = _ROOT) -> dict[str, str]:
    return {rel: _sha(root / rel) for rel in SWEEP_TRIGGERS}


def record(root: Path = _ROOT, receipt: Path = _RECEIPT) -> None:
    receipt.parent.mkdir(exist_ok=True)
    # F-1: the container has no .git — the HOST passes GIT_HEAD via env (the Makefile);
    # the subprocess path stays as the host-side fallback. An empty head is a defect.
    head = os.environ.get("GIT_HEAD", "").strip()
    if not head:
        try:
            head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                  text=True, cwd=root).stdout.strip()
        except Exception:  # noqa: BLE001 — the hash record is the load-bearing part
            pass
    receipt.write_text(json.dumps({
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_head": head,
        "files": trigger_state(root),
    }, indent=1))
    print(f"sweep receipt recorded ({len(SWEEP_TRIGGERS)} trigger files)")


def check(root: Path = _ROOT, receipt: Path = _RECEIPT) -> list[str]:
    """Return the list of UNSWEPT changed trigger files (empty = pass)."""
    if not receipt.exists():
        return ["<no sweep receipt at all>"]
    recorded = (json.loads(receipt.read_text()) or {}).get("files") or {}
    now = trigger_state(root)
    return [rel for rel, digest in now.items() if recorded.get(rel) != digest]


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode == "record":
        record()
        return 0
    stale = check()
    if stale:
        print("SWEEP-CHECK FAILED — consent-adjacent surfaces changed without a sweep:")
        for rel in stale:
            print(f"  ✗ {rel}")
        print("Run:  make harness-sweep   (records the receipt only when GREEN)")
        return 1
    print("sweep-check OK — every trigger surface matches the last green sweep")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
