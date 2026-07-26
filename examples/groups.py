"""textual-flowview group-collapse demo — a collapsible CI pipeline.

Group collapse is built on the library's entry-visibility primitive: a header
hides/shows its child entries with `child.hide()` / `child.show()`. Hidden
entries keep their cached presentation, so collapsing/expanding is instant and
never re-presents a body.

Run:  PYTHONPATH=src python examples/groups.py
Keys: q quit · c collapse/expand all · click a header to toggle its group
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
    kind: str            # "header" | "step"
    label: str
    detail: str = ""
    count: int = 0
    collapsed: bool = False


class PipelinePresenter:
    async def present(self, item: Node, width: int) -> Presentation:
        if item.kind == "header":
            chevron = "▸" if item.collapsed else "▾"
            line = Text.assemble(
                (f"{chevron} ", "bold cyan"),
                (item.label, "bold"),
                (f"    {item.count} steps", "grey50"),
            )
            return Presentation(height=1, renderable=line)
        line = Text.assemble(
            ("   ", ""),
            (item.label, "bold grey85"),
            ("   ", ""),
            (item.detail, "grey50"),
        )
        return Presentation(height=1, renderable=line)


# Gutter markers only for steps; headers stay blank.
class PipelineGutter(StateDecorator):
    def decorate(self, entry: Entry[Node], width: int, height: int) -> RenderableType:
        if entry.item.kind == "header":
            return Text(" ")
        return super().decorate(entry, width, height)


GROUPS: list[tuple[str, list[tuple[str, str, EntryState]]]] = [
    (
        "Build",
        [
            ("checkout", "actions/checkout@v4 · 0.4s", EntryState.SUCCESS),
            ("setup-python", "3.11 / 3.12 / 3.13 · 6s", EntryState.SUCCESS),
            ("install", "pip install -e .[dev] · 11s", EntryState.SUCCESS),
        ],
    ),
    (
        "Lint & Types",
        [
            ("ruff", "src tests · clean", EntryState.SUCCESS),
            ("mypy", "src · strict · 0 errors", EntryState.SUCCESS),
        ],
    ),
    (
        "Test",
        [
            ("pytest py3.11", "58 passed · 1.7s", EntryState.SUCCESS),
            ("pytest py3.12", "58 passed · 1.6s", EntryState.SUCCESS),
            ("pytest py3.13", "running…", EntryState.RUNNING),
        ],
    ),
    (
        "Deploy",
        [
            ("build wheel", "hatchling · py3-none-any", EntryState.SUCCESS),
            ("upload", "waiting on test", EntryState.DEFAULT),
            ("smoke test", "skipped", EntryState.CANCELLED),
        ],
    ),
]


class GroupsApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "group collapse"
    CSS = """
    Screen { background: $surface; }
    FlowView { height: 1fr; padding: 1 2; }
    FlowView > .flowview--selected { background: $accent 20%; }
    FlowView > .flowview--sticky-header { background: $panel; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "toggle_all", "Collapse / expand all"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.pipeline: FlowModel[Node] = FlowModel()
        # header entry id -> its child entries
        self._children: dict[int, list[Entry[Node]]] = {}
        self._all_collapsed = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield FlowView(
            model=self.pipeline,
            presenter=PipelinePresenter(),
            decorator=PipelineGutter(),
            gutter_width=2,
            selectable=True,   # click a group header to collapse/expand it
            sticky_header=lambda e: e.item.kind == "header",
        )
        yield Footer()

    def on_mount(self) -> None:
        for title, steps in GROUPS:
            # Pad each group with filler steps so the flow scrolls and the
            # sticky header is worth watching.
            padded = list(steps) + [
                (f"check {i}", "ok", EntryState.SUCCESS) for i in range(1, 7)
            ]
            header = self.pipeline.append(Node("header", title, count=len(padded)))
            kids: list[Entry[Node]] = []
            for label, detail, state in padded:
                child = self.pipeline.append(Node("step", label, detail))
                child.set_state(state)
                kids.append(child)
            self._children[header.id] = kids

    def action_toggle_all(self) -> None:
        self._all_collapsed = not self._all_collapsed
        for header_id, kids in self._children.items():
            header = self._header_by_id(header_id)
            if header is not None:
                self._set_group(header, kids, self._all_collapsed)

    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        entry = event.entry
        if entry is None or entry.item.kind != "header":
            return
        kids = self._children.get(entry.id, [])
        self._set_group(entry, kids, not entry.item.collapsed)
        event.control.clear_selection()

    def _set_group(
        self, header: Entry[Node], kids: list[Entry[Node]], collapsed: bool
    ) -> None:
        header.item.collapsed = collapsed
        header.update()  # redraw chevron
        for child in kids:
            child.set_hidden(collapsed)  # the group-collapse primitive

    def _header_by_id(self, header_id: int) -> Entry[Node] | None:
        for entry in self.pipeline:
            if entry.id == header_id:
                return entry
        return None


if __name__ == "__main__":
    GroupsApp().run()
