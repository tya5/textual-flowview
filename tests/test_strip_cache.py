from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import Entry, FlowModel, FlowView, Presentation


class TallPresenter:
    async def present(self, entry: Entry[str], width: int) -> Presentation:
        item = entry.item
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


class Swappable:
    def __init__(self, name: str) -> None:
        self.name = name
        self.heavy = True


class SwapPresenter:
    async def present(self, entry: Entry[Swappable], width: int) -> Presentation:
        item = entry.item
        if item.heavy:
            return Presentation(
                height=10,
                renderable=Text("\n".join(f"{item.name} heavy {i}" for i in range(10))),
            )
        return Presentation(height=1, renderable=Text(f"[img] {item.name}"))


@pytest.mark.asyncio
async def test_offscreen_update_releases_the_superseded_presentation() -> None:
    # Shedding a heavy body (swap the item for a light one, then update()) must
    # actually free it. That necessarily happens while the entry is off-screen —
    # where the update is deferred — so the superseded presentation has to be
    # released there, not kept until the entry is next visited.
    model: FlowModel[Swappable] = FlowModel()
    entries = [model.append(Swappable(f"e{i}")) for i in range(60)]

    class SwapApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=SwapPresenter(), spacing=0, estimated_height=10
            )
            yield self.flow

    app = SwapApp()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        for y in range(0, v.max_scroll_y, 20):
            v.scroll_to(y=y, animate=False)
            await pilot.pause()
        await pilot.pause()
        assert len(v._layout) == 60          # every visited entry is cached
        heights = {e.id: v._layout.last_known_height(e.id) for e in entries}

        off = [e for e in entries if e.id not in v._band_ids]
        for e in off:
            e.item.heavy = False
            e.update()
        await pilot.pause()
        await pilot.pause()

        # the superseded presentations are gone, not left as stale-revision junk
        assert len(v._layout) <= len(v._band_ids) + 1
        current = {e.id: e.revision for e in entries}
        stale = [k for k in v._layout._cache if k[2] != current.get(k[0])]
        assert stale == []
        # ...while the layout stays put: heights are remembered
        for e in off:
            assert v._layout.last_known_height(e.id) == heights[e.id]


@pytest.mark.asyncio
async def test_released_entry_re_presents_correctly_on_scrollback() -> None:
    model: FlowModel[Swappable] = FlowModel()
    entries = [model.append(Swappable(f"e{i}")) for i in range(60)]

    class SwapApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=SwapPresenter(), spacing=0, estimated_height=10
            )
            yield self.flow

    app = SwapApp()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        v.scroll_to(y=v.max_scroll_y, animate=False)
        await pilot.pause()
        await pilot.pause()
        first = entries[0]
        first.item.heavy = False       # lighten the (off-screen) first entry
        first.update()
        await pilot.pause()

        v.scroll_to(y=0, animate=False)   # scroll back: it re-presents from the item
        for _ in range(6):
            await pilot.pause()
        assert v._layout.get(first, v._body_width()) is not None
        assert "[img] e0" in "".join(seg.text for seg in v.render_line(0))


@pytest.mark.asyncio
async def test_gutter_and_separator_caches_are_bounded_too() -> None:
    # The gutter and separator caches are the same kind of per-frame paint
    # cache as strips, so they must be released on leaving the band as well.
    from rich.rule import Rule

    class Gutter:
        def decorate(self, entry: object, width: int, height: int) -> Text:
            return Text("*" * width)

    model: FlowModel[str] = FlowModel()
    for i in range(200):
        model.append(f"e{i:03d}")

    class DecoratedApp(App):
        def compose(self) -> ComposeResult:
            self.flow = FlowView(
                model=model, presenter=TallPresenter(), spacing=1,
                estimated_height=10, decorator=Gutter(), gutter_width=2,
                separator=lambda a, b: Rule(),
            )
            yield self.flow

    app = DecoratedApp()
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        for y in range(0, v.max_scroll_y, 20):
            v.scroll_to(y=y, animate=False)
            await pilot.pause()
            for row in range(v.size.height):  # paint, filling gutter/separator caches
                v.render_line(row)
        await pilot.pause()
        limit = len(v._band_ids) + 2  # + sticky slot / straddling separator
        assert len(v._strip_cache) <= limit
        assert len(v._gutter_cache) <= limit
        assert len(v._separator_cache) <= limit


@dataclass
class Chunk:
    text: str


class ChunkPresenter:
    async def present(self, entry: Entry[Chunk], width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(entry.item.text))


def _stream_app(model: FlowModel[Chunk]) -> App:
    class StreamApp(App):
        CSS = "FlowView { scrollbar-gutter: stable; }"

        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=ChunkPresenter(), spacing=0)

    return StreamApp()


@pytest.mark.asyncio
async def test_update_never_blinks_through_the_placeholder() -> None:
    """A re-present must keep drawing the previous body until the new one lands.

    Presentation is async, so a paint can land between the revision bump and the
    worker's result. Before this was fixed, `_band_ids` was only refreshed by
    `_present_visible` — never by a plain `append` — so an on-screen entry was
    classified off-band, its presentation *released*, and every streamed chunk
    painted a frame of "Loading..." over content the reader was mid-sentence in.
    """
    model: FlowModel[Chunk] = FlowModel()
    async with _stream_app(model).run_test(size=(50, 12)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        entry = model.append(Chunk("stream"))
        await pilot.pause()

        painted = []
        for i in range(5):
            entry.item.text = f"chunk {i}"
            entry.update()
            offset = view._viewport.offset_of(entry)
            assert offset is not None
            painted.append(view.render_line(offset).text.rstrip())
            await pilot.pause()

        assert not any("Loading" in row for row in painted), painted
        await pilot.pause()
        offset = view._viewport.offset_of(entry)
        assert offset is not None
        assert "chunk 4" in view.render_line(offset).text


@pytest.mark.asyncio
async def test_offscreen_update_still_releases_its_presentation() -> None:
    """The memory optimisation the band check exists for must survive the fix:
    an entry genuinely out of view still drops its cached body on update()."""
    model: FlowModel[Chunk] = FlowModel()
    entries = [model.append(Chunk(f"r{i}")) for i in range(400)]
    async with _stream_app(model).run_test(size=(50, 12)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        far = entries[-1]
        view.scroll_to_bottom(animate=False)
        await pilot.pause()
        width = view._body_width()
        assert view._layout.get(far, width) is not None

        view.scroll_to_top(animate=False)
        await pilot.pause()
        assert not view._in_band(far)
        far.item.text = "changed"
        far.update()
        assert view._layout.superseded(far.id, width) is None, "should be released"
