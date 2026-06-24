"""Provider swappability — the seam is real. A second provider (Outlook) plugs in
as ONE registry entry; the factory selects it by config; it implements the full
EmailProvider contract. The inbound pipeline + approval handler reference only the
interface, so they'd drive Outlook with zero changes (proven generically against a
fake in test_inbound_pipeline; here we pin the Outlook adapter + factory).
"""
import pytest

from app.email.provider import (
    EmailProvider,
    GmailProvider,
    OutlookProvider,
    get_email_provider,
)


def test_factory_selects_by_config(monkeypatch):
    # Default → gmail; EMAIL_PROVIDER flips it with NO code change.
    from app.config import settings

    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "outlook")
    assert isinstance(get_email_provider(), OutlookProvider)
    monkeypatch.setattr(settings, "EMAIL_PROVIDER", "gmail")
    assert isinstance(get_email_provider(), GmailProvider)


def test_outlook_implements_full_contract():
    # No abstract methods left unimplemented → it satisfies every layer's calls.
    assert not OutlookProvider.__abstractmethods__
    assert issubclass(OutlookProvider, EmailProvider)
    o = get_email_provider("outlook")
    assert o.name == "outlook"


async def test_outlook_skeleton_fails_loud_not_silent():
    """A skeleton method raises (loud) rather than silently dropping mail — so a
    misconfigured EMAIL_PROVIDER=outlook is obvious, not a silent data loss."""
    o = get_email_provider("outlook")
    with pytest.raises(NotImplementedError):
        await o.send("a@b.com", "Hi", "body")
    with pytest.raises(NotImplementedError):
        await o.fetch_message("x")
    with pytest.raises(NotImplementedError):
        o.parse_push({})
