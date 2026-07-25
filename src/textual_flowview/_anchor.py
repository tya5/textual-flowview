from __future__ import annotations

from enum import Enum, auto

__all__ = ["Anchor"]


class Anchor(Enum):
    """Scroll anchoring policy for a :class:`FlowView`.

    ``CURRENT``
        Preserve the current viewport position when items are inserted,
        removed, or their height is finalized. This is the safe default for
        timelines, git history, and any view the user actively browses.

    ``STICKY_BOTTOM``
        Follow the bottom edge *only while the user is already at the bottom*.
        Once the user scrolls up, following stops until they return to the
        bottom. This is the expected behaviour for chat and log views
        (Slack / Discord / Claude Code style).
    """

    CURRENT = auto()
    STICKY_BOTTOM = auto()
