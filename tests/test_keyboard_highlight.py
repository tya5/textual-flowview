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


class HighlightApp(App):
    def __init__(self, model, **kw) -> None:
        super().__init__()
        self._model = model
        self._kw = kw
        self.highlights: list = []
        self.activations: list = []

    def compose(self) -> ComposeResult:
        yield FlowView(
            model=self._model, presenter=RowPresenter(), spacing=0,
            estimated_height=1, **self._kw,
        )

    def on_flow_view_highlighted(self, event: FlowView.Highlighted) -> None:
        self.highlights.append(event.entry)

    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        self.activations.append(event.entry)


def _model(n: int = 50) -> FlowModel[Row]:
    m: FlowModel[Row] = FlowModel()
    for i in range(n):
        m.append(Row(f"row-{i:02d}"))
    return m


@pytest.mark.asyncio
async def test_highlight_moves_by_item_and_follows() -> None:
    model = _model()
    entries = list(model)
    app = HighlightApp(model, selectable=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.focus()
        await pilot.pause()
        await pilot.press("down", "down", "down")
        await pilot.pause()
        assert view.current is entries[2]
        assert app.highlights[-1] is entries[2]
        # many downs -> highlight moves one item each and the view auto-scrolls
        for _ in range(20):
            await pilot.press("down")
        await pilot.pause()
        assert view.current is entries[22]
        assert int(view.scroll_offset.y) > 0  # followed the highlight off-screen


@pytest.mark.asyncio
async def test_highlight_home_end_and_clamp() -> None:
    model = _model(20)
    entries = list(model)
    app = HighlightApp(model, selectable=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.focus()
        await pilot.pause()
        await pilot.press("end")
        await pilot.pause()
        assert view.current is entries[-1]
        await pilot.press("down")  # clamp at the end
        await pilot.pause()
        assert view.current is entries[-1]
        await pilot.press("home")
        await pilot.pause()
        assert view.current is entries[0]
        await pilot.press("up")  # clamp at the start
        await pilot.pause()
        assert view.current is entries[0]


@pytest.mark.asyncio
async def test_enter_activates_highlight() -> None:
    model = _model(10)
    entries = list(model)
    app = HighlightApp(model, selectable=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.focus()
        await pilot.pause()
        await pilot.press("down", "down")
        await pilot.press("enter")
        await pilot.pause()
        assert app.activations[-1] is entries[1]
        # space activates too
        await pilot.press("space")
        await pilot.pause()
        assert app.activations[-1] is entries[1]


@pytest.mark.asyncio
async def test_highlight_disabled_by_default_arrows_scroll() -> None:
    model = _model()
    app = HighlightApp(model)  # highlight defaults to False
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.focus()
        await pilot.pause()
        assert view.current is None
        await pilot.press("down", "down", "down")
        await pilot.pause()
        # arrows scrolled the viewport; no highlight was created
        assert view.current is None
        assert int(view.scroll_offset.y) > 0
        # enter is not consumed -> no activation
        await pilot.press("enter")
        await pilot.pause()
        assert app.activations == []


@pytest.mark.asyncio
async def test_highlight_skips_hidden_and_clears_on_remove() -> None:
    model = _model(10)
    entries = list(model)
    app = HighlightApp(model, selectable=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.set_current(entries[3])
        await pilot.pause()
        assert view.current is entries[3]
        # hiding the highlight entry clears the highlight
        entries[3].hide()
        await pilot.pause()
        assert view.current is None
        # highlight_entry a hidden entry is a no-op
        view.set_current(entries[3])
        assert view.current is None
        # removing the highlight entry clears it
        view.set_current(entries[5])
        assert view.current is entries[5]
        entries[5].remove()
        await pilot.pause()
        assert view.current is None
