"""textual-flowview intervention demo — a clickable selector inside the flow.

Shows two things FlowView supports without embedding real widgets:

* an in-flow *selector UI* — the presenter draws option chips as text, and
  FlowView.Clicked reports the click position within the entry so the app can
  hit-test which chip was pressed;
* *content replacement* — resolving the choice swaps the item via
  entry.set_item(), which re-presents just that entry.

Run:  PYTHONPATH=src python examples/intervention.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Anchor, Entry, FlowModel, FlowView, Presentation

INDENT = 2
GAP = 2


def _chip(i: int, label: str) -> str:
    return f"[ {i + 1} · {label} ]"


def chip_spans(options: list[str]) -> list[tuple[int, int, str]]:
    """(start_col, end_col, label) for each chip — shared by the presenter (to
    draw) and the click handler (to hit-test), so they always agree."""
    spans: list[tuple[int, int, str]] = []
    col = INDENT
    for i, label in enumerate(options):
        text = _chip(i, label)
        spans.append((col, col + len(text), label))
        col += len(text) + GAP
    return spans


@dataclass
class Message:
    role: str                       # "user" | "assistant"
    text: str
    options: list[str] = field(default_factory=list)
    chosen: str | None = None


class ChatPresenter:
    async def present(self, entry: Entry[Message], width: int) -> Presentation:
        item = entry.item
        who = "You" if item.role == "user" else "Assistant"
        style = "cyan" if item.role == "user" else "green"
        head = Text.assemble((f"{who}  ", f"bold {style}"), (item.text, ""))

        if item.options and item.chosen is None:
            chips = Text(" " * INDENT)
            for i, label in enumerate(item.options):
                chips.append(_chip(i, label), style="bold on grey30")
                chips.append(" " * GAP)
            body: RenderableType = Group(head, chips, Text("  ↑ click an option", "grey50"))
            return Presentation(height=3, renderable=body)

        if item.chosen is not None:
            resolved = Text.assemble(
                ("  ✓ chose: ", "grey50"), (item.chosen, "bold green")
            )
            return Presentation(height=2, renderable=Group(head, resolved))

        return Presentation(height=1, renderable=head)


class InterventionApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "in-flow selector · content replacement"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.chat: FlowModel[Message] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        yield FlowView(
            model=self.chat, presenter=ChatPresenter(), anchor=Anchor.STICKY_BOTTOM
        )
        yield Footer()

    def on_mount(self) -> None:
        self.chat.append(Message("user", "Refactor the auth module."))
        self.chat.append(
            Message(
                "assistant",
                "How should I approach it?",
                options=["MVP-first", "Risk-first", "User-first"],
            )
        )

    def on_flow_view_clicked(self, event: FlowView.Clicked) -> None:
        item = event.entry.item
        if not item.options or item.chosen is not None or event.y != 1:
            return
        for start, end, label in chip_spans(item.options):
            if start <= event.x < end:
                # Content replacement: swap the whole item (immutable style).
                event.entry.set_item(replace(item, chosen=label))
                self.call_later(self._follow_up, label)
                break

    async def _follow_up(self, label: str) -> None:
        entry = self.chat.append(Message("assistant", ""))
        words = f"Going with the {label} plan. Starting on the auth module now.".split()
        for w in words:
            entry.item.text += (" " if entry.item.text else "") + w
            entry.update()
            await asyncio.sleep(0.04)


if __name__ == "__main__":
    InterventionApp().run()
