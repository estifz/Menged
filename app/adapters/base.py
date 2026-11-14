"""Channel interface shared by the Telegram bot and the mobile app.

The engines never talk to Telegram or Firebase directly: they build an
`OutMessage` and hand it to the channel registered for the user's
`users.channel`. Adding the app later means adding a channel, not changing
the engines.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.models import Trip, User


@dataclass
class Action:
    """A button attached to a message (inline button in Telegram)."""

    id: str  # e.g. "food:show:12"
    label: str


@dataclass
class OutMessage:
    type: str  # template key, e.g. "time_left"
    text: str  # rendered in the user's language
    params: dict = field(default_factory=dict)
    priority: str = "normal"  # high | normal | low
    silent: bool = False  # deliver without sound
    voice: bool = True  # also send as a voice note when the user has voice on
    actions: list[Action] = field(default_factory=list)
    key: str | None = None  # one-shot dedupe key within a trip
    location: tuple[float, float] | None = None  # optional map pin

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "text": self.text,
            "params": self.params,
            "priority": self.priority,
            "actions": [{"id": a.id, "label": a.label} for a in self.actions],
        }


class Channel(Protocol):
    async def send(self, user: "User", msg: OutMessage) -> bool:
        """Deliver a message. Returns True if a voice note was also sent."""
        ...

    async def update_card(self, user: "User", trip: "Trip", text: str) -> int | None:
        """Create or silently update the live trip card. Returns its message id."""
        ...

    async def close_card(self, user: "User", trip: "Trip", text: str) -> None:
        """Final update of the trip card (and unpin)."""
        ...


class NullChannel:
    """Used when a channel is not configured (e.g. tests, bot disabled)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, OutMessage]] = []

    async def send(self, user, msg) -> bool:
        self.sent.append((user.id, msg))
        return False

    async def update_card(self, user, trip, text) -> int | None:
        return None

    async def close_card(self, user, trip, text) -> None:
        return None


_registry: dict[str, Channel] = {}
_null = NullChannel()


def register(name: str, channel: Channel) -> None:
    _registry[name] = channel


def get(name: str) -> Channel:
    return _registry.get(name, _null)
