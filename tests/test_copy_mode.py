from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import BindingType

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item.text))


class CopyApp(App):
    def __init__(self, lines: list[str]) -> None:
        super().__init__()
        self.model: FlowModel[Row] = FlowModel()
        for line in lines:
            self.model.append(Row(line))
        self.copied: list[str] = []

    def compose(self) -> ComposeResult:
        self.flow = FlowView(
            model=self.model, presenter=RowPresenter(), spacing=0, estimated_height=1
        )
        yield self.flow

    def copy_to_clipboard(self, text: str) -> None:  # capture yanks
        self.copied.append(text)


@pytest.mark.asyncio
async def test_copy_mode_motions_and_yank() -> None:
    app = CopyApp(["alpha beta gamma", "second row", "third and last"])
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()

        # keys do nothing until copy mode is entered (they bubble)
        await pilot.press("l", "l")
        assert (v._tc_row, v._tc_col) == (0, 0)
        assert not v.copy_mode

        v.enter_copy_mode()
        await pilot.pause()
        assert v.copy_mode
        await pilot.press("l", "l", "l")           # col -> 3
        assert (v._tc_row, v._tc_col) == (0, 3)
        await pilot.press("j")                       # row -> 1
        assert v._tc_row == 1
        await pilot.press("dollar_sign")             # end of "second row" (len 10)
        assert v._tc_col == len(v.row_text(1)) - 1
        await pilot.press("0")
        assert v._tc_col == 0
        await pilot.press("G")                       # last row
        assert v._tc_row == v.row_count - 1
        await pilot.press("g", "g")                  # back to top (two-key)
        assert v._tc_row == 0

        # visual select "alpha" and yank
        await pilot.press("0")
        await pilot.press("v", "l", "l", "l", "l")   # cols 0..4 inclusive
        await pilot.press("y")
        assert app.copied[-1] == "alpha"
        # yank clears the visual selection but stays in copy mode
        assert v.copy_mode and v._tc_anchor is None

        await pilot.press("escape")
        assert not v.copy_mode
        assert app.screen.selections.get(v) is None


@pytest.mark.asyncio
async def test_copy_mode_visual_line_yanks_whole_rows() -> None:
    app = CopyApp(["line one", "line two", "line three"])
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        await pilot.press("l", "l")          # move off column 0
        await pilot.press("V")               # line-visual from row 0
        await pilot.press("j")               # extend to row 1
        await pilot.press("y")
        assert app.copied[-1] == "line one\nline two"


@pytest.mark.asyncio
async def test_copy_mode_keys_bubble_when_inactive() -> None:
    # A consumer that binds j/k for its own use isn't shadowed while copy mode
    # is off.
    pressed: list[str] = []

    class BindApp(CopyApp):
        BINDINGS: ClassVar[list[BindingType]] = [
            ("j", "mark('j')", "j"),
            ("k", "mark('k')", "k"),
        ]

        def action_mark(self, key: str) -> None:
            pressed.append(key)

    app = BindApp(["a", "b"])
    async with app.run_test(size=(20, 4)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app.flow.focus()
        await pilot.press("j", "k")
        assert pressed == ["j", "k"]  # reached the app, not consumed by FlowView


@pytest.mark.asyncio
async def test_copy_scrolloff_centers_cursor() -> None:
    app = CopyApp([f"row {i}" for i in range(40)])
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.copy_scrolloff = 999  # pin to centre
        v.enter_copy_mode()
        await pilot.pause()
        for _ in range(15):
            await pilot.press("j")
        await pilot.pause()
        top = int(v.scroll_offset.y)
        pos = v._tc_row - top
        assert pos == v.content_size.height // 2  # cursor stays centred


@pytest.mark.asyncio
async def test_copy_scroll_line_keeps_cursor_row() -> None:
    app = CopyApp([f"row {i}" for i in range(40)])
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()  # scrolloff 0
        await pilot.pause()
        for _ in range(4):
            await pilot.press("j")  # cursor to row 4, still on screen
        row = v._tc_row
        top = int(v.scroll_offset.y)
        await pilot.press("ctrl+e")  # scroll view down 1; cursor row unchanged
        await pilot.pause()
        assert int(v.scroll_offset.y) == top + 1
        assert v._tc_row == row
        await pilot.press("ctrl+y")  # scroll back up
        await pilot.pause()
        assert int(v.scroll_offset.y) == top
        assert v._tc_row == row


class HighlightCopyApp(CopyApp):
    def compose(self) -> ComposeResult:
        self.flow = FlowView(
            model=self.model, presenter=RowPresenter(), spacing=1,
            estimated_height=1, highlight=True,
        )
        yield self.flow


@pytest.mark.asyncio
async def test_copy_mode_unifies_with_entry_highlight() -> None:
    # highlight=True + copy mode: one cursor. Entering copy mode starts on the
    # highlighted entry; ↑/↓ jump by entry and the current entry (and the
    # Highlighted state) follows the text cursor.
    app = HighlightCopyApp(["msg a", "msg b", "msg c"])
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)

        v.highlight_entry(es[1])          # highlight msg b
        v.enter_copy_mode()               # starts on msg b
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is es[1]
        assert v.highlighted is es[1]

        await pilot.press("down")          # entry-jump -> msg c
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is es[2]
        assert v.highlighted is es[2]

        await pilot.press("up")            # entry-jump back -> msg b
        await pilot.pause()
        assert v.highlighted is es[1]
