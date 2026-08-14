from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any, Generic, Protocol, TypeVar

from ._entry import Entry

__all__ = ["FlowModel", "ModelListener"]

T = TypeVar("T")


class ModelListener(Protocol[T]):
    """Internal contract a :class:`FlowView` implements to observe a model.

    Not part of the public API. Callbacks are invoked synchronously on the
    thread that mutates the model (normally the app's message loop).
    """

    def on_flow_insert(self, entry: Entry[T], index: int) -> None: ...
    def on_flow_insert_many(self, entries: list[Entry[T]], index: int) -> None: ...
    def on_flow_update(self, entry: Entry[T]) -> None: ...
    def on_flow_patch(self, entry: Entry[T], start: int, strips: list[Any]) -> None: ...
    def on_flow_remove(self, entry: Entry[T], index: int) -> None: ...
    def on_flow_clear(self) -> None: ...
    def on_flow_decorate(self, entry: Entry[T]) -> None: ...
    def on_flow_visibility(self, entry: Entry[T]) -> None: ...
    def on_flow_visibility_many(self, entries: list[Entry[T]]) -> None: ...
    def on_flow_collapse(self, entries: list[Entry[T]], collapsed: bool) -> None: ...
    def on_flow_remove_many(self, entries: list[Entry[T]]) -> None: ...


class FlowModel(Generic[T]):
    """An ordered collection of items displayed by a :class:`FlowView`.

    The model knows nothing about the UI. It owns item ordering, assigns each
    item a stable :class:`Entry` handle, and notifies its (optional) listener
    when the collection changes.

    All mutating methods return the affected :class:`Entry`; the returned entry
    is the only supported way to later update or remove the item.
    """

    def __init__(self) -> None:
        self._roots: list[Entry[T]] = []
        self._flat: list[Entry[T]] | None = None  # cached preorder flatten
        self._next_id: int = 0
        self._listener: ModelListener[T] | None = None

    # -- public API --------------------------------------------------------

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[Entry[T]]:
        """Iterate every entry in document order — parents immediately followed
        by their subtree — regardless of hidden or collapsed state."""
        return iter(self.entries)

    @property
    def entries(self) -> list[Entry[T]]:
        """Every entry in document order (preorder), hidden and folded ones
        included."""
        if self._flat is None:
            flat: list[Entry[T]] = []
            stack = list(reversed(self._roots))
            while stack:
                entry = stack.pop()
                flat.append(entry)
                stack.extend(reversed(entry._children))
            self._flat = flat
        return self._flat

    def visible_entries(self) -> list[Entry[T]]:
        """Document order with hidden entries and folded subtrees removed — the
        set the view actually lays out and draws.

        One pass: a hidden or collapsed entry lets the whole contiguous subtree
        below it be skipped, so this stays O(entries) however deep the tree.
        """
        out: list[Entry[T]] = []
        skip_depth: int | None = None
        for entry in self.entries:
            if skip_depth is not None:
                if entry._depth > skip_depth:
                    continue
                skip_depth = None
            if entry._hidden:
                skip_depth = entry._depth  # a hidden parent hides its subtree
                continue
            out.append(entry)
            if entry._collapsed:
                skip_depth = entry._depth  # folded: the entry shows, its kids don't
        return out

    def append(self, item: T, *, parent: Entry[T] | None = None) -> Entry[T]:
        """Append ``item`` and return its handle — at the end of the model, or
        as ``parent``'s last child."""
        siblings = self._roots if parent is None else parent._children
        return self.insert(len(siblings), item, parent=parent)

    def insert(
        self, index: int, item: T, *, parent: Entry[T] | None = None
    ) -> Entry[T]:
        """Insert ``item`` at ``index`` **among its siblings** and return its
        handle. With no ``parent`` the siblings are the top-level entries, so
        for a flat model this is a plain positional insert."""
        return self.insert_many(index, [item], parent=parent)[0]

    def insert_many(
        self, index: int, items: Iterable[T], *, parent: Entry[T] | None = None
    ) -> list[Entry[T]]:
        """Insert several items at ``index`` among ``parent``'s children (or at
        top level) as **one** operation, returning their handles in order.

        One notification, so the view reflows **once** instead of once per item
        — the primitive for infinite-scroll load-more, where a handler prepends a
        whole page (pair it with :class:`FlowView.ReachedTop`), and for adding a
        group's children in bulk. Prepending above the viewport keeps the scroll
        position either way; ``insert_many`` just does it in a single reflow."""
        if parent is not None and not parent.alive:
            return []
        siblings = self._roots if parent is None else parent._children
        index = max(0, min(index, len(siblings)))
        entries: list[Entry[T]] = []
        for offset, item in enumerate(items):
            entry = Entry(self, self._next_id, item, parent)
            self._next_id += 1
            siblings.insert(index + offset, entry)
            entries.append(entry)
        if not entries:
            return entries
        self._flat = None
        if self._listener is not None:
            if len(entries) == 1:
                self._listener.on_flow_insert(entries[0], index)
            else:
                self._listener.on_flow_insert_many(entries, index)
        return entries

    def extend(
        self, items: Iterable[T], *, parent: Entry[T] | None = None
    ) -> list[Entry[T]]:
        """Append several items at the end as one operation (batch
        :meth:`append`); see :meth:`insert_many`."""
        siblings = self._roots if parent is None else parent._children
        return self.insert_many(len(siblings), items, parent=parent)

    def clear(self) -> None:
        """Remove every item. All existing entries become dead."""
        for entry in self.entries:
            entry._kill()
        self._roots.clear()
        self._flat = None
        if self._listener is not None:
            self._listener.on_flow_clear()

    # -- internal (called by Entry) ---------------------------------------

    def _on_entry_updated(self, entry: Entry[T]) -> None:
        if self._listener is not None:
            self._listener.on_flow_update(entry)

    def _on_entry_patch(self, entry: Entry[T], start: int, strips: list[Any]) -> None:
        if self._listener is not None:
            self._listener.on_flow_patch(entry, start, strips)

    def _on_entry_decorated(self, entry: Entry[T]) -> None:
        if self._listener is not None:
            self._listener.on_flow_decorate(entry)

    def _on_entry_visibility(self, entry: Entry[T]) -> None:
        if self._listener is not None:
            self._listener.on_flow_visibility(entry)

    def set_hidden_many(self, entries: Iterable[Entry[T]], hidden: bool) -> None:
        """Show or hide several entries as **one** operation.

        The batch primitive behind group collapse, and the reason to prefer it
        over a loop of :meth:`Entry.hide`: each single change reflows the view
        *and* re-runs the present band, so as the layout closes up the entries
        that slide into the band get presented — including the ones being
        hidden. Collapsing a group one entry at a time therefore renders the
        very content it is collapsing. Measured, collapsing 200 of 2 000 entries
        with the group **at the viewport**: 573 ms and 104 `present()` calls
        one-by-one, against 35 ms and 8 batched. For a group entirely
        off-screen, neither presents anything and it is 201 ms against 43 ms.

        Entries already in the requested state, and dead ones, are skipped; if
        nothing changes, no notification is sent.
        """
        changed = [e for e in entries if e.alive and e._hidden != hidden]
        if not changed:
            return
        for entry in changed:
            entry._hidden = hidden
        if self._listener is not None:
            self._listener.on_flow_visibility_many(changed)

    def set_collapsed_many(
        self, entries: Iterable[Entry[T]], collapsed: bool
    ) -> None:
        """Fold or unfold several subtrees as **one** operation — one reflow and
        one present pass for the lot (see :meth:`set_hidden_many` for why that
        matters). Entries already in the requested state, leaves and dead ones
        are skipped; if nothing changes, no notification is sent.

        The headers themselves are *not* re-presented. If their bodies show the
        fold state (a ▸/▾ chevron), call :meth:`Entry.update` on them first: the
        pending re-presents are picked up by this call's single reflow."""
        changed = [
            e for e in entries
            if e.alive and e._children and e._collapsed != collapsed
        ]
        if not changed:
            return
        for entry in changed:
            entry._collapsed = collapsed
            entry._revision += 1  # the header's own body may draw the chevron
        if self._listener is not None:
            self._listener.on_flow_collapse(changed, collapsed)

    def _on_entry_removed(self, entry: Entry[T]) -> None:
        siblings = self._roots if entry._parent is None else entry._parent._children
        try:
            index = siblings.index(entry)
        except ValueError:
            return
        del siblings[index]
        self._flat = None
        # Removing an entry removes what hangs under it — a child cannot outlive
        # the parent that positions it.
        doomed = [entry, *entry.descendants()]
        for dead in doomed:
            dead._kill()
        if self._listener is not None:
            if len(doomed) == 1:
                self._listener.on_flow_remove(entry, index)
            else:
                self._listener.on_flow_remove_many(doomed)

    # -- internal (called by FlowView) ------------------------------------

    def _attach(self, listener: ModelListener[T]) -> None:
        self._listener = listener

    def _detach(self) -> None:
        self._listener = None
