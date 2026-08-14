"""textual-flowview minimap demo — a scrollbar-replacing overview.

A long scan log with errors/warnings scattered through it. The FlowView's
native scrollbar is hidden; a FlowMinimap on the right shows the whole log
compressed and state-coloured (red = error), with the on-screen range
highlighted as the "window". Click or drag the minimap to jump.

Run:  PYTHONPATH=src python examples/minimap.py
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Footer, Header

from textual_flowview import (
    Entry,
    EntryState,
    FlowMinimap,
    FlowModel,
    FlowView,
    Presentation,
    StateDecorator,
)


@dataclass
class LogLine:
    seq: int
    text: str


class LogPresenter:
    async def present(self, entry: Entry[LogLine], width: int) -> Presentation:
        item = entry.item
        return Presentation(height=1, renderable=Text(f"{item.seq:04d}  {item.text}"))


def _line(seq: int) -> tuple[str, EntryState]:
    # Scatter some errors and warnings deterministically.
    if seq % 37 == 0:
        return f"scan failed: checksum mismatch on shard {seq}", EntryState.ERROR
    if seq % 17 == 0:
        return f"retrying shard {seq} (slow response)", EntryState.RUNNING
    if seq % 5 == 0:
        return f"verified shard {seq}", EntryState.SUCCESS
    return f"processed record {seq}", EntryState.DEFAULT


class MinimapApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "minimap = scrollbar replacement"
    CSS = """
    Horizontal { height: 1fr; }
    FlowView {
        scrollbar-size-vertical: 0;   /* the minimap replaces it */
        width: 1fr;
        padding: 0 1;
    }
    FlowMinimap { width: 1; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.records: FlowModel[LogLine] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[LogLine] = FlowView(
            model=self.records, presenter=LogPresenter(), decorator=StateDecorator(), gutter_width=2
        )
        with Horizontal():
            yield self.view
            yield FlowMinimap(flow_view=self.view)
        yield Footer()

    def on_mount(self) -> None:
        for seq in range(1, 401):
            text, state = _line(seq)
            entry = self.records.append(LogLine(seq, text))
            entry.set_state(state)


if __name__ == "__main__":
    MinimapApp().run()
