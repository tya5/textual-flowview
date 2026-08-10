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
        # entry id -> its keys in `_cache`. Keeps the per-entry operations
        # (store's stale-eviction, discard, release) proportional to that
        # entry's own keys — usually one — instead of scanning the whole cache,
        # which streaming into a long transcript does on every chunk.
        self._by_entry: dict[int, set[_Key]] = {}
        # Last height seen for an entry at *any* width/revision. Survives a
        # width change (unlike the width-keyed cache) so the layout can keep an
        # entry near its real size while it re-presents after a resize, instead
        # of momentarily collapsing to the estimate.
        self._last_height: dict[int, int] = {}

    def get(self, entry: Entry[T], width: int) -> Presentation | None:
        """Return the cached presentation for ``entry`` at ``width`` for its
        *current* revision, or ``None`` on a miss."""
        return self._cache.get((entry.id, width, entry.revision))

    def height(self, entry: Entry[T], width: int) -> int | None:
        """Cached height for ``entry`` at ``width``, or ``None`` if not yet
        presented at that width/revision."""
        presentation = self.get(entry, width)
        return presentation.height if presentation is not None else None

    def last_known_height(self, entry_id: int) -> int | None:
        """The most recent height seen for this entry at any width, or
        ``None`` if it has never been presented. Used as a resize-friendly
        estimate so the layout doesn't collapse before re-presenting."""
        return self._last_height.get(entry_id)

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
        keys = self._by_entry.setdefault(entry_id, set())
        # Evict stale revisions for the same id+width (only this entry's keys).
        for key in [k for k in keys if k[1] == width and k[2] != revision]:
            del self._cache[key]
            keys.discard(key)
        new_key = (entry_id, width, revision)
        self._cache[new_key] = presentation
        keys.add(new_key)
        self._last_height[entry_id] = presentation.height

    def discard(self, entry_id: int) -> None:
        """Drop every cached presentation for an entry (call on removal)."""
        self._drop(entry_id)
        self._last_height.pop(entry_id, None)

    def release(self, entry_id: int) -> None:
        """Drop an entry's cached presentations but **keep its last-known
        height** — for an entry that is still in the model but whose cached
        render is now unreachable (e.g. its revision moved on while it was
        off-screen). Retaining the height keeps the layout stable until it
        re-presents; :meth:`discard` is the removal counterpart that forgets
        both."""
        self._drop(entry_id)

    def _drop(self, entry_id: int) -> None:
        for key in self._by_entry.pop(entry_id, ()):
            self._cache.pop(key, None)

    def retain_width(self, width: int) -> None:
        """Drop presentations produced for any width other than ``width``.

        Called by the view after a resize so the cache does not accumulate
        entries for widths that can no longer be displayed.
        """
        stale = [key for key in self._cache if key[1] != width]
        for key in stale:
            del self._cache[key]
            keys = self._by_entry.get(key[0])
            if keys is not None:
                keys.discard(key)
                if not keys:
                    del self._by_entry[key[0]]

    def clear(self) -> None:
        """Empty the entire cache."""
        self._cache.clear()
        self._by_entry.clear()
        self._last_height.clear()

    def __len__(self) -> int:
        return len(self._cache)
