"""De-risking PoC: reyn TUI conversation pane on textual-flowview.

Evaluates whether textual-flowview's FlowView fits reyn's TUI as a
replacement for the current prompt_toolkit + rich inline REPL conversation
pane. This file is a STANDALONE PoC — it does not import or modify anything
from the reyn repository.

Layout: a slim status line (top), a scrollable FlowView (main, the ONLY rich
widget), and a bottom Input box — Claude-Code-like chrome, not a multi-panel
dashboard.

Run interactively:
    PYTHONPATH=/Users/yasudatetsuya/Workspace/textual-flowview/src \\
        python examples/reyn_poc/reyn_chat_poc.py

On launch the app HYDRATES the FlowModel from conversation.json (mimicking
reyn's P6 .reyn/events replay) so the previous conversation is visible
immediately, before any new interaction. Press ctrl+d to stream a new demo
assistant reply (proves live streaming + sticky-bottom follow on top of the
restored history). Resize your terminal to see the conversation AND the
input box both reflow live.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from textual_flowview import (
    Anchor,
    Entry,
    EntryState,
    FlowModel,
    FlowView,
    Presentation,
    StateDecorator,
)

HERE = Path(__file__).parent
CONVERSATION_FIXTURE = HERE / "conversation.json"

STREAM_WORDS = (
    "Sure — resizing the terminal reflows the whole conversation pane live, "
    "because textual-flowview keys its presentation cache by width and "
    "re-presents every visible entry on Textual's on_resize hook. That is "
    "the headline capability this PoC is built to prove.".split()
)

STATE_MAP = {
    "default": EntryState.DEFAULT,
    "running": EntryState.RUNNING,
    "success": EntryState.SUCCESS,
    "error": EntryState.ERROR,
    "cancelled": EntryState.CANCELLED,
}

TOOL_ICON = {
    "grep": "\U0001f50d",
    "read_file": "\U0001f4c4",
    "edit": "✏️",
    "sandboxed_exec": "⚙️",
}

CHIP_INDENT = 2
CHIP_GAP = 2


# --------------------------------------------------------------------------
# Model: a single reyn-flavored "entry" item covers message / tool_call /
# ask_user. This mirrors what a real reyn events-replay would hand a
# FlowModel — one item per audit-event-derived conversation turn.
# --------------------------------------------------------------------------


@dataclass
class ConvItem:
    kind: str  # "message" | "tool_call" | "ask_user"
    role: str  # "user" | "assistant"
    text: str
    tool: str | None = None
    result: str | None = None
    options: list[str] = field(default_factory=list)
    chosen: str | None = None


def _chip(i: int, label: str) -> str:
    return f"[ {i + 1} · {label} ]"


def chip_spans(options: list[str]) -> list[tuple[int, int, str]]:
    """(start_col, end_col, label) per chip — shared by presenter + click
    handler so hit-testing always agrees with what was drawn."""
    spans: list[tuple[int, int, str]] = []
    col = CHIP_INDENT
    for i, label in enumerate(options):
        text = _chip(i, label)
        spans.append((col, col + len(text), label))
        col += len(text) + CHIP_GAP
    return spans


class ReynPresenter:
    """Turns a ConvItem into a Panel/Group sized to the available width.

    This is the ONE presenter for all three reyn-shaped entry kinds
    (message / tool_call / ask_user) — reyn's real integration point would
    swap this for a presenter keyed off its own Control-IR op-kind union.
    """

    def __init__(self) -> None:
        self._probe = Console()

    async def present(self, item: ConvItem, width: int) -> Presentation:
        if item.kind == "ask_user":
            return self._present_ask_user(item, width)
        if item.kind == "tool_call":
            return self._present_tool_call(item, width)
        return self._present_message(item, width)

    def _measure(self, renderable: RenderableType, width: int) -> int:
        self._probe.size = (width, 200)
        return len(self._probe.render_lines(renderable, self._probe.options.update_width(width)))

    def _present_message(self, item: ConvItem, width: int) -> Presentation:
        is_user = item.role == "user"
        style = "cyan" if is_user else "green"
        title = "You" if is_user else "Assistant"
        body: RenderableType = Markdown(item.text or " ")
        panel = Panel(
            Group(body),
            title=title,
            title_align="left",
            border_style=style,
            width=width,
        )
        return Presentation(height=self._measure(panel, width), renderable=panel)

    def _present_tool_call(self, item: ConvItem, width: int) -> Presentation:
        icon = TOOL_ICON.get(item.tool or "", "\U0001f6e0️")
        head = Text.assemble(
            (f"{icon} ", ""),
            (f"{item.tool}", "bold magenta"),
            ("  ", ""),
            (item.text, "grey62"),
        )
        lines: list[RenderableType] = [head]
        if item.result:
            lines.append(Text(f"  └─ {item.result}", style="grey50"))
        group = Group(*lines)
        return Presentation(height=self._measure(group, width), renderable=group)

    def _present_ask_user(self, item: ConvItem, width: int) -> Presentation:
        head = Text.assemble(("❓ ask_user  ", "bold yellow"), (item.text, ""))
        if item.chosen is None:
            chips = Text(" " * CHIP_INDENT)
            for i, label in enumerate(item.options):
                chips.append(_chip(i, label), style="bold on grey30")
                chips.append(" " * CHIP_GAP)
            body = Group(head, chips, Text("  ↑ click an option", style="grey50"))
            return Presentation(height=3, renderable=body)
        resolved = Text.assemble(("  ✓ resolved: ", "grey50"), (item.chosen, "bold green"))
        return Presentation(height=2, renderable=Group(head, resolved))


class ReynGutter(StateDecorator):
    """Reuse the library's EntryState -> marker mapping (RUNNING/SUCCESS/
    ERROR/...), which mirrors reyn's present-layer / audit-event phases."""


# --------------------------------------------------------------------------
# Hydration: load conversation.json the way a real reyn TUI would replay
# .reyn/events into a fresh FlowModel on startup.
# --------------------------------------------------------------------------


def hydrate_model(model: FlowModel[ConvItem], fixture_path: Path) -> None:
    data: dict[str, Any] = json.loads(fixture_path.read_text())
    for raw in data["entries"]:
        item = ConvItem(
            kind=raw["kind"],
            role=raw["role"],
            text=raw["text"],
            tool=raw.get("tool"),
            result=raw.get("result"),
            options=raw.get("options", []),
            chosen=raw.get("chosen"),
        )
        entry = model.append(item)
        state = raw.get("state")
        if state:
            entry.set_state(STATE_MAP.get(state, EntryState.DEFAULT))


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------


class StatusLine(Static):
    """Slim top status line — plain, not rich. Mirrors reyn's inline-REPL
    top-of-screen status (session id / model / turn count)."""


class ReynChatPoc(App):
    TITLE = "reyn · textual-flowview PoC"
    CSS = """
    Screen { layout: vertical; }
    StatusLine {
        height: 1;
        dock: top;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    FlowView {
        height: 1fr;
        border: round $panel;
    }
    FlowView > .flowview--selected { background: $accent 25%; }
    Input { dock: bottom; }
    """
    BINDINGS = [("ctrl+d", "demo_stream", "Stream a reply")]

    def __init__(self, fixture_path: Path = CONVERSATION_FIXTURE) -> None:
        super().__init__()
        self.fixture_path = fixture_path
        self.conversation: FlowModel[ConvItem] = FlowModel()
        self._turns = 0

    def compose(self) -> ComposeResult:
        yield StatusLine("reyn-poc · session=demo · model=sonnet · turns=0")
        yield FlowView(
            model=self.conversation,
            presenter=ReynPresenter(),
            decorator=ReynGutter(),
            gutter_width=2,
            anchor=Anchor.STICKY_BOTTOM,
        )
        yield Input(placeholder="Type a message and press Enter…")

    def on_mount(self) -> None:
        # Restore-on-restart: hydrate BEFORE any new interaction happens.
        hydrate_model(self.conversation, self.fixture_path)
        self._turns = len(self.conversation)
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self.query_one(StatusLine)
        status.update(f"reyn-poc · session=demo · model=sonnet · turns={self._turns}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self.conversation.append(ConvItem(kind="message", role="user", text=text))
        self._turns += 1
        self._refresh_status()
        await self._stream_reply()

    async def action_demo_stream(self) -> None:
        await self._stream_reply()

    async def _stream_reply(self) -> None:
        entry = self.conversation.append(ConvItem(kind="message", role="assistant", text=""))
        entry.set_state(EntryState.RUNNING)
        for word in STREAM_WORDS:
            entry.item.text += (" " if entry.item.text else "") + word
            entry.update()
            await asyncio.sleep(0.03)
        entry.set_state(EntryState.SUCCESS)
        self._turns += 1
        self._refresh_status()

    def on_flow_view_clicked(self, event: FlowView.Clicked) -> None:
        item = event.entry.item
        if item.kind != "ask_user" or item.chosen is not None or event.y != 1:
            return
        for start, end, label in chip_spans(item.options):
            if start <= event.x < end:
                event.entry.set_item(
                    ConvItem(
                        kind="ask_user",
                        role=item.role,
                        text=item.text,
                        options=item.options,
                        chosen=label,
                    )
                )
                break


if __name__ == "__main__":
    ReynChatPoc().run()
