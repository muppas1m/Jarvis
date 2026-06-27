"""#1 — the agent's self-knowledge is registry-DERIVED and accurate.

The hand-written CAPABILITIES_BLOCK had drifted: it omitted the passive inbound-email pipeline
and its "can't read the live inbox" line made the agent say "I can't receive emails" (false).
Now the "You CAN" tool list is built from the tool registry (the source of truth) so it can't
drift, plus a declared passive-inbound line; the CANNOT list is hand-fixed.
"""
from app.agent.prompts import build_capabilities
from app.agent.tools import register_all_tools, tool_registry


def setup_module(_module):
    register_all_tools()


def test_recital_lists_every_tool_capability_in_registry():
    recital = build_capabilities()
    caps = tool_registry.capabilities()
    assert caps, "registry should expose capability one-liners"
    for cap in caps:
        assert cap in recital, f"recital omits a registered capability: {cap!r}"


def test_internal_tools_excluded_no_capability():
    # deliver_briefing is an internal SIGNAL tool — no capability → never recited to the master.
    caps = tool_registry.capabilities()
    assert not any("deliver_briefing" in c or "signal" in c.lower() for c in caps)
    # it IS registered (just capability-less)
    assert "deliver_briefing" in tool_registry._entries
    assert tool_registry._entries["deliver_briefing"].capability == ""


def test_email_self_knowledge_is_correct():
    r = build_capabilities().lower()
    # CAN send
    assert "send an email" in r
    # CAN receive/triage/draft incoming email — the fix for "I can't receive emails"
    assert "receive" in r and "incoming email" in r
    assert "you do receive and read email that has come in" in r
    # the falsehood must be gone
    assert "can't receive" not in r and "cannot receive" not in r
    # CANNOT: the genuine boundary is the LIVE inbox on demand / delete / labels (NOT "receive")
    assert "pull the live email inbox on demand" in r
    assert "delete emails" in r


def test_no_stale_task_or_inbox_falsehoods():
    r = build_capabilities().lower()
    # task tools EXIST now → the old "can't manage a to-do/task list" line must be gone
    assert "manage a to-do" not in r and "manage a to-do / task list" not in r
    assert "add a task" in r and "list your tasks" in r


def test_drift_proof_added_tool_appears_removed_does_not():
    # A tool registered WITH a capability appears; the same surface WITHOUT one does not.
    before = build_capabilities()
    assert "Quack like a duck." not in before
    try:
        tool_registry.register(
            name="_recital_probe", handler=lambda: "ok", description="probe",
            capability="Quack like a duck.",
        )
        assert "Quack like a duck." in build_capabilities()
    finally:
        tool_registry._entries.pop("_recital_probe", None)
    assert "Quack like a duck." not in build_capabilities()
