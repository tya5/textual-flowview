"""textual-flowview group demo — a collapsible, nested CI pipeline.

FlowView owns the tree: `model.append(item, parent=entry)` (or
`entry.append_child(item)`) nests to any depth, and `entry.collapse()` folds a
subtree away. Folding keeps every descendant's cached presentation, so it never
re-presents what it hides, and a whole batch of folds is one reflow.

A parent is an **ordinary entry** — same presenter, same gutter, no special
case. The only things it has that a leaf doesn't are `entry.children` and
`entry.collapsed`, and the presenter reads both because it receives the entry.
Indentation is likewise yours: FlowView hands you `entry.depth` and leaves the
drawing alone.

Run:  PYTHONPATH=src python examples/groups.py
Keys: q quit · click a header to fold it
      za fold/unfold here · zo unfold · zc fold · zR unfold all · zM fold all
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import (
    Entry,
    EntryState,
    FlowModel,
    FlowView,
    Presentation,
    StateDecorator,
)


@dataclass
class Node:
    label: str
    detail: str = ""


class PipelinePresenter:
    async def present(self, entry: Entry[Node], width: int) -> Presentation:
        item = entry.item
        indent = "  " * entry.depth          # depth is FlowView's; indenting is ours
        if entry.children:
            chevron = "▸" if entry.collapsed else "▾"
            line = Text.assemble(
                (f"{indent}{chevron} ", "bold cyan"),
                (item.label, "bold"),
                (f"    {len(entry.children)} steps", "grey50"),
            )
        else:
            line = Text.assemble(
                (f"{indent}  ", ""),
                (item.label, "bold grey85"),
                ("   ", ""),
                (item.detail, "grey50"),
            )
        return Presentation(height=1, renderable=line)


# Gutter markers only for leaf steps; group headers stay blank.
class PipelineGutter(StateDecorator):
    def decorate(self, entry: Entry[Node], width: int, height: int) -> RenderableType:
        if entry.children:
            return Text(" ")
        return super().decorate(entry, width, height)


# label, detail, state, [nested children]
Step = tuple[str, str, EntryState, list["Step"]]

PIPELINE: list[Step] = [
    ("Build", "", EntryState.SUCCESS, [
        ("checkout", "actions/checkout@v4 · 0.4s", EntryState.SUCCESS, []),
        ("setup-python", "3.11 / 3.12 / 3.13 · 6s", EntryState.SUCCESS, []),
        ("install", "pip install -e .[dev] · 11s", EntryState.SUCCESS, []),
    ]),
    ("Lint & Types", "", EntryState.SUCCESS, [
        ("ruff", "src tests · clean", EntryState.SUCCESS, []),
        ("mypy", "src · strict · 0 errors", EntryState.SUCCESS, []),
    ]),
    ("Test", "", EntryState.RUNNING, [
        # a group inside a group — nesting is arbitrary
        ("unit", "", EntryState.SUCCESS, [
            ("pytest py3.11", "58 passed · 1.7s", EntryState.SUCCESS, []),
            ("pytest py3.12", "58 passed · 1.6s", EntryState.SUCCESS, []),
            ("pytest py3.13", "running…", EntryState.RUNNING, []),
        ]),
        ("integration", "", EntryState.DEFAULT, [
            ("wezterm", "queued", EntryState.DEFAULT, []),
            ("kitty", "queued", EntryState.DEFAULT, []),
        ]),
    ]),
    ("Deploy", "", EntryState.DEFAULT, [
        ("build wheel", "hatchling · py3-none-any", EntryState.SUCCESS, []),
        ("upload", "waiting on test", EntryState.DEFAULT, []),
        ("smoke test", "skipped", EntryState.CANCELLED, []),
    ]),
]


class GroupsApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "nested groups · fold with za/zo/zc/zR/zM"
    CSS = """
    Screen { background: $surface; }
    FlowView { height: 1fr; padding: 1 2; scrollbar-gutter: stable; }
    FlowView > .flowview--highlight { background: $accent 20%; }
    FlowView > .flowview--sticky-header { background: $panel; }
    """
    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self) -> None:
        super().__init__()
        self.pipeline: FlowModel[Node] = FlowModel()

    def compose(self) -> ComposeResult:
        yield Header()
        yield FlowView(
            model=self.pipeline,
            presenter=PipelinePresenter(),
            decorator=PipelineGutter(),
            gutter_width=2,
            selectable=True,   # click a group header to fold/unfold it
            sticky_header=lambda e: bool(e.children) and e.depth == 0,
        )
        yield Footer()

    def on_mount(self) -> None:
        self._build(PIPELINE, parent=None)

    def _build(self, steps: list[Step], parent: Entry[Node] | None) -> None:
        for label, detail, state, children in steps:
            # Pad leaf groups so the flow scrolls and the sticky header earns
            # its keep.
            padded = children + (
                [(f"check {i}", "ok", EntryState.SUCCESS, []) for i in range(1, 5)]
                if children and not any(c[3] for c in children)
                else []
            )
            entry = self.pipeline.append(Node(label, detail), parent=parent)
            entry.set_state(state)
            self._build(padded, parent=entry)

    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        # A header is an ordinary entry, so "did they click a group?" is just
        # "does it have children?".
        entry = event.entry
        if entry is not None and entry.children:
            entry.toggle_collapsed()
        event.control.set_current(None)

    def on_flow_view_collapsed(self, event: FlowView.Collapsed) -> None:
        state = "folded" if event.collapsed else "unfolded"
        self.notify(f"{state} {event.entry.item.label}", timeout=1.5)


if __name__ == "__main__":
    GroupsApp().run()
