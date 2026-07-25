from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from rich.console import RenderableType
from rich.text import Text

from ._entry import Entry
from ._state import EntryState

__all__ = ["FlowDecorator", "StateDecorator"]

T_contra = TypeVar("T_contra", contravariant=True)


@runtime_checkable
class FlowDecorator(Protocol[T_contra]):
    """Produces the *gutter* renderable for an entry.

    The decorator is the counterpart of :class:`FlowPresenter`: the presenter
    fills the body, the decorator fills the gutter (markers, icons, badges,
    timestamps). The two never know about each other — only the view composes
    them.

    ``decorate`` is **synchronous** and expected to be cheap: it may be called
    on every repaint. It must not trigger presentation or reflow. It reads the
    entry's :attr:`~Entry.state`, :attr:`~Entry.metadata`, and item, and
    returns a renderable sized to ``width`` (the gutter width) × ``height`` (the
    entry's body height in rows).
    """

    def decorate(self, entry: Entry[T_contra], width: int, height: int) -> RenderableType: ...


class StateDecorator:
    """A default decorator that renders a colored marker for each
    :class:`EntryState` on the entry's first row.

    Symbols and styles are overridable::

        StateDecorator(symbols={EntryState.RUNNING: "⟳"})
    """

    DEFAULT_SYMBOLS: dict[EntryState, str] = {
        EntryState.DEFAULT: " ",
        EntryState.RUNNING: "✻",
        EntryState.SUCCESS: "✓",
        EntryState.ERROR: "⚠",
        EntryState.CANCELLED: "✖",
    }

    DEFAULT_STYLES: dict[EntryState, str] = {
        EntryState.DEFAULT: "dim",
        EntryState.RUNNING: "yellow",
        EntryState.SUCCESS: "green",
        EntryState.ERROR: "red",
        EntryState.CANCELLED: "dim",
    }

    def __init__(
        self,
        symbols: dict[EntryState, str] | None = None,
        styles: dict[EntryState, str] | None = None,
    ) -> None:
        self._symbols = {**self.DEFAULT_SYMBOLS, **(symbols or {})}
        self._styles = {**self.DEFAULT_STYLES, **(styles or {})}

    def decorate(self, entry: Entry[object], width: int, height: int) -> RenderableType:
        symbol = self._symbols.get(entry.state, " ")
        style = self._styles.get(entry.state, "")
        return Text(symbol, style=style)
