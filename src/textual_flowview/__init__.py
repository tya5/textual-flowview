"""textual-flowview — a virtualized Flow View widget for Textual.

Public API (v0.3):

    from textual_flowview import (
        FlowModel,
        Entry,
        Presentation,
        FlowPresenter,
        Anchor,
    )

``FlowView`` (the widget) lands in the next milestone.
"""

from __future__ import annotations

from ._anchor import Anchor
from ._decorator import FlowDecorator, StateDecorator
from ._entry import Entry
from ._minimap import FlowMinimap
from ._model import FlowModel
from ._presentation import Presentation
from ._presenter import FlowPresenter
from ._state import EntryState
from ._view import AnimationHandle, FlowView, VisibilityHandle

__all__ = [
    "Anchor",
    "AnimationHandle",
    "Entry",
    "EntryState",
    "FlowDecorator",
    "FlowMinimap",
    "FlowModel",
    "FlowPresenter",
    "FlowView",
    "Presentation",
    "StateDecorator",
    "VisibilityHandle",
]

__version__ = "0.20.0"
