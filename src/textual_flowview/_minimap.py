from __future__ import annotations

from typing import ClassVar, Generic, TypeVar

from rich.segment import Segment
from rich.style import Style
from textual import events
from textual.strip import Strip
from textual.widget import Widget

from ._state import EntryState
from ._view import FlowView

__all__ = ["FlowMinimap"]

T = TypeVar("T")

# Higher wins when a minimap cell covers several entries.
_SEVERITY: dict[EntryState, int] = {
    EntryState.DEFAULT: 0,
    EntryState.SUCCESS: 1,
    EntryState.CANCELLED: 1,
    EntryState.RUNNING: 2,
    EntryState.ERROR: 3,
}

_DEFAULT_COLORS: dict[EntryState, str] = {
    EntryState.DEFAULT: "grey37",
    EntryState.SUCCESS: "green",
    EntryState.CANCELLED: "grey30",
    EntryState.RUNNING: "yellow",
    EntryState.ERROR: "red",
}


class FlowMinimap(Widget, Generic[T]):
    """A scrollbar-replacing overview strip for a :class:`FlowView`.

    Compresses the whole (laid-out) flow into a thin vertical strip: each row is
    a bucket of entries painted in the colour of its most notable state, and the
    rows corresponding to the on-screen range are highlighted as the "window"
    (a content-aware scroll thumb). Click or drag to scroll the view.

    Place it next to the view and hide the view's native scrollbar::

        with Horizontal():
            yield FlowView(model=m, presenter=p, id="flow")
            yield FlowMinimap(flow_view=self.query_one("#flow", FlowView))
        # CSS:  FlowView { scrollbar-size-vertical: 0; }
    """

    DEFAULT_CSS = """
    FlowMinimap {
        width: 1;
        height: 1fr;
    }
    FlowMinimap > .flowminimap--window {
        background: $panel;
    }
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {"flowminimap--window"}

    def __init__(
        self,
        *,
        flow_view: FlowView[T],
        colors: dict[EntryState, str] | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._view = flow_view
        self._colors = {**_DEFAULT_COLORS, **(colors or {})}
        self._dragging = False

    def on_mount(self) -> None:
        # Repaint whenever the view scrolls or its content/heights change.
        self.watch(self._view, "scroll_y", self._view_changed, init=False)
        self.watch(self._view, "virtual_size", self._view_changed, init=False)

    def _view_changed(self) -> None:
        self.refresh()

    # -- rendering ---------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        height = self.size.height
        entries = self._view.entries
        n = len(entries)
        if n == 0 or height <= 0 or width <= 0:
            return Strip.blank(max(0, width))

        lo = y * n // height
        hi = max(lo + 1, (y + 1) * n // height)
        bucket = entries[lo:hi]

        state = max(
            (entry.state for entry in bucket),
            key=lambda s: _SEVERITY.get(s, 0),
            default=EntryState.DEFAULT,
        )
        color = self._colors.get(state, "grey37")

        start, stop = self._view.visible_range()
        in_window = lo < stop and hi > start

        if in_window:
            window_bg = self.get_component_rich_style("flowminimap--window").bgcolor
            style = Style(color=color, bgcolor=window_bg)
        else:
            style = Style(color=color)
        return Strip([Segment("█" * width, style)], width)

    # -- interaction -------------------------------------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._dragging = True
        self.capture_mouse()
        self._scroll_to_row(event.y)

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._dragging:
            self._scroll_to_row(event.y)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._dragging = False
        self.release_mouse()

    def _scroll_to_row(self, y: int) -> None:
        entries = self._view.entries
        n = len(entries)
        height = self.size.height
        if n == 0 or height <= 0:
            return
        index = min(n - 1, max(0, y * n // height))
        self._view.scroll_to_entry(entries[index])
