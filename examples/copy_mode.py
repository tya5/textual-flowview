"""textual-flowview copy-mode demo — a vim-style text cursor over the flow.

`FlowView` has an opt-in **copy mode**: a character cursor you move over the
rendered content (across entries), with a visual selection and yank — like tmux
copy-mode / vim visual. It's a first-class feature: the motions are **public
methods / actions**, and the keys are **default, overridable bindings** that are
live only while in copy mode (so they bubble to your app otherwise). The
consumer decides whether to expose it and which keys drive it.

Here the app binds `c` to enter copy mode and leaves the vim defaults in place.
To use different keys, subclass FlowView and override `BINDINGS` (the motions are
actions like `copy_left` / `copy_word_forward` / `copy_yank`) — keybinding policy
stays the product's.

Run:  PYTHONPATH=src python examples/copy_mode.py
Keys: c enter copy-mode · then h/j/k/l move · w/b/e word · 0/$/^ line · gg/G ends
      v visual · V visual-line · y yank · zz/zt/zb scroll · Esc leave · q quit
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import FlowModel, FlowView, Presentation

LINES = [
    "The quick brown fox jumps over the lazy dog.",
    "日本語の行も選択できます（全角も1セル境界で崩れない）。",
    "def render_line(self, y): return self._compose(y)",
    "emoji 🎉 and 漢字 ABC 123 mixed in one line",
    "Press c, then move with h/j/k/l — v to select, y to yank.",
    "gg jumps to the top, G to the bottom, zz centres the row.",
    "Every motion is a public method; every key is yours to rebind.",
]


@dataclass
class Para:
    text: str


class ParaPresenter:
    async def present(self, item: Para, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item.text))


class CopyModeApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "copy mode — press c"
    CSS = """
    FlowView { height: 1fr; padding: 0 1; }
    /* the text cursor / selection uses Textual's screen--selection */
    """
    BINDINGS = [
        ("c", "copy", "Copy-mode"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.doc: FlowModel[Para] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        self.view: FlowView[Para] = FlowView(
            model=self.doc, presenter=ParaPresenter(), spacing=1, estimated_height=1
        )
        yield self.view
        yield Footer()

    def on_mount(self) -> None:
        for line in LINES:
            self.doc.append(Para(line))
        self.view.focus()

    def action_copy(self) -> None:
        self.view.enter_copy_mode()

    def on_flow_view_copy_mode_changed(self, event: FlowView.CopyModeChanged) -> None:
        # Keep the chrome in sync on both edges — including the Esc exit that
        # happens inside the widget.
        self.sub_title = (
            "copy mode — h/j/k/l move · v select · y yank · Esc leave"
            if event.copy_mode
            else "copy mode — press c"
        )


if __name__ == "__main__":
    CopyModeApp().run()
