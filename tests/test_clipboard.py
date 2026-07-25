from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str
    panel: bool = False


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        if item.panel:
            return Presentation(height=3, renderable=Panel(Text(item.text), width=width))
        return Presentation(height=1, renderable=Text(item.text))


def _app(model) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter())

    return FlowApp()


@pytest.mark.asyncio
async def test_entry_text_returns_plain_text() -> None:
    model: FlowModel[Row] = FlowModel()
    e = model.append(Row("hello world"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view.entry_text(e) == "hello world"


@pytest.mark.asyncio
async def test_entry_text_strips_styles_and_panel_chrome() -> None:
    model: FlowModel[Row] = FlowModel()
    e = model.append(Row("boxed", panel=True))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        text = view.entry_text(e)
        assert "boxed" in text
        assert "\x1b[" not in text  # no ANSI escapes


@pytest.mark.asyncio
async def test_entry_text_empty_when_not_presented() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"r{i}")) for i in range(300)]
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # An entry far below the visible + read-ahead band isn't presented yet.
        assert view.entry_text(entries[290]) == ""


@pytest.mark.asyncio
async def test_copy_entry_uses_clipboard_and_returns_text() -> None:
    model: FlowModel[Row] = FlowModel()
    e = model.append(Row("copy me"))
    app = _app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        copied: list[str] = []
        app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
        result = view.copy_entry(e)
        assert result == "copy me"
        assert copied == ["copy me"]
