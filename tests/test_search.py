from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import Entry, EntryState, FlowModel, FlowView, Presentation


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
            yield FlowView(
                model=model, presenter=RowPresenter(), spacing=0, selectable=True
            )

    return FlowApp()


def _has(sub: str):
    return lambda e: sub in e.item.text


@pytest.mark.asyncio
async def test_find_returns_all_matches_in_order() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(t)) for t in ["apple", "banana", "apricot", "cherry", "avocado"]]
    app = _app(model)
    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        hits = view.find(_has("a"))
        assert hits == [es[0], es[1], es[2], es[4]]  # cherry excluded


@pytest.mark.asyncio
async def test_find_next_advances_and_wraps() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(t)) for t in ["a1", "b", "a2", "c", "a3"]]
    app = _app(model)
    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        pred = _has("a")
        assert view.find_next(pred, after=es[0]) is es[2]
        assert view.find_next(pred, after=es[2]) is es[4]
        # wraps back to the first match
        assert view.find_next(pred, after=es[4]) is es[0]
        # no wrap -> None past the last match
        assert view.find_next(pred, after=es[4], wrap=False) is None


@pytest.mark.asyncio
async def test_find_next_uses_selection_as_origin() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(t)) for t in ["a1", "a2", "a3"]]
    app = _app(model)
    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.set_current(es[0])
        await pilot.pause()
        assert view.find_next(_has("a")) is es[1]


@pytest.mark.asyncio
async def test_find_previous_advances_and_wraps() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(t)) for t in ["a1", "b", "a2", "c", "a3"]]
    app = _app(model)
    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        pred = _has("a")
        assert view.find_previous(pred, before=es[2]) is es[0]
        assert view.find_previous(pred, before=es[0]) is es[4]  # wraps
        assert view.find_previous(pred, before=es[0], wrap=False) is None


@pytest.mark.asyncio
async def test_find_can_match_state() -> None:
    model: FlowModel[Row] = FlowModel()
    a = model.append(Row("x"))
    b = model.append(Row("y"))
    b.set_state(EntryState.ERROR)
    app = _app(model)
    async with app.run_test() as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view.find(lambda e: e.state is EntryState.ERROR) == [b]
        assert a not in view.find(lambda e: e.state is EntryState.ERROR)


@pytest.mark.asyncio
async def test_reveal_unhides_and_scrolls() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"r{i}")) for i in range(60)]  # taller than viewport
    app = _app(model)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        target = es[50]
        target.hide()
        await pilot.pause()
        assert target not in view._viewport.entries
        view.reveal(target)
        await pilot.pause()
        assert not target.hidden
        assert target in view._viewport.entries
        # brought into the visible range
        assert target in view._viewport.visible_range().entries


@pytest.mark.asyncio
async def test_scroll_to_entry_instant_and_animated() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"r{i}")) for i in range(200)]  # 200 rows, height 1
    app = _app(model)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # instant (default) snaps to the target this frame
        view.scroll_to_entry(es[150])
        await pilot.pause()
        assert round(view.scroll_offset.y) == 150

        view.scroll_to_top()
        await pilot.pause()
        assert round(view.scroll_offset.y) == 0

        # animated jump converges to the same target (no crash mid-animation)
        view.scroll_to_entry(es[150], animate=True, duration=0.2)
        for _ in range(20):
            await pilot.pause(0.05)
        assert round(view.scroll_offset.y) == 150  # arrived


@pytest.mark.asyncio
async def test_scroll_to_entry_alignment() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"r{i}")) for i in range(100)]  # height 1 each
    app = _app(model)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        vh = view.content_size.height
        target = es[50]

        def row_in_view() -> int:
            return view._viewport.offset_of(target) - int(view.scroll_offset.y)

        view.scroll_to_top()
        await pilot.pause()
        view.scroll_to_entry(target, align="start")
        await pilot.pause()
        assert row_in_view() == 0

        view.scroll_to_top()
        await pilot.pause()
        view.scroll_to_entry(target, align="end")
        await pilot.pause()
        assert row_in_view() == vh - 1  # bottom edge

        view.scroll_to_top()
        await pilot.pause()
        view.scroll_to_entry(target, align="center")
        await pilot.pause()
        assert abs(row_in_view() - vh // 2) <= 1  # centred


@pytest.mark.asyncio
async def test_stop_scroll_animation_stays_put() -> None:
    model: FlowModel[Row] = FlowModel()
    es = [model.append(Row(f"r{i}")) for i in range(300)]
    app = _app(model)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to_entry(es[200], animate=True, duration=1.0)
        await pilot.pause(0.25)
        mid = round(view.scroll_offset.y)
        assert 0 < mid < 200  # mid-animation
        view.stop_scroll_animation()
        for _ in range(20):
            await pilot.pause(0.05)
        final = round(view.scroll_offset.y)
        assert abs(final - mid) <= 2   # stayed put, did NOT reach 200
        # no-op when nothing is animating
        view.stop_scroll_animation()
        await pilot.pause()
        assert round(view.scroll_offset.y) == final


class CountingPresenter:
    """Counts present() calls so a test can prove search doesn't render the
    whole model just to look at it."""

    def __init__(self) -> None:
        self.calls = 0

    async def present(self, entry: Entry[Row], width: int) -> Presentation:
        item = entry.item
        self.calls += 1
        return Presentation(height=1, renderable=Text(item.text))


def _text_app(n: int, needle_at_end: bool, **kw: object) -> App:
    model: FlowModel[Row] = FlowModel()
    for i in range(n):
        model.append(Row(f"line {i:04d} alpha"))
    if needle_at_end:
        model.append(Row("the NEEDLE is here"))

    class SearchApp(App):
        def compose(self) -> ComposeResult:
            self.presenter = CountingPresenter()
            self.flow = FlowView(
                model=model, presenter=self.presenter, spacing=0,
                estimated_height=1, cursor=True, **kw,  # type: ignore[arg-type]
            )
            yield self.flow

    return SearchApp()


@pytest.mark.asyncio
async def test_search_finds_text_in_entries_never_rendered() -> None:
    # With search_text, the whole model is searchable — an entry that has never
    # scrolled into view has no presentation, so without it search would only
    # see the placeholder and silently miss the match.
    app = _text_app(500, needle_at_end=True, search_text=lambda item: item.text)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert v.row_text(v.row_count - 1) == "Loading..."  # never presented
        assert await v.search("NEEDLE") is True
        assert "NEEDLE" in v.row_text(v._tc_row)             # cursor is on the match


@pytest.mark.asyncio
async def test_search_presents_only_the_matching_entry() -> None:
    app = _text_app(500, needle_at_end=True, search_text=lambda item: item.text)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        before = app.presenter.calls
        assert await v.search("NEEDLE") is True
        assert app.presenter.calls - before == 1        # just the hit, not 500
        # a miss renders nothing at all
        before = app.presenter.calls
        assert await v.search("NOTHERE") is False
        assert app.presenter.calls == before


@pytest.mark.asyncio
async def test_search_advances_and_wraps() -> None:
    app = _text_app(200, needle_at_end=False, search_text=lambda item: item.text)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert await v.search("alpha") is True
        first = v._tc_row
        assert await v.search_next() is True
        assert v._tc_row > first                        # moved forward
        assert await v.search_previous() is True
        assert v._tc_row == first                       # and back
        # a query only in the last entry is reachable by wrapping backwards
        assert await v.search("line 0199", forward=False) is True
        assert "line 0199" in v.row_text(v._tc_row)


@pytest.mark.asyncio
async def test_search_without_search_text_sees_only_rendered_rows() -> None:
    # The documented fallback: no search_text means search can only see what has
    # been presented.
    app = _text_app(500, needle_at_end=True)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.focus()
        assert await v.search("NEEDLE") is False    # off-screen, never rendered
        assert await v.search("line 0001") is True  # on screen, rendered
