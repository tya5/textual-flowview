from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Generic, TypeVar

from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from ._anchor import Anchor
from ._decorator import FlowDecorator
from ._entry import Entry
from ._layout import FlowLayout
from ._model import FlowModel
from ._presentation import Presentation
from ._presenter import FlowPresenter
from ._state import EntryState
from ._viewport import AnchorState, Viewport

__all__ = ["FlowView"]

T = TypeVar("T")


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
    """

    DEFAULT_CSS = """
    FlowView > .flowview--selected {
        background: $accent 30%;
    }
    FlowView > .flowview--sticky-header {
        background: $panel;
    }
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
        sticky_header: Callable[[Entry[T]], bool] | None = None,
        anchor: Anchor = Anchor.CURRENT,
        estimated_height: int = 1,
        overscan: int = 4,
        read_ahead: int | None = None,
        placeholder: RenderableType = "Loading...",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._model = model
        self._presenter = presenter
        self._decorator = decorator
        # Predicate marking an entry as a group header to pin while scrolling.
        self._is_sticky_header = sticky_header
        # Rows to pre-present *ahead of the scroll direction*, beyond the static
        # overscan band. None -> one viewport height. 0 disables read-ahead.
        self._read_ahead = read_ahead
        # Direction of the last scroll: -1 up, +1 down, 0 none.
        self._scroll_dir = 0
        # Per-frame memo of the sticky-header computation, keyed by scroll_y.
        self._sticky_cache: tuple[int, tuple[Entry[T], int, int] | None] | None = None
        # No decorator -> no gutter. Decorator but unset width -> a sensible 2.
        if gutter_width is None:
            gutter_width = 2 if decorator is not None else 0
        self._gutter_width = max(0, gutter_width)
        self._layout: FlowLayout[T] = FlowLayout()
        self._viewport: Viewport[T] = Viewport(
            self._layout,
            anchor=anchor,
            estimated_height=estimated_height,
            overscan=overscan,
        )
        self._placeholder = placeholder
        # id -> (revision, width, strips)
        self._strip_cache: dict[int, tuple[int, int, list[Strip]]] = {}
        # id -> (decor_revision, width, height, strips)
        self._gutter_cache: dict[int, tuple[int, int, int, list[Strip]]] = {}
        # entry ids with an active presentation loop (one worker per entry).
        self._presenting: set[int] = set()
        # STICKY_BOTTOM: are we currently glued to the bottom edge?
        self._follow_bottom = anchor is Anchor.STICKY_BOTTOM
        # Single-selection state, owned by the view (not the entry).
        self._selected: Entry[T] | None = None

    # -- lifecycle ---------------------------------------------------------

    def on_mount(self) -> None:
        self._model._attach(self)
        self._sync_geometry()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(None)
        self._present_visible()

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
        self._present_visible()

    # -- ModelListener (internal, called on the message loop) -------------

    def on_flow_insert(self, entry: Entry[T], index: int) -> None:
        state = self._capture()
        self._viewport.set_entries(self._visible_entries())
        self._refresh_layout(state)

    def on_flow_update(self, entry: Entry[T]) -> None:
        # The revision bump already makes the cached presentation a miss;
        # drop the strip cache for this entry and re-present.
        self._strip_cache.pop(entry.id, None)
        state = self._capture()
        self._refresh_layout(state)
        self._present_entry(entry)

    def on_flow_remove(self, entry: Entry[T], index: int) -> None:
        if self._selected is entry:
            self.select(None)
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
        self._layout.clear()
        self._strip_cache.clear()
        self._gutter_cache.clear()
        self._presenting.clear()
        self._viewport.set_entries([])
        self._refresh_layout(None)
        self.scroll_to(y=0, animate=False)

    def on_flow_decorate(self, entry: Entry[T]) -> None:
        # Gutter-only change: drop the gutter cache and repaint. The body's
        # strip cache and the layout heights are untouched, so no re-present
        # and no reflow happen.
        self._gutter_cache.pop(entry.id, None)
        self.refresh()

    # -- public API --------------------------------------------------------

    def scroll_to_top(self) -> None:
        self.scroll_to(y=0, animate=False)

    def scroll_to_bottom(self) -> None:
        self.scroll_to(y=self.max_scroll_y, animate=False)

    def scroll_to_entry(self, entry: Entry[T]) -> None:
        """Scroll so ``entry`` sits at the top of the viewport."""
        self._sync_scroll()
        self._viewport.scroll_to_entry(entry, top=True)
        self.scroll_to(y=self._viewport.scroll_y, animate=False)

    def ensure_visible(self, entry: Entry[T]) -> None:
        """Scroll the minimum amount so ``entry`` is fully visible."""
        self._sync_scroll()
        self._viewport.scroll_to_entry(entry, top=False)
        self.scroll_to(y=self._viewport.scroll_y, animate=False)

    @property
    def selected(self) -> Entry[T] | None:
        """The currently selected entry, or ``None``."""
        return self._selected

    def select(self, entry: Entry[T] | None) -> None:
        """Select ``entry`` (or clear the selection with ``None``).

        A no-op if it is already selected. Posts :class:`FlowView.Selected`.
        """
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

    def reveal(self, entry: Entry[T]) -> None:
        """Bring ``entry`` into view, un-hiding it first if it was hidden
        (e.g. a search hit inside a collapsed group)."""
        if entry.hidden:
            entry.show()
        self.ensure_visible(entry)

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
        local_x = x - self._gutter_width
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
        _, scroll_y = self.scroll_offset

        # Sticky header: overlay the pinned group header on the top rows.
        sticky = self._sticky_state(int(scroll_y))
        if sticky is not None:
            header, header_h, push = sticky
            if 0 <= y < header_h - push:
                return self._compose_line(header, y + push, content_width, sticky=True)

        virtual_y = y + scroll_y
        located = self._viewport.locate(virtual_y)
        if located is None:
            return Strip.blank(content_width)
        index, local_y = located
        return self._compose_line(self._viewport.entries[index], local_y, content_width)

    def _compose_line(
        self, entry: Entry[T], local_y: int, content_width: int, *, sticky: bool = False
    ) -> Strip:
        gutter_w = self._gutter_width
        body_w = max(1, content_width - gutter_w)
        body_strips = self._entry_strips(entry, body_w)
        height = len(body_strips)
        body_line = (
            body_strips[local_y] if 0 <= local_y < height else Strip.blank(body_w)
        ).adjust_cell_length(body_w)

        if gutter_w > 0:
            gutter_strips = self._gutter_strips(entry, gutter_w, height)
            gutter_line = (
                gutter_strips[local_y]
                if 0 <= local_y < len(gutter_strips)
                else Strip.blank(gutter_w)
            ).adjust_cell_length(gutter_w)
            line = Strip.join([gutter_line, body_line])
        else:
            line = body_line

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

    def _gutter_strips(self, entry: Entry[T], width: int, height: int) -> list[Strip]:
        cached = self._gutter_cache.get(entry.id)
        if (
            cached is not None
            and cached[0] == entry._decor_revision
            and cached[1] == width
            and cached[2] == height
        ):
            return cached[3]
        if self._decorator is not None:
            renderable: RenderableType = self._decorator.decorate(entry, width, height)
        else:
            renderable = Text("")
        strips = self._render_to_strips(renderable, width, height)
        self._gutter_cache[entry.id] = (entry._decor_revision, width, height, strips)
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

    def _body_width(self) -> int:
        """Width available to the presenter (content width minus the gutter)."""
        return max(1, self._content_width() - self._gutter_width)

    def _sync_geometry(self) -> None:
        # The viewport looks up heights from the layout, which are cached under
        # the *body* width (content width minus the gutter). Feed it the body
        # width so height lookups hit instead of falling back to the estimate.
        self._viewport.set_size(self._body_width(), self._content_height())

    def _sync_scroll(self) -> None:
        _, scroll_y = self.scroll_offset
        self._viewport.scroll_to_offset(int(scroll_y))

    def _capture(self) -> AnchorState[T]:
        self._sync_geometry()
        self._sync_scroll()
        return self._viewport.capture_anchor()

    def _refresh_layout(self, anchor_state: AnchorState[T] | None) -> None:
        self._viewport.invalidate_heights()
        self._sticky_cache = None
        self.virtual_size = Size(self._content_width(), self._viewport.total_height)
        if self._viewport.anchor is Anchor.STICKY_BOTTOM and self._follow_bottom:
            self.scroll_to(y=self.max_scroll_y, animate=False)
        elif anchor_state is not None:
            self._viewport.restore_anchor(anchor_state)
            self.scroll_to(y=self._viewport.scroll_y, animate=False)
        self.refresh()

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
        for entry in self._viewport.entries_between(top, bottom):
            self._present_entry(entry)
