"""textual-flowview two-gutter demo — a notifications feed.

Each row has a body plus **two independent gutters**, one on each edge:

* left gutter  — an unread dot (and a `!` for high priority), driven by the
  entry's metadata;
* right gutter — the notification's age ("2m", "1h", "3d"), right-aligned;
* a `separator` (a `Rule`) drawn in the gap between rows.

Both are `FlowDecorator`s and neither re-presents the body:

* **click a row** to mark it read — only the *left* gutter redraws (the dot
  clears); the body and layout are untouched.
* the clock advances on its own (sped up), so the *right* gutter ticks the ages
  up — `animation_fps` re-derives the visible gutters each second, no app timer
  and no body re-present.

Run:  PYTHONPATH=src python examples/gutters.py
Keys: click a row = mark read · r = mark all read · [ / ] toggle left/right
      gutter · j/k scroll · q quit
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Entry, FlowModel, FlowView, Presentation

# 1 real second = TIME_SCALE virtual seconds, so ages visibly move.
TIME_SCALE = 15.0
_START = time.monotonic()


def _now() -> float:
    """Virtual 'seconds since start', accelerated so the demo doesn't crawl."""
    return (time.monotonic() - _START) * TIME_SCALE


def _rel(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


@dataclass
class Note:
    sender: str
    subject: str
    preview: str
    created_ago: float   # virtual seconds in the past at startup


class NotePresenter:
    async def present(self, entry: Entry[Note], width: int) -> Presentation:
        item = entry.item
        subject = Text(item.subject, style="bold")
        subject.append(f"   {item.sender}", style="grey54")
        preview = Text(item.preview, style="grey42", overflow="ellipsis", no_wrap=True)
        return Presentation(height=2, renderable=Group(subject, preview))


class UnreadGutter:
    """Left gutter: an unread dot, `!` for high priority. Reads metadata, so it
    redraws the moment `set_metadata` is called — no body re-present."""

    def decorate(self, entry: Entry[Note], width: int, height: int) -> RenderableType:
        unread = entry.metadata.get("unread", False)
        high = entry.metadata.get("priority") == "high"
        mark = Text()
        mark.append("!" if high else " ", style="bold red" if high else "")
        mark.append("●" if unread else " ", style="cyan" if unread else "")
        mark.append(" ")   # gap before the body
        rows = [mark] + [Text(" " * width) for _ in range(max(0, height - 1))]
        return Group(*rows)


class AgeGutter:
    """Right gutter: the note's age, right-aligned. Recomputed from the (moving)
    clock every time it's re-derived, so `animation_fps` makes it tick."""

    def decorate(self, entry: Entry[Note], width: int, height: int) -> RenderableType:
        age = _rel(_now() + entry.item.created_ago)
        rows = [Text(age.rjust(width), style="grey46")]
        rows += [Text(" " * width) for _ in range(max(0, height - 1))]
        return Group(*rows)


SEED = [
    ("ci-bot", "Build #4821 passed", "main · 3m12s · all checks green", 40, False),
    ("alice", "Re: gutter API review", "one nit on the cache key, otherwise LGTM", 320, True),
    ("pagerduty", "High CPU on web-03", "sustained >90% for 5 minutes", 95, "high"),
    ("github", "PR #212 approved", "two-gutter support — ready to merge", 610, True),
    ("bob", "lunch?", "the new ramen place at 12:30?", 1500, False),
    ("billing", "Invoice paid", "receipt attached · $49.00", 8000, False),
    ("security", "New sign-in", "from a new device · San Francisco", 240, "high"),
    ("newsletter", "Weekly digest", "5 stories you might have missed", 90000, False),
]


class GuttersApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "two gutters — unread (left) · age (right)"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"
    BINDINGS = [
        ("r", "read_all", "Mark all read"),
        ("left_square_bracket", "toggle_left", "Toggle left gutter"),
        ("right_square_bracket", "toggle_right", "Toggle right gutter"),
        ("j", "down", "Down"),
        ("k", "up", "Up"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.notes: FlowModel[Note] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[Note] = FlowView(
            model=self.notes,
            presenter=NotePresenter(),
            decorator=UnreadGutter(),
            gutter_width=3,
            right_decorator=AgeGutter(),
            right_gutter_width=5,
            separator=Rule(style="grey23"),   # a hairline in the 1-row gap
            animation_fps=1,   # re-derive visible gutters ~1x/s so ages tick
        )
        yield self.view
        yield Footer()

    def on_mount(self) -> None:
        # 60 notes: repeat the seed with staggered ages so there's plenty to
        # scroll and the ages span seconds → days.
        for k in range(60):
            sender, subject, preview, ago, flag = SEED[k % len(SEED)]
            note = self.notes.append(
                Note(sender, subject, preview, created_ago=ago + k * 37)
            )
            note.set_metadata("unread", bool(flag))
            if flag == "high":
                note.update_metadata(unread=True, priority="high")
        self._refresh_unread()

    def _refresh_unread(self) -> None:
        n = sum(1 for e in self.notes if e.metadata.get("unread"))
        self.sub_title = f"two gutters — {n} unread (left ●) · age (right)"

    def on_flow_view_clicked(self, event: FlowView.Clicked) -> None:
        # Mark the clicked note read: metadata-only -> left gutter redraws,
        # body is not re-presented.
        event.entry.set_metadata("unread", False)
        self._refresh_unread()

    def action_read_all(self) -> None:
        for entry in self.notes:
            if entry.metadata.get("unread"):
                entry.set_metadata("unread", False)
        self._refresh_unread()

    def action_toggle_left(self) -> None:
        on = self.view.toggle_gutter("left")
        self.notify(f"left gutter {'shown' if on else 'hidden'}")

    def action_toggle_right(self) -> None:
        on = self.view.toggle_gutter("right")
        self.notify(f"right gutter {'shown' if on else 'hidden'}")

    def action_down(self) -> None:
        self.view.scroll_relative(y=3)

    def action_up(self) -> None:
        self.view.scroll_relative(y=-3)


if __name__ == "__main__":
    GuttersApp().run()
