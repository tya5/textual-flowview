from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item.text))


class InfiniteApp(App):
    def __init__(self, model, **kw) -> None:
        super().__init__()
        self._model = model
        self._kw = kw
        self.tops = 0
        self.bottoms = 0

    def compose(self) -> ComposeResult:
        yield FlowView(
            model=self._model, presenter=RowPresenter(), spacing=0,
            estimated_height=1, **self._kw,
        )

    def on_flow_view_reached_top(self, event: FlowView.ReachedTop) -> None:
        self.tops += 1

    def on_flow_view_reached_bottom(self, event: FlowView.ReachedBottom) -> None:
        self.bottoms += 1


def _true_top(view: FlowView):
    loc = view._viewport.locate(int(view.scroll_offset.y))
    return view._viewport.entries[loc[0]] if loc else None


@pytest.mark.asyncio
async def test_reached_bottom_and_top_fire_and_rearm() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(60):
        model.append(Row(f"row-{i:03d}"))
    app = InfiniteApp(model)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # starts at the top -> ReachedTop fired on the first layout
        assert app.tops >= 1
        base_top = app.tops
        view.scroll_to_bottom()
        await pilot.pause()
        assert app.bottoms >= 1
        # sitting at the bottom does not re-fire
        base_bottom = app.bottoms
        view.scroll_relative(y=1)
        await pilot.pause()
        assert app.bottoms == base_bottom
        # leaving and returning to the top re-arms and fires again
        view.scroll_to_bottom()
        await pilot.pause()
        view.scroll_to_top()
        await pilot.pause()
        assert app.tops > base_top


@pytest.mark.asyncio
async def test_reach_threshold_fires_before_the_very_edge() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(60):
        model.append(Row(f"row-{i:03d}"))
    app = InfiniteApp(model, reach_threshold=5)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        base = app.bottoms
        # scroll to within 5 rows of the bottom, but not to it
        view.scroll_to(y=view.max_scroll_y - 3, animate=False)
        await pilot.pause()
        assert app.bottoms > base


@pytest.mark.asyncio
async def test_insert_many_prepend_preserves_scroll_position() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(60):
        model.append(Row(f"row-{i:03d}"))
    app = InfiniteApp(model)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to_entry(list(model)[40])
        await pilot.pause()
        top_before = _true_top(view)
        y_before = int(view.scroll_offset.y)
        # prepend a page of 8 older items as one batch
        new = model.insert_many(0, [Row(f"OLD-{i}") for i in range(8)])
        await pilot.pause()
        await pilot.pause()
        assert len(new) == 8
        # the row the user was looking at is still the top row, shifted down by 8
        assert _true_top(view) is top_before
        assert int(view.scroll_offset.y) == y_before + 8


@pytest.mark.asyncio
async def test_insert_many_at_top_edge_preserves_position() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(30):
        model.append(Row(f"row-{i:03d}"))
    app = InfiniteApp(model)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to_top()
        await pilot.pause()
        first = _true_top(view)
        model.insert_many(0, [Row(f"OLD-{i}") for i in range(5)])
        await pilot.pause()
        await pilot.pause()
        # still looking at the same first row, now 5 rows down from the new top
        assert _true_top(view) is first
        assert int(view.scroll_offset.y) == 5


@pytest.mark.asyncio
async def test_extend_appends_batch() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("a"))
    added = model.extend([Row("b"), Row("c")])
    assert [e.item.text for e in model] == ["a", "b", "c"]
    assert [e.item.text for e in added] == ["b", "c"]
