"""textual-flowview infinite-scroll demo — a log with lazy-loaded history.

Starts showing the newest lines. Scroll to the **top** and older lines load in a
page at a time (`FlowView.ReachedTop` -> `model.insert_many(0, ...)`), and the
view stays exactly where you were reading — the batch prepend preserves the
scroll position, so you don't get bounced around while paging back through
history. Keep going and it stops at the start of history.

This mirrors chat / log / transcript "scroll up for more". A real app would
`await` a fetch inside the handler (and can show the loading placeholder row for
not-yet-present entries); here the "fetch" is synchronous for clarity.

Run:  PYTHONPATH=src python examples/infinite.py
Keys: j/k or wheel scroll · g top · G bottom · q quit
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Anchor, FlowModel, FlowView, Presentation

HISTORY = 300  # lines 0..HISTORY-1 exist "on the server"
PAGE = 25      # how many to load per reach-top


@dataclass
class Line:
    n: int


class LinePresenter:
    async def present(self, item: Line, width: int) -> Presentation:
        hue = ["grey62", "cyan", "green", "magenta", "yellow"][item.n // 60 % 5]
        text = Text.assemble(
            (f"{item.n:04d}", hue),
            ("  log line — ", "grey42"),
            (f"event #{item.n} on host-{item.n % 7}", "grey70"),
        )
        return Presentation(height=1, renderable=text)


class InfiniteApp(App):
    TITLE = "textual-flowview"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"
    BINDINGS = [
        ("g", "top", "Top"),
        ("G", "bottom", "Bottom"),
        ("j", "down", "Down"),
        ("k", "up", "Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.log_lines: FlowModel[Line] = FlowModel()
        self._oldest = HISTORY - PAGE  # index of the oldest line currently loaded

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[Line] = FlowView(
            model=self.log_lines,
            presenter=LinePresenter(),
            spacing=0,
            estimated_height=1,
            reach_threshold=2,          # load a little before the very top edge
            anchor=Anchor.STICKY_BOTTOM,  # newest at the bottom, follow new lines
        )
        yield self.view
        yield Footer()

    def on_mount(self) -> None:
        # newest page first; start pinned to the bottom
        self.log_lines.extend(Line(n) for n in range(self._oldest, HISTORY))
        self.view.scroll_to_bottom()
        self._refresh_subtitle()

    def _refresh_subtitle(self) -> None:
        n = len(self.log_lines)
        if self._oldest > 0:
            self.sub_title = f"{n} lines · scroll up for older ({self._oldest} more)"
        else:
            self.sub_title = f"{n} lines · start of history reached"

    def on_flow_view_reached_top(self, event: FlowView.ReachedTop) -> None:
        if self._oldest <= 0:
            return  # no more history
        start = max(0, self._oldest - PAGE)
        # One batch -> one reflow, and the line you're reading stays put.
        self.log_lines.insert_many(0, [Line(n) for n in range(start, self._oldest)])
        self._oldest = start
        self._refresh_subtitle()
        self.notify(f"loaded older lines {start}-{start + PAGE - 1}")

    def action_top(self) -> None:
        self.view.scroll_to_top(animate=True, duration=0.3)

    def action_bottom(self) -> None:
        self.view.scroll_to_bottom(animate=True, duration=0.3)

    def action_down(self) -> None:
        self.view.scroll_relative(y=3)

    def action_up(self) -> None:
        self.view.scroll_relative(y=-3)


if __name__ == "__main__":
    InfiniteApp().run()
