from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    def __init__(self) -> None:
        self.calls = 0

    async def present(self, item: Row, width: int) -> Presentation:
        self.calls += 1
        return Presentation(height=2, renderable=Text(f"{item.text}\n."))


def _app(model, presenter) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=presenter, spacing=0)

    return FlowApp()


# -- Entry-level -----------------------------------------------------------


def test_hidden_defaults_false_and_toggles() -> None:
    m: FlowModel[Row] = FlowModel()
    e = m.append(Row("a"))
    assert e.hidden is False
    e.hide()
    assert e.hidden is True
    e.show()
    assert e.hidden is False


def test_set_hidden_does_not_bump_revision() -> None:
    m: FlowModel[Row] = FlowModel()
    e = m.append(Row("a"))
    rev = e.revision
    e.hide()
    assert e.revision == rev


def test_visibility_uses_dedicated_channel() -> None:
    m: FlowModel[Row] = FlowModel()
    events: list[str] = []

    class L:
        def on_flow_insert(self, e, i): ...
        def on_flow_update(self, e):
            events.append("update")
        def on_flow_remove(self, e, i): ...
        def on_flow_clear(self): ...
        def on_flow_decorate(self, e):
            events.append("decorate")
        def on_flow_visibility(self, e):
            events.append("visibility")

    m._attach(L())
    e = m.append(Row("a"))
    e.hide()
    e.show()
    e.hide()  # same as current after show? no -> toggles: hide,show,hide = 3
    assert events == ["visibility", "visibility", "visibility"]


def test_hide_is_idempotent() -> None:
    m: FlowModel[Row] = FlowModel()
    calls: list[str] = []

    class L:
        def on_flow_insert(self, e, i): ...
        def on_flow_update(self, e): ...
        def on_flow_remove(self, e, i): ...
        def on_flow_clear(self): ...
        def on_flow_decorate(self, e): ...
        def on_flow_visibility(self, e):
            calls.append("v")

    m._attach(L())
    e = m.append(Row("a"))
    e.hide()
    e.hide()  # no-op
    assert calls == ["v"]


def test_hide_on_dead_entry_is_noop() -> None:
    m: FlowModel[Row] = FlowModel()
    e = m.append(Row("a"))
    e.remove()
    e.hide()
    assert e.hidden is False


# -- Widget-level ----------------------------------------------------------


@pytest.mark.asyncio
async def test_hidden_entries_excluded_from_layout() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"r{i}")) for i in range(6)]  # 6 x 2 = 12
    app = _app(model, RowPresenter())
    async with app.run_test(size=(40, 40)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._viewport.total_height == 12
        entries[0].hide()
        entries[1].hide()
        await pilot.pause()
        # two 2-row items gone -> height 8, and only 4 entries laid out
        assert view._viewport.total_height == 8
        assert len(view._viewport.entries) == 4


@pytest.mark.asyncio
async def test_hidden_entry_is_not_located() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"r{i}")) for i in range(6)]
    app = _app(model, RowPresenter())
    async with app.run_test(size=(40, 40)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        entries[2].hide()
        await pilot.pause()
        assert entries[2] not in view._viewport.entries


@pytest.mark.asyncio
async def test_show_restores_without_repng() -> None:
    model: FlowModel[Row] = FlowModel()
    entries = [model.append(Row(f"r{i}")) for i in range(4)]
    presenter = RowPresenter()
    app = _app(model, presenter)
    async with app.run_test(size=(40, 40)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        baseline = presenter.calls
        entries[0].hide()
        await pilot.pause()
        entries[0].show()
        await pilot.pause()
        # showing again reuses the cached presentation: no new present() calls.
        assert presenter.calls == baseline
        assert entries[0] in view._viewport.entries


@pytest.mark.asyncio
async def test_hiding_selected_entry_clears_selection() -> None:
    model: FlowModel[Row] = FlowModel()
    a = model.append(Row("a"))
    model.append(Row("b"))
    app = _app(model, RowPresenter())
    async with app.run_test(size=(40, 40)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        view.set_current(a)
        await pilot.pause()
        a.hide()
        await pilot.pause()
        assert view.current is None


@pytest.mark.asyncio
async def test_group_collapse_hides_a_run() -> None:
    # A header hiding its children is just a batch of hide() calls.
    model: FlowModel[Row] = FlowModel()
    header = model.append(Row("== group =="))
    children = [model.append(Row(f"child-{i}")) for i in range(5)]
    app = _app(model, RowPresenter())
    async with app.run_test(size=(40, 40)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        for child in children:
            child.hide()
        await pilot.pause()
        assert view._viewport.entries == [header]
        for child in children:
            child.show()
        await pilot.pause()
        assert len(view._viewport.entries) == 6
