"""Outlook / Microsoft Graph adapter — SKELETON.

Proof that the EmailProvider seam is real: a second provider plugs in as ONE
module + ONE registry entry (``"outlook": OutlookProvider`` in
``provider/__init__``), selected by ``EMAIL_PROVIDER=outlook``, touching NONE of
the agent / approval / safety / send / inbound layers. Each method is annotated
with the exact Microsoft Graph call it maps to, so finishing this adapter is
filling in HTTP calls against a documented contract — not a redesign.

Identifier mapping (the opaque-id contract holds — callers never parse these):
  - InboundMessage.message_id   ← Graph message ``id``
  - InboundMessage.thread_ref   ← Graph ``conversationId``
  - InboundMessage.rfc822_message_id ← Graph ``internetMessageId`` (the RFC822
    Message-ID — the one cross-provider standard, used for In-Reply-To)

Auth would be MSAL (client-credentials or delegated) → a Graph bearer token,
the Outlook analogue of the Gmail adapter's google-auth refresh-token flow. Not
wired here — this skeleton intentionally raises so a misconfigured
``EMAIL_PROVIDER=outlook`` fails loudly rather than silently dropping mail.
"""
from __future__ import annotations

from typing import Any

from app.email.provider.base import EmailProvider, InboundMessage, ReplyRef, SendResult

_TODO = "OutlookProvider is a skeleton — wire the Microsoft Graph call here."


class OutlookProvider(EmailProvider):
    name = "outlook"

    async def send(
        self, to: str, subject: str, body: str, reply_to: ReplyRef | None = None
    ) -> SendResult:
        # Graph: a fresh message → POST /me/sendMail. A threaded reply →
        # POST /me/messages/{reply_to.message_id}/reply (Graph threads it by the
        # source message id; no manual In-Reply-To assembly needed). Map the
        # result id → SendResult(provider="outlook", sent_message_id=…).
        raise NotImplementedError(_TODO)

    async def fetch_message(self, message_id: str) -> InboundMessage:
        # Graph: GET /me/messages/{message_id}
        #   ?$select=id,conversationId,internetMessageId,from,subject,body
        # → map to InboundMessage (body.content stripped to plain text).
        raise NotImplementedError(_TODO)

    async def search(self, query: str, max_results: int = 20) -> list[InboundMessage]:
        # Graph: GET /me/messages?$search="{query}"&$top={max_results}
        raise NotImplementedError(_TODO)

    async def list_recent_message_ids(self, cursor: str | None = None) -> list[str]:
        # Graph: GET /me/mailFolders/inbox/messages?$select=id
        #   &$orderby=receivedDateTime desc&$top=N  (cursor = the @odata.deltaLink)
        raise NotImplementedError(_TODO)

    async def archive(self, message_id: str) -> None:
        # Graph: POST /me/messages/{message_id}/move {destinationId: "archive"}
        raise NotImplementedError(_TODO)

    async def setup_watch(self) -> dict[str, Any]:
        # Graph: POST /subscriptions (resource=/me/mailFolders/inbox/messages,
        # changeType=created, notificationUrl=/webhooks/outlook, ~3-day expiry).
        raise NotImplementedError(_TODO)

    async def stop_watch(self) -> None:
        # Graph: DELETE /subscriptions/{subscription_id}
        raise NotImplementedError(_TODO)

    def parse_push(self, push_payload: dict[str, Any]) -> str | None:
        # Graph change notifications POST a {"value": [{resource, ...}]} batch;
        # extract the resource id(s) → the cursor handed to list/fetch.
        raise NotImplementedError(_TODO)
