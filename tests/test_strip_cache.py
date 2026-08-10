from __future__ import annotations

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import Entry, FlowModel, FlowView, Presentation


class TallPresenter:
    async def present(self, item: str, width: int) -> Presentation:
        return Presentation(
            height=10,
            renderable=Text("\n".join(f"{item} row {i}" for i in range(10))),
        )


class FeedApp(App):
    def __init__(self, n: int = 200, **kw: object) -> None:
        super().__init__()
        self.model: FlowModel[str] = FlowModel()
        for i in range(n):
            self.model.append(f"e{i:03d}")
        self._kw = kw

    def compose(self) -> ComposeResult:
        self.flow = FlowView(
            model=self.model, presenter=TallPresenter(), spacing=0,
            estimated_height=10, **self._kw,  # type: ignore[arg-type]
        )
        yield self.flow


@pytest.mark.asyncio
async def test_strip_cache_is_bounded_by_the_band_not_entries_visited() -> None:
    # Strips are a per-frame optimisation, so off-band entries keep none: memory
    # tracks what's on screen, not everything ever scrolled past.
    app = FeedApp(200)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        for y in range(0, v.max_scroll_y, 20):
            v.scroll_to(y=y, animate=False)
            await pilot.pause()
        await pilot.pause()
        assert len(v._strip_cache) <= len(v._band_ids) + 1  # +1: sticky header slot
        assert len(v._strip_cache) < 20  # nowhere near the 200 entries visited
        # the layout (presentation) cache is deliberately NOT trimmed
        assert len(v._layout) > 100


@pytest.mark.asyncio
async def test_scrollback_after_trim_shows_content_not_a_placeholder() -> None:
    # Dropping strips keeps the Presentation, so a scroll-back re-renders
    # synchronously — no "Loading..." flash, no re-present.
    app = FeedApp(200)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.scroll_to(y=v.max_scroll_y, animate=False)
        await pilot.pause()
        await pilot.pause()
        assert 0 not in v._strip_cache  # the first entry's strips were dropped

        v.scroll_to(y=0, animate=False)
        await pilot.pause()
        row = "".join(seg.text for seg in v.render_line(0))
        assert "e000 row 0" in row  # real content on the very first paint


@pytest.mark.asyncio
async def test_sticky_header_strips_survive_the_trim() -> None:
    # A pinned header is composed every frame even when it sits far above the
    # band, so its strips must not be evicted (that would re-render it per frame).
    def is_header(entry: Entry[str]) -> bool:
        return entry.item.startswith("H")

    model: FlowModel[str] = FlowModel()
    header = model.append("H group")
    for i in range(60):
        model.append(f"item {i}")

    class StickyApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=TallPresenter(), spacing=0,
                estimated_height=10, sticky_header=is_header,
            )
            yield self.flow

    app = StickyApp()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.scroll_to(y=300, animate=False)  # deep inside the group
        await pilot.pause()
        for y in range(v.size.height):  # paint, so the header's strips get cached
            v.render_line(y)
        v.scroll_to(y=320, animate=False)  # scroll further; trim runs
        await pilot.pause()
        assert header.id not in v._band_ids       # header is outside the band...
        assert header.id in v._strip_cache        # ...but its strips are kept
