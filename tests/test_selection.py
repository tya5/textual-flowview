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
    async def present(self, item: Row, width: int) -> Presentation:
        return Presentation(height=2, renderable=Text(f"{item.text}\n{item.text}"))


class SelectApp(App):
    def __init__(self, model: FlowModel) -> None:
        super().__init__()
        self._model = model
        self.events: list[Entry | None] = []

    def compose(self) -> ComposeResult:
        yield FlowView(model=self._model, presenter=RowPresenter(), spacing=0)

    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        self.events.append(event.entry)


@pytest.mark.asyncio
async def test_click_selects_entry_under_cursor() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"row-{i}")) for i in range(10)]
    app = SelectApp(model)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        # each row is 2 tall; y=2..3 is the second entry
        await pilot.click(FlowView, offset=(2, 2))
        await pilot.pause()
        assert view.selected is entries[1]
        assert app.events[-1] is entries[1]


@pytest.mark.asyncio
async def test_clicking_empty_space_clears_selection() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"row-{i}")) for i in range(2)]  # content height 4
    app = SelectApp(model)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.select(entries[0])
        await pilot.pause()
        assert view.selected is entries[0]
        # click well below the 4 rows of content
        await pilot.click(FlowView, offset=(2, 15))
        await pilot.pause()
        assert view.selected is None
        assert app.events[-1] is None


@pytest.mark.asyncio
async def test_select_same_entry_is_noop() -> None:
    model: FlowModel[Row] = FlowModel()
    entry = model.append(Row("only"))
    app = SelectApp(model)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.select(entry)
        view.select(entry)
        await pilot.pause()
        assert app.events.count(entry) == 1


@pytest.mark.asyncio
async def test_removing_selected_entry_clears_selection() -> None:
    model: FlowModel[Row] = FlowModel()
    a = model.append(Row("a"))
    model.append(Row("b"))
    app = SelectApp(model)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.select(a)
        await pilot.pause()
        a.remove()
        await pilot.pause()
        assert view.selected is None
        assert app.events[-1] is None


@pytest.mark.asyncio
async def test_clear_drops_selection() -> None:
    model: FlowModel[Row] = FlowModel()
    a = model.append(Row("a"))
    app = SelectApp(model)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.select(a)
        await pilot.pause()
        model.clear()
        await pilot.pause()
        assert view.selected is None


@pytest.mark.asyncio
async def test_selecting_dead_entry_is_ignored() -> None:
    model: FlowModel[Row] = FlowModel()
    a = model.append(Row("a"))
    app = SelectApp(model)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        a.remove()
        view.select(a)  # dead entry
        await pilot.pause()
        assert view.selected is None
