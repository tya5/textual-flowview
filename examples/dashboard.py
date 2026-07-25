"""textual-flowview dynamic-view demo — a live hosts dashboard.

This is the kind of view that is *hard to build without FlowView*: **400
variable-height, live-updating entries** where only the ~visible handful ever
does work. Mounting 400 Textual widgets and animating them all would pay O(N)
mount / layout / repaint every frame; FlowView paints only the visible rows and
scopes all the dynamic work to the viewport — watch the "live" counter: 400
hosts, but only ~20 (the visible ones) animate and connect at any moment.

Exercises everything added for dynamic content, all viewport-scoped:

* animate_entry  — each host's CPU bar animates *only while on screen*; scroll a
  host off and its timer pauses, scroll back and it resumes.
* track_visibility — a host "connects" when it enters the viewport and
  "disconnects" when it leaves (watch the reconnect counter climb as you scroll
  back and forth) — the general acquire/release-on-visibility hook.
* animation_fps + a time-based decorator — the gutter spinner for a *live* host
  is driven by FlowView, no app timer.
* off-screen entry.update() is deferred by FlowView until the host scrolls in.

Run:  PYTHONPATH=src python examples/dashboard.py
Keys: q quit · j/k or wheel to scroll
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Entry, EntryState, FlowModel, FlowView, Presentation


@dataclass
class Host:
    name: str
    seed: float
    cpu: float = 0.0
    live: bool = False
    reconnects: int = 0


class HostPresenter:
    async def present(self, item: Host, width: int) -> Presentation:
        head = Text.assemble((f"{item.name:<16}", "bold"))
        bar = ProgressBar(total=100, completed=item.cpu, width=28, finished_style="red")
        top = Text.assemble(head, ("  ", ""))
        top.append_text(Text(f"{int(item.cpu):3d}% cpu", style="grey62"))
        if item.live:
            status = Text.assemble(
                ("● live", "green"), (f"   reconnects {item.reconnects}", "grey50")
            )
        else:
            status = Text("○ paused (off screen)", style="grey42")
        return Presentation(height=2, renderable=Group(Group(top, bar), status))


class HostGutter:
    """A spinner while the host is live (streaming), a dim dot otherwise. The
    spinner is time-based, so `animation_fps` animates it with no app timer."""

    def __init__(self) -> None:
        self._spinner = Spinner("dots", style="green")

    def decorate(self, entry: Entry[Host], width: int, height: int) -> RenderableType:
        rows = []
        for i in range(max(1, height)):
            if i == 0:
                rows.append(
                    self._spinner.render(time.monotonic()) if entry.item.live else Text("·", "grey42")
                )
            else:
                rows.append(Text("┊", style="grey30" if entry.item.live else "grey19"))
        return Group(*rows)


class DashboardApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "live hosts · viewport-scoped animation & resources"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"
    BINDINGS = [("q", "quit", "Quit"), ("j", "down", "Down"), ("k", "up", "Up")]

    def __init__(self) -> None:
        super().__init__()
        self.hosts: FlowModel[Host] = FlowModel()
        self._live = 0   # hosts currently connected (== visible)

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[Host] = FlowView(
            model=self.hosts,
            presenter=HostPresenter(),
            decorator=HostGutter(),
            gutter_width=2,
            animation_fps=10,   # FlowView drives the live-host gutter spinner
        )
        yield self.view
        yield Footer()

    HOSTS = 400

    def on_mount(self) -> None:
        for i in range(self.HOSTS):
            host = self.hosts.append(Host(name=f"host-{i:03d}", seed=i * 0.7))
            host.set_state(EntryState.RUNNING)
            # CPU bar animates only while the host is on screen.
            self.view.animate_entry(host, 0.1, self._tick_cpu)
            # Connection lifecycle acquired/released with visibility.
            self.view.track_visibility(host, on_show=self._connect, on_hide=self._disconnect)
        self._refresh_subtitle()

    def _refresh_subtitle(self) -> None:
        self.sub_title = f"{self.HOSTS} hosts · {self._live} live (only visible ones work)"

    def _tick_cpu(self, host: Entry[Host]) -> None:
        host.item.cpu = 50 + 40 * math.sin(time.monotonic() * 1.3 + host.item.seed)
        host.update()

    def _connect(self, host: Entry[Host]) -> None:
        host.item.live = True
        host.item.reconnects += 1
        self._live += 1
        self._refresh_subtitle()
        host.update()

    def _disconnect(self, host: Entry[Host]) -> None:
        host.item.live = False
        self._live -= 1
        self._refresh_subtitle()
        host.update()   # off-screen -> FlowView defers this until it scrolls back

    def action_down(self) -> None:
        self.view.scroll_relative(y=3)

    def action_up(self) -> None:
        self.view.scroll_relative(y=-3)


if __name__ == "__main__":
    DashboardApp().run()
