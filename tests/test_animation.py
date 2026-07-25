from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Job:
    text: str


class JobPresenter:
    def __init__(self) -> None:
        self.calls = 0

    async def present(self, item: Job, width: int) -> Presentation:
        self.calls += 1
        return Presentation(height=1, renderable=Text(item.text))


class CountingGutter:
    """Time-based decorator — no metadata; counts how often it is asked."""

    def __init__(self) -> None:
        self.calls = 0

    def decorate(self, entry, width, height):
        self.calls += 1
        return Text("*")


def _app(model, decorator, **kw) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(
                model=model, presenter=JobPresenter(), decorator=decorator,
                gutter_width=1, spacing=0, **kw,
            )

    return FlowApp()


@pytest.mark.asyncio
async def test_animation_fps_drives_gutter_without_app_timer() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("x"))
    gutter = CountingGutter()
    app = _app(model, gutter, animation_fps=20)
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        before = gutter.calls
        await asyncio.sleep(0.3)
        await pilot.pause()
        # FlowView re-derived the gutter several times on its own — no app
        # timer, no set_metadata.
        assert gutter.calls >= before + 3


@pytest.mark.asyncio
async def test_no_animation_fps_leaves_gutter_static() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("x"))
    gutter = CountingGutter()
    app = _app(model, gutter)  # animation_fps defaults to 0
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        before = gutter.calls
        await asyncio.sleep(0.3)
        await pilot.pause()
        # No self-driven repaints: the gutter isn't re-derived on a clock.
        assert gutter.calls == before


@pytest.mark.asyncio
async def test_animation_tick_does_not_repng_bodies() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("x"))
    gutter = CountingGutter()
    app = _app(model, gutter, animation_fps=20)
    async with app.run_test(size=(20, 6)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        entry = next(iter(model))
        cached = view._strip_cache.get(entry.id)
        assert cached is not None
        await asyncio.sleep(0.2)
        await pilot.pause()
        # animation ticks only clear the gutter cache; the body strip cache
        # (and thus the presentation) is left untouched — no re-present.
        assert view._strip_cache.get(entry.id) is cached


class Track:
    """Body item whose value is advanced by a viewport-gated animation."""

    def __init__(self) -> None:
        self.ticks = 0


class TrackPresenter:
    async def present(self, item, width) -> Presentation:
        return Presentation(height=1, renderable=Text(str(item.ticks)))


def _plain_app(model):
    class A(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=TrackPresenter(), spacing=0)

    return A()


@pytest.mark.asyncio
async def test_animate_entry_runs_only_while_visible() -> None:
    model: FlowModel[Track] = FlowModel()
    rows = [model.append(Track()) for _ in range(100)]
    app = _plain_app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)

        def tick(e):
            e.item.ticks += 1
            e.update()

        view.animate_entry(rows[0], 0.02, tick)   # visible
        view.animate_entry(rows[90], 0.02, tick)  # off-screen
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert rows[0].item.ticks > 0     # ran while visible
        assert rows[90].item.ticks == 0   # paused off-screen

        # scroll row 90 into view, row 0 out
        view.scroll_to(y=85, animate=False)
        await pilot.pause()
        frozen = rows[0].item.ticks
        await asyncio.sleep(0.2)
        await pilot.pause()
        assert rows[0].item.ticks == frozen   # paused after leaving
        assert rows[90].item.ticks > 0        # resumed after entering


@pytest.mark.asyncio
async def test_stop_and_handle_cancel_animation() -> None:
    model: FlowModel[Track] = FlowModel()
    row = model.append(Track())
    app = _plain_app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        handle = view.animate_entry(row, 0.02, lambda e: setattr(e.item, "ticks", e.item.ticks + 1))
        await asyncio.sleep(0.1)
        await pilot.pause()
        handle.stop()
        stopped = row.item.ticks
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert row.item.ticks == stopped   # no more ticks after stop


@pytest.mark.asyncio
async def test_removing_entry_drops_its_animation() -> None:
    model: FlowModel[Track] = FlowModel()
    row = model.append(Track())
    app = _plain_app(model)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.animate_entry(row, 0.02, lambda e: None)
        assert row.id in view._animations
        row.remove()
        await pilot.pause()
        assert row.id not in view._animations
