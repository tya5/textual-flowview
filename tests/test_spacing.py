from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str
    bg: str | None = None


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item.text), background=item.bg)


def _app(model, **kw) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter(), **kw)

    return FlowApp()


@pytest.mark.asyncio
async def test_spacing_default_is_one_row_gap() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(5):
        model.append(Row(f"r{i}"))  # each height 1
    app = _app(model)  # default spacing == 1
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # 5 rows of content + 4 one-row gaps between them
        assert view._viewport.total_height == 5 + 4


@pytest.mark.asyncio
async def test_spacing_zero_packs_rows() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(5):
        model.append(Row(f"r{i}"))
    app = _app(model, spacing=0)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._viewport.total_height == 5


@pytest.mark.asyncio
async def test_spacing_rows_render_blank_between_entries() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("first"))
    model.append(Row("second"))
    app = _app(model, spacing=2)
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view.render_line(0).text.strip() == "first"
        # rows 1 and 2 are the gap
        assert view.render_line(1).text.strip() == ""
        assert view.render_line(2).text.strip() == ""
        assert view.render_line(3).text.strip() == "second"


@pytest.mark.asyncio
async def test_full_row_background_paints_edge_to_edge() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("hi", bg="#2b2f37"))
    app = _app(model, spacing=0)
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        strip = view.render_line(0)
        # every cell (including trailing padding) carries the background colour
        bgs = {seg.style.bgcolor.name for seg in strip if seg.style and seg.style.bgcolor}
        assert bgs == {"#2b2f37"}
        # ...and it spans the whole content width
        assert strip.cell_length == view._content_width()


@pytest.mark.asyncio
async def test_no_background_leaves_row_transparent() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("plain"))
    app = _app(model, spacing=0)
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        strip = view.render_line(0)
        assert all(seg.style is None or seg.style.bgcolor is None for seg in strip)
