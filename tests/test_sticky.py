from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Node:
    kind: str   # "header" | "step"
    label: str


class NodePresenter:
    async def present(self, item: Node, width: int) -> Presentation:
        if item.kind == "header":
            return Presentation(height=2, renderable=Text(f"{item.label}\n="))
        return Presentation(height=1, renderable=Text(item.label))


def _is_header(entry) -> bool:
    return entry.item.kind == "header"


def _app(model, sticky=True) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(
                model=model,
                presenter=NodePresenter(),
                sticky_header=_is_header if sticky else None,
                spacing=0,
            )

    return FlowApp()


def _build() -> FlowModel[Node]:
    m: FlowModel[Node] = FlowModel()
    m.append(Node("header", "H0"))          # rows 0-1
    for i in range(3):
        m.append(Node("step", f"s{i}"))     # rows 2,3,4
    m.append(Node("header", "H1"))          # rows 5-6
    for i in range(3):
        m.append(Node("step", f"t{i}"))     # rows 7,8,9
    return m


@pytest.mark.asyncio
async def test_active_header_is_the_group_being_scrolled() -> None:
    model = _build()
    app = _app(model)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        headers = view.find(_is_header)

        # At the very top, H0 is active with no push.
        assert view._sticky_state(0) == (headers[0], 2, 0)
        # Scrolled inside group 0 (H0 above the fold): still H0 pinned.
        assert view._sticky_state(3) == (headers[0], 2, 0)
        # Scrolled into group 1: H1 becomes the pinned header.
        state = view._sticky_state(7)
        assert state is not None and state[0] is headers[1]


@pytest.mark.asyncio
async def test_next_header_pushes_the_pinned_one_up() -> None:
    model = _build()
    app = _app(model)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        headers = view.find(_is_header)
        # H1 top is row 5; header is 2 tall. At scroll 4, gap = 5-4 = 1 < 2,
        # so the pinned H0 is pushed up by 1 row.
        assert view._sticky_state(4) == (headers[0], 2, 1)


@pytest.mark.asyncio
async def test_sticky_overlays_the_top_row() -> None:
    model = _build()
    app = _app(model)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        view.scroll_to(y=3, animate=False)  # top of content is step s1 (row 3)
        await pilot.pause()
        # Row 0 shows the pinned header, not the scrolled step.
        assert "H0" in view.render_line(0).text


@pytest.mark.asyncio
async def test_disabled_by_default() -> None:
    model = _build()
    app = _app(model, sticky=False)
    async with app.run_test(size=(30, 12)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._sticky_state(3) is None
