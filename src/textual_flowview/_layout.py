from __future__ import annotations

from typing import Generic, TypeVar

from ._entry import Entry
from ._presentation import Presentation

__all__ = ["FlowLayout"]

T = TypeVar("T")

# Cache key: (entry id, width, revision)
_Key = tuple[int, int, int]


class FlowLayout(Generic[T]):
    """Pure presentation/height cache. Knows nothing about scrolling.

    ``FlowLayout`` maps an ``Entry`` (identified by ``id`` + ``revision``) at a
    given ``width`` to the :class:`Presentation` a presenter produced for it.
    It never decides what is visible and never reads scroll state — that is the
    :class:`Viewport`'s job. Dependency flows strictly ``Viewport -> FlowLayout``.

    The cache is keyed by ``(entry.id, width, entry.revision)`` so that:

    * a resize (new ``width``) is a cache miss and re-presents,
    * an ``entry.update()`` (new ``revision``) is a cache miss and re-presents,
    * scrolling never invalidates anything.

    Only one presentation per ``(id, width)`` is retained: storing a newer
    revision evicts older revisions for the same id/width, which keeps
    streaming (many rapid ``update()`` calls) from growing the cache without
    bound.
    """

    def __init__(self) -> None:
        self._cache: dict[_Key, Presentation] = {}

    def get(self, entry: Entry[T], width: int) -> Presentation | None:
        """Return the cached presentation for ``entry`` at ``width`` for its
        *current* revision, or ``None`` on a miss."""
        return self._cache.get((entry.id, width, entry.revision))

    def height(self, entry: Entry[T], width: int) -> int | None:
        """Cached height for ``entry`` at ``width``, or ``None`` if not yet
        presented at that width/revision."""
        presentation = self.get(entry, width)
        return presentation.height if presentation is not None else None

    def store(
        self,
        entry_id: int,
        width: int,
        revision: int,
        presentation: Presentation,
    ) -> None:
        """Store a worker result under the exact ``(id, width, revision)`` it
        was computed for.

        Explicit ``entry_id`` / ``revision`` (rather than an ``Entry``) because
        the value is produced asynchronously: by the time the worker finishes,
        the entry's live revision may already have advanced. The caller decides
        whether the result is still current.
        """
        # Evict stale revisions for the same id+width.
        stale = [
            key
            for key in self._cache
            if key[0] == entry_id and key[1] == width and key[2] != revision
        ]
        for key in stale:
            del self._cache[key]
        self._cache[(entry_id, width, revision)] = presentation

    def discard(self, entry_id: int) -> None:
        """Drop every cached presentation for an entry (call on removal)."""
        stale = [key for key in self._cache if key[0] == entry_id]
        for key in stale:
            del self._cache[key]

    def retain_width(self, width: int) -> None:
        """Drop presentations produced for any width other than ``width``.

        Called by the view after a resize so the cache does not accumulate
        entries for widths that can no longer be displayed.
        """
        stale = [key for key in self._cache if key[1] != width]
        for key in stale:
            del self._cache[key]

    def clear(self) -> None:
        """Empty the entire cache."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)
