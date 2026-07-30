from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Generic, Literal, TypeVar

from rich.cells import cell_len
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import events
from textual.binding import Binding, BindingType
from textual.geometry import Offset, Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.selection import Selection
from textual.strip import Strip
from textual.timer import Timer

from ._anchor import Anchor
from ._decorator import FlowDecorator
from ._entry import Entry
from ._layout import FlowLayout
from ._model import FlowModel
from ._presentation import Presentation
from ._presenter import FlowPresenter
from ._state import EntryState
from ._viewport import AnchorState, Viewport

__all__ = ["AnimationHandle", "FlowView", "VisibilityHandle"]

T = TypeVar("T")


class _VisibilityObserver(Generic[T]):
    """A user resource whose lifecycle is tied to an entry's viewport state."""

    __slots__ = ("entry", "on_hide", "on_show", "shown")

    def __init__(
        self,
        entry: Entry[T],
        on_show: Callable[[Entry[T]], None] | None,
        on_hide: Callable[[Entry[T]], None] | None,
    ) -> None:
        self.entry = entry
        self.on_show = on_show
        self.on_hide = on_hide
        self.shown = False


class VisibilityHandle:
    """Stops a visibility tracker started with :meth:`FlowView.track_visibility`.

    Stopping while the entry is on screen runs ``on_hide`` once, so a resource is
    always released."""

    __slots__ = ("_observer", "_view")

    def __init__(self, view: FlowView[Any], observer: _VisibilityObserver[Any]) -> None:
        self._view = view
        self._observer = observer

    def stop(self) -> None:
        self._view._remove_observer(self._observer)


class AnimationHandle:
    """Cancels an entry animation started with :meth:`FlowView.animate_entry`."""

    __slots__ = ("_entry_id", "_view")

    def __init__(self, view: FlowView[Any], entry_id: int) -> None:
        self._view = view
        self._entry_id = entry_id

    def stop(self) -> None:
        self._view._stop_animation(self._entry_id)


class FlowView(ScrollView, Generic[T]):
    """A virtualized flow of variable-height items.

    ``FlowView`` uses :class:`~textual.scroll_view.ScrollView` purely as a
    *scroll mechanism* (scrollbars, wheel, keyboard, focus, ``virtual_size``).
    It never relies on ScrollView's drawing model: it decides which entries to
    paint itself via :class:`Viewport` (visible range) and :class:`FlowLayout`
    (presentation/height cache), presenting off-screen items only when they are
    actually needed.

    The widget knows nothing about the item type ``T`` — only the
    :class:`FlowPresenter` does.
    """

    can_focus = True

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "flowview--selected",
        "flowview--sticky-header",
        "flowview--highlight",
    }
    """
    | Class | Applied to |
    | :- | :- |
    | ``flowview--selected`` | The currently selected entry's rows. |
    | ``flowview--sticky-header`` | The pinned sticky header's rows. |
    | ``flowview--highlight`` | The keyboard-highlight entry's rows (``highlight=True``). |

    FlowView ships **no colours of its own** — these classes are unstyled by
    default, so nothing is painted until your app (or theme) gives them a style
    (only the rules you declare are applied — an undeclared class contributes
    nothing). A declared background is applied as an **override**, so it wins
    over a row's :attr:`Presentation.background`. Text selection likewise defers
    to Textual's ``screen--selection``.
    """

    # Focus-scoped, overridable defaults. They map keys onto the highlight
    # *actions* (the real API); with ``highlight=False`` the arrow / page / home /
    # end actions fall through to plain scrolling, and enter/space are disabled
    # (see ``check_action``) so they bubble to the app. Override or clear them
    # freely — keybinding policy stays the product's.
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up", "highlight_up", "Highlight up", show=False),
        Binding("down", "highlight_down", "Highlight down", show=False),
        Binding("pageup", "highlight_page_up", "Highlight page up", show=False),
        Binding("pagedown", "highlight_page_down", "Highlight page down", show=False),
        Binding("home", "highlight_home", "Highlight to first", show=False),
        Binding("end", "highlight_end", "Highlight to last", show=False),
        Binding("enter", "activate", "Activate", show=False),
        Binding("space", "activate", "Activate", show=False),
        # Copy-mode (vim-like) — live only while in copy mode (see check_action),
        # so these keys bubble to the app otherwise. Rebind/clear as usual.
        Binding("h", "copy_left", "Left", show=False),
        Binding("l", "copy_right", "Right", show=False),
        Binding("k", "copy_up", "Up", show=False),
        Binding("j", "copy_down", "Down", show=False),
        Binding("0", "copy_line_start", "Line start", show=False),
        Binding("dollar_sign", "copy_line_end", "Line end", show=False),
        Binding("circumflex_accent", "copy_first_nonblank", "First non-blank", show=False),
        Binding("w", "copy_word_forward", "Word →", show=False),
        Binding("b", "copy_word_back", "Word ←", show=False),
        Binding("e", "copy_word_end", "Word end", show=False),
        Binding("G", "copy_bottom", "Bottom", show=False),
        Binding("left_square_bracket", "copy_entry_start", "Entry top", show=False),
        Binding("right_square_bracket", "copy_entry_end", "Entry bottom", show=False),
        Binding("v", "copy_visual", "Visual", show=False),
        Binding("V", "copy_visual_line", "Visual line", show=False),
        Binding("y", "copy_yank", "Yank", show=False),
        Binding("asterisk", "copy_search_selection", "Search selection", show=False),
        Binding("n", "copy_search_next", "Search next", show=False),
        Binding("N", "copy_search_previous", "Search prev", show=False),
        Binding("ctrl+e", "copy_scroll_line_down", "Scroll line down", show=False),
        Binding("ctrl+y", "copy_scroll_line_up", "Scroll line up", show=False),
        Binding("escape", "copy_exit", "Exit copy mode", show=False),
    ]

    class Selected(Message):
        """Posted when the selected entry changes (including to ``None``).

        Access the chosen entry via :attr:`entry`; ``event.control`` is the
        :class:`FlowView` that emitted it.
        """

        def __init__(self, flow_view: FlowView[Any], entry: Entry[Any] | None) -> None:
            self.flow_view = flow_view
            self.entry = entry
            super().__init__()

        @property
        def control(self) -> FlowView[Any]:
            return self.flow_view

    class Clicked(Message):
        """Posted on every click that lands on an entry (unlike
        :class:`Selected`, which only fires when the selection changes).

        Carries the entry and the click position **within that entry's body**:
        ``x`` is the column (0 = first body cell; negative means the gutter),
        ``y`` is the row within the entry. Use it to hit-test presenter-drawn
        controls — buttons, option chips, an intervention selector.
        """

        def __init__(self, flow_view: FlowView[Any], entry: Entry[Any], x: int, y: int) -> None:
            self.flow_view = flow_view
            self.entry = entry
            self.x = x
            self.y = y
            super().__init__()

        @property
        def control(self) -> FlowView[Any]:
            return self.flow_view

    class ReachedTop(Message):
        """Posted when scrolling brings the top edge within ``reach_threshold``
        rows. Handle it to lazy-load older items (prepend them with
        ``model.insert(0, ...)`` — the view keeps its position). Fires once per
        approach; scrolling away from the edge re-arms it.
        """

        def __init__(self, flow_view: FlowView[Any]) -> None:
            self.flow_view = flow_view
            super().__init__()

        @property
        def control(self) -> FlowView[Any]:
            return self.flow_view

    class ReachedBottom(Message):
        """Posted when scrolling brings the bottom edge within
        ``reach_threshold`` rows. Handle it to lazy-load newer items (append
        them). Fires once per approach; scrolling away re-arms it.
        """

        def __init__(self, flow_view: FlowView[Any]) -> None:
            self.flow_view = flow_view
            super().__init__()

        @property
        def control(self) -> FlowView[Any]:
            return self.flow_view

    class Highlighted(Message):
        """Posted when the keyboard highlight moves to an entry (``highlight=True``).
        ``entry`` is the newly highlighted entry, or ``None`` when cleared.
        """

        def __init__(self, flow_view: FlowView[Any], entry: Entry[Any] | None) -> None:
            self.flow_view = flow_view
            self.entry = entry
            super().__init__()

        @property
        def control(self) -> FlowView[Any]:
            return self.flow_view

    class Activated(Message):
        """Posted when the highlight entry is activated (Enter / Space by default).
        ``entry`` is the activated entry.
        """

        def __init__(self, flow_view: FlowView[Any], entry: Entry[Any]) -> None:
            self.flow_view = flow_view
            self.entry = entry
            super().__init__()

        @property
        def control(self) -> FlowView[Any]:
            return self.flow_view

    def __init__(
        self,
        *,
        model: FlowModel[T],
        presenter: FlowPresenter[T],
        decorator: FlowDecorator[T] | None = None,
        gutter_width: int | None = None,
        right_decorator: FlowDecorator[T] | None = None,
        right_gutter_width: int | None = None,
        selectable: bool = False,
        highlight: bool = False,
        copy_scrolloff: int = 0,
        sticky_header: Callable[[Entry[T]], bool] | None = None,
        anchor: Anchor = Anchor.CURRENT,
        estimated_height: int = 1,
        overscan: int = 4,
        read_ahead: int | None = None,
        reach_threshold: int = 0,
        spacing: int = 1,
        separator: RenderableType
        | Callable[[Entry[T], Entry[T]], RenderableType | None]
        | None = None,
        animation_fps: float = 0,
        placeholder: RenderableType = "Loading...",
        empty: RenderableType | None = None,
        empty_align: Literal["top", "middle", "bottom"] = "middle",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._model = model
        self._presenter = presenter
        # Left and right gutters are independent: each has its own decorator and
        # width. `decorator`/`gutter_width` are the left gutter (unchanged);
        # `right_decorator`/`right_gutter_width` add an optional right one.
        self._decorator = decorator
        self._right_decorator = right_decorator
        # Predicate marking an entry as a group header to pin while scrolling.
        self._is_sticky_header = sticky_header
        # Rows to pre-present *ahead of the scroll direction*, beyond the static
        # overscan band. None -> one viewport height. 0 disables read-ahead.
        self._read_ahead = read_ahead
        # Infinite scroll: post ReachedTop/ReachedBottom when the edge comes
        # within this many rows. Edge-triggered (fires once per approach), with
        # a re-arm flag per side so a handler that loads more isn't spammed.
        self._reach_threshold = max(0, reach_threshold)
        self._reached_top_signaled = False
        self._reached_bottom_signaled = False
        # >0: shorthand that auto-drives every visible entry's gutter at this
        # frame rate (like refresh_gutter on each, no per-entry registration) so
        # a time-based decorator animates on its own. 0 disables it.
        self._animation_fps = max(0.0, animation_fps)
        # Direction of the last scroll: -1 up, +1 down, 0 none.
        self._scroll_dir = 0
        # Per-frame memo of the sticky-header computation, keyed by scroll_y.
        self._sticky_cache: tuple[int, tuple[Entry[T], int, int] | None] | None = None
        # No decorator -> no gutter. Decorator but unset width -> a sensible 2.
        if gutter_width is None:
            gutter_width = 2 if decorator is not None else 0
        self._gutter_width = max(0, gutter_width)
        if right_gutter_width is None:
            right_gutter_width = 2 if right_decorator is not None else 0
        self._right_gutter_width = max(0, right_gutter_width)
        # Configured widths above are fixed; visibility is toggled at runtime
        # (show_gutter/hide_gutter). Effective width = width if visible else 0.
        self._gutter_visible = True
        self._right_gutter_visible = True
        self._layout: FlowLayout[T] = FlowLayout()
        self._viewport: Viewport[T] = Viewport(
            self._layout,
            anchor=anchor,
            estimated_height=estimated_height,
            overscan=overscan,
            spacing=spacing,
        )
        self._placeholder = placeholder
        # Shown (whole-viewport) when there are no entries to draw. Vertical
        # placement is `empty_align`; horizontal alignment / styling lives in the
        # renderable itself (wrap it in rich Align / Panel as you like).
        self._empty = empty
        self._empty_align = empty_align
        # Gap (in rows) between entries, and what's drawn in it. `spacing` is the
        # authoritative gap height; `separator` (a renderable, or a
        # callable(above, below) -> renderable | None) is painted into those
        # rows. None -> a plain blank gap (the default).
        self._spacing = max(0, spacing)
        self._separator = separator
        # id -> (revision, width, strips)
        self._strip_cache: dict[int, tuple[int, int, list[Strip]]] = {}
        # (id, side) -> (decor_revision, width, height, strips)
        self._gutter_cache: dict[
            tuple[int, str], tuple[int, int, int, list[Strip]]
        ] = {}
        # (above.id, below.id) -> (above_rev, below_rev, width, height, strips)
        self._separator_cache: dict[
            tuple[int, int], tuple[int, int, int, int, list[Strip]]
        ] = {}
        # entry ids with an active presentation loop (one worker per entry).
        self._presenting: set[int] = set()
        # STICKY_BOTTOM/STICKY_TOP: are we currently glued to that edge?
        self._follow_bottom = anchor is Anchor.STICKY_BOTTOM
        self._follow_top = anchor is Anchor.STICKY_TOP
        # Single-selection state, owned by the view (not the entry). Disabled by
        # default: no click-to-select and no highlight until `selectable=True`.
        self._selectable = selectable
        self._selected: Entry[T] | None = None
        # Keyboard highlight (opt-in). When off, the arrow/page/home/end bindings
        # fall through to scrolling and enter/space bubble (see check_action).
        self._highlight_enabled = highlight
        self._highlighted: Entry[T] | None = None
        # Text/copy cursor mode (vim-like): a character cursor over the rendered
        # content, drawn via the widget's own text selection. Entered at runtime
        # (enter_copy_mode); the motion keys are default bindings gated on it.
        self._copy_mode = False
        self._tc_row = 0
        self._tc_col = 0
        self._tc_anchor: tuple[int, int] | None = None  # visual-mode start (row, col)
        self._tc_line_visual = False
        self._tc_pending = ""  # multi-key prefix in copy-mode ("g" or "z")
        # The cursor is anchored to (entry, row-within-entry) so it rides content
        # changes (insert/remove/reflow) instead of sliding to a stale abs row.
        self._tc_entry: Entry[T] | None = None
        self._tc_local = 0
        self._copy_query = ""  # last copy-mode text search
        # Rows of context kept above/below the copy cursor (vim `scrolloff`); the
        # view scrolls early to preserve it. Capped at half the viewport, so a
        # large value (e.g. 999) pins the cursor to the centre.
        self._copy_scrolloff = max(0, copy_scrolloff)
        # Per-entry visibility observers: acquire/release a user resource as the
        # entry enters/leaves the viewport (the general lifecycle hook).
        self._observers: dict[int, list[_VisibilityObserver[T]]] = {}
        # Per-entry animations (a timer resource built on top of _observers).
        self._animations: dict[
            int, tuple[Entry[T], Callable[[Entry[T]], None], Timer, VisibilityHandle]
        ] = {}
        # Ids of entries currently in the visible range (for lifecycle gating).
        self._visible_ids: set[int] = set()
        # Ids of entries in the present band (visible + overscan + read-ahead).
        # An update() to an entry outside this band is deferred until it scrolls
        # in, so off-screen updates do no present/reflow work.
        self._band_ids: set[int] = set()

    # -- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        self._model._attach(self)
        self._sync_geometry()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(None)
        self._present_visible()
        if self._animation_fps > 0:
            # FlowView owns the animation clock (not the app): re-derive gutters
            # at this frame rate so a time-based decorator animates on its own.
            self.set_interval(1 / self._animation_fps, self._tick_animation)

    def _tick_animation(self) -> None:
        # Drop cached gutter strips so the decorator re-runs (with the current
        # time) on the next repaint. Bodies are left cached — no re-present.
        self._gutter_cache.clear()
        self.refresh()

    def on_unmount(self) -> None:
        self._model._detach()

    def on_resize(self) -> None:
        state = self._capture()
        self._sync_geometry()
        width = self._content_width()
        self._layout.retain_width(width)
        self._strip_cache.clear()
        self._refresh_layout(state)
        self._present_visible()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if new_value > old_value:
            self._scroll_dir = 1
        elif new_value < old_value:
            self._scroll_dir = -1
        if self._viewport.anchor is Anchor.STICKY_BOTTOM:
            # Follow only while parked at the bottom; scrolling up releases it.
            self._follow_bottom = int(new_value) >= self.max_scroll_y
        elif self._viewport.anchor is Anchor.STICKY_TOP:
            # Follow only while parked at the top; scrolling down releases it.
            self._follow_top = int(new_value) <= 0
        self._present_visible()
        self._check_edges()

    def _check_edges(self) -> None:
        """Post ReachedTop / ReachedBottom when an edge is within
        ``reach_threshold``. Edge-triggered: fires once on approach, re-arms on
        retreat, so a handler that loads more items isn't called repeatedly."""
        if not self.is_mounted or self._content_width() <= 0:
            return
        if not self._viewport.entries:
            return
        y = round(self.scroll_offset.y)
        thr = self._reach_threshold
        near_top = y <= thr
        near_bottom = y >= self.max_scroll_y - thr
        if near_top and not self._reached_top_signaled:
            self._reached_top_signaled = True
            self.post_message(self.ReachedTop(self))
        if not near_top:
            self._reached_top_signaled = False
        if near_bottom and not self._reached_bottom_signaled:
            self._reached_bottom_signaled = True
            self.post_message(self.ReachedBottom(self))
        if not near_bottom:
            self._reached_bottom_signaled = False

    # -- ModelListener (internal, called on the message loop) -------------

    def on_flow_insert(self, entry: Entry[T], index: int) -> None:
        state = self._capture()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)
        self._reanchor_copy_cursor()

    def on_flow_insert_many(self, entries: list[Entry[T]], index: int) -> None:
        # One capture/restore + one reflow for the whole batch (repeated single
        # inserts each reflow; position is preserved either way, this is just the
        # cheaper path for a page of load-more items).
        state = self._capture()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)
        self._reanchor_copy_cursor()

    def on_flow_update(self, entry: Entry[T]) -> None:
        # The revision bump already makes the cached presentation a miss.
        self._strip_cache.pop(entry.id, None)
        if entry.id not in self._band_ids:
            # Off-screen: skip the present + reflow. The new revision is a cache
            # miss, so the entry re-presents (and reflows) lazily when it scrolls
            # into view — no wasted work for an update no one can see. Its layout
            # keeps its last-known height until then, so nothing on screen shifts.
            return
        state = self._capture()
        self._refresh_layout(state)
        self._present_entry(entry)
        self._reanchor_copy_cursor()

    def on_flow_remove(self, entry: Entry[T], index: int) -> None:
        if self._selected is entry:
            self.select(None)
        if self._highlighted is entry:
            self.highlight_entry(None)
        self._stop_animation(entry.id)
        self._drop_observers(entry.id)
        self._visible_ids.discard(entry.id)
        if self._tc_entry is entry:
            self._tc_entry = None  # anchor entry gone; reanchor falls back to abs row
        state = self._capture()
        self._layout.discard(entry.id)
        self._strip_cache.pop(entry.id, None)
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)
        self._reanchor_copy_cursor()

    def on_flow_visibility(self, entry: Entry[T]) -> None:
        # Which entries are visible changed (a group collapsed/expanded). Rebuild
        # the viewport's entry list and reflow — but keep every cached
        # presentation, so hiding/showing is instant and never re-presents.
        if entry.hidden and self._selected is entry:
            self.select(None)
        if entry.hidden and self._highlighted is entry:
            self.highlight_entry(None)
        state = self._capture()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)
        self._present_visible()
        self._reanchor_copy_cursor()

    def on_flow_clear(self) -> None:
        self.exit_copy_mode()  # nothing left to navigate
        if self._selected is not None:
            self.select(None)
        if self._highlighted is not None:
            self.highlight_entry(None)
        for entry_id in list(self._animations):
            self._stop_animation(entry_id)
        for entry_id in list(self._observers):
            self._drop_observers(entry_id)
        self._visible_ids = set()
        self._layout.clear()
        self._strip_cache.clear()
        self._gutter_cache.clear()
        self._separator_cache.clear()
        self._presenting.clear()
        self._viewport.set_entries([])
        self._refresh_layout(None)
        self.scroll_to(y=0, animate=False)

    def on_flow_decorate(self, entry: Entry[T]) -> None:
        # Gutter-only change: drop the gutter cache and repaint. The body's
        # strip cache and the layout heights are untouched, so no re-present
        # and no reflow happen.
        self._drop_gutter_cache(entry)
        self.refresh()

    # -- public API --------------------------------------------------------

    @property
    def entries(self) -> list[Entry[T]]:
        """The entries currently laid out (model order, hidden ones excluded) —
        the same list the view draws. Useful for an overview like a minimap."""
        return self._viewport.entries

    def visible_range(self) -> tuple[int, int]:
        """``(start, stop)`` indices into :attr:`entries` for the rows currently
        on screen (``stop`` exclusive)."""
        self._sync_scroll()
        vr = self._viewport.visible_range()
        return vr.start, vr.stop

    @property
    def row_count(self) -> int:
        """Total number of content rows (all entries plus spacer gaps) — the
        virtual height. Row indices for :meth:`row_text` run ``0 .. row_count-1``
        and match the ``y`` in a text :class:`~textual.selection.Selection`."""
        return self._viewport.total_height

    def row_text(self, y: int) -> str:
        """The plain text of content row ``y`` (``""`` for an out-of-range row or
        a spacer gap). The ``x`` of a selection ``Offset`` indexes into this
        string, so it's the basis for a text/copy-mode cursor built on the
        selection API."""
        if self._content_width() <= 0:
            return ""
        return self._content_row_text(y, self._content_width())

    def entry_at_row(self, y: int) -> Entry[T] | None:
        """The entry that owns content row ``y`` (``None`` for a spacer gap or an
        out-of-range row). Ties the fine text/copy cursor to an entry — the
        *current entry* is ``entry_at_row(text-cursor row)``."""
        located = self._viewport.locate(y)
        return self._viewport.entries[located[0]] if located is not None else None

    def scroll_to_top(
        self, *, animate: bool = False, duration: float | None = None
    ) -> None:
        self.scroll_to(y=0, animate=animate, duration=duration)

    def scroll_to_bottom(
        self, *, animate: bool = False, duration: float | None = None
    ) -> None:
        self.scroll_to(y=self.max_scroll_y, animate=animate, duration=duration)

    def scroll_to_entry(
        self,
        entry: Entry[T],
        *,
        align: Literal["start", "center", "end", "nearest"] = "start",
        animate: bool = False,
        duration: float | None = None,
    ) -> None:
        """Scroll ``entry`` to ``align`` within the viewport: ``"start"`` (top,
        the default), ``"center"``, ``"end"`` (bottom), or ``"nearest"`` (the
        minimal scroll — same as :meth:`ensure_visible`). ``center`` is handy for
        a search hit, so context above and below is visible.

        Pass ``animate=True`` for a smooth jump (optionally timed with
        ``duration``); content presents as it scrolls past."""
        self._jump_to_entry(entry, align=align, animate=animate, duration=duration)

    def ensure_visible(
        self, entry: Entry[T], *, animate: bool = False, duration: float | None = None
    ) -> None:
        """Scroll the minimum amount so ``entry`` is fully visible
        (``scroll_to_entry(entry, align="nearest")``)."""
        self._jump_to_entry(entry, align="nearest", animate=animate, duration=duration)

    def _jump_to_entry(
        self,
        entry: Entry[T],
        *,
        align: Literal["start", "center", "end", "nearest"],
        animate: bool,
        duration: float | None,
    ) -> None:
        self._sync_scroll()
        self._viewport.scroll_entry_aligned(entry, align)
        self.scroll_to(y=self._viewport.scroll_y, animate=animate, duration=duration)

    def stop_scroll_animation(self) -> None:
        """Interrupt an in-flight animated scroll, staying at the current
        position (rather than snapping to where it was heading).

        A no-op when nothing is animating. It only affects an *animated* scroll
        (``scroll_to_entry(..., animate=True)`` and friends); an instant scroll
        has already landed. Note a fresh animated jump already supersedes the
        previous one, so reach for this only to stop *without* moving on."""
        self.scroll_to(y=round(self.scroll_offset.y), animate=False)

    @property
    def selected(self) -> Entry[T] | None:
        """The currently selected entry, or ``None``."""
        return self._selected

    def select(self, entry: Entry[T] | None) -> None:
        """Select ``entry`` (or clear the selection with ``None``).

        A no-op if it is already selected, or if the view is not ``selectable``
        (the default) — selection, including its highlight and the
        :class:`Selected` message, is entirely off until ``selectable=True``.
        Posts :class:`FlowView.Selected` when the selection changes.
        """
        if not self._selectable:
            return
        if entry is not None and not entry.alive:
            return
        if self._selected is entry:
            return
        self._selected = entry
        self.refresh()
        self.post_message(self.Selected(self, entry))

    def clear_selection(self) -> None:
        """Clear the current selection (if any)."""
        self.select(None)

    # -- keyboard highlight ---------------------------------------------------

    @property
    def highlighted(self) -> Entry[T] | None:
        """The entry under the keyboard highlight, or ``None`` (``highlight=True``)."""
        return self._highlighted

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> bool | None:
        # Disable enter/space when the highlight is off so they bubble to the app.
        # The arrow/page/home/end actions stay enabled and fall through to
        # scrolling (below), preserving the default scroll behaviour.
        if action == "activate" and not self._highlight_enabled:
            return False
        # Copy-mode motions are live only while in copy mode; otherwise their
        # keys bubble to the app untouched.
        if action.startswith("copy_") and not self._copy_mode:
            return False
        return True

    def highlight_entry(self, entry: Entry[T] | None) -> None:
        """Move the keyboard highlight to ``entry`` (or clear it with ``None``),
        scrolling it into view and posting :class:`Highlighted`. A no-op if the
        entry is dead, hidden, or already the highlight."""
        if entry is not None and (not entry.alive or entry.hidden):
            return
        if self._highlighted is entry:
            return
        self._highlighted = entry
        if entry is not None:
            self.ensure_visible(entry)
        self.refresh()
        self.post_message(self.Highlighted(self, entry))

    def move_highlight(self, delta: int) -> None:
        """Move the highlight by ``delta`` entries (clamped, hidden ones skipped —
        the viewport's entry list is already hidden-free). With no highlight yet,
        the first move lands on the first (``delta > 0``) or last entry."""
        entries = self._viewport.entries
        if not entries:
            return
        if self._highlighted is None:
            self.highlight_entry(entries[0] if delta > 0 else entries[-1])
            return
        try:
            index = entries.index(self._highlighted)
        except ValueError:
            self.highlight_entry(entries[0] if delta > 0 else entries[-1])
            return
        self.highlight_entry(entries[max(0, min(index + delta, len(entries) - 1))])

    def highlight_first(self) -> None:
        """Move the highlight to the first entry."""
        entries = self._viewport.entries
        if entries:
            self.highlight_entry(entries[0])

    def highlight_last(self) -> None:
        """Move the highlight to the last entry."""
        entries = self._viewport.entries
        if entries:
            self.highlight_entry(entries[-1])

    def activate(self) -> None:
        """Activate the highlight entry — posts :class:`Activated`. A no-op with no
        highlight."""
        if self._highlighted is not None:
            self.post_message(self.Activated(self, self._highlighted))

    def _highlight_page(self) -> int:
        """How many entries fit in the viewport, for page-wise highlight moves."""
        vr = self._viewport.visible_range()
        return max(1, len(vr.entries) - 1)

    def action_highlight_up(self) -> None:
        # In copy mode ↑/↓ move by *entry* (the text cursor jumps to the
        # adjacent entry's first row); the two granularities share one cursor.
        if self._copy_mode:
            self.copy_cursor_entry(-1)
        elif self._highlight_enabled:
            self.move_highlight(-1)
        else:
            self.action_scroll_up()

    def action_highlight_down(self) -> None:
        if self._copy_mode:
            self.copy_cursor_entry(1)
        elif self._highlight_enabled:
            self.move_highlight(1)
        else:
            self.action_scroll_down()

    def action_highlight_page_up(self) -> None:
        if self._highlight_enabled:
            self.move_highlight(-self._highlight_page())
        else:
            self.action_page_up()

    def action_highlight_page_down(self) -> None:
        if self._highlight_enabled:
            self.move_highlight(self._highlight_page())
        else:
            self.action_page_down()

    def action_highlight_home(self) -> None:
        self.highlight_first() if self._highlight_enabled else self.action_scroll_home()

    def action_highlight_end(self) -> None:
        self.highlight_last() if self._highlight_enabled else self.action_scroll_end()

    def action_activate(self) -> None:
        self.activate()

    # -- copy mode (a vim-like text cursor over the content) ---------------

    @property
    def copy_mode(self) -> bool:
        """Whether the text/copy cursor mode is active."""
        return self._copy_mode

    def enter_copy_mode(self) -> None:
        """Start copy mode: a character cursor you move over the rendered text
        (the motions below), with a visual selection and yank. Drawn via the
        widget's own text selection. Bind a key to this — the motion keys are
        default, overridable bindings that are live only while in copy mode."""
        if self._copy_mode:
            return
        self._copy_mode = True
        self._sync_scroll()
        # Start at the highlighted entry if there is one (unified cursor), else
        # the top of the viewport.
        start = None
        if self._highlighted is not None:
            start = self._viewport.offset_of(self._highlighted)
        self._tc_row = start if start is not None else int(self.scroll_offset.y)
        self._tc_row = max(0, min(self._tc_row, self.row_count - 1))
        self._tc_col = 0
        self._tc_anchor = None
        self._tc_line_visual = False
        self._tc_pending = ""
        self._render_copy_cursor()

    def exit_copy_mode(self) -> None:
        """Leave copy mode and clear its selection."""
        if not self._copy_mode:
            return
        self._copy_mode = False
        self._tc_anchor = None
        self._tc_pending = ""
        selections = dict(self.screen.selections)
        if selections.pop(self, None) is not None:
            self.screen.selections = selections
        self.refresh()

    def toggle_copy_mode(self) -> None:
        self.exit_copy_mode() if self._copy_mode else self.enter_copy_mode()

    # -- copy-mode motions (public; the real API keys map onto) ------------

    def copy_cursor_move(self, d_row: int = 0, d_col: int = 0) -> None:
        """Move the text cursor by ``d_row`` rows / ``d_col`` columns (clamped)."""
        self._tc_row += d_row
        self._tc_col += d_col
        self._render_copy_cursor()

    def copy_cursor_line_start(self) -> None:
        self._tc_col = 0
        self._render_copy_cursor()

    def copy_cursor_line_end(self) -> None:
        self._tc_col = max(0, len(self.row_text(self._tc_row)) - 1)
        self._render_copy_cursor()

    def copy_cursor_first_nonblank(self) -> None:
        text = self.row_text(self._tc_row)
        self._tc_col = next((i for i, ch in enumerate(text) if not ch.isspace()), 0)
        self._render_copy_cursor()

    def copy_cursor_entry(self, delta: int) -> None:
        """Jump the text cursor to the first row of the entry ``delta`` entries
        away (↑/↓ in copy mode). Unifies the entry- and character-level cursor:
        the current entry is always ``entry_at_row(row)``."""
        entries = self._viewport.entries
        if not entries:
            return
        cur = self.entry_at_row(self._tc_row)
        idx = entries.index(cur) if cur in entries else 0
        idx = max(0, min(idx + delta, len(entries) - 1))
        off = self._viewport.offset_of(entries[idx])
        if off is not None:
            self._tc_row = off
            self._tc_col = 0
            self._render_copy_cursor()

    def copy_cursor_entry_start(self) -> None:
        """Jump to the first row of the entry under the cursor."""
        entry = self.entry_at_row(self._tc_row)
        if entry is None:
            return
        off = self._viewport.offset_of(entry)
        if off is not None:
            self._tc_row = off
            self._tc_col = 0
            self._render_copy_cursor()

    def copy_cursor_entry_end(self) -> None:
        """Jump to the last row of the entry under the cursor."""
        entry = self.entry_at_row(self._tc_row)
        if entry is None:
            return
        off = self._viewport.offset_of(entry)
        if off is not None:
            self._tc_row = off + max(0, self._viewport.height_of(entry) - 1)
            self._tc_col = 0
            self._render_copy_cursor()

    def copy_cursor_top(self) -> None:
        self._tc_row = 0
        self._render_copy_cursor()

    def copy_cursor_bottom(self) -> None:
        self._tc_row = self.row_count - 1
        self._render_copy_cursor()

    def _word_bounds(self, text: str) -> list[tuple[int, int]]:
        words, i, n = [], 0, len(text)
        while i < n:
            if text[i].isspace():
                i += 1
                continue
            start = i
            while i < n and not text[i].isspace():
                i += 1
            words.append((start, i - 1))
        return words

    def copy_cursor_word_forward(self) -> None:
        words = self._word_bounds(self.row_text(self._tc_row))
        nxt = next((s for s, _ in words if s > self._tc_col), None)
        if nxt is not None:
            self._tc_col = nxt
        self._render_copy_cursor()

    def copy_cursor_word_back(self) -> None:
        words = self._word_bounds(self.row_text(self._tc_row))
        prev = next((s for s, _ in reversed(words) if s < self._tc_col), None)
        if prev is not None:
            self._tc_col = prev
        self._render_copy_cursor()

    def copy_cursor_word_end(self) -> None:
        words = self._word_bounds(self.row_text(self._tc_row))
        nxt = next((e for _, e in words if e > self._tc_col), None)
        if nxt is not None:
            self._tc_col = nxt
        self._render_copy_cursor()

    def copy_visual(self) -> None:
        """Toggle a character-wise visual selection anchored at the cursor."""
        self._tc_line_visual = False
        self._tc_anchor = None if self._tc_anchor is not None else (self._tc_row, self._tc_col)
        self._render_copy_cursor()

    def copy_visual_line(self) -> None:
        """Toggle a line-wise visual selection anchored at the cursor row."""
        if self._tc_anchor is not None and self._tc_line_visual:
            self._tc_anchor = None
            self._tc_line_visual = False
        else:
            self._tc_anchor = (self._tc_row, self._tc_col)
            self._tc_line_visual = True
        self._render_copy_cursor()

    def copy_yank(self) -> str:
        """Copy the current selection to the clipboard and return it; clears the
        visual selection (stays in copy mode)."""
        text = self.screen.get_selected_text() or ""
        if text:
            self.app.copy_to_clipboard(text)
        self._tc_anchor = None
        self._tc_line_visual = False
        self._render_copy_cursor()
        return text

    def _current_word(self) -> str:
        text = self.row_text(self._tc_row)
        for start, end in self._word_bounds(text):
            if start <= self._tc_col <= end:
                return text[start : end + 1]
        return ""

    def copy_search(self, query: str, *, forward: bool = True) -> bool:
        """Search the content for ``query`` and move the cursor to the next
        occurrence (wrapping). Returns whether a match was found; remembers the
        query for :meth:`copy_search_next` / :meth:`copy_search_previous`."""
        if not query:
            return False
        self._copy_query = query
        return self._do_copy_search(query, forward=forward)

    def copy_search_selection(self) -> bool:
        """Search for the current visual selection (or, with no selection, the
        word under the cursor) — vim ``*``."""
        query = self.screen.get_selected_text() if self._tc_anchor is not None else ""
        query = (query or self._current_word()).strip("\n")
        return self.copy_search(query, forward=True)

    def copy_search_next(self) -> bool:
        return self._do_copy_search(self._copy_query, forward=True)

    def copy_search_previous(self) -> bool:
        return self._do_copy_search(self._copy_query, forward=False)

    def _do_copy_search(self, query: str, *, forward: bool) -> bool:
        n = self.row_count
        if not query or n == 0:
            return False
        row, col = self._tc_row, self._tc_col
        if forward:
            order = (
                [(row, self.row_text(row).find(query, col + 1))]
                + [(r, self.row_text(r).find(query)) for r in range(row + 1, n)]
                + [(r, self.row_text(r).find(query)) for r in range(0, row + 1)]
            )
        else:
            order = (
                [(row, self.row_text(row).rfind(query, 0, col))]
                + [(r, self.row_text(r).rfind(query)) for r in range(row - 1, -1, -1)]
                + [(r, self.row_text(r).rfind(query)) for r in range(n - 1, row - 1, -1)]
            )
        for r, c in order:
            if c != -1:
                self._tc_row, self._tc_col = r, c
                self._tc_anchor = None  # land on the match (like vim search)
                self._render_copy_cursor()
                return True
        return False

    def copy_scroll_center(self) -> None:
        self.scroll_to(y=self._tc_row - self.content_size.height // 2, animate=False)
        self._render_copy_cursor()

    def copy_scroll_top(self) -> None:
        self.scroll_to(y=self._tc_row, animate=False)
        self._render_copy_cursor()

    def copy_scroll_bottom(self) -> None:
        self.scroll_to(y=self._tc_row - self.content_size.height + 1, animate=False)
        self._render_copy_cursor()

    @property
    def copy_scrolloff(self) -> int:
        """Rows of context kept above/below the copy cursor before the view
        scrolls (vim ``scrolloff``). Capped at half the viewport, so a large
        value (``999``) keeps the cursor centred while the content scrolls under
        it. Settable at runtime."""
        return self._copy_scrolloff

    @copy_scrolloff.setter
    def copy_scrolloff(self, value: int) -> None:
        self._copy_scrolloff = max(0, value)
        self._render_copy_cursor()

    def _render_copy_cursor(self, *, reveal: bool = True) -> None:
        if not self._copy_mode:
            return
        rows = max(1, self.row_count)
        self._tc_row = max(0, min(self._tc_row, rows - 1))
        self._tc_col = max(0, min(self._tc_col, max(0, len(self.row_text(self._tc_row)) - 1)))
        row, col = self._tc_row, self._tc_col
        if self._tc_anchor is None:
            sel = Selection(Offset(col, row), Offset(col + 1, row))
        elif self._tc_line_visual:
            (sy, _), (ey, _) = sorted([self._tc_anchor, (row, col)])
            sel = Selection(Offset(0, sy), Offset(len(self.row_text(ey)), ey))
        else:
            (sy, sx), (ey, ex) = sorted([self._tc_anchor, (row, col)])
            sel = Selection(Offset(sx, sy), Offset(ex + 1, ey))  # inclusive end cell
        self.screen.selections = {self: sel}
        # Anchor to the entry under the cursor + local row, so a later content
        # change can re-derive the absolute row (see _reanchor_copy_cursor).
        entry = self.entry_at_row(row)
        if entry is not None:
            off = self._viewport.offset_of(entry)
            if off is not None:
                self._tc_entry = entry
                self._tc_local = row - off
        # The entry highlight is **fixed** during copy mode — it is not moved and
        # no ``Highlighted`` is posted as the text cursor roams. (A consumer may
        # mutate an entry in its ``Highlighted`` handler; moving the highlight on
        # every keypress would fire those side effects mid-copy.) Copy mode only
        # *reads* the highlight — it starts there (see ``enter_copy_mode``).
        if reveal:
            self._reveal_row(row)

    def _reanchor_copy_cursor(self) -> None:
        """After a content change, re-derive the cursor's absolute row from its
        anchored entry + local row so it rides the entry instead of sliding."""
        if not self._copy_mode:
            return
        entry = self._tc_entry
        if entry is not None and entry.alive and not entry.hidden:
            off = self._viewport.offset_of(entry)
            if off is not None:
                self._tc_row = off + self._tc_local
        self._render_copy_cursor(reveal=False)

    def _scrolloff(self) -> int:
        # Can't keep more context than fits above/below the middle row.
        return min(self._copy_scrolloff, max(0, (self.content_size.height - 1) // 2))

    def _reveal_row(self, row: int) -> None:
        top = int(self.scroll_offset.y)
        height = self.content_size.height
        off = self._scrolloff()
        if row - off < top:
            self.scroll_to(y=row - off, animate=False)
        elif row + off > top + height - 1:
            self.scroll_to(y=row + off - height + 1, animate=False)

    def copy_scroll_line_down(self) -> None:
        """Scroll the view down one row, keeping the cursor on its buffer row
        until ``scrolloff`` forces it along (vim ``Ctrl-E``)."""
        self.scroll_to(y=int(self.scroll_offset.y) + 1, animate=False)
        self._follow_view_with_cursor()

    def copy_scroll_line_up(self) -> None:
        """Scroll the view up one row (vim ``Ctrl-Y``)."""
        self.scroll_to(y=int(self.scroll_offset.y) - 1, animate=False)
        self._follow_view_with_cursor()

    def _follow_view_with_cursor(self) -> None:
        top = int(self.scroll_offset.y)
        height = self.content_size.height
        off = self._scrolloff()
        self._tc_row = max(top + off, min(self._tc_row, top + height - 1 - off))
        self._render_copy_cursor(reveal=False)

    # -- copy-mode actions (default, overridable bindings map onto these) --

    def action_copy_left(self) -> None:
        self.copy_cursor_move(d_col=-1)

    def action_copy_right(self) -> None:
        self.copy_cursor_move(d_col=1)

    def action_copy_up(self) -> None:
        self.copy_cursor_move(d_row=-1)

    def action_copy_down(self) -> None:
        self.copy_cursor_move(d_row=1)

    def action_copy_line_start(self) -> None:
        self.copy_cursor_line_start()

    def action_copy_line_end(self) -> None:
        self.copy_cursor_line_end()

    def action_copy_first_nonblank(self) -> None:
        self.copy_cursor_first_nonblank()

    def action_copy_bottom(self) -> None:
        self.copy_cursor_bottom()

    def action_copy_entry_start(self) -> None:
        self.copy_cursor_entry_start()

    def action_copy_entry_end(self) -> None:
        self.copy_cursor_entry_end()

    def action_copy_search_selection(self) -> None:
        self.copy_search_selection()

    def action_copy_search_next(self) -> None:
        self.copy_search_next()

    def action_copy_search_previous(self) -> None:
        self.copy_search_previous()

    def action_copy_word_forward(self) -> None:
        self.copy_cursor_word_forward()

    def action_copy_word_back(self) -> None:
        self.copy_cursor_word_back()

    def action_copy_word_end(self) -> None:
        self.copy_cursor_word_end()

    def action_copy_visual(self) -> None:
        self.copy_visual()

    def action_copy_visual_line(self) -> None:
        self.copy_visual_line()

    def action_copy_yank(self) -> None:
        self.copy_yank()

    def action_copy_scroll_line_down(self) -> None:
        self.copy_scroll_line_down()

    def action_copy_scroll_line_up(self) -> None:
        self.copy_scroll_line_up()

    def action_copy_exit(self) -> None:
        self.exit_copy_mode()

    def on_key(self, event: events.Key) -> None:
        # Two-key vim prefixes (gg, zz/zt/zb) while in copy mode. Single-key
        # motions stay as normal, overridable BINDINGS.
        if not self._copy_mode:
            return
        pending, self._tc_pending = self._tc_pending, ""
        if pending == "g":
            if event.key == "g":
                self.copy_cursor_top()
                event.stop()
                event.prevent_default()
            return
        if pending == "z":
            if event.key == "z":
                self.copy_scroll_center()
            elif event.key == "t":
                self.copy_scroll_top()
            elif event.key == "b":
                self.copy_scroll_bottom()
            event.stop()
            event.prevent_default()
            return
        if event.key in ("g", "z"):
            self._tc_pending = event.key
            event.stop()
            event.prevent_default()

    # -- viewport-scoped resource lifecycle --------------------------------

    def track_visibility(
        self,
        entry: Entry[T],
        *,
        on_show: Callable[[Entry[T]], None] | None = None,
        on_hide: Callable[[Entry[T]], None] | None = None,
    ) -> VisibilityHandle:
        """Tie a resource's lifecycle to whether ``entry`` is on screen.

        ``on_show(entry)`` runs when the entry enters the viewport (and
        immediately if it is already visible); ``on_hide(entry)`` runs when it
        leaves — and also when tracking stops or the entry is removed, so a
        resource is always released. Use it to acquire/release anything scoped
        to visibility: a subscription, a video, a lazy-loaded image, a timer.

            view.track_visibility(
                entry,
                on_show=lambda e: e.item.stream.subscribe(),
                on_hide=lambda e: e.item.stream.unsubscribe(),
            )

        Returns a :class:`VisibilityHandle`; call ``.stop()`` to unregister.
        """
        observer: _VisibilityObserver[T] = _VisibilityObserver(entry, on_show, on_hide)
        self._observers.setdefault(entry.id, []).append(observer)
        self._visible_ids = self._current_visible_ids()
        if entry.id in self._visible_ids:
            observer.shown = True
            if on_show is not None:
                on_show(entry)
        return VisibilityHandle(self, observer)

    def _remove_observer(self, observer: _VisibilityObserver[Any]) -> None:
        observers = self._observers.get(observer.entry.id)
        if observers is None or observer not in observers:
            return
        observers.remove(observer)
        if not observers:
            del self._observers[observer.entry.id]
        if observer.shown and observer.on_hide is not None:
            observer.shown = False
            observer.on_hide(observer.entry)

    def _drop_observers(self, entry_id: int) -> None:
        for observer in self._observers.pop(entry_id, []):
            if observer.shown and observer.on_hide is not None:
                observer.on_hide(observer.entry)

    # -- gutter visibility -------------------------------------------------

    @property
    def left_gutter_visible(self) -> bool:
        """Whether the left gutter is currently shown."""
        return self._gutter_visible

    @property
    def right_gutter_visible(self) -> bool:
        """Whether the right gutter is currently shown."""
        return self._right_gutter_visible

    @property
    def body_width(self) -> int:
        """Width currently available to the presenter — content width minus both
        gutters, counting a hidden gutter as 0.

        This is exactly the ``width`` passed to :meth:`FlowPresenter.present`,
        and it shrinks or grows as gutters are configured, hidden, or shown.
        Prefer it over ``region.width`` (the whole content width, which does
        *not* change with gutter configuration) when asserting gutter width
        accounting."""
        return self._body_width()

    @property
    def left_gutter_effective_width(self) -> int:
        """The left gutter's current width in cells (0 when hidden)."""
        return self._left_gutter_w()

    @property
    def right_gutter_effective_width(self) -> int:
        """The right gutter's current width in cells (0 when hidden)."""
        return self._right_gutter_w()

    def set_gutter_visible(self, side: Literal["left", "right"], visible: bool) -> None:
        """Show or hide the left or right gutter at runtime.

        The gutter's configured width is preserved; hiding it hands that width
        back to the body and reflows (the body width changes, like a resize).
        A no-op if that side is already in the requested state."""
        flag = "_gutter_visible" if side == "left" else "_right_gutter_visible"
        if getattr(self, flag) is visible:
            return
        setattr(self, flag, visible)
        self._relayout_for_gutter_change()

    def show_gutter(self, side: Literal["left", "right"] = "left") -> None:
        """Show the ``side`` gutter (default ``"left"``)."""
        self.set_gutter_visible(side, True)

    def hide_gutter(self, side: Literal["left", "right"] = "left") -> None:
        """Hide the ``side`` gutter (default ``"left"``)."""
        self.set_gutter_visible(side, False)

    def toggle_gutter(self, side: Literal["left", "right"] = "left") -> bool:
        """Flip the ``side`` gutter's visibility; returns the new state."""
        flag = "_gutter_visible" if side == "left" else "_right_gutter_visible"
        self.set_gutter_visible(side, not getattr(self, flag))
        return bool(getattr(self, flag))

    def _relayout_for_gutter_change(self) -> None:
        # Body width changed: re-present at the new width and reflow (mirrors
        # on_resize). Before mount / with no width, geometry syncs on its own.
        if not self.is_mounted or self._content_width() <= 0:
            return
        state = self._capture()
        self._sync_geometry()
        self._strip_cache.clear()
        self._refresh_layout(state)
        self._present_visible()

    # -- per-entry animation (a timer built on track_visibility) -----------

    def refresh_gutter(self, entry: Entry[T]) -> None:
        """Re-derive ``entry``'s gutter on the next paint — the gutter animation
        counterpart of ``entry.update()`` (which re-presents the body).

        Pair it with a time-based decorator (e.g. ``rich.spinner.Spinner``) to
        animate a gutter spinner via :meth:`animate_entry`::

            view.animate_entry(entry, 1 / 12, view.refresh_gutter)

        The body is left cached — no re-present, no reflow.
        """
        self._drop_gutter_cache(entry)
        self.refresh()

    def _drop_gutter_cache(self, entry: Entry[T]) -> None:
        self._gutter_cache.pop((entry.id, "left"), None)
        self._gutter_cache.pop((entry.id, "right"), None)

    def animate_entry(
        self,
        entry: Entry[T],
        interval: float,
        callback: Callable[[Entry[T]], None],
    ) -> AnimationHandle:
        """Run ``callback(entry)`` every ``interval`` seconds — but **only while
        the entry is on screen**. A convenience over :meth:`track_visibility`
        that manages a paused/resumed timer for you.

            def tick(e):
                e.item.progress = min(1.0, e.item.progress + 0.05)
                e.update()
                if e.item.progress >= 1.0:
                    view.stop_entry_animation(e)

            view.animate_entry(entry, 0.1, tick)

        Registering again for the same entry replaces the previous animation;
        it is dropped automatically when the entry is removed.
        """
        self._stop_animation(entry.id)
        timer = self.set_interval(interval, lambda: self._fire_animation(entry.id))
        timer.pause()
        handle = self.track_visibility(entry, on_show=lambda _: timer.resume(),
                                       on_hide=lambda _: timer.pause())
        self._animations[entry.id] = (entry, callback, timer, handle)
        return AnimationHandle(self, entry.id)

    def stop_entry_animation(self, entry: Entry[T]) -> None:
        """Stop the animation started for ``entry`` (a no-op if none)."""
        self._stop_animation(entry.id)

    def _stop_animation(self, entry_id: int) -> None:
        record = self._animations.pop(entry_id, None)
        if record is not None:
            record[2].stop()   # the timer
            record[3].stop()   # the visibility tracker

    def _fire_animation(self, entry_id: int) -> None:
        record = self._animations.get(entry_id)
        if record is None:
            return
        entry, callback, _timer, _handle = record
        if not entry.alive:
            self._stop_animation(entry_id)
            return
        callback(entry)

    # -- search ------------------------------------------------------------

    def find(self, predicate: Callable[[Entry[T]], bool]) -> list[Entry[T]]:
        """All entries matching ``predicate``, in model order.

        The predicate receives the :class:`Entry`, so it can test the item,
        state, or metadata. Hidden entries are included — search reaches inside
        collapsed groups; use :meth:`reveal` to bring a hit into view."""
        return [entry for entry in self._model if predicate(entry)]

    def find_next(
        self,
        predicate: Callable[[Entry[T]], bool],
        *,
        after: Entry[T] | None = None,
        wrap: bool = True,
    ) -> Entry[T] | None:
        """First match strictly after ``after`` (default: the selection) in
        model order, wrapping around unless ``wrap`` is False."""
        entries = list(self._model)
        origin = after if after is not None else self._selected
        start = 0
        if origin is not None and origin in entries:
            start = entries.index(origin) + 1
        for entry in entries[start:]:
            if predicate(entry):
                return entry
        if wrap:
            for entry in entries[:start]:
                if predicate(entry):
                    return entry
        return None

    def find_previous(
        self,
        predicate: Callable[[Entry[T]], bool],
        *,
        before: Entry[T] | None = None,
        wrap: bool = True,
    ) -> Entry[T] | None:
        """First match strictly before ``before`` (default: the selection) in
        model order, wrapping around unless ``wrap`` is False."""
        entries = list(self._model)
        origin = before if before is not None else self._selected
        start = len(entries)
        if origin is not None and origin in entries:
            start = entries.index(origin)
        for entry in reversed(entries[:start]):
            if predicate(entry):
                return entry
        if wrap:
            for entry in reversed(entries[start:]):
                if predicate(entry):
                    return entry
        return None

    def reveal(
        self, entry: Entry[T], *, animate: bool = False, duration: float | None = None
    ) -> None:
        """Bring ``entry`` into view, un-hiding it first if it was hidden
        (e.g. a search hit inside a collapsed group)."""
        if entry.hidden:
            entry.show()
        self.ensure_visible(entry, animate=animate, duration=duration)

    # -- clipboard ---------------------------------------------------------

    def entry_text(self, entry: Entry[T]) -> str:
        """The entry's rendered body as plain text (styles stripped), or ``""``
        if it hasn't been presented yet. Useful for copying what's on screen."""
        presentation = self._layout.get(entry, self._body_width())
        if presentation is None:
            return ""
        console = Console(width=max(1, self._body_width()), no_color=True)
        with console.capture() as capture:
            console.print(presentation.renderable, end="")
        return "\n".join(line.rstrip() for line in capture.get().splitlines())

    def copy_entry(self, entry: Entry[T]) -> str:
        """Copy :meth:`entry_text` to the system clipboard (via Textual's
        OSC 52 support) and return the copied text."""
        text = self.entry_text(entry)
        self.app.copy_to_clipboard(text)
        return text

    # -- input -------------------------------------------------------------

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None:
            self.clear_selection()
            return
        hit = self._entry_at_screen(offset.x, offset.y)
        if hit is None:
            self.clear_selection()
            return
        entry, local_x, local_y = hit
        self.select(entry)
        self.post_message(self.Clicked(self, entry, local_x, local_y))

    def _entry_at_screen(self, x: int, y: int) -> tuple[Entry[T], int, int] | None:
        """Map a screen cell ``(x, y)`` in the content area to the entry drawn
        there and the position within that entry's body — accounting for a
        pinned sticky header overlaying the top rows."""
        local_x = x - self._left_gutter_w()
        scroll_y = int(self.scroll_offset.y)

        sticky = self._sticky_state(scroll_y)
        if sticky is not None:
            header, header_h, push = sticky
            if 0 <= y < header_h - push:
                return header, local_x, y + push

        located = self._viewport.locate(y + scroll_y)
        if located is None:
            return None
        index, local_y = located
        return self._viewport.entries[index], local_x, local_y

    # -- rendering ---------------------------------------------------------

    def render_line(self, y: int) -> Strip:
        content_width = self._content_width()
        if content_width <= 0:
            return Strip.blank(self.size.width)

        # Empty state: nothing to draw (no entries, or all hidden). Show the
        # `empty` renderable placed vertically per `empty_align`.
        if self._empty is not None and not self._viewport.entries:
            return self._empty_line(y, content_width)

        scroll_y = int(self.scroll_offset.y)
        virtual_y = y + scroll_y

        # Sticky header: overlay the pinned group header on the top rows.
        sticky = self._sticky_state(scroll_y)
        if sticky is not None:
            header, header_h, push = sticky
            if 0 <= y < header_h - push:
                line = self._compose_line(header, y + push, content_width, sticky=True)
                return self._decorate_line(line, virtual_y)

        located = self._viewport.locate(virtual_y)
        if located is None:
            return self._separator_line(virtual_y, content_width)
        index, local_y = located
        line = self._compose_line(self._viewport.entries[index], local_y, content_width)
        return self._decorate_line(line, virtual_y)

    def _separator_line(self, virtual_y: int, content_width: int) -> Strip:
        """The row for a virtual_y that isn't inside an entry: a separator row
        if it falls in a spacer gap and a separator is configured, else blank."""
        if self._separator is None:
            return Strip.blank(content_width)
        gap = self._viewport.gap_at(virtual_y)
        if gap is None:
            return Strip.blank(content_width)
        above_i, below_i, gap_local_y = gap
        above = self._viewport.entries[above_i]
        below = self._viewport.entries[below_i]
        strips = self._separator_strips(above, below, content_width, self._spacing)
        return (
            strips[gap_local_y]
            if 0 <= gap_local_y < len(strips)
            else Strip.blank(content_width)
        ).adjust_cell_length(content_width)

    def _separator_strips(
        self, above: Entry[T], below: Entry[T], width: int, height: int
    ) -> list[Strip]:
        key = (above.id, below.id)
        cached = self._separator_cache.get(key)
        if (
            cached is not None
            and cached[0] == above.revision
            and cached[1] == below.revision
            and cached[2] == width
            and cached[3] == height
        ):
            return cached[4]
        sep = self._separator
        renderable: RenderableType | None
        # A plain str / Text / Rule / Panel isn't callable; only a supplied
        # separator *function* is, so callable() cleanly tells them apart.
        if callable(sep):
            renderable = sep(above, below)
        else:
            renderable = sep
        if renderable is None:
            strips = [Strip.blank(width) for _ in range(max(1, height))]
        else:
            strips = self._render_to_strips(renderable, width, height)
        self._separator_cache[key] = (
            above.revision,
            below.revision,
            width,
            height,
            strips,
        )
        return strips

    def _decorate_line(self, line: Strip, virtual_y: int) -> Strip:
        """Apply the text-selection highlight for this content row and stamp
        each cell with its content offset so Textual's native mouse selection
        (and Ctrl+C copy) can map clicks back to text."""
        selection = self.text_selection
        if selection is not None:
            span = selection.get_span(virtual_y)
            if span is not None:
                width = line.cell_length
                text = line.text
                n = len(text)
                start, end = span
                # The span is in *character* offsets (end == -1 means "to end of
                # line"); Strip.crop works in *cells*. Convert, or a row with
                # double-width glyphs (CJK, emoji) highlights the wrong columns
                # and clips characters mid-cell.
                end = n if end == -1 else end
                start = max(0, min(start, n))
                end = max(start, min(end, n))
                start_cell = cell_len(text[:start])
                end_cell = cell_len(text[:end])
                if end_cell > start_cell:
                    line = Strip.join(
                        [
                            line.crop(0, start_cell),
                            line.crop(start_cell, end_cell).apply_style(
                                self.selection_style
                            ),
                            line.crop(end_cell, width),
                        ]
                    )
        return line.apply_offsets(0, virtual_y)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Extract the text under ``selection`` (Textual's selection protocol).

        Selection y-coordinates are content rows (stamped by
        :meth:`_decorate_line`), so extraction is stable across scrolling and
        spans the whole virtual list, not just the painted viewport.

        A ``None`` bound means "to the edge" — this is how **select-all**
        (``Ctrl+A``) arrives: ``Selection(None, None)`` covers every row. Rows
        that have never been presented (far off-screen) extract as the
        placeholder until they are; scrolling through them (as a drag-select
        does) presents them first."""
        width = self._content_width()
        if width <= 0:
            return None
        last_row = self._viewport.total_height - 1
        if last_row < 0:
            return None
        start_y = 0 if selection.start is None else max(0, selection.start.y)
        end_y = last_row if selection.end is None else min(selection.end.y, last_row)
        parts: list[str] = []
        for virtual_y in range(start_y, end_y + 1):
            span = selection.get_span(virtual_y)
            if span is None:
                continue
            row = self._content_row_text(virtual_y, width)
            x0, x1 = span
            if x1 == -1 or x1 > len(row):
                x1 = len(row)
            x0 = max(0, min(x0, len(row)))
            parts.append(row[x0:x1])
        return "\n".join(parts), "\n"

    def _content_row_text(self, virtual_y: int, width: int) -> str:
        located = self._viewport.locate(virtual_y)
        if located is None:
            return ""
        index, local_y = located
        # rstrip the padding the compositor adds to fill the width, so a
        # "to end of line" selection doesn't copy trailing spaces.
        return self._compose_line(self._viewport.entries[index], local_y, width).text.rstrip()

    def _compose_line(
        self, entry: Entry[T], local_y: int, content_width: int, *, sticky: bool = False
    ) -> Strip:
        left_w = self._left_gutter_w()
        right_w = self._right_gutter_w()
        body_w = max(1, content_width - left_w - right_w)
        body_strips = self._entry_strips(entry, body_w)
        height = len(body_strips)
        body_line = (
            body_strips[local_y] if 0 <= local_y < height else Strip.blank(body_w)
        ).adjust_cell_length(body_w)

        parts: list[Strip] = []
        if left_w > 0:
            parts.append(
                self._gutter_line(entry, "left", left_w, height, local_y)
            )
        parts.append(body_line)
        if right_w > 0:
            parts.append(
                self._gutter_line(entry, "right", right_w, height, local_y)
            )
        line = Strip.join(parts) if len(parts) > 1 else body_line

        # Full-row background: paint the whole line (gutter + body + padding)
        # edge to edge, so the entry reads as one continuous coloured block.
        presentation = self._layout.get(entry, body_w)
        if presentation is not None and presentation.background is not None:
            line = line.apply_style(Style(bgcolor=presentation.background))

        if sticky:
            line = self._overlay_component(line, "flowview--sticky-header")
        if self._selected is entry:
            line = self._overlay_component(line, "flowview--selected")
        if self._highlighted is entry:
            line = self._overlay_component(line, "flowview--highlight")
        return line

    def _overlay_component(self, line: Strip, name: str) -> Strip:
        """Overlay a component-class style on a row.

        Two things the plain ``apply_style(get_component_rich_style(...))`` got
        wrong (issues #5, #6):

        * uses the **partial** style — only what the app actually declared — so
          an *undeclared* class contributes nothing (the fully-resolved style
          otherwise carries the widget's inherited fg/bg and paints the row);
        * applies it as an **override on top** of each segment, so a declared
          highlight background wins over a row's ``Presentation.background``
          (``apply_style`` merges as a base *under* the segment, which the row
          background would always beat)."""
        style = self.get_component_rich_style(name, partial=True)
        if not style:
            return line
        segments = [
            Segment(text, (seg_style + style) if seg_style is not None else style, control)
            for text, seg_style, control in line
        ]
        return Strip(segments, line.cell_length)

    def _sticky_state(self, scroll_y: int) -> tuple[Entry[T], int, int] | None:
        """The pinned header for the current scroll position: ``(header,
        header_height, push)``. ``push`` is how many rows the next header has
        shoved it up (0 normally). ``None`` when there's nothing to pin.

        Memoized per scroll position — render_line calls this for every visible
        row, but the answer only changes when scroll_y or the layout does."""
        if self._is_sticky_header is None:
            return None
        if self._sticky_cache is not None and self._sticky_cache[0] == scroll_y:
            return self._sticky_cache[1]
        result = self._compute_sticky(scroll_y)
        self._sticky_cache = (scroll_y, result)
        return result

    def _compute_sticky(self, scroll_y: int) -> tuple[Entry[T], int, int] | None:
        assert self._is_sticky_header is not None
        entries = self._viewport.entries
        located = self._viewport.locate(scroll_y)
        if located is None:
            return None
        top_index = located[0]

        active = None
        for i in range(top_index, -1, -1):
            if self._is_sticky_header(entries[i]):
                active = i
                break
        if active is None:
            return None

        header = entries[active]
        header_h = self._viewport.height_of(header)

        # Push: if the next header is within header_h of the top, slide up.
        push = 0
        for j in range(active + 1, len(entries)):
            if self._is_sticky_header(entries[j]):
                push = max(0, header_h - (self._viewport.offset_at(j) - scroll_y))
                break
        return header, header_h, min(push, header_h)

    def _entry_strips(self, entry: Entry[T], width: int) -> list[Strip]:
        presentation = self._layout.get(entry, width)
        if presentation is None:
            # Not presented at this width/revision yet: show placeholder and
            # kick off (deduped) presentation.
            self._present_entry(entry)
            return self._render_to_strips(
                self._placeholder, width, self._viewport.estimated_height
            )
        cached = self._strip_cache.get(entry.id)
        if cached is not None and cached[0] == entry.revision and cached[1] == width:
            return cached[2]
        strips = self._render_to_strips(presentation.renderable, width, presentation.height)
        self._strip_cache[entry.id] = (entry.revision, width, strips)
        return strips

    def _gutter_line(
        self, entry: Entry[T], side: str, width: int, height: int, local_y: int
    ) -> Strip:
        strips = self._gutter_strips(entry, side, width, height)
        return (
            strips[local_y] if 0 <= local_y < len(strips) else Strip.blank(width)
        ).adjust_cell_length(width)

    def _gutter_strips(
        self, entry: Entry[T], side: str, width: int, height: int
    ) -> list[Strip]:
        key = (entry.id, side)
        cached = self._gutter_cache.get(key)
        if (
            cached is not None
            and cached[0] == entry._decor_revision
            and cached[1] == width
            and cached[2] == height
        ):
            return cached[3]
        decorator = self._decorator if side == "left" else self._right_decorator
        if decorator is not None:
            renderable: RenderableType = decorator.decorate(entry, width, height)
        else:
            renderable = Text("")
        strips = self._render_to_strips(renderable, width, height)
        self._gutter_cache[key] = (entry._decor_revision, width, height, strips)
        return strips

    def _render_to_strips(
        self, renderable: RenderableType, width: int, height: int
    ) -> list[Strip]:
        options = self.app.console.options.update_dimensions(width, max(1, height))
        lines = self.app.console.render_lines(renderable, options, pad=True)
        return [Strip(line, width) for line in lines]

    def _empty_line(self, y: int, width: int) -> Strip:
        """A screen row of the empty-state block, placed vertically per
        ``empty_align`` (horizontal alignment lives in the renderable itself)."""
        assert self._empty is not None
        # Render the empty renderable to its natural height at the content width.
        options = self.app.console.options.update_width(width)
        lines = self.app.console.render_lines(self._empty, options, pad=True)
        block = [Strip(line, width) for line in lines]
        view_h = self._content_height()
        if self._empty_align == "top":
            top = 0
        elif self._empty_align == "bottom":
            top = max(0, view_h - len(block))
        else:  # middle
            top = max(0, (view_h - len(block)) // 2)
        i = y - top
        if 0 <= i < len(block):
            return block[i]
        return Strip.blank(width)

    # -- presentation workers ---------------------------------------------

    def _present_entry(self, entry: Entry[T]) -> None:
        if not entry.alive:
            return
        if self._content_width() <= 0:
            return
        width = self._body_width()
        if self._layout.get(entry, width) is not None:
            return
        if entry.id in self._presenting:
            # A loop is already converging this entry to its latest revision;
            # it will pick up any newer revision on its own.
            return
        self._presenting.add(entry.id)
        self.run_worker(
            self._present_loop(entry, width),
            group=f"flowview-present-{entry.id}",
            exclusive=True,
        )

    async def _present_loop(self, entry: Entry[T], width: int) -> None:
        """Present ``entry`` repeatedly until the stored result matches its
        latest revision.

        One loop per entry (guarded by ``_presenting``) rather than one worker
        per ``update()``. Streaming bumps the revision many times a second; the
        loop simply re-presents for the newest revision after each pass, so it
        always converges to the final state — no per-revision worker churn, no
        dropped final present, no leaked bookkeeping.
        """
        try:
            while entry.alive:
                revision = entry.revision
                if self._layout.get(entry, width) is not None:
                    break
                errored = False
                try:
                    presentation = await self._presenter.present(entry.item, width)
                except Exception as exc:
                    presentation = self._error_presentation(exc)
                    errored = True
                if not entry.alive:
                    break
                self._layout.store(entry.id, width, revision, presentation)
                self._strip_cache.pop(entry.id, None)
                state = self._capture()
                self._refresh_layout(state)
                if errored:
                    # Spec: a rendering error also flips the entry to ERROR so
                    # the gutter reflects it. Does not re-present the body.
                    entry.set_state(EntryState.ERROR)
                if entry.revision == revision:
                    break  # converged to the latest revision
                # Otherwise the item changed mid-present; loop for the new one.
        finally:
            self._presenting.discard(entry.id)

    def _error_presentation(self, exc: BaseException) -> Presentation:
        body = Text(f"{type(exc).__name__}: {exc}", style="red")
        panel = Panel(body, title="Rendering Error", border_style="red")
        return Presentation(height=3, renderable=panel)

    # -- geometry helpers --------------------------------------------------

    def _visible_entries(self) -> list[Entry[T]]:
        """Model order with hidden entries filtered out — the set the viewport
        actually lays out and draws."""
        return [entry for entry in self._model if not entry.hidden]

    def _content_width(self) -> int:
        region = self.scrollable_content_region
        return region.width if region.width > 0 else self.size.width

    def _content_height(self) -> int:
        region = self.scrollable_content_region
        return region.height if region.height > 0 else self.size.height

    def _left_gutter_w(self) -> int:
        """Effective left-gutter width — the configured width, or 0 when hidden."""
        return self._gutter_width if self._gutter_visible else 0

    def _right_gutter_w(self) -> int:
        """Effective right-gutter width — the configured width, or 0 when hidden."""
        return self._right_gutter_width if self._right_gutter_visible else 0

    def _body_width(self) -> int:
        """Width available to the presenter (content width minus both gutters)."""
        return max(
            1, self._content_width() - self._left_gutter_w() - self._right_gutter_w()
        )

    def _sync_geometry(self) -> None:
        # The viewport looks up heights from the layout, which are cached under
        # the *body* width (content width minus the gutter). Feed it the body
        # width so height lookups hit instead of falling back to the estimate.
        self._viewport.set_size(self._body_width(), self._content_height())

    def _sync_scroll(self) -> None:
        _, scroll_y = self.scroll_offset
        self._viewport.scroll_to_offset(int(scroll_y))

    def _current_visible_ids(self) -> set[int]:
        if self._content_width() <= 0:
            return set()
        self._sync_geometry()
        self._sync_scroll()
        return {entry.id for entry in self._viewport.visible_range().entries}

    def _sync_visibility(self) -> None:
        """Fire on_show / on_hide for entries that just entered or left the
        viewport. Cheap no-op when nothing is tracked."""
        if not self._observers:
            return
        current = self._current_visible_ids()
        for entry_id in current - self._visible_ids:
            for observer in self._observers.get(entry_id, ()):
                if not observer.shown:
                    observer.shown = True
                    if observer.on_show is not None:
                        observer.on_show(observer.entry)
        for entry_id in self._visible_ids - current:
            for observer in self._observers.get(entry_id, ()):
                if observer.shown:
                    observer.shown = False
                    if observer.on_hide is not None:
                        observer.on_hide(observer.entry)
        self._visible_ids = current

    def _capture(self) -> AnchorState[T]:
        self._sync_geometry()
        self._sync_scroll()
        return self._viewport.capture_anchor()

    def _refresh_layout(self, anchor_state: AnchorState[T] | None) -> None:
        self._viewport.invalidate_heights()
        self._sticky_cache = None
        self.virtual_size = Size(self._content_width(), self._viewport.total_height)
        target: int | None = None
        if self._viewport.anchor is Anchor.STICKY_BOTTOM and self._follow_bottom:
            target = self.max_scroll_y
        elif self._viewport.anchor is Anchor.STICKY_TOP and self._follow_top:
            target = 0
        elif anchor_state is not None:
            self._viewport.restore_anchor(anchor_state)
            target = self._viewport.scroll_y
        # Only scroll if the anchor target actually differs from where we are.
        # A no-op scroll_to would cancel an in-flight animated scroll mid-flight
        # (e.g. a fixed-height entry.update() during a keyboard/wheel scroll),
        # corrupting Textual's animator — so skip it when nothing moved.
        if target is not None and target != round(self.scroll_offset.y):
            self.scroll_to(y=target, animate=False)
        self.refresh()
        self._sync_visibility()
        self._check_edges()

    def _present_visible(self) -> None:
        """Kick off presentation for the visible range plus the overscan band,
        plus a read-ahead band biased in the current scroll direction — so
        fast scrolling reveals real content instead of placeholders.

        Already-cached or in-flight entries are skipped by ``_present_entry``,
        so the read-ahead band is cheap once warm."""
        if self._content_width() <= 0:
            return
        self._sync_geometry()
        self._sync_scroll()
        height = self._viewport.height
        overscan = self._viewport.overscan
        ahead = self._read_ahead if self._read_ahead is not None else height
        up = overscan + (ahead if self._scroll_dir < 0 else 0)
        down = overscan + (ahead if self._scroll_dir > 0 else 0)
        top = self._viewport.scroll_y - up
        bottom = self._viewport.scroll_y + height + down
        band = self._viewport.entries_between(top, bottom)
        self._band_ids = {entry.id for entry in band}
        for entry in band:
            self._present_entry(entry)
        self._sync_visibility()
