"""
Comprehensive tests for the Action Safety Classifier.

Cover every category, every public override path, and a handful of adversarial
inputs (unknown tool names, malformed args dicts, args that try to spoof
master-chat semantics).
"""
import pytest

from app.agent.safety import TOOL_SAFETY_MAP, SafetyClassifier, SafetyLevel


@pytest.fixture
def classifier() -> SafetyClassifier:
    return SafetyClassifier()


# ---------------------------------------------------------------------------
# Each declared tool resolves to its mapped level (no args).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "tool_name,expected",
    [
        # SAFE
        ("brave_search",    SafetyLevel.SAFE),
        ("tavily_search",   SafetyLevel.SAFE),
        ("firecrawl_crawl", SafetyLevel.SAFE),
        ("gmail_read",      SafetyLevel.SAFE),
        ("gmail_list",      SafetyLevel.SAFE),
        ("calendar_read",   SafetyLevel.SAFE),
        ("memory_search",   SafetyLevel.SAFE),
        ("web_research",    SafetyLevel.SAFE),
        # NOTIFY
        ("email_archive",   SafetyLevel.NOTIFY),
        ("email_label",     SafetyLevel.NOTIFY),
        # APPROVE
        ("email_send",          SafetyLevel.APPROVE),
        ("email_reply",         SafetyLevel.APPROVE),
        ("whatsapp_send",       SafetyLevel.APPROVE),
        ("calendar_create",     SafetyLevel.APPROVE),
        ("calendar_update",     SafetyLevel.APPROVE),
        ("calendar_delete",     SafetyLevel.APPROVE),
        ("booking_reserve",     SafetyLevel.APPROVE),
        ("book_restaurant",     SafetyLevel.APPROVE),
        ("search_flights",      SafetyLevel.APPROVE),
        ("browser_form_submit", SafetyLevel.APPROVE),
        # BLOCKED
        ("delete_account",      SafetyLevel.BLOCKED),
        ("share_credentials",   SafetyLevel.BLOCKED),
    ],
)
def test_known_tools_resolve_to_mapped_level(
    classifier: SafetyClassifier, tool_name: str, expected: SafetyLevel
) -> None:
    assert classifier.classify(tool_name) is expected


def test_every_known_tool_is_in_an_enum_value(classifier: SafetyClassifier) -> None:
    """Catches typos in TOOL_SAFETY_MAP — values must be SafetyLevel members."""
    for tool, level in TOOL_SAFETY_MAP.items():
        assert isinstance(level, SafetyLevel), f"{tool} is not a SafetyLevel"


# ---------------------------------------------------------------------------
# Unknown tools fail-safe to APPROVE.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "tool_name",
    [
        "this_tool_does_not_exist",
        "random_made_up_action",
        "",                       # empty string
        "GMAIL_SEND",             # case-sensitive — uppercase is unknown
        "gmail-send",             # hyphen variant
        "gmail.send",             # dot variant
    ],
)
def test_unknown_tools_default_to_approve(
    classifier: SafetyClassifier, tool_name: str
) -> None:
    assert classifier.classify(tool_name) is SafetyLevel.APPROVE


# ---------------------------------------------------------------------------
# Telegram override — message to master = NOTIFY, anyone else = APPROVE.
# ---------------------------------------------------------------------------
def test_telegram_to_master_stays_notify(
    classifier: SafetyClassifier, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"
    )
    assert (
        classifier.classify("telegram_send", {"chat_id": "12345", "text": "hi"})
        is SafetyLevel.NOTIFY
    )
    # int chat_id should also coerce to string and match.
    assert (
        classifier.classify("telegram_send", {"chat_id": 12345, "text": "hi"})
        is SafetyLevel.NOTIFY
    )


def test_telegram_to_non_master_escalates_to_approve(
    classifier: SafetyClassifier, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"
    )
    # Different chat_id
    assert (
        classifier.classify("telegram_send", {"chat_id": "99999", "text": "hi"})
        is SafetyLevel.APPROVE
    )
    # @somegroup style
    assert (
        classifier.classify("telegram_send", {"chat_id": "@somegroup", "text": "hi"})
        is SafetyLevel.APPROVE
    )


def test_telegram_with_no_chat_id_keeps_base_level(
    classifier: SafetyClassifier, monkeypatch
) -> None:
    """Empty/missing chat_id is the base case — Telegram routing layer fills it
    in to master by default later. Don't gratuitously escalate at classifier."""
    monkeypatch.setattr(
        "app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"
    )
    assert classifier.classify("telegram_send", {}) is SafetyLevel.NOTIFY
    assert (
        classifier.classify("telegram_send", {"chat_id": "", "text": "hi"})
        is SafetyLevel.NOTIFY
    )


def test_telegram_master_chat_id_unset_does_not_crash(
    classifier: SafetyClassifier, monkeypatch
) -> None:
    """If TELEGRAM_MASTER_CHAT_ID is empty (e.g., during fresh setup), the
    classifier shouldn't false-match an empty chat_id and downgrade."""
    monkeypatch.setattr(
        "app.config.settings.TELEGRAM_MASTER_CHAT_ID", ""
    )
    # chat_id="" against TELEGRAM_MASTER_CHAT_ID="" would naively match — the
    # classifier's `if chat_id and ...` guard prevents that.
    assert (
        classifier.classify("telegram_send", {"chat_id": "", "text": "hi"})
        is SafetyLevel.NOTIFY
    )
    # Non-empty chat_id with empty master setting should escalate.
    assert (
        classifier.classify("telegram_send", {"chat_id": "12345", "text": "hi"})
        is SafetyLevel.APPROVE
    )


# ---------------------------------------------------------------------------
# Adversarial: BLOCKED is terminal, args can never downgrade it.
# ---------------------------------------------------------------------------
def test_blocked_tools_cannot_be_downgraded_via_args(
    classifier: SafetyClassifier,
) -> None:
    # Fake every plausible "make this safe" arg shape.
    for args in [
        None,
        {},
        {"safe": True},
        {"approved": True},
        {"override": "force"},
        {"chat_id": "anything"},
    ]:
        assert (
            classifier.classify("delete_account", args)
            is SafetyLevel.BLOCKED
        ), f"BLOCKED was downgraded for args={args!r}"


def test_args_overrides_never_downgrade(
    classifier: SafetyClassifier, monkeypatch
) -> None:
    """SAFE/NOTIFY/APPROVE: passing weird args shouldn't lower the severity."""
    monkeypatch.setattr(
        "app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"
    )
    # email_send is APPROVE — can't go to NOTIFY by passing chat_id.
    assert (
        classifier.classify("email_send", {"chat_id": "12345"})
        is SafetyLevel.APPROVE
    )
    # web_research is SAFE — passing chat_id="999" must not escalate either
    # (no override applies to it; staying SAFE is correct).
    assert (
        classifier.classify("web_research", {"chat_id": "999"})
        is SafetyLevel.SAFE
    )


# ---------------------------------------------------------------------------
# Adversarial: malformed args don't crash.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "args",
    [
        None,
        {},
        {"chat_id": None},
        {"chat_id": 0},          # int zero
        {"chat_id": []},         # wrong type
        {"chat_id": {"a": "b"}}, # dict (wrong type, str() coerces to "{'a': 'b'}")
    ],
)
def test_malformed_args_do_not_raise(
    classifier: SafetyClassifier, monkeypatch, args
) -> None:
    monkeypatch.setattr(
        "app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"
    )
    # Any value is acceptable as long as the classifier returns SOME SafetyLevel.
    assert isinstance(classifier.classify("telegram_send", args), SafetyLevel)
    assert isinstance(classifier.classify("email_send", args), SafetyLevel)
    assert isinstance(classifier.classify("unknown_tool", args), SafetyLevel)
