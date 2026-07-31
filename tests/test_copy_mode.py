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

    def on_flow_view_highlighted(self, event: FlowView.Highlighted) -> None:
        self.highlights = getattr(self, "highlights", [])
        self.highlights.append(event.entry)


@pytest.mark.asyncio
async def test_copy_mode_starts_at_highlight_but_leaves_it_fixed() -> None:
    # Copy mode *starts* on the highlighted entry, but the highlight is then
    # FIXED: moving the text cursor never moves the highlight or fires
    # Highlighted (a consumer may mutate content in that handler).
    app = HighlightCopyApp(["msg a", "msg b", "msg c"])
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)

        v.highlight_entry(es[1])          # highlight msg b
        await pilot.pause()               # let that Highlighted flush
        app.highlights = []
        v.enter_copy_mode()               # starts on msg b (no Highlighted fired)
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is es[1]
        assert v.highlighted is es[1]

        await pilot.press("down")          # text cursor jumps entry -> msg c
        await pilot.press("j", "down")     # more cursor movement
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is not es[1]  # cursor moved off msg b
        assert v.highlighted is es[1]                  # highlight stayed put
        assert app.highlights == []                    # no Highlighted side effects


@pytest.mark.asyncio
async def test_copy_cursor_rides_content_changes() -> None:
    # A content change (insert/remove elsewhere) must not slide the cursor to a
    # stale absolute row: it stays on its entry.
    app = CopyApp([f"row-{i:02d}" for i in range(10)])
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        for _ in range(5):
            await pilot.press("j")            # cursor onto row-05
        target = v.entry_at_row(v._tc_row)
        assert target is not None and target.item.text == "row-05"

        app.model.insert_many(0, [Row(f"NEW-{i}") for i in range(3)])  # 3 rows above
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is target  # still on row-05

        next(iter(app.model)).remove()          # remove a row above
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is target

        app.model.clear()                        # clear -> leaves copy mode cleanly
        await pilot.pause()
        assert not v.copy_mode


@pytest.mark.asyncio
async def test_copy_cursor_entry_start_end() -> None:
    class TallPresenter:
        async def present(self, item: Row, width: int) -> Presentation:
            return Presentation(height=3, renderable=Text(f"{item.text}\n.\n."))

    model: FlowModel[Row] = FlowModel()
    for i in range(3):
        model.append(Row(f"E{i}"))

    class TallApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=TallPresenter(), spacing=0, estimated_height=3
            )
            yield self.flow

    app = TallApp()
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        for _ in range(4):
            await pilot.press("j")  # into entry E1, middle row
        entry = v.entry_at_row(v._tc_row)
        start = v._viewport.offset_of(entry)
        await pilot.press("left_square_bracket")   # entry top
        assert v._tc_row == start
        await pilot.press("right_square_bracket")  # entry bottom
        assert v._tc_row == start + 2              # 3-row entry
        assert v.entry_at_row(v._tc_row) is entry  # still the same entry


@pytest.mark.asyncio
async def test_copy_mode_search_selection() -> None:
    app = CopyApp(["find the fox here", "nothing", "the fox again",
                   "another fox line", "end"])
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        for _ in range(9):
            await pilot.press("l")           # to col 9 ("fox" start on row 0)
        await pilot.press("v", "l", "l")     # select "fox"
        await pilot.pause()
        assert app.screen.get_selected_text() == "fox"

        await pilot.press("asterisk")          # search the selection -> next "fox"
        assert v._copy_query == "fox"
        assert v.row_text(v._tc_row)[v._tc_col:v._tc_col + 3] == "fox"
        assert v._tc_row == 2

        await pilot.press("n")                 # next
        assert v._tc_row == 3
        await pilot.press("n")                 # wraps to the first
        assert v._tc_row == 0
        await pilot.press("N")                 # previous
        assert v._tc_row == 3


@pytest.mark.asyncio
async def test_copy_search_word_under_cursor() -> None:
    app = CopyApp(["apple banana", "cherry apple", "banana split"])
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        # cursor on "apple" (row 0, col 0), no selection -> search the word
        await pilot.press("asterisk")
        assert v._copy_query == "apple"
        assert v._tc_row == 1  # "cherry apple"
        assert v.row_text(1)[v._tc_col:v._tc_col + 5] == "apple"


@pytest.mark.asyncio
async def test_copy_yank_uses_clipboard_hook() -> None:
    # #7: a per-view clipboard sink receives the yank (instead of only OSC 52),
    # and its result is observable.
    sink: list[str] = []

    class HookApp(CopyApp):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=self.model, presenter=RowPresenter(), spacing=0,
                estimated_height=1, clipboard=lambda s: sink.append(s) or True,
            )
            yield self.flow

    app = HookApp(["hello world", "second"])
    async with app.run_test(size=(30, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        await pilot.press("v", "l", "l", "l", "l")  # "hello"
        assert v.copy_yank() == "hello"
        assert sink == ["hello"]
        assert app.copied == []                      # did NOT go through OSC 52
        assert v.write_clipboard("x") is True


@pytest.mark.asyncio
async def test_copy_mode_changed_message() -> None:
    # #8: enter/exit both post CopyModeChanged.
    events: list[bool] = []

    class ModeApp(CopyApp):
        def on_flow_view_copy_mode_changed(self, e: FlowView.CopyModeChanged) -> None:
            events.append(e.copy_mode)

    app = ModeApp(["a", "b"])
    async with app.run_test(size=(20, 4)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        v.enter_copy_mode()
        await pilot.pause()
        await pilot.press("escape")                  # library-side exit
        await pilot.pause()
        assert events == [True, False]


@pytest.mark.asyncio
async def test_copy_mode_excludes_gutter_from_selection() -> None:
    # #9: the gutter is decoration; copy mode addresses the *body* only, so a
    # yank never carries gutter glyphs, and row_text is body-only.
    class Gutter:
        def decorate(self, entry: object, width: int, height: int) -> Text:
            return Text(("**")[:width])

    sink: list[str] = []
    model: FlowModel[Row] = FlowModel()
    model.append(Row("newest reply body"))
    model.append(Row("second body line"))

    class GutterApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=RowPresenter(), spacing=0, estimated_height=1,
                decorator=Gutter(), gutter_width=2,
                clipboard=lambda s: sink.append(s) or True,
            )
            yield self.flow

    app = GutterApp()
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert v.row_text(0) == "newest reply body"   # body only, no '**'
        v.enter_copy_mode()
        await pilot.pause()
        assert v.row_text(0)[v._tc_col] == "n"         # starts at the body
        await pilot.press("v", "j", "l", "l", "l")     # multi-row selection
        assert v.copy_yank() == "newest reply body\nseco"  # no gutter on any row
