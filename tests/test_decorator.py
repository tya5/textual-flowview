from __future__ import annotations

from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import (
    EntryState,
    FlowModel,
    FlowView,
    Presentation,
    StateDecorator,
)


@dataclass
class Job:
    text: str


class CountingPresenter:
    """Counts how many times present() runs, to prove state changes don't
    re-present the body."""

    def __init__(self) -> None:
        self.calls = 0

    async def present(self, item: Job, width: int) -> Presentation:
        self.calls += 1
        return Presentation(height=2, renderable=Text(f"{item.text}\n."))


class BoomPresenter:
    async def present(self, item: Job, width: int) -> Presentation:
        raise RuntimeError("nope")


def _app(model, presenter, **kw) -> App:
    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=presenter, spacing=0, **kw)

    return FlowApp()


# -- Entry-level (no widget) ----------------------------------------------


def test_entry_defaults() -> None:
    m: FlowModel[Job] = FlowModel()
    e = m.append(Job("x"))
    assert e.state is EntryState.DEFAULT
    assert dict(e.metadata) == {}


def test_set_state_does_not_bump_revision() -> None:
    m: FlowModel[Job] = FlowModel()
    e = m.append(Job("x"))
    rev = e.revision
    e.set_state(EntryState.RUNNING)
    assert e.state is EntryState.RUNNING
    assert e.revision == rev  # body cache stays valid


def test_metadata_is_read_only_view() -> None:
    m: FlowModel[Job] = FlowModel()
    e = m.append(Job("x"))
    e.set_metadata("icon", "✓")
    e.update_metadata(badge="NEW", time="09:31")
    assert e.metadata["icon"] == "✓"
    assert e.metadata["badge"] == "NEW"
    with pytest.raises(TypeError):
        e.metadata["icon"] = "x"  # type: ignore[index]


def test_state_on_dead_entry_is_noop() -> None:
    m: FlowModel[Job] = FlowModel()
    e = m.append(Job("x"))
    e.remove()
    e.set_state(EntryState.SUCCESS)
    assert e.state is EntryState.DEFAULT


def test_state_notifies_decorate_channel() -> None:
    m: FlowModel[Job] = FlowModel()
    events: list[str] = []

    class L:
        def on_flow_insert(self, e, i): ...
        def on_flow_update(self, e):
            events.append("update")
        def on_flow_remove(self, e, i): ...
        def on_flow_clear(self): ...
        def on_flow_decorate(self, e):
            events.append("decorate")

    m._attach(L())
    e = m.append(Job("x"))
    e.set_state(EntryState.RUNNING)
    e.set_metadata("k", 1)
    assert events == ["decorate", "decorate"]  # never "update"


# -- Widget-level ----------------------------------------------------------


@pytest.mark.asyncio
async def test_state_change_does_not_repng_body() -> None:
    model: FlowModel[Job] = FlowModel()
    entry = model.append(Job("work"))
    presenter = CountingPresenter()
    app = _app(model, presenter, decorator=StateDecorator())
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        first = presenter.calls
        assert first >= 1
        entry.set_state(EntryState.RUNNING)
        entry.set_state(EntryState.SUCCESS)
        entry.set_metadata("badge", "done")
        await pilot.pause()
        # No additional present() calls from state/metadata churn.
        assert presenter.calls == first


@pytest.mark.asyncio
async def test_gutter_renders_state_symbol() -> None:
    model: FlowModel[Job] = FlowModel()
    entry = model.append(Job("work"))
    app = _app(model, CountingPresenter(), decorator=StateDecorator(), gutter_width=2)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        entry.set_state(EntryState.SUCCESS)
        await pilot.pause()
        view = app.query_one(FlowView)
        line0 = view.render_line(0)
        # gutter shows the SUCCESS marker in the first cells
        assert "✓" in line0.text


@pytest.mark.asyncio
async def test_body_width_excludes_gutter() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("work"))
    presenter = CountingPresenter()
    app = _app(model, presenter, decorator=StateDecorator(), gutter_width=3)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._body_width() == view._content_width() - 3


@pytest.mark.asyncio
async def test_gutter_does_not_collapse_heights() -> None:
    # Regression: with a gutter, presentations are cached at the body width.
    # The viewport must resolve real heights (not the estimate=1 fallback),
    # otherwise every multi-row item collapses to a single line.
    model: FlowModel[Job] = FlowModel()
    for i in range(5):
        model.append(Job(f"job-{i}"))  # each presents at height 2
    app = _app(model, CountingPresenter(), decorator=StateDecorator(), gutter_width=3)
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        view = app.query_one(FlowView)
        # 5 items x 2 rows each = 10 (not 5, which is the collapsed estimate).
        assert view._viewport.total_height == 10


@pytest.mark.asyncio
async def test_render_error_sets_error_state() -> None:
    model: FlowModel[Job] = FlowModel()
    entry = model.append(Job("bad"))
    app = _app(model, BoomPresenter(), decorator=StateDecorator())
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        assert entry.state is EntryState.ERROR


@pytest.mark.asyncio
async def test_no_decorator_means_no_gutter() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("work"))
    app = _app(model, CountingPresenter())  # no decorator
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._gutter_width == 0
        assert view._body_width() == view._content_width()


# -- Right / dual gutter ---------------------------------------------------


class MarkDecorator:
    """A gutter that fills its width with a single marker char, so we can spot
    it on either edge of the rendered line."""

    def __init__(self, char: str) -> None:
        self.char = char

    def decorate(self, entry: object, width: int, height: int) -> Text:
        return Text("\n".join(self.char * width for _ in range(max(1, height))))


@pytest.mark.asyncio
async def test_right_gutter_renders_on_right_edge() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("work"))
    app = _app(
        model,
        CountingPresenter(),
        right_decorator=MarkDecorator("R"),
        right_gutter_width=2,
    )
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._gutter_width == 0  # nothing on the left
        assert view._right_gutter_width == 2
        assert view._body_width() == view._content_width() - 2
        line0 = view.render_line(0).text
        assert line0[:1] != "R"  # left edge is body, not gutter
        assert line0[-2:] == "RR"  # right edge is the gutter


@pytest.mark.asyncio
async def test_both_gutters_are_independent() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("work"))
    app = _app(
        model,
        CountingPresenter(),
        decorator=MarkDecorator("L"),
        gutter_width=2,
        right_decorator=MarkDecorator("R"),
        right_gutter_width=3,
    )
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        assert view._body_width() == view._content_width() - 2 - 3
        line0 = view.render_line(0).text
        assert line0[:2] == "LL"
        assert line0[-3:] == "RRR"
        assert "work" in line0  # body still drawn between the gutters


@pytest.mark.asyncio
async def test_gutter_visibility_toggles_independently() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("work"))
    app = _app(
        model,
        CountingPresenter(),
        decorator=MarkDecorator("L"),
        gutter_width=2,
        right_decorator=MarkDecorator("R"),
        right_gutter_width=3,
    )
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        full = view._content_width()
        assert view.left_gutter_visible and view.right_gutter_visible
        assert view._body_width() == full - 2 - 3

        # hide the left gutter -> its width goes back to the body
        view.hide_gutter("left")
        await pilot.pause()
        assert view.left_gutter_visible is False
        assert view._body_width() == full - 3  # only the right gutter remains
        line = view.render_line(0).text
        assert line[:1] != "L"
        assert line[-3:] == "RRR"

        # hide the right gutter too -> body spans the whole width
        view.hide_gutter("right")
        await pilot.pause()
        assert view._body_width() == full
        assert view.render_line(0).text.rstrip()[-1:] != "R"

        # toggle the left back on
        assert view.toggle_gutter("left") is True
        await pilot.pause()
        assert view._body_width() == full - 2
        assert view.render_line(0).text[:2] == "LL"

        # configured widths are untouched by hiding
        assert view._gutter_width == 2 and view._right_gutter_width == 3


@pytest.mark.asyncio
async def test_set_gutter_visible_same_state_is_noop() -> None:
    model: FlowModel[Job] = FlowModel()
    model.append(Job("work"))
    presenter = CountingPresenter()
    app = _app(model, presenter, decorator=MarkDecorator("L"), gutter_width=2)
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        view = app.query_one(FlowView)
        calls = presenter.calls
        view.set_gutter_visible("left", True)  # already visible
        await pilot.pause()
        assert presenter.calls == calls  # no reflow / re-present
