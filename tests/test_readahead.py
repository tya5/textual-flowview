from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    n: int


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        # Height 1 == the default estimate, so offsets stay uniform and
        # deterministic (presenting an item never reflows the others).
        return Presentation(height=1, renderable=Text(f"row-{item.n}"))


def _app(model, **kw) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter(), spacing=0, **kw)

    return FlowApp()


def _presented(view: FlowView, entry) -> bool:
    return view._layout.get(entry, view._body_width()) is not None


@pytest.mark.asyncio
async def test_read_ahead_prefetches_in_scroll_direction() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(i)) for i in range(100)]  # each 2 rows
    # viewport 10 rows -> 5 items visible; no overscan so the band is exact.
    app = _app(model, overscan=0, read_ahead=10)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to(y=40, animate=False)  # rows 40..50 -> items 40..49 visible
        await pilot.pause()
        await pilot.pause()

        # Read-ahead (10 rows) below the fold -> items 50..59 pre-presented.
        assert _presented(view, entries[50])  # just below the fold
        assert _presented(view, entries[59])  # end of the read-ahead band
        # Far below the read-ahead band: not presented yet.
        assert not _presented(view, entries[70])
        # Opposite direction (above) is not read ahead when scrolling down.
        assert not _presented(view, entries[30])


@pytest.mark.asyncio
async def test_read_ahead_zero_only_presents_overscan() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(i)) for i in range(100)]
    app = _app(model, overscan=0, read_ahead=0)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to(y=40, animate=False)  # items 40..49 visible
        await pilot.pause()
        await pilot.pause()
        # With no overscan and no read-ahead, the row just below the fold is
        # not pre-presented.
        assert not _presented(view, entries[50])
