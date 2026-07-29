from __future__ import annotations

from typing import Generic, TypeVar

from ._anchor import Anchor
from ._entry import Entry
from ._layout import FlowLayout

__all__ = ["AnchorState", "Viewport", "VisibleRange"]

T = TypeVar("T")


class VisibleRange(Generic[T]):
    """The slice of entries the view should draw, plus paint geometry."""

    __slots__ = ("entries", "first_offset", "start", "stop")

    def __init__(
        self,
        start: int,
        stop: int,
        entries: list[Entry[T]],
        first_offset: int,
    ) -> None:
        self.start = start
        """Index (inclusive) of the first entry to draw, overscan included."""
        self.stop = stop
        """Index (exclusive) after the last entry to draw."""
        self.entries = entries
        """The entries ``[start:stop]``."""
        self.first_offset = first_offset
        """Virtual y-offset (rows) of ``entries[0]``'s top edge."""

    def __repr__(self) -> str:
        return f"<VisibleRange {self.start}:{self.stop} first_offset={self.first_offset}>"


class Viewport(Generic[T]):
    """Owns scroll position and decides what is visible.

    The viewport holds the ordered list of entries and, using heights it looks
    up from :class:`FlowLayout` (falling back to ``estimated_height`` for
    not-yet-presented items), computes cumulative offsets, the total virtual
    height, and the visible range with overscan.

    It also owns scroll-anchoring: ``STICKY_BOTTOM`` follows the bottom edge
    only while the user is already there, and ``CURRENT`` preserves the topmost
    visible entry's position across reflows (so height changes above the fold
    don't yank the view).

    Dependency direction is one-way: ``Viewport -> FlowLayout``. The layout
    never calls back into the viewport.
    """

    def __init__(
        self,
        layout: FlowLayout[T],
        *,
        anchor: Anchor = Anchor.CURRENT,
        estimated_height: int = 1,
        overscan: int = 4,
        spacing: int = 0,
    ) -> None:
        self._layout = layout
        self._anchor = anchor
        self._estimated_height = max(1, estimated_height)
        self._overscan = max(0, overscan)
        self._spacing = max(0, spacing)

        self._entries: list[Entry[T]] = []
        self._width = 0
        self._height = 0
        self._scroll_y = 0

        # Lazily rebuilt prefix-offset cache. _offsets[i] = rows above entry i;
        # _offsets[len] = total virtual height.
        self._offsets: list[int] | None = None

    # -- configuration -----------------------------------------------------

    @property
    def anchor(self) -> Anchor:
        return self._anchor

    @property
    def scroll_y(self) -> int:
        return self._scroll_y

    @property
    def estimated_height(self) -> int:
        return self._estimated_height

    @property
    def overscan(self) -> int:
        return self._overscan

    @property
    def height(self) -> int:
        return self._height

    def set_size(self, width: int, height: int) -> None:
        """Set the viewport's inner size in cells. A width change invalidates
        all offsets (heights are width-dependent)."""
        if width != self._width:
            self._width = width
            self._invalidate_offsets()
        self._height = height
        self._clamp_scroll()

    # -- entry list --------------------------------------------------------

    def set_entries(self, entries: list[Entry[T]]) -> None:
        """Replace the ordered entry list (e.g. after a structural change)."""
        self._entries = entries
        self._invalidate_offsets()

    def invalidate_heights(self) -> None:
        """Mark offsets stale because one or more heights changed (a present
        completed, or an item was updated)."""
        self._invalidate_offsets()

    # -- geometry ----------------------------------------------------------

    @property
    def total_height(self) -> int:
        return self._prefix()[-1]

    @property
    def max_scroll(self) -> int:
        return max(0, self.total_height - self._height)

    def height_of(self, entry: Entry[T]) -> int:
        """The height the layout will use for ``entry`` (cached, last-known, or
        the estimate) — the same value that drives the offsets."""
        return self._height_of(entry)

    def _height_of(self, entry: Entry[T]) -> int:
        if self._width > 0:
            h = self._layout.height(entry, self._width)
            if h is not None:
                return h
        # Fall back to the last height seen at any width (keeps the layout
        # stable across a resize) before dropping to the estimate.
        last = self._layout.last_known_height(entry.id)
        return last if last is not None else self._estimated_height

    def _prefix(self) -> list[int]:
        """Cumulative offsets: ``prefix[i]`` = the start row of entry ``i``,
        ``prefix[len]`` = total height. ``spacing`` blank rows sit between
        consecutive entries (not before the first or after the last)."""
        if self._offsets is None:
            offsets = []
            acc = 0
            last = len(self._entries) - 1
            for i, entry in enumerate(self._entries):
                offsets.append(acc)
                acc += self._height_of(entry)
                if i < last:
                    acc += self._spacing
            offsets.append(acc)
            self._offsets = offsets
        return self._offsets

    def _invalidate_offsets(self) -> None:
        self._offsets = None

    @property
    def entries(self) -> list[Entry[T]]:
        return self._entries

    def locate(self, y: int) -> tuple[int, int] | None:
        """Map a virtual y-offset to ``(entry_index, local_y)`` — the entry
        covering row ``y`` and the row within that entry. ``None`` if ``y`` is
        outside the content or falls in a spacer gap between entries."""
        prefix = self._prefix()
        n = len(self._entries)
        if n == 0 or y < 0 or y >= prefix[-1]:
            return None
        index = _upper_bound(prefix, y) - 1
        if index < 0 or index >= n:
            return None
        local_y = y - prefix[index]
        if local_y >= self._height_of(self._entries[index]):
            return None  # in the spacer gap after this entry
        return index, local_y

    def gap_at(self, y: int) -> tuple[int, int, int] | None:
        """If ``y`` falls in the spacer gap *between* two entries, return
        ``(above_index, below_index, gap_local_y)`` where ``gap_local_y`` is the
        row within the gap (0-based, < spacing). ``None`` otherwise (inside an
        entry, before the first, or past the last)."""
        if self._spacing <= 0:
            return None
        prefix = self._prefix()
        n = len(self._entries)
        if n == 0 or y < 0 or y >= prefix[-1]:
            return None
        index = _upper_bound(prefix, y) - 1
        if index < 0 or index >= n - 1:  # no gap after the last entry
            return None
        gap_local = y - prefix[index] - self._height_of(self._entries[index])
        if gap_local < 0 or gap_local >= self._spacing:
            return None  # actually inside the entry
        return index, index + 1, gap_local

    def entries_between(self, top: int, bottom: int) -> list[Entry[T]]:
        """Entries whose rows intersect the virtual band ``[top, bottom)``.

        Used for read-ahead: the view asks for a band wider than the visible
        range so it can pre-present entries before they scroll in."""
        prefix = self._prefix()
        n = len(self._entries)
        if n == 0 or bottom <= top:
            return []
        start = max(0, _upper_bound(prefix, max(0, top)) - 1)
        stop = start
        while stop < n and prefix[stop] < bottom:
            stop += 1
        return self._entries[start:stop]

    def offset_at(self, index: int) -> int:
        """Virtual y-offset of the entry at ``index`` (O(1) via the prefix)."""
        prefix = self._prefix()
        if index < 0 or index >= len(prefix):
            return 0
        return prefix[index]

    def offset_of(self, entry: Entry[T]) -> int | None:
        """Virtual y-offset of ``entry``'s top edge, or ``None`` if unknown."""
        prefix = self._prefix()
        for i, e in enumerate(self._entries):
            if e is entry:
                return prefix[i]
        return None

    # -- visible range -----------------------------------------------------

    def visible_range(self) -> VisibleRange[T]:
        """Compute the entries to draw for the current scroll position,
        padded by ``overscan`` rows above and below."""
        prefix = self._prefix()
        n = len(self._entries)
        if n == 0 or self._height <= 0:
            return VisibleRange(0, 0, [], 0)

        top = max(0, self._scroll_y - self._overscan)
        bottom = self._scroll_y + self._height + self._overscan

        start = _upper_bound(prefix, top) - 1
        start = max(0, min(start, n - 1))
        # advance stop until an entry starts at/after bottom
        stop = start
        while stop < n and prefix[stop] < bottom:
            stop += 1

        return VisibleRange(start, stop, self._entries[start:stop], prefix[start])

    # -- scrolling ---------------------------------------------------------

    def is_at_bottom(self) -> bool:
        return self._scroll_y >= self.max_scroll

    def scroll_to_offset(self, y: int) -> None:
        self._scroll_y = y
        self._clamp_scroll()

    def scroll_to_top(self) -> None:
        self._scroll_y = 0

    def scroll_to_bottom(self) -> None:
        self._scroll_y = self.max_scroll

    def scroll_by(self, delta: int) -> None:
        self.scroll_to_offset(self._scroll_y + delta)

    def scroll_to_entry(self, entry: Entry[T], *, top: bool = False) -> None:
        """Scroll so ``entry`` is at the top (``top=True``) or merely visible."""
        offset = self.offset_of(entry)
        if offset is None:
            return
        if top:
            self.scroll_to_offset(offset)
            return
        height = self._height_of(entry)
        if offset < self._scroll_y:
            self.scroll_to_offset(offset)
        elif offset + height > self._scroll_y + self._height:
            self.scroll_to_offset(offset + height - self._height)

    def scroll_entry_aligned(self, entry: Entry[T], align: str) -> None:
        """Scroll so ``entry`` lands at ``align`` within the viewport:
        ``"start"`` (top), ``"center"``, ``"end"`` (bottom), or ``"nearest"``
        (minimal scroll). Offsets are clamped by :meth:`scroll_to_offset`."""
        if align == "nearest":
            self.scroll_to_entry(entry, top=False)
            return
        offset = self.offset_of(entry)
        if offset is None:
            return
        height = self._height_of(entry)
        if align == "start":
            target = offset
        elif align == "end":
            target = offset + height - self._height
        else:  # center
            target = offset + (height - self._height) // 2
        self.scroll_to_offset(target)

    def _clamp_scroll(self) -> None:
        self._scroll_y = max(0, min(self._scroll_y, self.max_scroll))

    # -- anchoring ---------------------------------------------------------

    def capture_anchor(self) -> AnchorState[T]:
        """Snapshot enough state to preserve position across a reflow."""
        stick_bottom = self._anchor is Anchor.STICKY_BOTTOM and self.is_at_bottom()
        vr = self.visible_range()
        top_entry = vr.entries[0] if vr.entries else None
        delta = self._scroll_y - vr.first_offset if top_entry is not None else 0
        return AnchorState(stick_bottom, top_entry, delta)

    def restore_anchor(self, state: AnchorState[T]) -> None:
        """Reposition after a reflow according to a captured anchor."""
        self._invalidate_offsets()
        if state.stick_bottom:
            self.scroll_to_bottom()
            return
        if state.top_entry is not None:
            offset = self.offset_of(state.top_entry)
            if offset is not None:
                self.scroll_to_offset(offset + state.delta)
                return
        self._clamp_scroll()


class AnchorState(Generic[T]):
    __slots__ = ("delta", "stick_bottom", "top_entry")

    def __init__(self, stick_bottom: bool, top_entry: Entry[T] | None, delta: int) -> None:
        self.stick_bottom = stick_bottom
        self.top_entry = top_entry
        self.delta = delta


def _upper_bound(prefix: list[int], value: int) -> int:
    """Index of the first element in ``prefix`` strictly greater than ``value``
    (binary search; ``prefix`` is non-decreasing)."""
    lo, hi = 0, len(prefix)
    while lo < hi:
        mid = (lo + hi) // 2
        if prefix[mid] <= value:
            lo = mid + 1
        else:
            hi = mid
    return lo
