"""textual-flowview animation demo — reusing Rich's Spinner and ProgressBar.

Display-only indicators are just Rich renderables, so the built-in components
drop straight into a Presentation — no custom drawing:

* gutter spinner  -> rich.spinner.Spinner (redrawn via set_metadata; gutter only)
* body progress   -> rich.progress_bar.ProgressBar (redrawn via update(); body)

FlowView caches an entry's render and only redraws on update()/metadata change,
so animation is app-driven: a timer advances the frame. Gutter redraws are
cheap (no body re-present, no reflow); body redraws re-present but never reflow
at fixed height.

Run:  PYTHONPATH=src python examples/progress.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Group, RenderableType
from rich.progress_bar import ProgressBar
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Entry, EntryState, FlowModel, FlowView, Presentation, StateDecorator


@dataclass
class Task:
    name: str
    progress: float = 0.0
    speed: float = 0.02


class TaskPresenter:
    async def present(self, item: Task, width: int) -> Presentation:
        head = Text(item.name, style="bold")
        bar = ProgressBar(
            total=100,
            completed=item.progress * 100,
            width=32,
            finished_style="green",
        )
        row = Table.grid(padding=(0, 2))
        row.add_column()
        row.add_column()
        row.add_row(bar, Text(f"{int(item.progress * 100):3d}%", style="bold"))
        # Fixed 2-row height regardless of progress -> no reflow per frame.
        return Presentation(height=2, renderable=Group(head, row))


class SpinnerGutter(StateDecorator):
    """Rich's Spinner in the gutter for RUNNING entries; the standard state
    marker otherwise."""

    def __init__(self) -> None:
        super().__init__()
        self._spinner = Spinner("dots", style="yellow")

    def decorate(self, entry: Entry[Task], width: int, height: int) -> RenderableType:
        if entry.state is EntryState.RUNNING:
            return self._spinner.render(time.monotonic())
        return super().decorate(entry, width, height)


class ProgressApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "Rich Spinner + ProgressBar in entries"
    CSS = "FlowView { height: 1fr; padding: 1 2; }"
    BINDINGS = [("q", "quit", "Quit"), ("r", "restart", "Restart")]

    TASKS = [
        ("Download deps", 0.010),
        ("Compile sources", 0.006),
        ("Run tests", 0.015),
        ("Build wheel", 0.022),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.tasks: FlowModel[Task] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        yield FlowView(
            model=self.tasks,
            presenter=TaskPresenter(),
            decorator=SpinnerGutter(),
            gutter_width=2,
        )
        yield Footer()

    def on_mount(self) -> None:
        self.action_restart()
        self.set_interval(1 / 12, self._tick)

    def action_restart(self) -> None:
        self.tasks.clear()
        for name, speed in self.TASKS:
            entry = self.tasks.append(Task(name, speed=speed))
            entry.set_state(EntryState.RUNNING)

    def _tick(self) -> None:
        for entry in self.tasks:
            if entry.state is not EntryState.RUNNING:
                continue
            # Advance the gutter spinner: bump metadata to redraw the gutter.
            entry.set_metadata("tick", entry.metadata.get("tick", 0) + 1)
            # Advance the body progress bar: re-present the body.
            entry.item.progress = min(1.0, entry.item.progress + entry.item.speed)
            entry.update()
            if entry.item.progress >= 1.0:
                entry.set_state(EntryState.SUCCESS)


if __name__ == "__main__":
    ProgressApp().run()
