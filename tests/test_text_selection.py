from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.selection import Selection

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item.text))


def _app(model) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter())

    return FlowApp()


@pytest.mark.asyncio
async def test_get_selection_single_row() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("hello world"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        sel = Selection(Offset(0, 0), Offset(5, 0))
        text, ending = view.get_selection(sel)
        assert text == "hello"
        assert ending == "\n"


@pytest.mark.asyncio
async def test_get_selection_multi_row() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("hello world"))
    model.append(Row("second line"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # from col 6 of row 0, to col 6 of row 1
        sel = Selection(Offset(6, 0), Offset(6, 1))
        text, _ = view.get_selection(sel)
        assert text == "world\nsecond"


@pytest.mark.asyncio
async def test_selection_survives_scroll_via_content_coords() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(100):
        model.append(Row(f"row-number-{i}"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to(y=50, animate=False)
        await pilot.pause()
        # content row 50 is "row-number-50" regardless of scroll
        sel = Selection(Offset(0, 50), Offset(10, 50))
        text, _ = view.get_selection(sel)
        assert text == "row-number"


@pytest.mark.asyncio
async def test_render_line_stamps_offset_meta() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("abc"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        strip = view.render_line(0)
        offsets = [
            seg.style.meta.get("offset")
            for seg in strip
            if seg.style is not None and seg.style.meta
        ]
        # first content cell is stamped with content coordinate (0, 0)
        assert (0, 0) in offsets


@pytest.mark.asyncio
async def test_native_copy_path_uses_get_selection() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("copy this row"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # Emulate what a mouse drag produces, then trigger Ctrl+C's action.
        app.screen.selections = {view: Selection(Offset(0, 0), Offset(9, 0))}
        copied: list[str] = []
        app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
        app.screen.action_copy_text()
        assert copied == ["copy this"]
