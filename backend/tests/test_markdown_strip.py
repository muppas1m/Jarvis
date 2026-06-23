"""
Tests for `strip_markdown_for_speech` — the spoken-path markdown strip.

The bar (the master's stated risk): kill markdown SYNTAX so it never reads aloud
as "asterisk asterisk", but NEVER mangle ordinary text that merely contains the
same characters (math, "C#", URLs, "$5", hyphens, snake_case).
"""
import pytest

from app.voice.markdown_strip import strip_markdown_for_speech as strip


@pytest.mark.parametrize(
    "raw, expected",
    [
        # --- the master's real cases ---
        ("considered **Highly Required**", "considered Highly Required"),
        ("##Side Note:", "Side Note:"),
        ("## Side Note: the details", "Side Note: the details"),
        ("1. This action is important", "This action is important"),
        ("1.", ""),  # lone ordinal the chunker split off → nothing to say
        ("This action is important.", "This action is important."),
        # --- emphasis variants ---
        ("*italic* word", "italic word"),
        ("__bold__ too", "bold too"),
        ("_under_ score", "under score"),
        ("a **bold** and *italic* mix", "a bold and italic mix"),
        # --- headings / lists / quotes / code / links ---
        ("### Heading three", "Heading three"),
        ("- bullet item", "bullet item"),
        ("* star bullet", "star bullet"),
        ("> a quote", "a quote"),
        ("see `the_code` here", "see the_code here"),
        ("read [the docs](https://x.com)", "read the docs"),
        ("![alt text](img.png) shown", "alt text shown"),
        # --- cross-chunk split (partial / mid-stream): never read "asterisk" ---
        ("**Highly Req", "Highly Req"),
        ("more bold**", "more bold"),
        # --- ADVERSARIAL: must NOT be mangled ---
        ("2 * 3 equals 6", "2 * 3 equals 6"),
        ("compute 2 ** 3", "compute 2 ** 3"),
        ("the language C#", "the language C#"),
        ("a price of $5", "a price of $5"),
        ("a well-known fact", "a well-known fact"),
        ("visit https://example.com/page now", "visit https://example.com/page now"),
        ("use a*b for the product", "use a*b for the product"),
        ("snake_case_name stays", "snake_case_name stays"),
        ("pi is 3.14 today", "pi is 3.14 today"),
        ("plain words, nothing here", "plain words, nothing here"),
    ],
)
def test_strip(raw, expected):
    assert strip(raw) == expected


def test_idempotent():
    for c in ["considered **Highly Required**", "## Side Note:", "2 * 3", "C#", "- item"]:
        once = strip(c)
        assert strip(once) == once, f"not idempotent: {c!r}"


def test_empty_and_whitespace():
    assert strip("") == ""
    assert strip("   ") == ""
