"""
Strip markdown SYNTAX from a sentence so it speaks (and captions) as clean words.

The LLM writes answers in markdown (**bold**, ## headings, `code`, 1. lists). On
the spoken path that reads aloud as garbage ("asterisk asterisk Highly Required")
and shows raw in the live caption. This strips the syntax while PRESERVING
ordinary text that merely contains the same characters — the real risk is
over-reach, so every rule is scoped tightly:

  - emphasis (`**`, `*`, `__`, `_`) is stripped only when it hugs content with no
    inner space and a word/space boundary outside → "2 * 3", "C#", "C*D", "2 ** 3"
    survive; "**Highly Required**" / "*italic*" don't.
  - headings / bullets / blockquotes / ordered-list markers are stripped only at
    the START of a line → "C#", "well-known", a mid-sentence "- " survive.
  - links/images keep their visible text; code keeps its content.
  - a lone ordered-list number the chunker split off ("1.") → dropped (nothing to
    say); decimals like "3.14" are never split, so they're safe.
  - leftover word-adjacent `**`/`__` (an emphasis pair the sentence chunker split
    across two chunks, e.g. "**bold across.") is stripped so it never reads as
    "asterisk asterisk"; space-surrounded "**" ("2 ** 3") is left alone.

Applied per sentence (the chunker's unit), on the SAME string that drives both
the Piper audio and the caption, so the two can't drift.
"""
import re

_FENCE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE = re.compile(r"`+([^`]*)`+")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BOLD = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*")
_BOLD_U = re.compile(r"__(\S(?:.*?\S)?)__")
# single * / _ emphasis: marker not adjacent to a word char or another marker
# (so "C*D", "a_b_c" survive) and content has no leading/trailing space (so the
# spaced "2 * 3" survives).
_ITALIC = re.compile(r"(?<![\w*])\*(\S(?:[^*\n]*?\S)?)\*(?![\w*])")
_ITALIC_U = re.compile(r"(?<![\w_])_(\S(?:[^_\n]*?\S)?)_(?![\w_])")
_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]*")
_HR = re.compile(r"(?m)^[ \t]{0,3}([-*_])(?:[ \t]?\1){2,}[ \t]*$")
_BULLET = re.compile(r"(?m)^[ \t]{0,3}[-*+][ \t]+")
_ORDERED = re.compile(r"(?m)^[ \t]{0,3}\d+\.[ \t]+")
_BLOCKQUOTE = re.compile(r"(?m)^[ \t]{0,3}>[ \t]?")
_BARE_ORDINAL = re.compile(r"^\s*\d+\.?\s*$")  # a lone list number chunk → drop
# leftover emphasis markers from a cross-chunk split — only when word-adjacent,
# so space-surrounded math ("2 ** 3") is preserved.
_STRAY_EMPH = re.compile(r"(?<=\w)\*\*|\*\*(?=\w)|(?<=\w)__|__(?=\w)")
_WS = re.compile(r"[ \t]{2,}")


def strip_markdown_for_speech(text: str) -> str:
    """Return `text` with markdown syntax removed for TTS + caption. Idempotent;
    preserves non-markdown uses of *, #, -, _, $, etc. Empty string for a chunk
    that was only a list ordinal."""
    if not text:
        return text
    if _BARE_ORDINAL.match(text):
        return ""
    text = _FENCE.sub("", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _IMAGE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _BOLD.sub(r"\1", text)
    text = _BOLD_U.sub(r"\1", text)
    text = _ITALIC.sub(r"\1", text)
    text = _ITALIC_U.sub(r"\1", text)
    text = _HEADING.sub("", text)
    text = _HR.sub("", text)
    text = _BULLET.sub("", text)
    text = _ORDERED.sub("", text)
    text = _BLOCKQUOTE.sub("", text)
    text = _STRAY_EMPH.sub("", text)
    text = _WS.sub(" ", text)
    return text.strip()
