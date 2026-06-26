"""
Channel abstraction.

Every messaging platform (Telegram, WhatsApp, Discord, iMessage, web chat,
…) implements the `Channel` contract. The agent layer (`runner.py`,
`nodes.py`) NEVER imports anything from `messaging/` — it works against
`NormalizedMessage` only. This keeps adding a new channel a one-class change
rather than a multi-file rewrite.

Two pieces here:
  - `NormalizedMessage` — channel-agnostic shape every inbound message
    becomes after the channel's `normalize()` method runs.
  - `Channel` — abstract base class. Concrete channels live in
    `messaging/channels/<platform>.py`.

The `thread_id_for(platform, user_id)` helper produces the canonical
`<platform>:<channel_user_id>` LangGraph thread identifier. Same person on
the same platform always gets the same thread ID across restarts; same
person on a different platform gets a different thread (intentional —
WhatsApp and Telegram conversations are not the same conversation).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal


PlatformName = Literal["telegram", "whatsapp", "imessage", "discord", "signal", "web"]


@dataclass
class NormalizedMessage:
    """Channel-agnostic representation of an inbound message."""

    platform: PlatformName
    channel_user_id: str            # platform-native ID (chat_id, phone, etc.)
    text: str                       # message body
    thread_id: str                  # canonical: `<platform>:<channel_user_id>`
    is_master: bool                 # whether this user is the authorized master
    reply_to_message_id: str | None = None
    raw: dict = field(default_factory=dict)   # original platform payload (debugging)


class Channel(ABC):
    """Contract every messaging platform must satisfy.

    Subclasses set `platform` to their PlatformName and implement the five
    async methods (normalize, send_reply, send_alert, send_approval_request,
    show_typing). Lifespan wiring constructs an instance via the channel's
    lazy factory and registers it with `channel_registry`.
    """

    platform: str   # subclass sets this

    @abstractmethod
    async def normalize(self, raw_payload: dict) -> NormalizedMessage | None:
        """Convert a raw inbound platform payload into a NormalizedMessage.

        Return None for messages we should ignore (the bot's own messages, edits,
        non-text content this channel doesn't handle, etc.). Returning None is
        a normal control-flow signal, not an error.
        """

    @abstractmethod
    async def send_reply(
        self, msg: NormalizedMessage, text: str, parse_mode: str = "Markdown"
    ) -> None:
        """Send a text reply back via this channel, addressed to the original sender."""

    @abstractmethod
    async def send_alert(self, text: str) -> None:
        """Send a system alert (failure notice, system notification) to the master."""

    @abstractmethod
    async def send_approval_request(
        self, approval_id: str, description: str, needs_drafting: bool = False
    ) -> None:
        """Send an interactive approval prompt to the master.

        On platforms with rich UI (Telegram inline buttons, WhatsApp quick
        replies) this should render approve/reject affordances. On
        text-only platforms, the channel may fall back to text + ask the
        master to reply with `/approve <id>` / `/reject <id>`.

        ``needs_drafting`` flags a COMPLEX-email heads-up (no draft yet): approving
        DRAFTS rather than sends, so the affordances should read "Draft it / Leave it"
        and the confirmation "Drafted." — never "Approve / Approved".
        """

    @abstractmethod
    async def show_typing(self, msg: NormalizedMessage) -> None:
        """Show a typing indicator if the platform supports it. No-op otherwise.

        Defensive: implementations should swallow errors here — a failed
        typing indicator must never block the actual reply.
        """

    # Helper — keep the canonical thread_id format in one place.
    @staticmethod
    def thread_id_for(platform: str, channel_user_id: str) -> str:
        """e.g. `telegram:6038659957` — used as LangGraph thread_id."""
        return f"{platform}:{channel_user_id}"
