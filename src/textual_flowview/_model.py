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


class FlowModel(Generic[T]):
    """An ordered collection of items displayed by a :class:`FlowView`.

    The model knows nothing about the UI. It owns item ordering, assigns each
    item a stable :class:`Entry` handle, and notifies its (optional) listener
    when the collection changes.

    All mutating methods return the affected :class:`Entry`; the returned entry
    is the only supported way to later update or remove the item.
    """

    def __init__(self) -> None:
        self._entries: list[Entry[T]] = []
        self._next_id: int = 0
        self._listener: ModelListener[T] | None = None

    # -- public API --------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterator[Entry[T]]:
        return iter(self._entries)

    def append(self, item: T) -> Entry[T]:
        """Append ``item`` to the end and return its handle."""
        return self.insert(len(self._entries), item)

    def insert(self, index: int, item: T) -> Entry[T]:
        """Insert ``item`` at ``index`` and return its handle."""
        index = max(0, min(index, len(self._entries)))
        entry = Entry(self, self._next_id, item)
        self._next_id += 1
        self._entries.insert(index, entry)
        if self._listener is not None:
            self._listener.on_flow_insert(entry, index)
        return entry

    def insert_many(self, index: int, items: Iterable[T]) -> list[Entry[T]]:
        """Insert several items at ``index`` as **one** operation, returning
        their handles in order.

        One notification, so the view reflows **once** instead of once per item
        — the primitive for infinite-scroll load-more, where a handler prepends a
        whole page (pair it with :class:`FlowView.ReachedTop`). Prepending above
        the viewport keeps the scroll position either way; ``insert_many`` just
        does it in a single reflow."""
        items = list(items)
        index = max(0, min(index, len(self._entries)))
        entries: list[Entry[T]] = []
        for offset, item in enumerate(items):
            entry = Entry(self, self._next_id, item)
            self._next_id += 1
            self._entries.insert(index + offset, entry)
            entries.append(entry)
        if entries and self._listener is not None:
            self._listener.on_flow_insert_many(entries, index)
        return entries

    def extend(self, items: Iterable[T]) -> list[Entry[T]]:
        """Append several items at the end as one operation (batch
        :meth:`append`); see :meth:`insert_many`."""
        return self.insert_many(len(self._entries), items)

    def clear(self) -> None:
        """Remove every item. All existing entries become dead."""
        for entry in self._entries:
            entry._kill()
        self._entries.clear()
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
        changed = [
            entry
            for entry in entries
            if entry.alive and entry._hidden != hidden
        ]
        if not changed:
            return
        for entry in changed:
            entry._hidden = hidden
        if self._listener is not None:
            self._listener.on_flow_visibility_many(changed)

    def _on_entry_removed(self, entry: Entry[T]) -> None:
        try:
            index = self._entries.index(entry)
        except ValueError:
            return
        del self._entries[index]
        entry._kill()
        if self._listener is not None:
            self._listener.on_flow_remove(entry, index)

    # -- internal (called by FlowView) ------------------------------------

    def _attach(self, listener: ModelListener[T]) -> None:
        self._listener = listener

    def _detach(self) -> None:
        self._listener = None
