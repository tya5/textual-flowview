from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

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
    def __init__(self, lines: list[str], **flow_kw: Any) -> None:
        super().__init__()
        self.model: FlowModel[Row] = FlowModel()
        for line in lines:
            self.model.append(Row(line))
        self.copied: list[str] = []
        self.highlights: list[Any] = []
        self._flow_kw = flow_kw

    def compose(self) -> ComposeResult:
        self.flow = FlowView(
            model=self.model, presenter=RowPresenter(), spacing=0,
            estimated_height=1, **self._flow_kw,
        )
        yield self.flow

    def copy_to_clipboard(self, text: str) -> None:  # capture yanks
        self.copied.append(text)

    def on_flow_view_highlighted(self, event: FlowView.Highlighted) -> None:
        self.highlights.append(event.entry)


@pytest.mark.asyncio
async def test_text_cursor_motions_and_yank() -> None:
    app = CopyApp(["alpha beta gamma", "second row", "third and last"], cursor=True)
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert v.cursor_visible  # shown on mount via cursor=True

        await pilot.press("l", "l", "l")           # col -> 3
        assert (v._tc_row, v._tc_col) == (0, 3)
        await pilot.press("j")                       # row -> 1 (text cursor)
        assert v._tc_row == 1
        await pilot.press("dollar_sign")             # end of "second row"
        assert v._tc_col == len(v.row_text(1)) - 1
        await pilot.press("0")
        assert v._tc_col == 0
        await pilot.press("G")                       # last row (doc bottom)
        assert v._tc_row == v.row_count - 1
        await pilot.press("g")                       # back to top (single key now)
        assert v._tc_row == 0

        # visual select "alpha" and yank
        await pilot.press("0")
        await pilot.press("v", "l", "l", "l", "l")   # cols 0..4 inclusive
        await pilot.press("y")
        assert app.copied[-1] == "alpha"
        assert v._tc_anchor is None                  # yank cleared the selection


@pytest.mark.asyncio
async def test_visual_line_yanks_whole_rows() -> None:
    app = CopyApp(["line one", "line two", "line three"], cursor=True)
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        await pilot.press("l", "l")          # move off column 0
        await pilot.press("V")               # line-visual from row 0
        await pilot.press("j")               # extend to row 1
        await pilot.press("y")
        assert app.copied[-1] == "line one\nline two"


@pytest.mark.asyncio
async def test_char_keys_bubble_while_cursor_hidden() -> None:
    # With the cursor hidden, char-level keys (h/l/w/y) bubble to the app so a
    # plain feed doesn't steal them. (j/k stay live — they navigate entries.)
    pressed: list[str] = []

    class BindApp(CopyApp):
        BINDINGS: ClassVar[list[BindingType]] = [
            ("l", "mark('l')", "l"),
            ("w", "mark('w')", "w"),
        ]

        def action_mark(self, key: str) -> None:
            pressed.append(key)

    app = BindApp(["a", "b"])  # cursor hidden (default)
    async with app.run_test(size=(20, 4)) as pilot:
        await pilot.pause()
        await pilot.pause()
        app.flow.focus()
        assert not app.flow.cursor_visible
        await pilot.press("l", "w")
        assert pressed == ["l", "w"]  # reached the app


@pytest.mark.asyncio
async def test_hidden_jk_navigate_entries_c_toggles_cursor() -> None:
    app = CopyApp([f"row {i}" for i in range(10)], selectable=True)
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)
        # hidden: j/k move the entry cursor (first move lands on the first entry)
        await pilot.press("j", "j")
        await pilot.pause()
        assert v.current is es[1]
        assert not v.cursor_visible
        # c shows the cursor; now j moves the text cursor by row
        await pilot.press("c")
        await pilot.pause()
        assert v.cursor_visible
        row = v._tc_row
        await pilot.press("l", "l")  # char move works now
        assert v._tc_col == 2
        await pilot.press("j")
        assert v._tc_row == row + 1  # fine row move, not entry jump
        # c again hides it and cancels any selection overlay
        await pilot.press("c")
        assert not v.cursor_visible
        assert v.screen.selections.get(v) is None


@pytest.mark.asyncio
async def test_show_cursor_does_not_move_current() -> None:
    # #11: revealing the cursor is visibility-only. The text cursor rides
    # `current` even when it was moved by set_current/click (not just keys), so
    # show_cursor never yanks `current` back to a stale row.
    app = CopyApp([f"row {i}" for i in range(9)], selectable=True)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)
        for idx in (8, 5, 2):  # incl. the last entry (the reported trigger)
            v.set_current(es[idx])
            await pilot.pause()
            before = v.current
            v.show_cursor()
            await pilot.pause()
            assert v.current is before is es[idx]  # unmoved
            assert v.entry_at_row(v._tc_row) is es[idx]  # cursor sits on it
            v.hide_cursor()
            await pilot.pause()


@pytest.mark.asyncio
async def test_cursor_entry_relative_move_while_hidden() -> None:
    # #11 (secondary): a relative move issued before showing the cursor takes
    # effect from `current`, not from a stale row 0.
    app = CopyApp([f"row {i}" for i in range(9)], selectable=True)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)
        v.set_current(es[5])
        await pilot.pause()
        v.cursor_entry(1)  # relative, cursor hidden
        await pilot.pause()
        assert v.current is es[6]


@pytest.mark.asyncio
async def test_cursor_constructor_shows_on_mount() -> None:
    app = CopyApp([f"row {i}" for i in range(20)], cursor=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert v.cursor_visible is True
        await pilot.press("j", "j")  # text cursor moves by row immediately
        assert v._tc_row == 2


@pytest.mark.asyncio
async def test_highlight_syncs_with_cursor() -> None:
    app = CopyApp([f"row {i}" for i in range(10)], selectable=True, cursor=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)
        app.highlights = []
        await pilot.press("j", "j")  # text cursor down 2 rows
        await pilot.pause()
        assert v.current is es[2]            # highlight followed the cursor
        assert app.highlights[-1] is es[2]   # Highlighted fired


@pytest.mark.asyncio
async def test_visual_freezes_highlight_then_follows_on_exit() -> None:
    app = CopyApp([f"row {i}" for i in range(10)], selectable=True, cursor=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        es = list(app.model)
        await pilot.press("j")               # cursor + highlight on row 1
        await pilot.pause()
        assert v.current is es[1]
        app.highlights = []
        await pilot.press("v")               # start visual (anchor at row 1)
        await pilot.press("j", "j")          # extend down to row 3
        await pilot.pause()
        assert v.current is es[1]            # highlight FROZEN at the anchor
        assert app.highlights == []          # no Highlighted mid-select
        await pilot.press("y")               # exit visual -> highlight follows cursor
        await pilot.pause()
        assert v.current is es[3]            # caught up to where the cursor ended
        assert app.highlights[-1] is es[3]


@pytest.mark.asyncio
async def test_escape_cancels_selection_only() -> None:
    app = CopyApp(["hello world", "second"], cursor=True)
    async with app.run_test(size=(30, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        await pilot.press("v", "l", "l")     # selecting
        assert v._tc_anchor is not None
        await pilot.press("escape")          # cancels the selection
        assert v._tc_anchor is None
        assert v.cursor_visible              # cursor itself stays shown


@pytest.mark.asyncio
async def test_cursor_scrolloff_centers_cursor() -> None:
    app = CopyApp([f"row {i}" for i in range(40)], cursor=True, cursor_scrolloff=999)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        for _ in range(15):
            await pilot.press("j")
        await pilot.pause()
        top = int(v.scroll_offset.y)
        assert v._tc_row - top == v.content_size.height // 2  # stays centred


@pytest.mark.asyncio
async def test_scroll_line_keeps_cursor_row() -> None:
    app = CopyApp([f"row {i}" for i in range(40)], cursor=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        for _ in range(4):
            await pilot.press("j")
        row = v._tc_row
        top = int(v.scroll_offset.y)
        await pilot.press("ctrl+e")  # scroll view down 1; cursor row unchanged
        await pilot.pause()
        assert int(v.scroll_offset.y) == top + 1
        assert v._tc_row == row
        await pilot.press("ctrl+y")
        await pilot.pause()
        assert int(v.scroll_offset.y) == top
        assert v._tc_row == row


@pytest.mark.asyncio
async def test_scroll_half_and_full_page_carry_cursor() -> None:
    app = CopyApp([f"row {i}" for i in range(60)], cursor=True)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        h = v.content_size.height
        screen_pos = v._tc_row - int(v.scroll_offset.y)
        await pilot.press("ctrl+d")
        await pilot.pause()
        assert int(v.scroll_offset.y) == h // 2
        assert v._tc_row - int(v.scroll_offset.y) == screen_pos
        await pilot.press("ctrl+f")
        await pilot.pause()
        assert int(v.scroll_offset.y) == h // 2 + (h - 2)
        await pilot.press("ctrl+u")
        await pilot.pause()
        assert int(v.scroll_offset.y) == (h - 2)
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert int(v.scroll_offset.y) == 0
        assert v._tc_row == 0


@pytest.mark.asyncio
async def test_cursor_rides_content_changes() -> None:
    app = CopyApp([f"row-{i:02d}" for i in range(10)], cursor=True)
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        for _ in range(5):
            await pilot.press("j")
        target = v.entry_at_row(v._tc_row)
        assert target is not None and target.item.text == "row-05"

        app.model.insert_many(0, [Row(f"NEW-{i}") for i in range(3)])
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is target  # still on row-05

        next(iter(app.model)).remove()
        await pilot.pause()
        assert v.entry_at_row(v._tc_row) is target

        app.model.clear()  # clears cleanly, cursor position resets
        await pilot.pause()
        assert v._tc_row == 0


@pytest.mark.asyncio
async def test_cursor_entry_start_end() -> None:
    class TallPresenter:
        async def present(self, item: Row, width: int) -> Presentation:
            return Presentation(height=3, renderable=Text(f"{item.text}\n.\n."))

    model: FlowModel[Row] = FlowModel()
    for i in range(3):
        model.append(Row(f"E{i}"))

    class TallApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=TallPresenter(), spacing=0,
                estimated_height=3, cursor=True,
            )
            yield self.flow

    app = TallApp()
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        for _ in range(4):
            await pilot.press("j")  # into entry E1, middle row
        entry = v.entry_at_row(v._tc_row)
        assert entry is not None
        start = v._viewport.offset_of(entry)
        assert start is not None
        await pilot.press("left_square_bracket")   # entry top
        assert v._tc_row == start
        await pilot.press("right_square_bracket")  # entry bottom
        assert v._tc_row == start + 2
        assert v.entry_at_row(v._tc_row) is entry


@pytest.mark.asyncio
async def test_search_selection() -> None:
    app = CopyApp(["find the fox here", "nothing", "the fox again",
                   "another fox line", "end"], cursor=True)
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        for _ in range(9):
            await pilot.press("l")           # to col 9 ("fox" start on row 0)
        await pilot.press("v", "l", "l")     # select "fox"
        await pilot.pause()
        assert app.screen.get_selected_text() == "fox"

        await pilot.press("asterisk")          # search the selection -> next "fox"
        assert v._search_query == "fox"
        assert v.row_text(v._tc_row)[v._tc_col:v._tc_col + 3] == "fox"
        assert v._tc_row == 2

        await pilot.press("n")
        assert v._tc_row == 3
        await pilot.press("n")                 # wraps
        assert v._tc_row == 0
        await pilot.press("N")
        assert v._tc_row == 3


@pytest.mark.asyncio
async def test_search_word_under_cursor() -> None:
    app = CopyApp(["apple banana", "cherry apple", "banana split"], cursor=True)
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        await pilot.press("asterisk")          # no selection -> word under cursor
        assert v._search_query == "apple"
        assert v._tc_row == 1
        assert v.row_text(1)[v._tc_col:v._tc_col + 5] == "apple"


@pytest.mark.asyncio
async def test_yank_uses_clipboard_hook() -> None:
    sink: list[str] = []
    app = CopyApp(["hello world", "second"], cursor=True,
                  clipboard=lambda s: sink.append(s) or True)
    async with app.run_test(size=(30, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        await pilot.press("v", "l", "l", "l", "l")  # "hello"
        assert v.yank() == "hello"
        assert sink == ["hello"]
        assert app.copied == []                      # did NOT go through OSC 52
        assert v.write_clipboard("x") is True


@pytest.mark.asyncio
async def test_selection_excludes_gutter() -> None:
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
                decorator=Gutter(), gutter_width=2, cursor=True,
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
        assert v.row_text(0)[v._tc_col] == "n"         # starts at the body
        await pilot.press("v", "j", "l", "l", "l")     # multi-row selection
        assert v.yank() == "newest reply body\nseco"   # no gutter on any row


@pytest.mark.asyncio
async def test_revealing_the_cursor_syncs_it_to_the_highlight() -> None:
    """Showing the cursor must not move the highlight.

    0.13 states the invariant in its own commit message — "The text cursor is
    now SYNCED with the entry highlight" — but the sync only ran one way,
    cursor -> highlight. So revealing the cursor dragged the highlight to
    wherever ``_tc_row`` was left, which after any move that was not a key
    press is the old position.

    The last entry is the case that showed it, because that is where the
    highlight sits after content arrives, and it is where a reader is when
    they press the key that reveals the cursor.
    """
    app = CopyApp([f"entry {i}" for i in range(9)])
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert not v.cursor_visible, "setup: this test starts with the cursor hidden"

        entries = list(v.entries)
        v.set_current(entries[-1])
        await pilot.pause()
        assert v.current is entries[-1], "setup: the highlight is on the last entry"

        v.show_cursor()
        await pilot.pause()

        assert v.current is entries[-1], (
            "revealing the cursor moved the highlight off the entry it was on"
        )


@pytest.mark.asyncio
async def test_revealing_the_cursor_leaves_a_keyboard_position_alone() -> None:
    """The keys already keep the two in step, and that must not regress.

    They update the cursor row even while it is hidden, so a reader who moved
    with j/k finds the cursor exactly where they left it. The sync added for
    the case above must not overwrite that.
    """
    app = CopyApp([f"entry {i}" for i in range(9)])
    async with app.run_test(size=(40, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()

        await pilot.press("k", "k")
        moved_to = v.current
        await pilot.pause()

        v.show_cursor()
        await pilot.pause()

        assert v.current is moved_to, (
            "revealing the cursor moved the highlight away from where the keys "
            "had put it"
        )
