from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ._state import EntryState

if TYPE_CHECKING:
    from textual.strip import Strip

    from ._model import FlowModel

__all__ = ["Entry"]

T = TypeVar("T")


class Entry(Generic[T]):
    """A stable handle to one item inside a :class:`FlowModel`.

    An ``Entry`` is the single way to refer to a displayed item — analogous to
    a file handle, socket, or task handle. It is returned by
    :meth:`FlowModel.append` / :meth:`FlowModel.insert` and is the sole target
    of updates, removals, and scrolling::

        entry = model.append(item)
        item.text += "..."
        entry.update()
        entry.remove()

    Identity is the entry object itself; the model never inspects the item with
    ``==``. This keeps mutable and in-place-mutated items safe.

    ``id`` and ``revision`` are managed entirely by the model. The item carries
    no bookkeeping fields of its own.
    """

    __slots__ = (
        "_alive",
        "_children",
        "_collapsed",
        "_decor_revision",
        "_depth",
        "_hidden",
        "_id",
        "_item",
        "_metadata",
        "_model",
        "_parent",
        "_revision",
        "_state",
    )

    def __init__(
        self, model: FlowModel[T], id: int, item: T, parent: Entry[T] | None = None
    ) -> None:
        self._model = model
        self._id = id
        self._item = item
        self._revision = 0
        self._alive = True
        self._hidden = False
        self._parent = parent
        self._children: list[Entry[T]] = []
        self._depth: int = 0 if parent is None else parent._depth + 1
        self._collapsed = False
        self._state: EntryState = EntryState.DEFAULT
        self._metadata: dict[str, Any] = {}
        # Bumped on state/metadata changes; drives gutter (not body) redraws.
        self._decor_revision = 0

    @property
    def item(self) -> T:
        """The domain object this entry wraps."""
        return self._item

    @property
    def id(self) -> int:
        """Stable, model-assigned identifier. Unique within the model."""
        return self._id

    @property
    def revision(self) -> int:
        """Monotonically increasing counter, bumped on every ``update()``.

        Forms part of the presentation cache key; stale worker results whose
        revision is older than the current one are discarded.
        """
        return self._revision

    @property
    def alive(self) -> bool:
        """``False`` once the entry has been removed or the model cleared."""
        return self._alive

    @property
    def state(self) -> EntryState:
        """The entry's lifecycle state. Consumed by decorators only; changing
        it never re-presents the body."""
        return self._state

    @property
    def metadata(self) -> Mapping[str, Any]:
        """Read-only view of the decorator-facing metadata bag."""
        return MappingProxyType(self._metadata)

    @property
    def hidden(self) -> bool:
        """Whether this entry is currently excluded from the view.

        Hidden entries stay in the model and keep their cached presentation
        (so showing them again is instant), but contribute no height and are
        not drawn — and neither is their subtree, since a hidden parent cannot
        show its children. This is the primitive for *filtering*; folding a
        group is :attr:`collapsed`, which is independent of it.
        """
        return self._hidden

    def hide(self) -> None:
        """Exclude this entry from the view. A no-op if already hidden."""
        self.set_hidden(True)

    def show(self) -> None:
        """Re-include this entry in the view. A no-op if already visible."""
        self.set_hidden(False)

    def set_hidden(self, hidden: bool) -> None:
        """Set visibility. Does not bump the revision or re-present the body;
        only the set of visible entries and the layout change. No-op on a
        removed entry or when unchanged."""
        if not self._alive or hidden == self._hidden:
            return
        self._hidden = hidden
        self._model._on_entry_visibility(self)

    # -- tree ------------------------------------------------------------

    @property
    def parent(self) -> Entry[T] | None:
        """The entry this one hangs under, or ``None`` for a top-level entry."""
        return self._parent

    @property
    def children(self) -> tuple[Entry[T], ...]:
        """This entry's direct children, in order. Empty for a leaf."""
        return tuple(self._children)

    @property
    def depth(self) -> int:
        """Nesting depth: 0 for a top-level entry, 1 for its children, and so on.

        Fixed when the entry is created — entries are never re-parented — so it
        is safe to render from. Indentation is **yours to apply**: FlowView
        lays out and clips rows, it never indents or draws tree guides for you.
        """
        return self._depth

    def ancestors(self) -> Iterator[Entry[T]]:
        """Yield this entry's parent, grandparent, … up to the root."""
        entry = self._parent
        while entry is not None:
            yield entry
            entry = entry._parent

    def descendants(self) -> Iterator[Entry[T]]:
        """Yield the whole subtree below this entry in document order."""
        for child in self._children:
            yield child
            yield from child.descendants()

    def append_child(self, item: T) -> Entry[T]:
        """Append ``item`` as this entry's last child and return its handle."""
        return self._model.append(item, parent=self)

    def insert_child(self, index: int, item: T) -> Entry[T]:
        """Insert ``item`` among this entry's children at ``index``."""
        return self._model.insert(index, item, parent=self)

    # -- collapse ---------------------------------------------------------

    @property
    def collapsed(self) -> bool:
        """Whether this entry's **subtree** is folded away.

        Orthogonal to :attr:`hidden`: ``collapsed`` is about the descendants
        (the entry itself stays on screen — it is the header you fold from),
        ``hidden`` is about this entry (and, since a hidden parent can't show
        its children, its subtree with it). A filter that hides entries and a
        fold that collapses them therefore compose instead of fighting over one
        flag.

        Independent of whether the subtree exists yet: an entry with no children
        can hold ``collapsed=True``, so a group can be declared folded before
        its first child arrives.
        """
        return self._collapsed

    @property
    def visible(self) -> bool:
        """Whether this entry is actually laid out and drawn.

        ``True`` when it is not hidden and no ancestor is hidden or collapsed.
        """
        if self._hidden:
            return False
        return all(not (a._hidden or a._collapsed) for a in self.ancestors())

    def collapse(self) -> None:
        """Fold this entry's subtree away. A no-op if already collapsed."""
        self.set_collapsed(True)

    def expand(self) -> None:
        """Unfold this entry's subtree. A no-op if already expanded."""
        self.set_collapsed(False)

    def toggle_collapsed(self) -> None:
        """Fold or unfold this entry's subtree."""
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold or unfold the subtree.

        Descendants keep their cached presentations, so the fold itself never
        re-presents them. *This* entry does re-present: its body is free to draw
        the fold state (a ▸/▾ chevron, a "12 steps" summary) now that presenters
        receive the entry, so a fold is a content change for the header and the
        revision bumps accordingly.

        Safe to call **before the first child exists** — that is how a group
        declares "I start folded" at registration time. The state is recorded on
        any live entry; a child appended later checks its ancestors and is born
        folded. Folding something with no subtree simply draws nothing, so it
        neither re-presents nor posts :class:`FlowView.Collapsed`. A no-op on a
        removed entry or when unchanged."""
        self._model.set_collapsed_many([self], collapsed)

    def set_state(self, state: EntryState) -> None:
        """Set the lifecycle state and redraw the gutter only.

        Does **not** bump the revision, so the cached presentation stays valid
        and the body is not regenerated. A no-op on a removed entry or when the
        state is unchanged.
        """
        if not self._alive or state is self._state:
            return
        self._state = state
        self._decorated()

    def set_metadata(self, key: str, value: Any) -> None:
        """Set one metadata key and redraw the gutter only. No body re-present."""
        if not self._alive:
            return
        self._metadata[key] = value
        self._decorated()

    def update_metadata(self, **kwargs: Any) -> None:
        """Merge several metadata keys and redraw the gutter only."""
        if not self._alive or not kwargs:
            return
        self._metadata.update(kwargs)
        self._decorated()

    def _decorated(self) -> None:
        self._decor_revision += 1
        self._model._on_entry_decorated(self)

    def update(self) -> None:
        """Signal that the wrapped item's state changed.

        Bumps the revision and notifies the model (and thus the view) to
        re-present this item. A no-op on a removed entry, so streaming code
        that races against removal never crashes.
        """
        if not self._alive:
            return
        self._revision += 1
        self._model._on_entry_updated(self)

    def set_item(self, item: T) -> None:
        """Replace the wrapped item and re-present.

        Use this to swap the whole object (e.g. immutable items via
        ``dataclasses.replace``); use :meth:`update` when you mutated the
        existing item in place. Both bump the revision and re-present. A no-op
        on a removed entry.
        """
        if not self._alive:
            return
        self._item = item
        self._revision += 1
        self._model._on_entry_updated(self)

    def patch_rows(self, start: int, strips: list[Strip]) -> None:
        """Incrementally replace this entry's body rows from ``start`` onward
        with ``strips`` — already rendered, one :class:`~textual.strip.Strip`
        per line, at the width ``present`` was last called with.

        The cheap streaming path: rows ``[0:start]`` are kept as-is (**not**
        re-rendered), only the tail is swapped. ``start`` is the *safe
        watermark* you computed — the first row that may still change. You own
        that judgement and the tail rendering; FlowView just splices.

        **The contract:** ``start`` may only point at a row you know will
        **never change again**. FlowView will not revisit ``[0:start]`` — you
        have declared it final. This is a scalpel, not an auto-incremental
        engine: FlowView can't see inside an opaque renderable, so the stability
        judgement is yours by design.

        This is unconditionally correct for **append-only** output (plain text
        past the last newline: rows above a hard ``\\n`` don't reflow at a fixed
        width). It is **not** correct for **context-sensitive** renderables. In
        markdown a line's rendering is not final until its *block closes* — an
        open ``*`` becomes italic once closed, a `````` ``` ```` fence
        re-renders the whole block as code when it closes, a delimiter row snaps
        the paragraphs above into a table, ``===`` retroactively makes the line
        above an ``<h1>``. So for markdown, ``start`` must be the first row of a
        **closed** block, and the still-open block (everything from ``start``
        down) must be **fully re-rendered on every patch**, not frozen — still
        O(open block), not O(size). Renderables whose layout depends on *total*
        content (tables, ``Columns``, right-justify, content-sized panels)
        cannot be patched mid-stream at all; patch only at completion or use
        :meth:`set_item`.

        Keep the item itself in sync so a later re-``present`` (e.g. on resize,
        which invalidates the pre-rendered widths) still produces the full body,
        and drop your watermark on resize. A no-op on a removed entry."""
        if not self._alive:
            return
        self._revision += 1
        self._model._on_entry_patch(self, start, list(strips))

    def remove(self) -> None:
        """Remove this item from the model. A no-op if already removed."""
        if not self._alive:
            return
        self._model._on_entry_removed(self)

    def _kill(self) -> None:
        """Internal: mark the entry dead without re-entering the model."""
        self._alive = False

    def __repr__(self) -> str:
        state = "alive" if self._alive else "dead"
        tree = f" depth={self._depth}" if self._depth else ""
        fold = " collapsed" if self._collapsed else ""
        return f"<Entry id={self._id} rev={self._revision} {state}{tree}{fold}>"
