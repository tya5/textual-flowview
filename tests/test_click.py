from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import Entry, FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, entry: Entry[Row], width: int) -> Presentation:
        item = entry.item
        return Presentation(height=1, renderable=Text(item.text))


class ClickApp(App):
    def __init__(self, model, **kw) -> None:
        super().__init__()
        self._model = model
        self._kw = kw
        self.clicks: list[tuple] = []

    def compose(self) -> ComposeResult:
        yield FlowView(model=self._model, presenter=RowPresenter(), spacing=0, **self._kw)

    def on_flow_view_clicked(self, event: FlowView.Clicked) -> None:
        self.clicks.append((event.entry, event.x, event.y))


@pytest.mark.asyncio
async def test_click_reports_entry_and_local_position() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"row-{i}")) for i in range(6)]
    app = ClickApp(model)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.click(FlowView, offset=(4, 2))  # 3rd row, column 4
        await pilot.pause()
        entry, x, y = app.clicks[-1]
        assert entry is es[2]
        assert x == 4  # no gutter -> body column == screen column
        assert y == 0  # single-row entry


@pytest.mark.asyncio
async def test_click_x_is_body_relative_with_gutter() -> None:
    from textual_flowview import StateDecorator

    model: FlowModel[Row] = FlowModel()
    model.append(Row("a"))
    app = ClickApp(model, decorator=StateDecorator(), gutter_width=3)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.click(FlowView, offset=(5, 0))
        await pilot.pause()
        _, x, _ = app.clicks[-1]
        assert x == 5 - 3  # gutter subtracted


@pytest.mark.asyncio
async def test_click_fires_every_time_even_same_entry() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("a"))
    app = ClickApp(model)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.click(FlowView, offset=(1, 0))
        await pilot.click(FlowView, offset=(2, 0))
        await pilot.pause()
        assert len(app.clicks) == 2  # Selected would dedupe; Clicked does not


@pytest.mark.asyncio
async def test_click_on_sticky_header_targets_the_header() -> None:
    model: FlowModel[Row] = FlowModel()
    header = model.append(Row("== HEADER =="))
    for i in range(20):
        model.append(Row(f"item-{i}"))
    app = ClickApp(model, sticky_header=lambda e: e.item.text.startswith("=="))
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to(y=6, animate=False)  # header scrolled above the fold
        await pilot.pause()
        await pilot.click(FlowView, offset=(2, 0))  # top row = pinned header
        await pilot.pause()
        entry, _, _ = app.clicks[-1]
        assert entry is header


@pytest.mark.asyncio
async def test_not_selectable_by_default() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"row-{i}")) for i in range(4)]
    app = ClickApp(model)  # default: selectable=False
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        await pilot.click(FlowView, offset=(2, 0))
        await pilot.pause()
        assert view.current is None  # click reported, but nothing selected
        assert app.clicks  # Clicked still fired
        view.set_current(es[1])  # programmatic select is a no-op too
        assert view.current is None


@pytest.mark.asyncio
async def test_selectable_true_selects_on_click() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"row-{i}")) for i in range(4)]
    app = ClickApp(model, selectable=True)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        await pilot.click(FlowView, offset=(2, 1))  # second row
        await pilot.pause()
        assert view.current is es[1]
        view.set_current(None)
        assert view.current is None
