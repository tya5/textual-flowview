from __future__ import annotations

from typing import Generic, Protocol, TypeVar

from ._entry import Entry

__all__ = ["FlowModel", "ModelListener"]

T = TypeVar("T")


class ModelListener(Protocol[T]):
    """Internal contract a :class:`FlowView` implements to observe a model.

    Not part of the public API. Callbacks are invoked synchronously on the
    thread that mutates the model (normally the app's message loop).
    """

    def on_flow_insert(self, entry: Entry[T], index: int) -> None: ...
    def on_flow_update(self, entry: Entry[T]) -> None: ...
    def on_flow_remove(self, entry: Entry[T], index: int) -> None: ...
    def on_flow_clear(self) -> None: ...
    def on_flow_decorate(self, entry: Entry[T]) -> None: ...


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

    def __iter__(self):  # type: ignore[no-untyped-def]
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

    def _on_entry_decorated(self, entry: Entry[T]) -> None:
        if self._listener is not None:
            self._listener.on_flow_decorate(entry)

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
