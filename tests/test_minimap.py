from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal

from textual_flowview import EntryState, FlowMinimap, FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item.text))


class MiniApp(App):
    CSS = "FlowView { scrollbar-size-vertical: 0; }"

    def __init__(self, model) -> None:
        super().__init__()
        self._model = model

    def compose(self) -> ComposeResult:
        self.view: FlowView = FlowView(
            model=self._model, presenter=RowPresenter(), spacing=0, id="flow"
        )
        with Horizontal():
            yield self.view
            yield FlowMinimap(flow_view=self.view, id="mini")


def _colors_of(strip) -> list[str]:
    out = []
    for seg in strip:
        if seg.style is not None and seg.style.color is not None:
            out.append(seg.style.color.name)
    return out


@pytest.mark.asyncio
async def test_minimap_paints_error_state_red() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"r{i}")) for i in range(60)]
    entries[30].set_state(EntryState.ERROR)
    app = MiniApp(model)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        mini = app.query_one(FlowMinimap)
        h = mini.size.height
        # the minimap row whose bucket covers entry 30
        y = 30 * h // 60
        assert "red" in _colors_of(mini.render_line(y))
        # a row far from the error is not red
        assert "red" not in _colors_of(mini.render_line(0))


@pytest.mark.asyncio
async def test_minimap_highlights_the_viewport_window() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(200):
        model.append(Row(f"r{i}"))
    app = MiniApp(model)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        mini = app.query_one(FlowMinimap)
        # At the top, the first minimap row is inside the window (has a bg);
        # the last row (far below the fold) is not.
        top = list(mini.render_line(0))
        bottom = list(mini.render_line(mini.size.height - 1))
        assert any(seg.style and seg.style.bgcolor is not None for seg in top)
        assert all(seg.style is None or seg.style.bgcolor is None for seg in bottom)


@pytest.mark.asyncio
async def test_click_minimap_scrolls_the_view() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(200):
        model.append(Row(f"r{i}"))
    app = MiniApp(model)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view.scroll_offset.y == 0
        mini = app.query_one(FlowMinimap)
        await pilot.click(FlowMinimap, offset=(0, mini.size.height - 1))  # click bottom
        await pilot.pause()
        assert view.scroll_offset.y > 0  # jumped down
