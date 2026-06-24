"""Provider-agnostic email interface.

Every Jarvis layer that touches "email" — the send tool, the approval handler,
the inbound receive pipeline, the watch/renew scheduler — goes through
``EmailProvider`` instead of any Gmail SDK. Gmail is the first adapter
(``provider/gmail.py``); a second provider (Outlook / Microsoft Graph — a real
near-future need) plugs in as another adapter selected by ``EMAIL_PROVIDER``,
touching NONE of those layers.

Design rule — OPAQUE identifiers. Providers disagree on how they name messages
and threads:

  =================  ==========================  =============================
  concept            Gmail                       Outlook (Microsoft Graph)
  =================  ==========================  =============================
  message id         messages.get id             message `id` (AAMk…)
  thread ref         `threadId`                  `conversationId`
  reply threading    set threadId + In-Reply-To  POST /messages/{id}/reply
  RFC822 Message-ID  `Message-ID` header         `internetMessageId`  ← standard
  =================  ==========================  =============================

So callers NEVER parse a ``message_id`` or ``thread_ref`` — they're opaque
strings the owning adapter understands. The only cross-provider STANDARD is the
RFC822 ``Message-ID`` (an internet standard both providers expose), used to set
``In-Reply-To``/``References`` for clients that thread on headers. Threading a
reply otherwise is provider-specific, so the interface carries an opaque
``ReplyRef`` (produced by the adapter on receive, consumed by it on send) rather
than asking callers to assemble threading themselves.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    """A normalized inbound email. Identifiers are OPAQUE — pass them back to the
    SAME provider verbatim; never parse them.

    ``message_id`` / ``thread_ref`` are provider-internal (Gmail messages.get id
    / threadId; Graph message id / conversationId). ``rfc822_message_id`` is the
    cross-provider RFC822 ``Message-ID`` standard (Gmail header / Graph
    internetMessageId), used for ``In-Reply-To`` threading."""

    provider: str
    message_id: str
    thread_ref: str
    rfc822_message_id: str
    sender: str  # "Display Name <addr@domain>" as received
    subject: str
    body: str  # plain text


@dataclass(frozen=True)
class ReplyRef:
    """Everything a provider needs to thread a REPLY to a received message — an
    opaque bundle the adapter produced on receive and consumes on send. Callers
    store it (in an approval payload) and round-trip it without interpreting it.

    Gmail uses ``message_id`` to look up the threadId + ``rfc822_message_id`` for
    the ``In-Reply-To`` header; Graph would POST to ``/messages/{id}/reply``
    keyed by ``message_id``. Same neutral bundle, different adapter mechanics."""

    provider: str
    message_id: str = ""
    thread_ref: str = ""
    rfc822_message_id: str = ""


@dataclass(frozen=True)
class SendResult:
    """Outcome of a send. ``sent_message_id`` is the opaque id of the SENT
    message (Gmail send result id / Graph sent message id)."""

    provider: str
    sent_message_id: str
    raw: dict[str, Any] = field(default_factory=dict)


class EmailProvider(ABC):
    """The seam every Jarvis email layer calls. One adapter per provider,
    selected by config. Methods cover the surfaces Jarvis actually uses: send
    (with threading), header/message fetch, and the receive/watch seam. (A live
    mailbox ``search`` was cut — recall is DB-backed, ``email_history_search``;
    no layer queried the provider, so the interface stays honest to its callers.)

    Adapters are constructed once and cached by ``get_email_provider``; they must
    be safe to reuse across requests/loops (build a fresh underlying client per
    call if the SDK is loop-bound — see the Gmail adapter)."""

    #: Short provider tag stored on inbound messages / approval payloads /
    #: EmailLog rows so a resolution can find the SAME adapter again.
    name: str = "base"

    # --- outbound ----------------------------------------------------------
    @abstractmethod
    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: ReplyRef | None = None,
    ) -> SendResult:
        """Send a plain-text email. When ``reply_to`` is given, thread the reply
        to that message however the provider threads (Gmail: threadId +
        In-Reply-To header; Graph: /reply)."""

    # --- read / fetch ------------------------------------------------------
    @abstractmethod
    async def fetch_message(self, message_id: str) -> InboundMessage:
        """Fetch a single message by its opaque id → a normalized
        ``InboundMessage`` (headers + plain-text body). Gmail: messages.get
        format=full; Graph: GET /messages/{id}."""

    # --- receive / watch seam ---------------------------------------------
    @abstractmethod
    async def list_recent_message_ids(self, cursor: str | None = None) -> list[str]:
        """Opaque ids of recent inbox messages (newest-bounded). The neutral
        inbound pipeline dedups these against EmailLog before fetching full
        bodies. ``cursor`` is the provider's delta token (Gmail historyId /
        Graph deltaLink) — accepted for forward-compat; today's adapters list a
        bounded recent window. Gmail: messages.list labelIds=INBOX."""

    @abstractmethod
    async def archive(self, message_id: str) -> None:
        """Remove a message from the inbox (low-confidence spam routing). Gmail:
        messages.modify removeLabelIds=[INBOX]; Graph: POST /messages/{id}/move
        to the archive folder."""

    @abstractmethod
    async def setup_watch(self) -> dict[str, Any]:
        """(Re)register the provider's push subscription so new mail notifies
        Jarvis. Gmail: users.watch → Pub/Sub topic (7-day TTL); Graph: POST
        /subscriptions (≈3-day TTL). Returns the raw provider result (carries the
        expiration the renew scheduler logs)."""

    @abstractmethod
    async def stop_watch(self) -> None:
        """Tear down the push subscription. Gmail: users.stop; Graph: DELETE
        /subscriptions/{id}.

        KEPT deliberately though it has no caller yet: it's the lifecycle pair of
        ``setup_watch`` (which IS used by the renew scheduler). Trigger to wire a
        caller — a "disconnect / switch email provider" flow, which multi-provider
        makes a concrete near-term need (tear down the old provider's watch before
        registering the new one). Cutting it would leave the watch lifecycle
        half-defined; that asymmetry is the cost a 2-line method doesn't justify."""

    @abstractmethod
    def parse_push(self, push_payload: dict[str, Any]) -> str | None:
        """Extract the delta cursor from a raw push notification (the value
        handed to ``list_recent_message_ids``), or None if the push carries
        nothing actionable. Gmail: base64-decode the Pub/Sub ``data`` →
        historyId; Graph: read the change-notification resource. Synchronous —
        it's pure payload parsing, no I/O."""
