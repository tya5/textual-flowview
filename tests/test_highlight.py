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


def _row_bgcolors(view: FlowView, text: str) -> set[str]:
    for y in range(view.size.height):
        strip = view.render_line(y)
        if "".join(s.text for s in strip).strip() == text:
            return {str(s.style.bgcolor) for s in strip if s.style and s.style.bgcolor}
    raise AssertionError(f"row {text!r} not found")


def _app(css: str, **kw) -> tuple[App, FlowModel[Row]]:
    model: FlowModel[Row] = FlowModel()

    class FlowApp(App):
        CSS = css

        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter(), spacing=0, **kw)

    return FlowApp(), model


@pytest.mark.asyncio
async def test_undeclared_highlight_paints_nothing() -> None:
    # Issue #5: an undeclared flowview--highlight must not paint the inherited
    # background across the highlighted row.
    app, model = _app("FlowView { height: 1fr; }", selectable=True)
    model.append(Row("A"))
    model.append(Row("B"))
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.current_last()  # highlight on B
        await pilot.pause()
        assert _row_bgcolors(view, "B") == set()  # nothing painted
        assert _row_bgcolors(view, "A") == set()


@pytest.mark.asyncio
async def test_declared_highlight_wins_over_presentation_background() -> None:
    # Issue #6: a declared highlight background must override a row's own
    # Presentation.background, not be swallowed by it.
    css = """
    FlowView { height: 1fr; }
    FlowView > .flowview--highlight { background: #ff0000; }
    """
    app, model = _app(css, selectable=True)
    model.append(Row("plain"))
    model.append(Row("tinted", bg="#1e222a"))
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        for text in ("plain", "tinted"):
            view.set_current(view.entries[0] if text == "plain" else view.entries[1])
            await pilot.pause()
            bgs = _row_bgcolors(view, text)
            assert bgs == {"Color('#ff0000', ColorType.TRUECOLOR, "
                           "triplet=ColorTriplet(red=255, green=0, blue=0))"}, (text, bgs)


@pytest.mark.asyncio
async def test_declared_current_highlight_paints() -> None:
    # A declared highlight on the current entry shows.
    css = """
    FlowView { height: 1fr; }
    FlowView > .flowview--highlight { background: #0000ff; }
    """
    app, model = _app(css, selectable=True)
    model.append(Row("one"))
    model.append(Row("two"))
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.set_current(view.entries[1])
        await pilot.pause()
        assert _row_bgcolors(view, "two") == {"Color('#0000ff', ColorType.TRUECOLOR, "
                                              "triplet=ColorTriplet(red=0, green=0, blue=255))"}
        assert _row_bgcolors(view, "one") == set()  # not current, unstyled
