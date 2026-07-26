"""Side-by-side, live: the same list two ways, with a real-time FPS meter.

Two independent axes:

* backend — the "obvious" approach (`c`: a Textual `VerticalScroll` with one
  `Static` per row) vs `FlowView` (`f`).
* content — `static` rows (rendered once, only the *scroll* moves) vs `dynamic`
  rows (every visible CPU bar re-renders each frame). Toggle with `d`.

`space` starts the auto-scroll — the heavy part — and the top bar shows the FPS
the app actually sustains. The gap is biggest with *static* content, where the
container still pays O(N) layout per scrolled frame while FlowView paints only
the viewport; *dynamic* rich `ProgressBar`s narrow it, because both sides then
spend most of their time re-rendering the same handful of visible bars.

Starts paused. In dynamic mode the bars still pulse; the list just doesn't
auto-scroll yet, so you can read it. `space` starts the scroll.

For a true side-by-side (each in its own process = its own render loop), pass a
backend + content mode and run four panes — e.g. a 2x2 terminal split:

    PYTHONPATH=src python examples/compare.py flowview  static
    PYTHONPATH=src python examples/compare.py container static
    PYTHONPATH=src python examples/compare.py flowview  dynamic
    PYTHONPATH=src python examples/compare.py container dynamic

Run:  PYTHONPATH=src python examples/compare.py [flowview|container] [static|dynamic]
Keys: c container · f flowview · d static/dynamic · space run/pause · j/k scroll · q quit
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


def _detail(i: int) -> str:
    # Static text row — variable height, every 3rd row taller.
    return f"row {i:04d}\n  detail line" + ("\n  more detail" if i % 3 == 0 else "")


def render_dynamic(i: int) -> RenderableType:
    """A live dashboard row: a rich ProgressBar that re-renders every frame."""
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
    def __init__(self, dynamic: bool) -> None:
        self.dynamic = dynamic

    async def present(self, item: Row, width: int) -> Presentation:
        if self.dynamic:
            # FlowView carries an explicit height, so a ProgressBar (whose height
            # a Static can't auto-measure) just works.
            return Presentation(height=ROW_HEIGHT, renderable=render_dynamic(item.i))
        text = _detail(item.i)
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
        ("d", "toggle_dynamic", "Static/dynamic"),
        ("space", "toggle_run", "Run/pause"),
        ("j", "down", "Down"),
        ("k", "up", "Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, mode: str = "flowview", dynamic: bool = True) -> None:
        super().__init__()
        self.model: FlowModel[Row] = FlowModel()
        for i in range(N):
            self.model.append(Row(i))
        self._mode = mode
        self._dynamic = dynamic
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
            FlowView(model=self.model, presenter=RowPresenter(self._dynamic), spacing=0)
        )

    async def _mount_container(self) -> None:
        await self._clear_host()
        self._mode = "container"
        vs = VerticalScroll()
        await self.query_one("#host").mount(vs)
        self._statics = []
        for i in range(N):
            if self._dynamic:
                st = Static(render_dynamic(i))
                st.styles.height = ROW_HEIGHT   # a Static can't auto-measure a ProgressBar
            else:
                st = Static(Text(_detail(i)))   # plain text auto-measures fine
            self._statics.append(st)
        await vs.mount_all(self._statics)

    async def _remount(self) -> None:
        if self._mode == "container":
            await self._mount_container()
        else:
            await self._mount_flowview()

    async def action_container(self) -> None:
        if self._mode != "container":
            await self._mount_container()

    async def action_flowview(self) -> None:
        if self._mode != "flowview":
            await self._mount_flowview()

    async def action_toggle_dynamic(self) -> None:
        self._dynamic = not self._dynamic
        await self._remount()

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
        # Auto-scroll (wraps) so rows keep flowing past — only while running.
        if self._playing:
            if s.scroll_offset.y >= s.max_scroll_y:
                s.scroll_to(y=0, animate=False)
            else:
                s.scroll_relative(y=3, animate=False)
        # Static content never re-renders — only the scroll moves.
        if not self._dynamic:
            return
        # Dynamic: re-render the on-screen rows with the current value (both
        # backends update only the visible rows — a fair fight). The bars keep
        # pulsing even while paused; pause only stops the auto-scroll.
        if self._mode == "flowview":
            lo, hi = s.visible_range()
            for entry in s.entries[lo:hi]:
                entry.update()
        else:
            top = int(s.scroll_offset.y) // ROW_HEIGHT
            bottom = top + s.content_size.height // ROW_HEIGHT + 2
            for i in range(max(0, top), min(N, bottom)):
                self._statics[i].update(render_dynamic(i))

    def _frame(self) -> None:
        meters = self.query(Meter)
        if not meters:
            return
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        if dt > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / dt)

        self._workload()   # bars always animate; pause only halts the auto-scroll

        fps = self._fps
        widgets = len(self.query("*"))
        colour = "green" if fps >= 40 else "yellow" if fps >= 20 else "red"
        state = "▶ scrolling" if self._playing else "⏸ paused (space)"
        label = "FlowView " if self._mode == "flowview" else "Container"
        content = "dynamic" if self._dynamic else "static"
        meters.first().update(
            Text.assemble(
                (f" {label} ", f"reverse {colour}"),
                (f" {content} ", "reverse grey58"),
                (f"   {fps:5.1f} FPS", colour),
                (f"   {dt * 1000:5.1f} ms/frame", "grey62"),
                (f"   {widgets:,} widgets", "grey62"),
                (f"   ({N} rows)   ", "grey42"),
                (state, "grey70"),
                ("     [c/f] backend  [d] static/dynamic", "grey42"),
            )
        )


if __name__ == "__main__":
    argv = [a.lower() for a in sys.argv[1:]]
    mode = "container" if any(a.startswith("c") for a in argv) else "flowview"
    dynamic = not any(a.startswith("stat") for a in argv)   # default: dynamic
    CompareApp(mode, dynamic).run()
