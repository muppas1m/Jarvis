"""
Channel registry.

One instance per platform. The router picks the right channel by reading
the `platform` field on a `NormalizedMessage` (defined in `channel.py`).

Module-level singleton (`channel_registry`) is what the rest of the
codebase imports. Lifespan wiring (`app.main`) calls
`channel_registry.register(channel_instance)` once per platform after the
DB and checkpointer are up.

Filename note: originally `normalizer.py` (filename predated this file
holding the registry); renamed to `channel_registry.py` at frontier-upgrade
Step 9 audit (2026-05-25) to match contents — discoverability fix.
"""
from app.messaging.channel import Channel
from app.utils.logging import get_logger

logger = get_logger(__name__)


class ChannelRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        if channel.platform in self._channels:
            logger.warning("channel_re_registered", platform=channel.platform)
        self._channels[channel.platform] = channel
        logger.info("channel_registered", platform=channel.platform)

    def get(self, platform: str) -> Channel:
        ch = self._channels.get(platform)
        if ch is None:
            raise ValueError(f"No channel registered for platform: {platform!r}")
        return ch

    def has(self, platform: str) -> bool:
        return platform in self._channels

    def all(self) -> list[Channel]:
        return list(self._channels.values())


# Singleton — every other module imports this.
channel_registry = ChannelRegistry()
