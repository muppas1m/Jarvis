"""Semantic chunking with token-budget ceiling.

The plan-verbatim chunker windows a flat string by token count with fixed
overlap, which works but splits mid-paragraph (and mid-sentence) routinely —
hurting retrieval recall and producing chunks that are awkward to cite. This
module instead consumes the structured ``ExtractedBlock`` list from
:mod:`app.documents.extractors`, packs contiguous blocks into chunks until
the token budget would overflow, and splits at the last paragraph boundary
instead of mid-sentence.

Strategy:
  1. Walk blocks in order, accumulating into a current-chunk buffer.
  2. When adding the next block would exceed ``max_tokens``: flush the buffer
     as a chunk, start fresh with the next block.
  3. If a single block exceeds ``max_tokens`` on its own (rare: long PDF
     paragraph, oversized cell content): flush any current buffer, then
     fall back to token-window slicing for that one block with
     ``overlap_tokens`` overlap between windows. All sibling windows
     inherit the parent block's locators.
  4. Each emitted chunk's ``meta`` carries source_file, page_start/page_end,
     paragraph_start/paragraph_end, section_heading (the heading active at
     the FIRST block of the chunk), and ``fallback=True`` when produced by
     the oversized-block split path.

Semantic chunks do NOT carry overlap between siblings — clean paragraph
boundaries are the whole point. Retrieval continuity is preserved by
section_heading propagation, Turn 19's contextual summaries, and top-k > 1
retrieval at search time.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import tiktoken

from app.documents.extractors import ExtractedBlock


@dataclass(frozen=True)
class Chunk:
    """One retrieval-unit chunk with citation-ready metadata."""

    chunk_index: int
    content: str
    token_count: int
    meta: dict = field(default_factory=dict)


_DEFAULT_MAX_TOKENS = 500
_DEFAULT_OVERLAP_TOKENS = 50
_DEFAULT_ENCODING = "cl100k_base"


def chunk_blocks(
    blocks: list[ExtractedBlock],
    source_file: str,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
    overlap_tokens: int = _DEFAULT_OVERLAP_TOKENS,
    encoding: str = _DEFAULT_ENCODING,
) -> list[Chunk]:
    """Pack ``blocks`` into chunks respecting paragraph boundaries.

    Returns an empty list for empty input. Asserts that ``max_tokens > 0`` and
    ``overlap_tokens < max_tokens`` so the oversized-block split makes forward
    progress.
    """
    if not blocks:
        return []
    if max_tokens <= 0:
        raise ValueError("max_tokens must be positive")
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    enc = tiktoken.get_encoding(encoding)

    chunks: list[Chunk] = []
    buffer: list[ExtractedBlock] = []
    buffer_tokens = 0
    chunk_index = 0

    def flush(idx: int) -> int:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return idx
        chunks.append(_chunk_from_blocks(buffer, idx, source_file, enc))
        buffer = []
        buffer_tokens = 0
        return idx + 1

    for block in blocks:
        if not block.text.strip():
            continue

        block_tokens = len(enc.encode(block.text))

        if block_tokens > max_tokens:
            # Single block too big to fit even on its own — flush buffer,
            # then window the oversized block.
            chunk_index = flush(chunk_index)
            for sub in _split_oversized_block(
                block, max_tokens, overlap_tokens, enc, source_file, chunk_index
            ):
                chunks.append(sub)
                chunk_index += 1
            continue

        if buffer_tokens + block_tokens > max_tokens:
            # Adding this block would overflow; flush the buffer and start fresh.
            chunk_index = flush(chunk_index)

        buffer.append(block)
        buffer_tokens += block_tokens

    flush(chunk_index)
    return chunks


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _chunk_from_blocks(
    blocks: list[ExtractedBlock],
    chunk_index: int,
    source_file: str,
    enc: tiktoken.Encoding,
) -> Chunk:
    """Concatenate ``blocks`` with double-newline separators; build meta."""
    content = "\n\n".join(b.text for b in blocks)
    token_count = len(enc.encode(content))

    pages = [b.page for b in blocks if b.page is not None]
    paragraph_indices = [b.paragraph_index for b in blocks]
    # Use the heading active at the START of the chunk for citation purposes;
    # the chunker doesn't try to invent a "best heading" if multiple are seen.
    section_heading = blocks[0].section_heading

    meta: dict = {
        "source_file": source_file,
        "paragraph_start": paragraph_indices[0],
        "paragraph_end": paragraph_indices[-1],
        "section_heading": section_heading,
        "block_count": len(blocks),
    }
    if pages:
        meta["page_start"] = pages[0]
        meta["page_end"] = pages[-1]

    return Chunk(
        chunk_index=chunk_index,
        content=content,
        token_count=token_count,
        meta=meta,
    )


def _split_oversized_block(
    block: ExtractedBlock,
    max_tokens: int,
    overlap_tokens: int,
    enc: tiktoken.Encoding,
    source_file: str,
    start_chunk_index: int,
) -> list[Chunk]:
    """Token-window an oversized block. All windows share the block's locators.

    Each emitted chunk's ``meta`` is marked ``fallback=True`` so downstream
    code can tell it apart from a clean semantic chunk (useful for retrieval
    quality monitoring — too many fallbacks signals max_tokens is mistuned).
    """
    tokens = enc.encode(block.text)
    if not tokens:
        return []

    stride = max_tokens - overlap_tokens
    if stride <= 0:
        raise ValueError("overlap_tokens must be smaller than max_tokens")

    sub_chunks: list[Chunk] = []
    chunk_index = start_chunk_index
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        window_tokens = tokens[start:end]
        window_text = enc.decode(window_tokens)

        meta: dict = {
            "source_file": source_file,
            "paragraph_start": block.paragraph_index,
            "paragraph_end": block.paragraph_index,
            "section_heading": block.section_heading,
            "block_count": 1,
            "fallback": True,
            "fallback_window_start": start,
            "fallback_window_end": end,
        }
        if block.page is not None:
            meta["page_start"] = block.page
            meta["page_end"] = block.page

        sub_chunks.append(Chunk(
            chunk_index=chunk_index,
            content=window_text,
            token_count=len(window_tokens),
            meta=meta,
        ))
        chunk_index += 1

        if end == len(tokens):
            break
        start += stride

    return sub_chunks
