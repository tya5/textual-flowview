from __future__ import annotations

from typing import ClassVar, Protocol, TypeVar, runtime_checkable

from rich.console import RenderableType
from rich.text import Text

from ._entry import Entry
from ._state import EntryState

__all__ = ["FlowDecorator", "StateDecorator"]

# Invariant: the protocol wraps the item in Entry[T], which is itself invariant.
T = TypeVar("T")


@runtime_checkable
class FlowDecorator(Protocol[T]):
    """Produces the *gutter* renderable for an entry.

    The decorator is the counterpart of :class:`FlowPresenter`: the presenter
    fills the body, the decorator fills the gutter (markers, icons, badges,
    timestamps). The two never know about each other — only the view composes
    them.

    ``decorate`` is **synchronous** and expected to be cheap: it may be called
    on every repaint. It must not trigger presentation or reflow. It reads the
    entry's :attr:`~Entry.state`, :attr:`~Entry.metadata`, and item, and
    returns a renderable sized to ``width`` (the gutter width) by ``height``
    (the entry's body height in rows).

    It runs **on the event loop, inside painting**, which has to produce a row
    synchronously — so it cannot be async and cannot wait for anything. Whatever
    it draws must already be in memory. If the gutter wants data it doesn't have,
    draw a placeholder, fetch it off the paint path (e.g.
    ``view.run_worker(...)`` from a :meth:`~FlowView.track_visibility` hook), and
    call :meth:`~FlowView.refresh_gutter` when it lands. Blocking here freezes
    the UI on every repaint; see ``docs/event-loop.md``.

    Two properties of the contract are load-bearing for multi-line gutters:

    * ``height`` is **post-wrap** — the body's presented height *at the current
      width* (the row count the body actually occupies now), not a fixed
      declared height: the presenter re-presents when the width changes, so a
      decorator always sees the up-to-date count and multi-line gutters line up.
      (During the brief window before an entry is presented, ``height`` is the
      placeholder's line count; because the gutter cache is keyed on height,
      ``decorate`` is re-invoked once the real presentation lands, so the final
      state is correct — but a decorator with side effects may run more than
      once with different heights.)
    * The returned renderable is **clamped to ``width``** (via
      ``Strip.adjust_cell_length``): content wider than ``width`` — easy to hit
      with double-width or East-Asian-ambiguous glyphs, where cell count differs
      from character count — is **silently truncated**, never overflowed. Size
      to ``width`` in *cells* to avoid losing content.
    """

    def decorate(self, entry: Entry[T], width: int, height: int) -> RenderableType: ...


class StateDecorator:
    """A default decorator that renders a colored marker for each
    :class:`EntryState` on the entry's first row.

    Symbols and styles are overridable::

        StateDecorator(symbols={EntryState.RUNNING: "⟳"})
    """

    DEFAULT_SYMBOLS: ClassVar[dict[EntryState, str]] = {
        EntryState.DEFAULT: " ",
        EntryState.RUNNING: "✻",
        EntryState.SUCCESS: "✓",
        EntryState.ERROR: "⚠",
        EntryState.CANCELLED: "✖",
    }

    DEFAULT_STYLES: ClassVar[dict[EntryState, str]] = {
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
