from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ._state import EntryState

if TYPE_CHECKING:
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
        "_decor_revision",
        "_hidden",
        "_id",
        "_item",
        "_metadata",
        "_model",
        "_revision",
        "_state",
    )

    def __init__(self, model: FlowModel[T], id: int, item: T) -> None:
        self._model = model
        self._id = id
        self._item = item
        self._revision = 0
        self._alive = True
        self._hidden = False
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
        not drawn. This is the primitive group-collapse is built on: collapse
        a header by hiding its child entries.
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
        return f"<Entry id={self._id} rev={self._revision} {state}>"
