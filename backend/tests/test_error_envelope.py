"""
TurnEnvelope error-path shape test.

The envelope is the canonical contract for both /api/chat (HTTP) and
route_inbound (Telegram). When the agent graph errors mid-invoke,
run_turn must return a complete envelope — not a truncated dict — so
the messaging layer's `result["status"] == "error"` and HTTP clients'
response parsers don't blow up.

This test forces graph.ainvoke to raise and asserts the envelope:
  - status == "error"
  - response is a non-empty user-friendly string
  - all canonical envelope keys are present (thread_id, messages,
    interrupt, trace_id, usage)
  - usage is a dict with the expected sub-keys (zero values are fine)
"""
from unittest.mock import patch

import pytest

from app.agent.graph import init_checkpointer
from app.agent.runner import run_turn


@pytest.fixture
async def checkpointer():
    """The runner needs an open checkpointer before graph().ainvoke can
    even reach the failure point we're testing. init_checkpointer is
    idempotent; we don't tear it down because the runner caches a
    graph singleton that holds the reference."""
    await init_checkpointer()
    yield


@pytest.mark.asyncio
async def test_run_turn_returns_complete_envelope_on_invoke_error(
    checkpointer,
) -> None:
    """If graph.ainvoke raises, the envelope must still be well-formed.
    Otherwise route_inbound can't reach `if result["status"] == "error"`
    and the HTTP layer would error its serializer trying to render a
    half-built dict."""

    async def boom(*args, **kwargs):  # noqa: ARG001
        raise RuntimeError("synthetic failure for envelope contract test")

    with patch("app.agent.runner.graph") as mock_graph_factory:
        mock_graph = mock_graph_factory.return_value
        mock_graph.ainvoke.side_effect = boom

        # _existing_message_count also calls graph().aget_state — make sure
        # that returns something benign so we reach the ainvoke failure path
        # cleanly (otherwise the test fails for the wrong reason).
        async def fake_aget_state(_config):
            class _FakeState:
                values: dict = {}
            return _FakeState()
        mock_graph.aget_state.side_effect = fake_aget_state

        envelope = await run_turn(
            user_message="anything",
            thread_id="test-error-envelope",
            platform="web",
            channel_user_id="test-runner",
        )

    # --- top-level shape -------------------------------------------------
    assert envelope["status"] == "error", (
        f"Expected status='error' on graph failure; got {envelope['status']!r}"
    )
    assert isinstance(envelope["response"], str) and envelope["response"].strip(), (
        f"Error envelope must carry a non-empty user-facing response string; "
        f"got {envelope['response']!r}"
    )

    # --- all canonical keys present (no truncation under failure) --------
    expected_keys = {
        "thread_id", "status", "response", "messages",
        "interrupt", "trace_id", "usage",
    }
    missing = expected_keys - set(envelope.keys())
    assert not missing, (
        f"Error envelope is missing canonical keys: {sorted(missing)}. "
        f"This breaks the contract /api/chat clients depend on."
    )

    # --- field-level shape -----------------------------------------------
    assert envelope["thread_id"] == "test-error-envelope"
    assert envelope["messages"] == [], (
        "Error envelope before any agent step ran should have empty messages, "
        f"got {envelope['messages']!r}"
    )
    assert envelope["interrupt"] is None
    assert envelope["trace_id"] is None

    usage = envelope["usage"]
    assert isinstance(usage, dict)
    expected_usage_keys = {
        "input_tokens", "output_tokens", "total_tokens",
        "cost_usd", "duration_ms",
    }
    missing_usage = expected_usage_keys - set(usage.keys())
    assert not missing_usage, (
        f"Usage sub-dict missing keys: {sorted(missing_usage)}"
    )
    # All counters zero on a turn that never hit an LLM.
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["total_tokens"] == 0
    assert usage["cost_usd"] == 0.0
