"""A minimal streaming chat demo for textual-flowview.

Run with:  python -m examples.chat   (from the repo root, with src on the path)
or:        PYTHONPATH=src python examples/chat.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from rich.console import Group
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Input

from textual_flowview import (
    Anchor,
    EntryState,
    FlowModel,
    FlowView,
    Presentation,
    StateDecorator,
)

WORDS = (
    "Textual makes it easy to build sophisticated user interfaces in the "
    "terminal, and textual-flowview adds a virtualized flow of variable-height "
    "items on top so you can stream thousands of messages smoothly.".split()
)


@dataclass
class ChatMessage:
    role: str
    text: str


class ChatPresenter:
    """Turns a ChatMessage into a Panel sized to the available width."""

    async def present(self, item: ChatMessage, width: int) -> Presentation:
        is_user = item.role == "user"
        style = "cyan" if is_user else "green"
        title = "You" if is_user else "Assistant"
        body = Text(item.text or " ", style=style)
        panel = Panel(
            Group(body),
            title=title,
            title_align="left",
            border_style=style,
            width=width,
        )
        # Measure how tall the panel renders at this width.
        from rich.console import Console

        console = Console(width=width)
        height = len(console.render_lines(panel, console.options))
        return Presentation(height=height, renderable=panel)


class ChatApp(App):
    CSS = "FlowView { border: round $panel; height: 1fr; } Input { dock: bottom; }"
    BINDINGS = [("ctrl+d", "demo", "Stream a reply")]

    def __init__(self) -> None:
        super().__init__()
        self.conversation: FlowModel[ChatMessage] = FlowModel()

    def compose(self) -> ComposeResult:
        yield FlowView(
            model=self.conversation,
            presenter=ChatPresenter(),
            decorator=StateDecorator(),
            gutter_width=2,
            anchor=Anchor.STICKY_BOTTOM,
        )
        yield Input(placeholder="Type a message and press Enter…")
        yield Footer()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self.conversation.append(ChatMessage(role="user", text=text))
        await self._stream_reply()

    async def action_demo(self) -> None:
        self.conversation.append(ChatMessage(role="user", text="Tell me about this widget."))
        await self._stream_reply()

    async def _stream_reply(self) -> None:
        entry = self.conversation.append(ChatMessage(role="assistant", text=""))
        # Gutter shows RUNNING while the body streams — the body re-presents on
        # every update(), the marker changes without touching the body.
        entry.set_state(EntryState.RUNNING)
        for word in WORDS:
            entry.item.text += (" " if entry.item.text else "") + word
            entry.update()
            await asyncio.sleep(0.03)
        entry.set_state(EntryState.SUCCESS)


if __name__ == "__main__":
    ChatApp().run()
