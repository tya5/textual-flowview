"""textual-flowview showcase — a live AI-agent activity feed.

Demonstrates: variable-height panels, a colored per-state gutter, streaming
updates, independent body/gutter refresh, and sticky-bottom auto-follow.

Run:  PYTHONPATH=src python examples/showcase.py
Keys: q quit · r replay stream · j/k or wheel scroll · click to select
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Anchor, Entry, EntryState, FlowModel, FlowView, Presentation

# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


@dataclass
class Event:
    kind: str          # "tool" | "code" | "log" | "result"
    title: str
    time: str
    body: str = ""
    meta: dict = field(default_factory=dict)


STATE_ICON = {
    EntryState.DEFAULT: "•",
    EntryState.RUNNING: "◐",
    EntryState.SUCCESS: "✓",
    EntryState.ERROR: "✗",
    EntryState.CANCELLED: "⊘",
}
STATE_COLOR = {
    EntryState.DEFAULT: "grey50",
    EntryState.RUNNING: "yellow",
    EntryState.SUCCESS: "green",
    EntryState.ERROR: "red",
    EntryState.CANCELLED: "grey50",
}
KIND_COLOR = {
    "tool": "cyan",
    "code": "magenta",
    "log": "grey62",
    "result": "green",
}


# --------------------------------------------------------------------------
# Gutter: a colored vertical bar with a state glyph on the first row
# --------------------------------------------------------------------------


class ActivityGutter:
    def decorate(self, entry: Entry[Event], width: int, height: int) -> RenderableType:
        color = STATE_COLOR.get(entry.state, "grey50")
        icon = STATE_ICON.get(entry.state, "•")
        rows = [icon if i == 0 else "┃" for i in range(max(1, height))]
        return Text("\n".join(rows), style=f"bold {color}")


# --------------------------------------------------------------------------
# Presenter: renders each Event as a bordered panel sized to width
# --------------------------------------------------------------------------


class ActivityPresenter:
    def __init__(self) -> None:
        from rich.console import Console

        self._probe = Console()

    async def present(self, item: Event, width: int) -> Presentation:
        border = KIND_COLOR.get(item.kind, "grey50")
        title = Text.assemble(
            (f" {item.kind.upper()} ", f"reverse {border}"),
            ("  ", ""),
            (item.title, "bold"),
        )
        subtitle = Text(item.time, style="grey50")

        body: RenderableType
        if item.kind == "code":
            body = Syntax(item.body, "python", theme="ansi_dark", line_numbers=False)
        elif item.kind == "result":
            table = Table.grid(padding=(0, 2))
            table.add_column(style="grey62")
            table.add_column(style="bold")
            for k, v in item.meta.items():
                table.add_row(k, str(v))
            body = table
        else:
            body = Text(item.body, style="grey85")

        panel = Panel(
            Group(body),
            title=title,
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            border_style=border,
            width=width,
            padding=(0, 1),
        )
        self._probe.size = (width, 100)
        height = len(self._probe.render_lines(panel, self._probe.options.update_width(width)))
        return Presentation(height=height, renderable=panel)


# --------------------------------------------------------------------------
# Seed data + live stream
# --------------------------------------------------------------------------

SEED: list[tuple[Event, EntryState]] = [
    (Event("log", "Session started", "09:31:02", "Booting textual-flowview showcase…"), EntryState.DEFAULT),
    (Event("tool", "read_file", "09:31:04", "src/textual_flowview/_view.py  (462 lines)"), EntryState.SUCCESS),
    (Event("tool", "grep", "09:31:05", "pattern='render_line'  →  3 matches in 2 files"), EntryState.SUCCESS),
    (
        Event(
            "code",
            "patch _view.py",
            "09:31:09",
            "def render_line(self, y: int) -> Strip:\n"
            "    content_width = self._content_width()\n"
            "    virtual_y = y + self.scroll_offset.y\n"
            "    return self._compose(virtual_y, content_width)",
        ),
        EntryState.SUCCESS,
    ),
    (Event("tool", "run_tests", "09:31:12", "pytest -q  →  collecting…"), EntryState.ERROR),
    (
        Event(
            "log",
            "test failure",
            "09:31:13",
            "FAILED tests/test_view.py::test_sticky_bottom\n"
            "AssertionError: expected scroll at bottom (40) but was 0",
        ),
        EntryState.ERROR,
    ),
    (Event("tool", "edit", "09:31:20", "Add _follow_bottom flag + watch_scroll_y hook"), EntryState.SUCCESS),
    (Event("tool", "run_tests", "09:31:24", "pytest -q"), EntryState.SUCCESS),
    (
        Event(
            "result",
            "all green",
            "09:31:27",
            meta={"passed": 46, "failed": 0, "duration": "1.5s", "coverage": "core 100%"},
        ),
        EntryState.SUCCESS,
    ),
]

STREAM_TASK = (
    "Composing the final answer. FlowView virtualizes thousands of "
    "variable-height rows, presenting only what's on screen, streaming body "
    "updates while the gutter tracks state independently — no reflow storms, "
    "no jank. Sticky-bottom keeps you pinned to the latest."
)


class ShowcaseApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "live activity feed"
    CSS = """
    Screen { background: $surface; }
    FlowView {
        height: 1fr;
        padding: 1 2;
        background: $surface;
    }
    FlowView > .flowview--selected { background: $accent 25%; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "replay", "Replay stream"),
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.feed: FlowModel[Event] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield FlowView(
            model=self.feed,
            presenter=ActivityPresenter(),
            decorator=ActivityGutter(),
            gutter_width=2,
            anchor=Anchor.STICKY_BOTTOM,
            overscan=6,
        )
        yield Footer()

    async def on_mount(self) -> None:
        for event, state in SEED:
            entry = self.feed.append(event)
            entry.set_state(state)
        self.set_timer(0.6, self._stream)

    def action_replay(self) -> None:
        self.call_later(self._stream)

    async def _stream(self) -> None:
        entry = self.feed.append(Event("log", "assistant", "09:31:31", ""))
        entry.set_state(EntryState.RUNNING)
        words = STREAM_TASK.split()
        for i, word in enumerate(words):
            entry.item.body += (" " if entry.item.body else "") + word
            entry.update()
            if i % 5 == 0:
                await asyncio.sleep(0.05)
        entry.set_state(EntryState.SUCCESS)

    def action_scroll_down(self) -> None:
        self.query_one(FlowView).scroll_relative(y=3)

    def action_scroll_up(self) -> None:
        self.query_one(FlowView).scroll_relative(y=-3)


if __name__ == "__main__":
    ShowcaseApp().run()
