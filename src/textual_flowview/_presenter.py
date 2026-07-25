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
    declare it ``async def``); presentation runs inside a Textual worker so a
    slow presenter never blocks the UI.

    ``present`` must be pure with respect to ``(item, width)``: given the same
    item state and width it should produce an equivalent ``Presentation``.
    The item's revision (bumped via ``entry.update()``) is what tells the view
    that the item state changed and the result must be recomputed.
    """

    async def present(self, item: T_contra, width: int) -> Presentation: ...
