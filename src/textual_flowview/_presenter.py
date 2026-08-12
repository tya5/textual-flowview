from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable

from ._presentation import Presentation

__all__ = ["FlowPresenter"]

T_contra = TypeVar("T_contra", contravariant=True)


@runtime_checkable
class FlowPresenter(Protocol[T_contra]):
    """Converts a domain item into a :class:`Presentation`.

    The presenter is the *only* component that knows the concrete item type.
    Implementations are always ``async`` (a synchronous body is fine — just
    declare it ``async def``).

    ``present`` must be pure with respect to ``(item, width)``: given the same
    item state and width it should produce an equivalent ``Presentation``.
    The item's revision (bumped via ``entry.update()``) is what tells the view
    that the item state changed and the result must be recomputed.

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

    async def present(self, item: T_contra, width: int) -> Presentation: ...
