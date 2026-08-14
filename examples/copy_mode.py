"""textual-flowview text-cursor demo — a vim-style cursor over the flow.

`FlowView` has a **text cursor**: a character cursor you move over the rendered
content (across entries), with a **visual mode** (v/V … y) for selection and yank
— like vim visual. The movement keys are always live; **`c` shows/hides** the
cursor block. Everything is **public methods / overridable bindings**, so the
consumer decides which keys drive it.

The cursor is synced with the entry highlight (moving it moves `current`), except
during a visual selection, when the highlight is frozen so the content you saw at
`v` doesn't shift while you select.

To use different keys, subclass FlowView and override `BINDINGS` (actions like
`cursor_left` / `cursor_word_forward` / `visual` / `yank`).

Run:  PYTHONPATH=src python examples/copy_mode.py
Keys: c show/hide cursor · h/j/k/l move · w/b/e word · 0/$/^ line · g/G ends
      v visual · V visual-line · y yank · zz/zt/zb scroll · Esc cancel · q quit
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import Entry, FlowModel, FlowView, Presentation

LINES = [
    "The quick brown fox jumps over the lazy dog.",
    "日本語の行も選択できます（全角も1セル境界で崩れない）。",
    "def render_line(self, y): return self._compose(y)",
    "emoji 🎉 and 漢字 ABC 123 mixed in one line",
    "Press c to show the cursor — h/j/k/l move, v to select, y to yank.",
    "g jumps to the top, G to the bottom, zz centres the row.",
    "Every motion is a public method; every key is yours to rebind.",
]


@dataclass
class Para:
    text: str


class ParaPresenter:
    async def present(self, entry: Entry[Para], width: int) -> Presentation:
        item = entry.item
        return Presentation(height=1, renderable=Text(item.text))


class CopyModeApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "text cursor — press c to show it"
    CSS = """
    FlowView { height: 1fr; padding: 0 1; }
    FlowView > .flowview--highlight { background: $accent 25%; }
    /* the text cursor / selection uses Textual's screen--selection */
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.doc: FlowModel[Para] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        # `c` (built into FlowView) toggles the cursor; selectable=True syncs the
        # entry highlight with it.
        self.view: FlowView[Para] = FlowView(
            model=self.doc, presenter=ParaPresenter(), spacing=1,
            estimated_height=1, selectable=True,
        )
        yield self.view
        yield Footer()

    def on_mount(self) -> None:
        for line in LINES:
            self.doc.append(Para(line))
        self.view.focus()


if __name__ == "__main__":
    CopyModeApp().run()
