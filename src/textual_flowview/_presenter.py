from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from ._presentation import Presentation

if TYPE_CHECKING:
    from ._entry import Entry

__all__ = ["FlowPresenter"]

# Invariant, not contravariant: the presenter now receives Entry[T], and
# Entry is invariant in its item type.
T = TypeVar("T")


@runtime_checkable
class FlowPresenter(Protocol[T]):
    """Converts an entry into a :class:`Presentation`.

    The presenter is the *only* component that knows the concrete item type.
    Implementations are always ``async`` (a synchronous body is fine — just
    declare it ``async def``)::

        async def present(self, entry: Entry[Msg], width: int) -> Presentation:
            item = entry.item
            body = Text(("  " * entry.depth) + item.text)   # indent is yours
            return Presentation(height=..., renderable=body)

    You get the whole :class:`Entry`, not just the item, because some of what a
    body draws is state FlowView owns rather than your item: :attr:`Entry.depth`
    for indentation, :attr:`Entry.collapsed` for a ▸/▾ chevron. Mirroring those
    into your own item would be the same fact stored twice.

    ``present`` must be pure with respect to ``(entry state, width)``: given the
    same entry state and width it should produce an equivalent ``Presentation``.
    The entry's revision (bumped via ``entry.update()``) is what tells the view
    the result must be recomputed — so a body that draws ``depth`` or
    ``collapsed`` needs an ``update()`` when those change, exactly as for the
    item's own fields (:meth:`FlowModel.set_collapsed_many` folds that into its
    single reflow).

    .. warning::

       **Presentation runs on the event loop, not on a thread.** It is driven by
       a Textual worker, but a worker is an ``asyncio`` task on the *same* loop
       as input, painting and animation — so an ``async def`` body with no
       ``await`` in it (the usual shape, since rendering is pure CPU) holds the
       loop for its whole duration and the UI freezes. Measured: four 250 ms
       CPU-bound presents starved a 10 ms UI heartbeat down to 10 ticks where a
       free loop would manage ~121.

       Rendering a few Rich renderables is microseconds and fine. The trap is
       work that grows with content — re-rendering a whole large Markdown body
       on every streamed chunk, say — where the *per-call* cost looks small but
       the loop never gets a turn. Keep ``present`` cheap and bounded; do
       expensive or blocking work (network, disk, a big parse) before the item
       reaches the model, or with ``await`` so the loop can breathe. See
       ``docs/event-loop.md``.
    """

    async def present(self, entry: Entry[T], width: int) -> Presentation: ...
