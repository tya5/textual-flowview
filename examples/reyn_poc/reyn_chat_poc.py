"""De-risking PoC: reyn TUI conversation pane on textual-flowview.

Evaluates whether textual-flowview's FlowView fits reyn's TUI as a
replacement for the current prompt_toolkit + rich inline REPL conversation
pane. This file is a STANDALONE PoC — it does not import or modify anything
from the reyn repository.

Layout: a slim status line (top), a scrollable FlowView (main, the ONLY rich
widget), and a bottom multi-line Composer — Claude-Code-like chrome, not a
multi-panel dashboard.

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
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Static, TextArea

from textual_flowview import (
    Anchor,
    Entry,
    EntryState,
    FlowModel,
    FlowView,
    Presentation,
)

HERE = Path(__file__).parent
CONVERSATION_FIXTURE = HERE / "conversation.json"

# --------------------------------------------------------------------------
# reyn's own Claude-Code-style palette, copied verbatim from
# `src/reyn/interfaces/repl/renderer.py` (read-only reference — that file is
# NOT imported or modified). Restyling this PoC to match reyn's own renderer
# per owner feedback: too cluttered, de-frame it, dot-gutter it.
# --------------------------------------------------------------------------
_CC_TEXT = "default"    # terminal default fg — normal text + markers (no forced colour)
_CC_DIM = "#6b7280"     # low-importance / ambient
_CC_DONE = "#7ee787"    # green — completion / success
_CC_ERR = "#f97066"     # red — failure / error
_CC_WARN = "#e3b341"    # amber — an intervention that needs the user to act / running
_CC_USER_BG = "#2b2f37"  # subtle full-width background block behind the user's own line

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
    """Turns a ConvItem into a bare renderable sized to the available width —
    NO Panel/box, NO role-label text. Claude-Code style: the gutter dot
    (painted by ``ReynGutter``) plus, for the user's own line, a full-width
    background block are the only visual affordances distinguishing message
    kinds.

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
        # No "You" / "Assistant" title, no Panel — just the body. Assistant
        # replies render as markdown (reyn's `_body_renderable` does the
        # same for "agent"-kind bodies); the user's own line is plain text.
        # The user's line gets a full-row background via Presentation.background,
        # which FlowView paints edge to edge across gutter + body — no more
        # hand-rolled expand=True grid, and no gutter-background coordination.
        body: RenderableType = Text(item.text or " ", style=_CC_DIM) if is_user else Markdown(item.text or " ")
        return Presentation(
            height=self._measure(body, width),
            renderable=body,
            background=_CC_USER_BG if is_user else None,
        )

    def _present_tool_call(self, item: ConvItem, width: int) -> Presentation:
        head = Text.assemble(
            (f"{item.tool}", f"bold {_CC_DIM}"),
            ("  ", ""),
            (item.text, _CC_DIM),
        )
        lines: list[RenderableType] = [head]
        if item.result:
            lines.append(Text(f"  └─ {item.result}", style=_CC_DIM))
        group = Group(*lines)
        return Presentation(height=self._measure(group, width), renderable=group)

    def _present_ask_user(self, item: ConvItem, width: int) -> Presentation:
        head = Text(item.text, style=_CC_TEXT)
        if item.chosen is None:
            chips = Text(" " * CHIP_INDENT)
            for i, label in enumerate(item.options):
                chips.append(_chip(i, label), style=f"bold {_CC_WARN}")
                chips.append(" " * CHIP_GAP)
            body = Group(head, chips, Text("  ↑ click an option", style=_CC_DIM))
            return Presentation(height=3, renderable=body)
        resolved = Text.assemble(("  ✓ resolved: ", _CC_DIM), (item.chosen, f"bold {_CC_DONE}"))
        return Presentation(height=2, renderable=Group(head, resolved))


class ReynGutter:
    """Claude-Code-style gutter: a single colored ● per :class:`EntryState`.

    Implements the library's :class:`FlowDecorator` protocol directly
    (``decorate(entry, width, height) -> RenderableType``) rather than
    reusing ``StateDecorator``'s glyph set, because reyn's own renderer uses
    one uniform ● dot colored by state — not a different glyph per state.
    The user row's continuous background (gutter + body) is now handled by
    FlowView via ``Presentation.background`` — the gutter no longer paints its
    own background to match.
    """

    _STATE_COLOR: dict[EntryState, str] = {
        EntryState.DEFAULT: _CC_DIM,
        EntryState.RUNNING: _CC_WARN,
        EntryState.SUCCESS: _CC_DONE,
        EntryState.ERROR: _CC_ERR,
        EntryState.CANCELLED: _CC_DIM,
    }

    def decorate(self, entry: Entry[ConvItem], width: int, height: int) -> RenderableType:
        color = self._STATE_COLOR.get(entry.state, _CC_DIM)
        return Text("●".ljust(width), style=color)


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


class Composer(TextArea):
    """Multi-line, Claude-Code-style input composer.

    ``TextArea`` normally inserts a newline on plain ``enter`` (see
    ``TextArea._on_key`` in textual's own source, which maps the ``enter``
    key to an inline ``"\\n"`` insert). This PoC wants the opposite —
    chat-composer convention: **Enter submits**, **Shift+Enter inserts a
    newline** — so ``_on_key`` is overridden to intercept both keys before
    they reach the base implementation, and every other key (printable
    chars, backspace, arrows, tab, …) falls through to
    ``TextArea._on_key``/normal bindings unchanged.

    Auto-grows in height as the wrapped line count increases, capped at
    ``MAX_ROWS`` — past that the TextArea's own internal viewport scrolls,
    same as any bounded chat composer.
    """

    MAX_ROWS = 6

    class Submitted(Message):
        """Posted when the user presses Enter with non-empty content."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def on_mount(self) -> None:
        self.show_line_numbers = False
        self._sync_height()

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            text = self.text
            if text.strip():
                self.post_message(self.Submitted(text))
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            start, end = self.selection
            self._replace_via_keyboard("\n", start, end)
            return
        await super()._on_key(event)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._sync_height()

    def _sync_height(self) -> None:
        # +2 for the top/bottom border rows; clamp to [1, MAX_ROWS] wrapped
        # content rows so the composer auto-grows then internally scrolls.
        wrapped_rows = max(self.wrapped_document.height, 1)
        self.styles.height = min(wrapped_rows, self.MAX_ROWS) + 2

    def clear_and_reset(self) -> None:
        self.text = ""
        self._sync_height()


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
        scrollbar-size-vertical: 0;
    }
    FlowView > .flowview--selected { background: $accent 25%; }
    Composer {
        dock: bottom;
        height: 3;
        max-height: 8;
        border: round $panel;
    }
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
        yield Composer(placeholder="Type a message — Enter to send, Shift+Enter for a newline…")

    def on_mount(self) -> None:
        # Restore-on-restart: hydrate BEFORE any new interaction happens.
        hydrate_model(self.conversation, self.fixture_path)
        self._turns = len(self.conversation)
        self._refresh_status()

    def _refresh_status(self) -> None:
        status = self.query_one(StatusLine)
        status.update(f"reyn-poc · session=demo · model=sonnet · turns={self._turns}")

    async def on_composer_submitted(self, event: Composer.Submitted) -> None:
        text = event.value.strip()
        self.query_one(Composer).clear_and_reset()
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
