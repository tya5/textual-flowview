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


def _app(model, **kw) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter(), spacing=0, **kw)

    return FlowApp()


def _text_rows(view: FlowView) -> list[int]:
    return [
        y
        for y in range(view.content_size.height)
        if view.render_line(y).text.strip()
    ]


@pytest.mark.asyncio
async def test_empty_state_shows_and_clears() -> None:
    model: FlowModel[Row] = FlowModel()
    app = _app(model, empty=Text("nothing here"))
    async with app.run_test(size=(30, 7)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        assert _text_rows(view)  # the empty message is drawn
        assert "nothing here" in "".join(
            view.render_line(y).text for y in range(view.content_size.height)
        )
        # adding an entry replaces the empty state with content
        model.append(Row("first"))
        await pilot.pause()
        joined = "".join(view.render_line(y).text for y in range(view.content_size.height))
        assert "first" in joined
        assert "nothing here" not in joined


@pytest.mark.asyncio
async def test_empty_state_vertical_alignment() -> None:
    model: FlowModel[Row] = FlowModel()
    for align in ("top", "bottom", "middle"):
        app = _app(model, empty=Text("x"), empty_align=align)
        async with app.run_test(size=(20, 7)) as pilot:
            await pilot.pause()
            await pilot.pause()
            view = app.query_one(FlowView)
            h = view.content_size.height
            rows = _text_rows(view)
            assert len(rows) == 1
            if align == "top":
                assert rows[0] == 0
            elif align == "bottom":
                assert rows[0] == h - 1
            else:
                assert rows[0] == h // 2


@pytest.mark.asyncio
async def test_empty_state_when_all_hidden() -> None:
    model: FlowModel[Row] = FlowModel()
    a = model.append(Row("a"))
    b = model.append(Row("b"))
    app = _app(model, empty=Text("all filtered out"))
    async with app.run_test(size=(30, 7)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        joined = "".join(view.render_line(y).text for y in range(view.content_size.height))
        assert "all filtered out" not in joined  # has entries
        a.hide()
        b.hide()
        await pilot.pause()
        joined = "".join(view.render_line(y).text for y in range(view.content_size.height))
        assert "all filtered out" in joined  # all hidden -> empty state


@pytest.mark.asyncio
async def test_no_empty_by_default() -> None:
    model: FlowModel[Row] = FlowModel()
    app = _app(model)  # no empty renderable
    async with app.run_test(size=(30, 7)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        assert _text_rows(view) == []  # blank
