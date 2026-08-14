from __future__ import annotations

import pytest
from rich.segment import Segment
from rich.text import Text
from textual.app import App, ComposeResult
from textual.strip import Strip

from textual_flowview import Entry, FlowModel, FlowView, Presentation


class CountingPresenter:
    """Full render of an item whose text is newline-joined lines. Counts calls
    so tests can prove patch_rows does not go through present()."""

    def __init__(self) -> None:
        self.calls = 0

    async def present(self, entry: Entry[str], width: int) -> Presentation:
        item = entry.item
        self.calls += 1
        lines = item.split("\n")
        return Presentation(height=len(lines), renderable=Text(item))


def _strip(text: str) -> Strip:
    return Strip([Segment(text)])


def _rows(view: FlowView) -> list[str]:
    return [view.row_text(y) for y in range(view.row_count)]


@pytest.mark.asyncio
async def test_patch_rows_splices_without_presenting() -> None:
    presenter = CountingPresenter()
    model: FlowModel[str] = FlowModel()
    entry = model.append("line0")

    class A(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(model=model, presenter=presenter, spacing=0,
                                 estimated_height=1)
            yield self.flow

    app = A()
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        base = presenter.calls
        acc = ["line0"]
        for i in range(1, 6):
            acc.append(f"line{i}")
            entry._item = "\n".join(acc)          # keep item in sync
            entry.patch_rows(len(acc) - 1, [_strip(acc[-1])])   # append the tail line
            await pilot.pause()
        assert presenter.calls == base            # no present() during patches
        assert _rows(v) == ["line0", "line1", "line2", "line3", "line4", "line5"]

        # a resize re-presents fully from the item (fallback path)
        await pilot.resize_terminal(20, 10)
        await pilot.pause()
        assert presenter.calls > base
        assert _rows(v) == ["line0", "line1", "line2", "line3", "line4", "line5"]


@pytest.mark.asyncio
async def test_patch_rows_replaces_the_growing_tail_line() -> None:
    # Streaming a paragraph: the last line grows (replaced), not just appended.
    presenter = CountingPresenter()
    model: FlowModel[str] = FlowModel()
    entry = model.append("hel")

    class A(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(model=model, presenter=presenter, spacing=0,
                                 estimated_height=1)
            yield self.flow

    app = A()
    async with app.run_test(size=(30, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        for text in ("hell", "hello", "hello wor", "hello world"):
            entry._item = text
            entry.patch_rows(0, [_strip(text)])   # single line, replace row 0
            await pilot.pause()
        assert _rows(v) == ["hello world"]


@pytest.mark.asyncio
async def test_presentation_strips_drawn_directly() -> None:
    # A presenter can return pre-rendered strips; FlowView draws them as-is.
    class StripPresenter:
        async def present(self, entry: Entry[str], width: int) -> Presentation:
            item = entry.item
            lines = item.split("\n")
            return Presentation(height=len(lines), strips=[_strip(s) for s in lines])

    model: FlowModel[str] = FlowModel()
    model.append("alpha\nbeta")

    class A(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(model=model, presenter=StripPresenter(), spacing=0,
                                 estimated_height=2)
            yield self.flow

    app = A()
    async with app.run_test(size=(30, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert _rows(app.flow) == ["alpha", "beta"]
