"""The enforcement self-test — the checker itself is proven, both directions."""
import json
from pathlib import Path

from tests.harness.sweep_check import check, record, trigger_state


def test_record_then_check_passes(tmp_path):
    root = tmp_path
    (root / "app/agent").mkdir(parents=True)
    for rel in ("app/agent/nodes.py", "app/agent/answer_consumption.py",
                "app/agent/decision_resolver.py", "app/agent/approval_essentials.py",
                "app/agent/runner.py", "app/agent/prompts.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("original")
    receipt = root / "receipt.json"
    record(root, receipt)
    assert check(root, receipt) == []                        # untouched → pass


def test_changed_trigger_fails_until_reswept(tmp_path):
    root = tmp_path
    for rel in ("app/agent/nodes.py", "app/agent/answer_consumption.py",
                "app/agent/decision_resolver.py", "app/agent/approval_essentials.py",
                "app/agent/runner.py", "app/agent/prompts.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("original")
    receipt = root / "receipt.json"
    record(root, receipt)
    (root / "app/agent/decision_resolver.py").write_text("A PROMPT EDIT")   # the incident class
    stale = check(root, receipt)
    assert stale == ["app/agent/decision_resolver.py"]       # named, precisely
    record(root, receipt)                                    # the re-sweep
    assert check(root, receipt) == []


def test_missing_receipt_fails_loud(tmp_path):
    assert check(tmp_path, tmp_path / "nope.json") != []
