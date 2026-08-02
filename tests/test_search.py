from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import EntryState, FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
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
