from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Generic, Literal, TypeVar

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
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
    }
    """
    | Class | Applied to |
    | :- | :- |
    | ``flowview--selected`` | The currently selected entry's rows. |
    | ``flowview--sticky-header`` | The pinned sticky header's rows. |

    FlowView ships **no colours of its own** — these classes are unstyled by
    default, so nothing is painted until your app (or theme) gives them a style.
    Text selection likewise defers to Textual's ``screen--selection``.
    """

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
        sticky_header: Callable[[Entry[T]], bool] | None = None,
        anchor: Anchor = Anchor.CURRENT,
        estimated_height: int = 1,
        overscan: int = 4,
        read_ahead: int | None = None,
        spacing: int = 1,
        separator: RenderableType
        | Callable[[Entry[T], Entry[T]], RenderableType | None]
        | None = None,
        animation_fps: float = 0,
        placeholder: RenderableType = "Loading...",
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

    # -- ModelListener (internal, called on the message loop) -------------

    def on_flow_insert(self, entry: Entry[T], index: int) -> None:
        state = self._capture()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)

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

    def on_flow_remove(self, entry: Entry[T], index: int) -> None:
        if self._selected is entry:
            self.select(None)
        self._stop_animation(entry.id)
        self._drop_observers(entry.id)
        self._visible_ids.discard(entry.id)
        state = self._capture()
        self._layout.discard(entry.id)
        self._strip_cache.pop(entry.id, None)
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)

    def on_flow_visibility(self, entry: Entry[T]) -> None:
        # Which entries are visible changed (a group collapsed/expanded). Rebuild
        # the viewport's entry list and reflow — but keep every cached
        # presentation, so hiding/showing is instant and never re-presents.
        if entry.hidden and self._selected is entry:
            self.select(None)
        state = self._capture()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)
        self._present_visible()

    def on_flow_clear(self) -> None:
        if self._selected is not None:
            self.select(None)
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

    def scroll_to_top(
        self, *, animate: bool = False, duration: float | None = None
    ) -> None:
        self.scroll_to(y=0, animate=animate, duration=duration)

    def scroll_to_bottom(
        self, *, animate: bool = False, duration: float | None = None
    ) -> None:
        self.scroll_to(y=self.max_scroll_y, animate=animate, duration=duration)

    def scroll_to_entry(
        self, entry: Entry[T], *, animate: bool = False, duration: float | None = None
    ) -> None:
        """Scroll so ``entry`` sits at the top of the viewport.

        Pass ``animate=True`` for a smooth jump (optionally timed with
        ``duration``); content presents as it scrolls past."""
        self._jump_to_entry(entry, top=True, animate=animate, duration=duration)

    def ensure_visible(
        self, entry: Entry[T], *, animate: bool = False, duration: float | None = None
    ) -> None:
        """Scroll the minimum amount so ``entry`` is fully visible."""
        self._jump_to_entry(entry, top=False, animate=animate, duration=duration)

    def _jump_to_entry(
        self, entry: Entry[T], *, top: bool, animate: bool, duration: float | None
    ) -> None:
        self._sync_scroll()
        self._viewport.scroll_to_entry(entry, top=top)
        self.scroll_to(y=self._viewport.scroll_y, animate=animate, duration=duration)

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
                start, end = span
                if end == -1 or end > width:
                    end = width
                start = max(0, min(start, width))
                end = max(start, min(end, width))
                if end > start:
                    line = Strip.join(
                        [
                            line.crop(0, start),
                            line.crop(start, end).apply_style(self.selection_style),
                            line.crop(end, width),
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
            line = line.apply_style(self.get_component_rich_style("flowview--sticky-header"))
        if self._selected is entry:
            line = line.apply_style(self.get_component_rich_style("flowview--selected"))
        return line

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
