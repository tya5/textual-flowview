"""Side-by-side, live: the same list two ways, with a real-time FPS meter.

Press `c` for the "obvious" approach (a Textual `VerticalScroll` with one
`Static` per row) and `f` for `FlowView`. Press `space` to start the live
workload — every row's CPU bar animates and the list auto-scrolls — and the top
bar shows the frames-per-second the app actually sustains. Watch it collapse
with 1500 mounted widgets and recover when FlowView paints instead.

Starts paused so you can read it before the numbers move.

For a true side-by-side (each in its own process = its own render loop), pass a
backend and run two panes — e.g. split the terminal:

    PYTHONPATH=src python examples/compare.py flowview    # left pane
    PYTHONPATH=src python examples/compare.py container   # right pane

Run:  PYTHONPATH=src python examples/compare.py [flowview|container]
Keys: c container · f flowview · space run/pause · j/k scroll · q quit
"""

from __future__ import annotations

import math
import sys
import time
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.progress_bar import ProgressBar
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from textual_flowview import FlowModel, FlowView, Presentation

N = 1500
BAR_WIDTH = 34
ROW_HEIGHT = 2


def _cpu(i: int) -> float:
    # Time-based so every render shows motion — a moving CPU load per host.
    return max(1.0, 50 + 45 * math.sin(time.monotonic() * 1.4 + i * 0.25))


def render_row(i: int) -> RenderableType:
    """A dashboard row — identical for both backends, so it's a fair fight."""
    cpu = _cpu(i)
    head = Text.assemble(
        (f"host-{i:04d}", "bold"),
        (f"   {int(cpu):3d}% cpu   ", "grey62"),
        ("● live", "green"),
    )
    bar = ProgressBar(total=100, completed=cpu, width=BAR_WIDTH, finished_style="red")
    return Group(head, bar)


@dataclass
class Row:
    i: int


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        # FlowView carries an explicit height, so a ProgressBar (whose height a
        # Static can't auto-measure) just works.
        return Presentation(height=ROW_HEIGHT, renderable=render_row(item.i))


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
        ("space", "toggle_run", "Run/pause"),
        ("j", "down", "Down"),
        ("k", "up", "Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, mode: str = "flowview") -> None:
        super().__init__()
        self.model: FlowModel[Row] = FlowModel()
        for i in range(N):
            self.model.append(Row(i))
        self._mode = mode
        self._fps = 60.0
        self._last = 0.0
        self._playing = False          # start paused (NB: not `_running` — App uses that)
        self._statics: list[Static] = []

    def compose(self) -> ComposeResult:
        yield Meter(id="meter")
        yield Container(id="host")

    async def on_mount(self) -> None:
        if self._mode == "container":
            await self._mount_container()
        else:
            await self._mount_flowview()
        self._last = time.monotonic()
        self.set_interval(1 / 60, self._frame)

    # -- backends ----------------------------------------------------------

    async def _clear_host(self) -> None:
        self._statics = []
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
        self._statics = []
        for i in range(N):
            st = Static(render_row(i))
            st.styles.height = ROW_HEIGHT   # a Static can't auto-measure a ProgressBar
            self._statics.append(st)
        await vs.mount_all(self._statics)

    async def action_container(self) -> None:
        if self._mode != "container":
            await self._mount_container()

    async def action_flowview(self) -> None:
        if self._mode != "flowview":
            await self._mount_flowview()

    def action_toggle_run(self) -> None:
        self._playing = not self._playing

    def _scroller(self):
        host = self.query_one("#host")
        return host.children[0] if host.children else None

    def action_down(self) -> None:
        s = self._scroller()
        if s is not None:
            s.scroll_relative(y=3, animate=False)

    def action_up(self) -> None:
        s = self._scroller()
        if s is not None:
            s.scroll_relative(y=-3, animate=False)

    # -- workload + meter --------------------------------------------------

    def _workload(self) -> None:
        s = self._scroller()
        if s is None:
            return
        # Auto-scroll (wraps) so rows keep flowing past.
        if s.scroll_offset.y >= s.max_scroll_y:
            s.scroll_to(y=0, animate=False)
        else:
            s.scroll_relative(y=3, animate=False)
        # Animate the bars: re-render the on-screen rows with the current value
        # (both backends update only the visible rows — a fair fight).
        if self._mode == "flowview":
            lo, hi = s.visible_range()
            for entry in s.entries[lo:hi]:
                entry.update()
        else:
            top = int(s.scroll_offset.y) // ROW_HEIGHT
            bottom = top + s.content_size.height // ROW_HEIGHT + 2
            for i in range(max(0, top), min(N, bottom)):
                self._statics[i].update(render_row(i))

    def _frame(self) -> None:
        meters = self.query(Meter)
        if not meters:
            return
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)

        if self._playing:
            self._workload()

        fps = self._fps
        widgets = len(self.query("*"))
        colour = "green" if fps >= 40 else "yellow" if fps >= 20 else "red"
        state = "▶ running" if self._playing else "⏸ paused (space)"
        label = "FlowView " if self._mode == "flowview" else "Container"
        meters.first().update(
            Text.assemble(
                (f" {label} ", f"reverse {colour}"),
                (f"   {fps:5.1f} FPS", colour),
                (f"   {dt * 1000:5.1f} ms/frame", "grey62"),
                (f"   {widgets:,} widgets", "grey62"),
                (f"   ({N} rows)   ", "grey42"),
                (state, "grey70"),
                ("     [c] container  [f] flowview", "grey42"),
            )
        )


if __name__ == "__main__":
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "flowview"
    CompareApp("container" if arg.startswith("c") else "flowview").run()
