"""textual-flowview current-entry demo.

`selectable=True` turns on the current entry — one cursor driven by keyboard and
mouse: ↑/↓ move it item-by-item (the view follows), PageUp/PageDown by a page,
Home/End jump to the first/last entry, and Enter/Space (or a click) commit it
(`FlowView.Selected`; `FlowView.Highlighted` fires as it moves).

These are **focus-scoped, overridable defaults** mapped onto public actions —
FlowView doesn't claim product-level keybindings. The current row has **no colour
of its own**; style `flowview--highlight` in your app (done in CSS below).

Run:  PYTHONPATH=src python examples/highlight.py
Keys: ↑/↓ move · PgUp/PgDn page · Home/End ends · Enter/Space activate · q quit
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Entry, FlowModel, FlowView, Presentation


@dataclass
class Command:
    name: str
    detail: str


class CommandPresenter:
    async def present(self, entry: Entry[Command], width: int) -> Presentation:
        item = entry.item
        line = Text.assemble((f"  {item.name:<18}", "bold"), (item.detail, "grey54"))
        return Presentation(height=1, renderable=line)


COMMANDS = [
    Command(f"command-{i:02d}", detail=f"does thing #{i} to the workspace")
    for i in range(60)
]


class HighlightApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "keyboard highlight — ↑/↓ move · Enter activate"
    # The highlight highlight is unstyled by default (FlowView ships no colours);
    # give flowview--highlight a look here.
    CSS = """
    FlowView { height: 1fr; padding: 0 1; }
    FlowView > .flowview--highlight { background: $accent 30%; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.commands: FlowModel[Command] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[Command] = FlowView(
            model=self.commands,
            presenter=CommandPresenter(),
            spacing=0,
            estimated_height=1,
            selectable=True,   # opt-in current-entry cursor
        )
        yield self.view
        yield Footer()

    def on_mount(self) -> None:
        self.commands.extend(COMMANDS)
        self.view.focus()
        self.view.current_first()

    def on_flow_view_highlighted(self, event: FlowView.Highlighted) -> None:
        if event.entry is not None:
            self.sub_title = f"highlight on {event.entry.item.name}"

    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        if event.entry is not None:
            self.notify(f"activated {event.entry.item.name}")


if __name__ == "__main__":
    HighlightApp().run()
