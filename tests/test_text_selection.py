from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.selection import SELECT_ALL, Selection

from textual_flowview import Entry, FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, entry: Entry[Row], width: int) -> Presentation:
        item = entry.item
        return Presentation(height=1, renderable=Text(item.text))


def _app(model) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter(), spacing=0)

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
async def test_select_all_spans_whole_list_not_just_viewport() -> None:
    # SELECT_ALL == Selection(None, None) — what Ctrl+A produces. It must cover
    # every content row, including rows below the visible viewport.
    model: FlowModel[Row] = FlowModel()
    for i in range(6):
        model.append(Row(f"line-{i}"))
    app = _app(model)
    async with app.run_test(size=(20, 10)) as pilot:  # all 6 fit / get presented
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        text, ending = view.get_selection(SELECT_ALL)
        assert text == "\n".join(f"line-{i}" for i in range(6))
        assert ending == "\n"
        # and the real screen-level select-all path agrees
        app.screen._select_all_in_widget(view)
        assert app.screen.get_selected_text() == text


@pytest.mark.asyncio
async def test_selection_open_ended_bounds() -> None:
    model: FlowModel[Row] = FlowModel()
    for i in range(4):
        model.append(Row(f"row{i}"))
    app = _app(model)
    async with app.run_test(size=(20, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # start=None -> from the top; end=None -> to the last row
        assert view.get_selection(Selection(None, Offset(2, 1)))[0] == "row0\nro"
        assert view.get_selection(Selection(Offset(2, 1), None))[0] == "w1\nrow2\nrow3"


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


@pytest.mark.asyncio
async def test_selection_highlight_aligns_with_double_width_glyphs() -> None:
    # Regression: the selection span is in character offsets but the highlight
    # crops in cells. With CJK / emoji (2 cells wide) the two diverged, so the
    # highlighted columns and copied text disagreed (and glyphs got clipped).
    from rich.cells import cell_len

    model: FlowModel[Row] = FlowModel()
    model.append(Row("あいうえおXYZ"))  # 5 full-width + 3 half-width
    app = _app(model)
    async with app.run_test(size=(30, 4)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # select the first 4 characters ("あいうえ" = 8 cells)
        app.screen.selections = {view: Selection(Offset(0, 0), Offset(4, 0))}
        await pilot.pause()
        strip = view.render_line(0)
        highlighted = "".join(
            ch
            for seg in strip
            for ch in seg.text
            if seg.style is not None and seg.style.bgcolor is not None
        )
        # the highlighted glyphs match the selected characters, not a cell-count
        # truncation of them
        assert highlighted == "あいうえ"
        assert cell_len(highlighted) == 8
        assert app.screen.get_selected_text() == "あいうえ"


@pytest.mark.asyncio
async def test_selection_highlight_ascii_unchanged() -> None:
    model: FlowModel[Row] = FlowModel()
    model.append(Row("0123456789"))
    app = _app(model)
    async with app.run_test(size=(30, 4)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        app.screen.selections = {view: Selection(Offset(2, 0), Offset(6, 0))}
        await pilot.pause()
        strip = view.render_line(0)
        highlighted = "".join(
            ch
            for seg in strip
            for ch in seg.text
            if seg.style is not None and seg.style.bgcolor is not None
        )
        assert highlighted == "2345"
