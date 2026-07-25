from __future__ import annotations

from enum import Enum, auto

__all__ = ["EntryState"]


class EntryState(Enum):
    """Library-standard lifecycle state of an entry.

    State is consumed only by a :class:`FlowDecorator` to paint the gutter; it
    never affects :class:`Presentation` generation, and changing it does not
    re-present the body. Applications needing richer states can attach their
    own values through :meth:`Entry.set_metadata`.
    """

    DEFAULT = auto()
    RUNNING = auto()
    SUCCESS = auto()
    ERROR = auto()
    CANCELLED = auto()
