from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType

__all__ = ["Presentation"]


@dataclass(frozen=True)
class Presentation:
    """The visual result of presenting a single item at a given width.

    A ``Presentation`` is the *only* thing a :class:`FlowView` knows how to
    draw. It carries no knowledge of the underlying item type.
    """

    height: int
    """Number of terminal rows the ``renderable`` occupies at the width it
    was produced for."""

    renderable: RenderableType
    """Any Rich renderable (``Text``, ``Panel``, ``Table``, a Textual
    ``Content``, ...) to be drawn for this item."""

    background: str | None = None
    """Optional background colour for the *whole row* — painted edge to edge
    across the gutter, body, and trailing padding, so the entry reads as one
    continuous coloured block (e.g. a user's own message). A colour string
    like ``"#2b2f37"``; ``None`` leaves the row transparent."""
