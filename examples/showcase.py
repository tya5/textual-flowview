"""textual-flowview showcase — a live AI-agent activity feed.

Demonstrates: variable-height panels, a colored per-state gutter, streaming
updates, independent body/gutter refresh, a contextual `separator` (a section
divider drawn only when the activity kind changes), and sticky-bottom
auto-follow.

Run:  PYTHONPATH=src python examples/showcase.py
Keys: q quit · r replay stream · c fold/unfold all · n next non-OK entry
      j/k or wheel scroll · click an item to fold/unfold just that one
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
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
    collapsed: bool = False


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


def kind_divider(above: Entry[Event], below: Entry[Event]) -> RenderableType | None:
    """A full-width labelled rule drawn in the gap, but only where the activity
    kind changes — a `separator` callable reading each entry's item."""
    if above.item.kind == below.item.kind:
        return None
    colour = KIND_COLOR.get(below.item.kind, "grey50")
    return Rule(
        title=f"{below.item.kind}",
        characters="─",
        style=colour,
    )


# --------------------------------------------------------------------------
# Gutter: a colored vertical bar with a state glyph on the first row
# --------------------------------------------------------------------------


SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class ActivityGutter:
    def decorate(self, entry: Entry[Event], width: int, height: int) -> RenderableType:
        color = STATE_COLOR.get(entry.state, "grey50")
        if entry.state is EntryState.RUNNING:
            # Animated spinner: the app ticks a "spin" metadata frame, which
            # redraws only the gutter (never the body).
            icon = SPINNER[entry.metadata.get("spin", 0) % len(SPINNER)]
        else:
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
        chevron = "▸" if item.collapsed else "▾"
        title = Text.assemble(
            (f"{chevron} ", "grey62"),
            (f" {item.kind.upper()} ", f"reverse {border}"),
            ("  ", ""),
            (item.title, "bold"),
        )
        subtitle = Text(item.time, style="grey50")

        # Collapsed: a single compact summary line — no body re-rendered.
        if item.collapsed:
            line = Text.assemble(title, ("   ", ""), (item.time, "grey42"))
            return Presentation(height=1, renderable=line)

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
    (Event("tool", "watch", "09:31:29", "watching for file changes…"), EntryState.RUNNING),
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
        ("c", "fold", "Fold / unfold"),
        ("n", "next_issue", "Next non-OK"),
        ("y", "copy_last", "Copy last"),
        ("j", "scroll_down", "Down"),
        ("k", "scroll_up", "Up"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.feed: FlowModel[Event] = FlowModel()
        self._folded = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield FlowView(
            model=self.feed,
            presenter=ActivityPresenter(),
            decorator=ActivityGutter(),
            gutter_width=2,
            separator=kind_divider,   # section label only when the kind changes
            selectable=True,          # click an item to select (and fold) it
            anchor=Anchor.STICKY_BOTTOM,
            overscan=6,
        )
        yield Footer()

    async def on_mount(self) -> None:
        for event, state in SEED:
            entry = self.feed.append(event)
            entry.set_state(state)
        self.set_timer(0.6, self._stream)
        # Drive the gutter spinner animation for RUNNING entries.
        self.set_interval(0.08, self._spin)

    def _spin(self) -> None:
        for entry in self.feed:
            if entry.state is EntryState.RUNNING:
                entry.set_metadata("spin", entry.metadata.get("spin", 0) + 1)

    def action_replay(self) -> None:
        self.call_later(self._stream)

    def action_next_issue(self) -> None:
        # Search: jump to the next entry whose state isn't SUCCESS/DEFAULT and
        # reveal it (un-hiding + scrolling into view). find_next uses the
        # current selection as its origin and wraps around.
        view = self.query_one(FlowView)
        hit = view.find_next(
            lambda e: e.state in (EntryState.RUNNING, EntryState.ERROR, EntryState.CANCELLED)
        )
        if hit is not None:
            if hit.hidden:
                hit.show()
            # center it so the surrounding context is visible, animated
            view.scroll_to_entry(hit, align="center", animate=True, duration=0.2)

    def action_copy_last(self) -> None:
        entries = list(self.feed)
        if not entries:
            return
        text = self.query_one(FlowView).copy_entry(entries[-1])
        preview = text.splitlines()[0] if text else "(empty)"
        self.notify(f"Copied: {preview[:40]}")

    def action_fold(self) -> None:
        # Collapse is purely a presenter concern: flip a flag and update().
        # Each item re-presents at its new height; the flow reflows itself.
        self._folded = not self._folded
        for entry in self.feed:
            entry.item.collapsed = self._folded
            entry.update()

    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        # Click an item to toggle just that one. We clear the selection right
        # after so clicking the same item again re-fires (select() dedupes a
        # still-selected entry), giving a clean per-item toggle.
        entry = event.entry
        if entry is None:
            return
        entry.item.collapsed = not entry.item.collapsed
        entry.update()
        event.control.clear_selection()

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
