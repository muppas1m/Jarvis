"""Regression fix — concurrent contextualization routed off Groq.

The per-chunk fan-out now runs concurrently (bounded semaphore) on the paid
Gemini `contextualizer` slot, with a per-call timeout. asyncio.gather must
preserve input order; a timeout/failure degrades that chunk to "" (caller falls
back to raw-chunk embedding).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.documents.contextualizer import contextualize_chunks


def _chunk(idx: int, content: str) -> MagicMock:
    c = MagicMock()
    c.content = content
    c.chunk_index = idx
    return c


def _resp(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


@pytest.mark.asyncio
async def test_order_preserved_under_concurrency():
    async def fake_complete(messages, **kwargs):  # noqa: ARG001
        prompt = messages[0]["content"]
        chunk_text = prompt.split("<chunk>")[1].split("</chunk>")[0].strip()
        return _resp(f"SUM-{chunk_text}")

    chunks = [_chunk(i, f"c{i:02d}") for i in range(6)]
    with patch("app.documents.contextualizer.llm_gateway.complete",
               new=AsyncMock(side_effect=fake_complete)):
        out = await contextualize_chunks(chunks, "excerpt")
    assert out == [f"SUM-c{i:02d}" for i in range(6)]  # order intact despite gather


@pytest.mark.asyncio
async def test_routed_to_contextualizer_slot():
    mock = AsyncMock(return_value=_resp("ctx"))
    with patch("app.documents.contextualizer.llm_gateway.complete", new=mock):
        await contextualize_chunks([_chunk(0, "hi")], "ex")
    assert mock.await_args.kwargs.get("force_model") == "contextualizer"  # OFF Groq


@pytest.mark.asyncio
async def test_empty_chunk_skips_call():
    mock = AsyncMock(return_value=_resp("x"))
    with patch("app.documents.contextualizer.llm_gateway.complete", new=mock):
        out = await contextualize_chunks([_chunk(0, "   ")], "ex")
    assert out == [""]
    mock.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_degrades_to_empty():
    async def slow(messages, **kwargs):  # noqa: ARG001
        await asyncio.sleep(0.3)
        return _resp("late")

    with patch("app.documents.contextualizer.llm_gateway.complete",
               new=AsyncMock(side_effect=slow)), \
         patch("app.config.settings.CONTEXTUALIZE_TIMEOUT_S", 0.05):
        out = await contextualize_chunks([_chunk(0, "c0")], "ex")
    assert out == [""]  # degraded, did not hang


@pytest.mark.asyncio
async def test_failure_degrades_to_empty():
    with patch("app.documents.contextualizer.llm_gateway.complete",
               new=AsyncMock(side_effect=RuntimeError("boom"))):
        out = await contextualize_chunks([_chunk(0, "c0"), _chunk(1, "c1")], "ex")
    assert out == ["", ""]  # both degrade, batch never raises
