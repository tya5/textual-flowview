"""Side-by-side, live: the same list two ways, with a real-time FPS meter.

Press `c` for the "obvious" approach (a Textual `VerticalScroll` with one
`Static` per row) and `f` for `FlowView`. A steady auto-scroll workload runs in
both, and the top bar shows the frames-per-second the app actually sustains — so
you *watch* the number collapse when 1500 widgets are mounted and recover when
FlowView paints instead.

Great for an asciinema recording: launch, then tap `c` / `f` to flip back and
forth and watch the FPS / frame-ms / widget-count change live.

Run:  PYTHONPATH=src python examples/compare.py
Keys: c container · f flowview · space pause/resume scroll · q quit
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from textual_flowview import FlowModel, FlowView, Presentation

N = 1500


def _content(i: int) -> str:
    return f"row {i:04d}   the quick brown fox" + ("\n   …with a second line" if i % 3 == 0 else "")


@dataclass
class Row:
    i: int


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        text = _content(item.i)
        return Presentation(height=text.count("\n") + 1, renderable=Text(text))


class Meter(Static):
    pass


class CompareApp(App):
    TITLE = "textual-flowview"
    CSS = """
    Meter { dock: top; height: 1; background: $panel; padding: 0 1; }
    #host { height: 1fr; }
    VerticalScroll, FlowView { height: 1fr; scrollbar-size-vertical: 1; }
    """
    BINDINGS = [
        ("c", "container", "Container"),
        ("f", "flowview", "FlowView"),
        ("space", "toggle_scroll", "Pause scroll"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.model: FlowModel[Row] = FlowModel()
        for i in range(N):
            self.model.append(Row(i))
        self._mode = "flowview"
        self._fps = 60.0
        self._last = 0.0
        self._scrolling = True

    def compose(self) -> ComposeResult:
        yield Meter(id="meter")
        yield Container(id="host")

    async def on_mount(self) -> None:
        await self._mount_flowview()
        self._last = time.monotonic()
        self.set_interval(1 / 60, self._frame)   # workload + FPS meter

    # -- backends ----------------------------------------------------------

    async def _clear_host(self) -> None:
        await self.query_one("#host").remove_children()

    async def _mount_flowview(self) -> None:
        await self._clear_host()
        self._mode = "flowview"
        await self.query_one("#host").mount(
            FlowView(model=self.model, presenter=RowPresenter(), spacing=0)
        )

    async def _mount_container(self) -> None:
        await self._clear_host()
        self._mode = "container"
        vs = VerticalScroll()
        await self.query_one("#host").mount(vs)
        await vs.mount_all([Static(Text(_content(i))) for i in range(N)])

    async def action_container(self) -> None:
        if self._mode != "container":
            await self._mount_container()

    async def action_flowview(self) -> None:
        if self._mode != "flowview":
            await self._mount_flowview()

    def action_toggle_scroll(self) -> None:
        self._scrolling = not self._scrolling

    # -- workload + meter --------------------------------------------------

    def _scroller(self):
        try:
            return self.query_one(FlowView if self._mode == "flowview" else VerticalScroll)
        except Exception:
            return None

    def _frame(self) -> None:
        meters = self.query(Meter)
        if not meters:   # teardown / mid-transition
            return
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)   # smoothed

        if self._scrolling:
            s = self._scroller()
            if s is not None:
                if s.scroll_offset.y >= s.max_scroll_y:
                    s.scroll_to(y=0, animate=False)
                else:
                    s.scroll_relative(y=4, animate=False)

        fps = self._fps
        widgets = len(self.query("*"))
        colour = "green" if fps >= 40 else "yellow" if fps >= 20 else "red"
        label = "FlowView " if self._mode == "flowview" else "Container"
        meters.first().update(
            Text.assemble(
                (f" {label} ", f"reverse {colour}"),
                (f"   {fps:5.1f} FPS", colour),
                (f"   {dt * 1000:5.1f} ms/frame", "grey62"),
                (f"   {widgets:,} widgets", "grey62"),
                (f"   ({N} rows)", "grey42"),
                ("     [c] container  [f] flowview  [space] pause", "grey42"),
            )
        )


if __name__ == "__main__":
    CompareApp().run()
