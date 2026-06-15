"""Sentence chunker — slices a streamed token feed into speakable sentences.

The §D-1 latency lever: never wait for the full LLM response. Push each token
in; get back any complete sentences to hand straight to TTS while the next
sentence still generates. Flush at the end for the trailing partial.
"""
from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[.!?]+[\"')\]]?(?:\s|$)")


class SentenceChunker:
    """Accumulates tokens, emits complete sentences.

    Flush conditions: sentence-ending punctuation followed by whitespace/end,
    or a soft length cap so a long comma-spliced clause still speaks promptly
    rather than waiting for a period that may be far off.
    """

    def __init__(self, soft_cap: int = 180) -> None:
        self._buf = ""
        self._soft_cap = soft_cap

    def push(self, token: str) -> list[str]:
        self._buf += token
        out: list[str] = []
        while True:
            m = _SENTENCE_END.search(self._buf)
            if m:
                end = m.end()
                sentence = self._buf[:end].strip()
                self._buf = self._buf[end:].lstrip()
                if sentence:
                    out.append(sentence)
                continue
            if len(self._buf) >= self._soft_cap:
                cut = self._buf.rfind(" ", 0, self._soft_cap)
                if cut <= 0:
                    cut = self._soft_cap
                sentence = self._buf[:cut].strip()
                self._buf = self._buf[cut:].lstrip()
                if sentence:
                    out.append(sentence)
                continue
            break
        return out

    def flush(self) -> str:
        """Return the trailing partial (if any) and clear the buffer."""
        s = self._buf.strip()
        self._buf = ""
        return s
