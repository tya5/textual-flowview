"""textual-flowview animated-scroll demo.

Shows the animated jump API on a long list:

* `scroll_to_entry(entry, animate=True, duration=...)` — smooth jumps; content
  presents as it scrolls past (still virtualized — one widget, not 500).
* a fresh animated jump **supersedes** one already in flight (press digits fast,
  or `r` for a scripted jump-to-bottom-then-redirect-to-top).
* `stop_scroll_animation()` — halt an in-flight animation *where it is* (`s`).

Run:  PYTHONPATH=src python examples/scroll_anim.py
Keys: g top · G bottom · 1..9 jump to 10..90% · s stop · r redirect demo
      j/k scroll · q quit
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Group
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import FlowModel, FlowView, Presentation

N = 500
DURATION = 1.2  # slow enough to watch the motion (and to stop / redirect it)


@dataclass
class Row:
    i: int


class RowPresenter:
    async def present(self, item: Row, width: int) -> Presentation:
        # A wide progress-style band so the position is obvious as it scrolls.
        filled = int((item.i / (N - 1)) * max(1, width - 8))
        bar = Text("█" * filled, style="grey37")
        head = Text.assemble(
            (f"row {item.i:03d}", "bold"),
            ("   ", ""),
            (f"{item.i / (N - 1) * 100:5.1f}%", "grey54"),
        )
        return Presentation(height=2, renderable=Group(head, bar))


class ScrollAnimApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "animated scroll — g/G ends · 1-9 jump · s stop · r redirect"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"
    BINDINGS = [
        ("g", "top", "Top"),
        ("G", "bottom", "Bottom"),
        ("s", "stop", "Stop"),
        ("r", "redirect", "Redirect demo"),
        ("j", "down", "Down"),
        ("k", "up", "Up"),
        ("q", "quit", "Quit"),
    ] + [(str(d), f"jump({d})", f"{d}0%") for d in range(1, 10)]

    def __init__(self) -> None:
        super().__init__()
        self.rows: FlowModel[Row] = FlowModel()
        self._entries: list = []

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[Row] = FlowView(
            model=self.rows,
            presenter=RowPresenter(),
            spacing=0,
            estimated_height=2,  # every row is 2 tall -> exact offsets before present
        )
        yield self.view
        yield Footer()

    def on_mount(self) -> None:
        self._entries = [self.rows.append(Row(i)) for i in range(N)]

    def action_top(self) -> None:
        self.view.scroll_to_top(animate=True, duration=DURATION)

    def action_bottom(self) -> None:
        self.view.scroll_to_bottom(animate=True, duration=DURATION)

    def action_jump(self, decile: int) -> None:
        target = self._entries[min(N - 1, decile * N // 10)]
        self.view.scroll_to_entry(target, animate=True, duration=DURATION)

    def action_stop(self) -> None:
        self.view.stop_scroll_animation()
        self.notify("stopped in place")

    def action_redirect(self) -> None:
        # Jump to the bottom, then redirect to the top mid-flight — the second
        # animated jump supersedes the first (no snap, no crash).
        self.view.scroll_to_bottom(animate=True, duration=DURATION * 2)
        self.set_timer(
            DURATION * 0.5,
            lambda: self.view.scroll_to_entry(
                self._entries[0], animate=True, duration=DURATION
            ),
        )

    def action_down(self) -> None:
        self.view.scroll_relative(y=3)

    def action_up(self) -> None:
        self.view.scroll_relative(y=-3)


if __name__ == "__main__":
    ScrollAnimApp().run()
