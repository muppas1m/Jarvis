"""Unit tests for FallbackChatLLM (Turn 17.7).

Five scenarios cover the retry-predicate's decision surface:
  1. Primary succeeds → fallback not called, primary result returned
  2. RateLimitError on primary → fallback called, fallback result returned
  3. BadRequestError with `tool_use_failed` in message → fallback called
  4. BadRequestError WITHOUT tool_use_failed → propagates (no fallback)
  5. AuthenticationError → propagates (no fallback — real config bug)

Mocks at the Runnable.ainvoke level via AsyncMock — preserves the
LangChain Runnable interface contract without depending on
ChatLiteLLM's internal _agenerate plumbing.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import litellm
import pytest

from app.llm.fallback_llm import FallbackChatLLM


def _make_mock_runnable(name: str, ainvoke_side_effect=None, ainvoke_return=None):
    """Construct a Runnable-like mock with an async ainvoke."""
    mock = MagicMock(name=name)
    if ainvoke_side_effect is not None:
        mock.ainvoke = AsyncMock(side_effect=ainvoke_side_effect)
    else:
        mock.ainvoke = AsyncMock(return_value=ainvoke_return)
    return mock


@pytest.mark.asyncio
async def test_primary_success_no_fallback() -> None:
    """When primary succeeds, fallback is never invoked."""
    primary = _make_mock_runnable("primary", ainvoke_return="primary_result")
    fallback = _make_mock_runnable("fallback", ainvoke_return="fallback_result")

    model = FallbackChatLLM(primary=primary, fallback=fallback)
    result = await model.ainvoke("input")

    assert result == "primary_result"
    primary.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_rate_limit_triggers_fallback() -> None:
    """litellm.RateLimitError on primary → fallback called with same input."""
    rate_limit_exc = litellm.RateLimitError(
        message="Rate limit reached for model `llama-3.3-70b-versatile` ...",
        llm_provider="groq",
        model="groq/llama-3.3-70b-versatile",
    )
    primary = _make_mock_runnable("primary", ainvoke_side_effect=rate_limit_exc)
    fallback = _make_mock_runnable("fallback", ainvoke_return="fallback_result")

    model = FallbackChatLLM(primary=primary, fallback=fallback)
    result = await model.ainvoke("input")

    assert result == "fallback_result"
    primary.ainvoke.assert_awaited_once()
    fallback.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_tool_use_failed_triggers_fallback() -> None:
    """BadRequestError with `tool_use_failed` in message → fallback called.

    Mimics the actual Groq error shape observed in Turn 17.6 live testing:
    `litellm.BadRequestError: GroqException - {"error":{"message":"Failed
    to call a function. ...","code":"tool_use_failed",...}}`.
    """
    tool_use_failed_exc = litellm.BadRequestError(
        message=(
            'GroqException - {"error":{"message":"Failed to call a function. '
            'Please adjust your prompt. See \'failed_generation\' for more '
            'details.","type":"invalid_request_error","code":"tool_use_failed"}}'
        ),
        llm_provider="groq",
        model="groq/llama-3.3-70b-versatile",
    )
    primary = _make_mock_runnable("primary", ainvoke_side_effect=tool_use_failed_exc)
    fallback = _make_mock_runnable("fallback", ainvoke_return="fallback_result")

    model = FallbackChatLLM(primary=primary, fallback=fallback)
    result = await model.ainvoke("input")

    assert result == "fallback_result"
    fallback.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_bad_request_propagates() -> None:
    """BadRequestError WITHOUT tool_use_failed (e.g., model-not-found) → propagates.

    Falling over to gpt-4o-mini for a "model not found" error doesn't help
    and burns paid quota for no recovery. Predicate narrowness matters."""
    other_bad_request = litellm.BadRequestError(
        message='GroqException - {"error":{"message":"The model `made-up-model` does not exist","code":"model_not_found"}}',
        llm_provider="groq",
        model="groq/made-up-model",
    )
    primary = _make_mock_runnable("primary", ainvoke_side_effect=other_bad_request)
    fallback = _make_mock_runnable("fallback", ainvoke_return="should_not_be_called")

    model = FallbackChatLLM(primary=primary, fallback=fallback)

    with pytest.raises(litellm.BadRequestError):
        await model.ainvoke("input")

    fallback.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_authentication_error_propagates() -> None:
    """AuthenticationError → propagates (no fallback).

    Real config issue (revoked API key, missing scope, etc.). Falling over
    to a different provider hides the underlying issue and probably fails
    the same way. Surfacing the exception loudly is the right behavior."""
    auth_exc = litellm.AuthenticationError(
        message="Invalid API key",
        llm_provider="groq",
        model="groq/llama-3.3-70b-versatile",
    )
    primary = _make_mock_runnable("primary", ainvoke_side_effect=auth_exc)
    fallback = _make_mock_runnable("fallback", ainvoke_return="should_not_be_called")

    model = FallbackChatLLM(primary=primary, fallback=fallback)

    with pytest.raises(litellm.AuthenticationError):
        await model.ainvoke("input")

    fallback.ainvoke.assert_not_awaited()
