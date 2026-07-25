from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import Anchor, FlowModel, FlowView, Presentation


@dataclass
class Note:
    text: str
    lines: int = 2


class NotePresenter:
    async def present(self, item: Note, width: int) -> Presentation:
        body = "\n".join(f"{item.text} ({width})" for _ in range(item.lines))
        return Presentation(height=item.lines, renderable=Text(body))


class BoomPresenter:
    async def present(self, item: Note, width: int) -> Presentation:
        raise RuntimeError("kaboom")


def _app(model: FlowModel, presenter, anchor=Anchor.CURRENT) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=presenter, anchor=anchor)

    return FlowApp()


@pytest.mark.asyncio
async def test_mounts_and_presents_visible_items() -> None:
    model: FlowModel[Note] = FlowModel()
    for i in range(50):
        model.append(Note(text=f"note-{i}"))
    app = _app(model, NotePresenter())
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        # Virtualization: only visible items are presented. Off-screen items
        # keep the estimated height (1), so the total is between the all-
        # estimated (50) and all-real (100) bounds, and NOT everything is
        # cached.
        assert 50 < view._viewport.total_height < 100
        assert 0 < len(view._layout) < 50


@pytest.mark.asyncio
async def test_streaming_update_reflows() -> None:
    model: FlowModel[Note] = FlowModel()
    entry = model.append(Note(text="stream", lines=1))
    app = _app(model, NotePresenter())
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        entry.item.lines = 6
        entry.update()
        await pilot.pause()
        assert view._layout.height(entry, view._content_width()) == 6


@pytest.mark.asyncio
async def test_rapid_streaming_converges_to_latest_revision() -> None:
    # Regression: a burst of update()s must converge to the final revision's
    # presentation (no dropped final present) and must not leak per-entry
    # bookkeeping.
    model: FlowModel[Note] = FlowModel()
    entry = model.append(Note(text="", lines=1))
    app = _app(model, NotePresenter())
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        for i in range(30):
            entry.item.text = f"chunk-{i}"
            entry.item.lines = 1 + (i % 3)
            entry.update()
        await pilot.pause()
        await pilot.pause()
        pres = view._layout.get(entry, view._body_width())
        assert pres is not None
        assert "chunk-29" in pres.renderable.plain  # final text won
        assert view._presenting == set()  # no leaked in-flight bookkeeping


@pytest.mark.asyncio
async def test_presenter_error_does_not_crash() -> None:
    model: FlowModel[Note] = FlowModel()
    entry = model.append(Note(text="bad"))
    app = _app(model, BoomPresenter())
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        presentation = view._layout.get(entry, view._content_width())
        assert presentation is not None  # replaced by an error presentation
        assert presentation.height == 3


@pytest.mark.asyncio
async def test_sticky_bottom_follows_new_items() -> None:
    model: FlowModel[Note] = FlowModel()
    for i in range(40):
        model.append(Note(text=f"n{i}"))
    app = _app(model, NotePresenter(), anchor=Anchor.STICKY_BOTTOM)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view.scroll_offset.y == view.max_scroll_y  # started at bottom
        model.append(Note(text="newest"))
        await pilot.pause()
        await pilot.pause()
        assert view.scroll_offset.y == view.max_scroll_y  # still glued to bottom


@pytest.mark.asyncio
async def test_clear_resets_scroll_and_layout() -> None:
    model: FlowModel[Note] = FlowModel()
    for i in range(30):
        model.append(Note(text=f"n{i}"))
    app = _app(model, NotePresenter())
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        model.clear()
        await pilot.pause()
        assert len(model) == 0
        assert len(view._layout) == 0
        assert view.scroll_offset.y == 0
