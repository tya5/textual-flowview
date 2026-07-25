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
