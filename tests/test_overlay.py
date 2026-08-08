from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from rich.console import RenderableType
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


class P:
    async def present(self, item: str, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item))


class OverlayApp(App):
    def __init__(self, n: int = 30) -> None:
        super().__init__()
        self.model: FlowModel[str] = FlowModel()
        for i in range(n):
            self.model.append(f"content {i}")
        self.finished = 0

    def compose(self) -> ComposeResult:
        self.flow = FlowView(model=self.model, presenter=P(), spacing=0,
                             estimated_height=1)
        yield self.flow

    def on_flow_view_overlay_finished(self, event: FlowView.OverlayFinished) -> None:
        self.finished += 1


def _viewport_text(flow: FlowView) -> list[str]:
    return ["".join(s.text for s in flow.render_line(y)) for y in range(flow.size.height)]


@pytest.mark.asyncio
async def test_overlay_property_paints_and_clears_non_destructively() -> None:
    app = OverlayApp()
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.scroll_to(y=12, animate=False)
        await pilot.pause()
        scroll_before = int(v.scroll_offset.y)

        v.overlay = Text("\n".join("XXXX" for _ in range(v.size.height)))
        await pilot.pause()
        assert v.overlay_active
        rows = _viewport_text(v)
        assert all("XXXX" in r for r in rows)          # fills the viewport
        assert not any("content" in r for r in rows)    # content hidden

        v.overlay = None  # clear -> non-destructive restore
        await pilot.pause()
        assert not v.overlay_active
        assert int(v.scroll_offset.y) == scroll_before  # scroll untouched
        assert any("content" in r for r in _viewport_text(v))


def _frames(n: int) -> Callable[[int, int, list[str]], Iterator[RenderableType]]:
    def factory(w: int, h: int, covered: list[str]) -> Iterator[RenderableType]:
        for i in range(n):
            yield Text("\n".join(f"frame{i}" for _ in range(h)))
    return factory


@pytest.mark.asyncio
async def test_play_overlay_hands_the_covered_lines_to_the_factory() -> None:
    # The overlay passes the text it is covering (the current viewport) to the
    # frame factory, so an effect can act on the screen without the consumer
    # recomputing it from the scroll offset.
    app = OverlayApp(60)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.scroll_to(y=12, animate=False)
        await pilot.pause()
        captured: list[list[str]] = []

        def factory(w: int, h: int, covered: list[str]) -> Iterator[RenderableType]:
            captured.append(covered)
            yield Text("\n".join("." * w for _ in range(h)))

        v.play_overlay(factory, fps=120, loop=False)
        await pilot.pause()
        assert captured, "factory was called"
        covered = captured[0]
        assert len(covered) == v.size.height          # one string per covered row
        assert any("content 1" in line for line in covered)  # the scrolled-to screen


@pytest.mark.asyncio
async def test_covered_lines_include_the_gutter() -> None:
    # The overlay paints the FULL content width (gutters included), so the
    # covered text must match — not the body-only view of row_text (whose
    # offsets are body-relative for selection).
    class Gutter:
        def decorate(self, entry: object, width: int, height: int) -> Text:
            return Text("**"[:width])

    model: FlowModel[str] = FlowModel()
    for i in range(20):
        model.append(f"content {i}")

    class GutterApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=P(), spacing=0, estimated_height=1,
                decorator=Gutter(), gutter_width=2,
            )
            yield self.flow

    app = GutterApp()
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        captured: list[list[str]] = []

        def factory(w: int, h: int, covered: list[str]) -> Iterator[RenderableType]:
            captured.append(covered)
            yield Text("\n".join("." * w for _ in range(h)))

        v.play_overlay(factory, fps=120, loop=False)
        await pilot.pause()
        covered = captured[0]
        assert covered[0].startswith("**")        # gutter glyphs are included
        assert "content 0" in covered[0]          # ...along with the body
        assert v.row_text(0) == "content 0"       # row_text stays body-only


@pytest.mark.asyncio
async def test_play_overlay_oneshot_finishes_and_posts_message() -> None:
    app = OverlayApp()
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.play_overlay(_frames(6), fps=60, loop=False)
        assert v.overlay_active
        assert "frame0" in _viewport_text(v)[0]  # frame 0 painted immediately
        for _ in range(40):                       # run to natural completion
            await pilot.pause()
            if not v.overlay_active:
                break
        assert not v.overlay_active           # oneshot cleared itself
        assert app.finished == 1              # OverlayFinished posted once
        assert any("content" in r for r in _viewport_text(v))  # content revealed


@pytest.mark.asyncio
async def test_play_overlay_loop_repeats_until_stopped() -> None:
    app = OverlayApp()
    async with app.run_test(size=(30, 8)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.play_overlay(_frames(2), fps=120, loop=True)
        for _ in range(20):  # would exhaust many times over
            await pilot.pause()
        assert v.overlay_active     # still running (looped)
        assert app.finished == 0    # loop never "finishes"
        v.stop_overlay()
        await pilot.pause()
        assert not v.overlay_active
        assert app.finished == 0    # explicit stop posts no OverlayFinished
