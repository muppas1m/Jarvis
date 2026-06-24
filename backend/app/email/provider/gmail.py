"""Gmail adapter for the EmailProvider interface.

The ONLY module outside this file that may import ``googleapiclient`` /
``google.oauth2`` is — nothing: this adapter is the single home for Gmail SDK
calls. Every method wraps the exact working logic that previously lived in
``gmail_send`` / ``gmail_watch`` / ``gmail_pubsub`` so behaviour is identical;
only the call site moved behind the interface.

OAuth: the master's app is published to Production, so the refresh token is
durable and google-auth mints access tokens transparently
(project_gmail_refresh_token_expiry_rootcause — fixed, permanent). A fresh
service is built per call (the google client isn't async/loop-bound, and build
is cheap) — matching the prior code, which did the same.
"""
from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from email.mime.text import MIMEText
from typing import Any, TypeVar

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings
from app.email.provider.base import EmailProvider, InboundMessage, ReplyRef, SendResult
from app.utils.logging import get_logger

logger = get_logger(__name__)

_T = TypeVar("_T")


class GmailProvider(EmailProvider):
    name = "gmail"

    # --- blocking-call discipline ------------------------------------------
    async def _blocking(self, fn: Callable[[], _T], *, timeout: float | None = None) -> _T:
        """Run a SYNCHRONOUS Gmail SDK call off the event loop AND bounded.

        The google-api-python-client is synchronous — a bare ``…execute()`` blocks
        the whole backend for the round-trip, and a hung call would wedge it. This
        is the codebase's own to_thread+wait_for idiom (see
        ``app/documents/search.py`` reranker degrade). PLACEMENT: this lives in
        the adapter, not a neutral layer, because "the SDK is synchronous" is a
        Gmail-specific fact — an async-native adapter (Outlook via httpx) wouldn't
        need to_thread, and the timeout is a provider-specific tuning. ``fn``
        builds the service AND executes inside the worker thread, so the OAuth
        ``build`` (which can fetch a discovery doc) is off-loop too."""
        return await asyncio.wait_for(
            asyncio.to_thread(fn),
            timeout=timeout if timeout is not None else settings.EMAIL_PROVIDER_TIMEOUT_S,
        )

    # --- OAuth + service ---------------------------------------------------
    def _service(self):
        """Authenticated Gmail service. token=None + a live refresh token + client
        creds → google-auth refreshes the access token on every call. Called
        INSIDE ``_blocking``'s worker thread (build can do blocking discovery I/O)."""
        creds = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_REFRESH_TOKEN,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
        )
        return build("gmail", "v1", credentials=creds)

    # --- outbound ----------------------------------------------------------
    async def send(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to: ReplyRef | None = None,
    ) -> SendResult:
        """Send plain text; thread the reply when ``reply_to`` is given. Every
        Gmail round-trip runs off-loop + bounded via ``_blocking``."""
        mime = MIMEText(body, "plain", "utf-8")
        mime["To"] = to
        mime["Subject"] = subject
        irt = (reply_to.rfc822_message_id or "").strip() if reply_to else ""
        if irt:
            mime["In-Reply-To"] = irt
            mime["References"] = irt

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
        request_body: dict[str, Any] = {"raw": raw}

        # Belt-and-braces threading: set threadId from the source message so Gmail
        # groups the reply into the same conversation. Idempotent read, off-loop.
        gmid = (reply_to.message_id or "").strip() if reply_to else ""
        if gmid:
            thread_id_gmail = await self._lookup_thread_id(gmid)
            if thread_id_gmail:
                request_body["threadId"] = thread_id_gmail

        result = await self._blocking(
            lambda: self._service().users().messages().send(userId="me", body=request_body).execute()
        )
        return SendResult(
            provider=self.name,
            sent_message_id=result.get("id", "(no-id)"),
            raw=result,
        )

    async def _lookup_thread_id(self, gmid: str) -> str:
        """The source message's threadId (best-effort, off-loop + bounded). A
        failure just means the In-Reply-To header alone threads it in most
        clients, so we log + return ""."""
        try:
            original = await self._blocking(
                lambda: self._service().users().messages().get(
                    userId="me", id=gmid, format="metadata"
                ).execute()
            )
            return original.get("threadId") or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("gmail_send_thread_lookup_failed", message_id=gmid, error=str(exc))
            return ""

    # --- read / fetch ------------------------------------------------------
    async def fetch_message(self, message_id: str) -> InboundMessage:
        full = await self._blocking(
            lambda: self._service().users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        )
        return self._to_inbound(full)

    async def search(self, query: str, max_results: int = 20) -> list[InboundMessage]:
        listing = await self._blocking(
            lambda: self._service().users().messages().list(
                userId="me", q=query, maxResults=max_results
            ).execute()
        )
        ids = [m["id"] for m in listing.get("messages", [])]
        out: list[InboundMessage] = []
        for mid in ids:
            try:
                out.append(await self.fetch_message(mid))
            except Exception as exc:  # noqa: BLE001 — skip a message that vanished mid-search
                logger.warning("gmail_search_fetch_failed", message_id=mid, error=str(exc))
        return out

    # --- receive / watch ---------------------------------------------------
    async def list_recent_message_ids(self, cursor: str | None = None) -> list[str]:
        """Recent INBOX message ids (bounded). `cursor` (historyId) is accepted
        for forward-compat but unused — Phase-1's reset dropped the sync-state
        table, so we list a bounded recent window and the pipeline dedups against
        EmailLog (verbatim from gmail_pubsub._fetch_new_messages' list step)."""
        listing = await self._blocking(
            lambda: self._service().users().messages().list(
                userId="me", labelIds=["INBOX"], maxResults=10
            ).execute()
        )
        return [m["id"] for m in listing.get("messages", [])]

    async def archive(self, message_id: str) -> None:
        await self._blocking(
            lambda: self._service().users().messages().modify(
                userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
            ).execute()
        )

    async def setup_watch(self) -> dict[str, Any]:
        result = await self._blocking(
            lambda: self._service().users().watch(
                userId="me",
                body={"topicName": settings.GMAIL_PUBSUB_TOPIC, "labelIds": ["INBOX"]},
            ).execute()
        )
        logger.info("gmail_watch_registered", expiration=result.get("expiration"))
        return result

    async def stop_watch(self) -> None:
        await self._blocking(
            lambda: self._service().users().stop(userId="me").execute()
        )
        logger.info("gmail_watch_stopped")

    def parse_push(self, push_payload: dict[str, Any]) -> str | None:
        """Pub/Sub push → historyId (verbatim from gmail_pubsub.handle_gmail_push
        decode). The `data` field is base64 JSON carrying historyId."""
        data = push_payload.get("data", "")
        if not data:
            return None
        try:
            decoded = base64.b64decode(data).decode("utf-8")
            return json.loads(decoded).get("historyId")
        except Exception as exc:  # noqa: BLE001 — a malformed push isn't actionable
            logger.warning("gmail_push_parse_failed", error=str(exc))
            return None

    # --- mapping -----------------------------------------------------------
    def _to_inbound(self, full: dict[str, Any]) -> InboundMessage:
        headers = {h["name"]: h["value"] for h in full.get("payload", {}).get("headers", [])}
        return InboundMessage(
            provider=self.name,
            message_id=full.get("id", ""),
            thread_ref=full.get("threadId", ""),
            rfc822_message_id=headers.get("Message-ID") or headers.get("Message-Id") or "",
            sender=headers.get("From", "Unknown"),
            subject=headers.get("Subject", "(No Subject)"),
            body=_extract_body(full),
        )


def _extract_body(message: dict[str, Any]) -> str:
    """Plain-text body from a Gmail message (verbatim from
    gmail_pubsub._extract_body)."""
    payload = message.get("payload", {})
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""
