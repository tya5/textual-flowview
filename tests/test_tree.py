from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import Entry, FlowModel, FlowView, Presentation


@dataclass
class Row:
    text: str


class RowPresenter:
    def __init__(self) -> None:
        self.calls = 0

    async def present(self, entry: Entry[Row], width: int) -> Presentation:
        item = entry.item
        self.calls += 1
        return Presentation(height=2, renderable=Text(f"{item.text}\n."))


def _app(model, presenter, **kwargs) -> App:
    class FlowApp(App):
        # A fold that shrinks content below the viewport would otherwise drop
        # the scrollbar, change the body width and invalidate every cached
        # presentation; reserving the gutter keeps folding free.
        CSS = "FlowView { scrollbar-gutter: stable; }"

        def compose(self) -> ComposeResult:
            yield FlowView(
                model=model, presenter=presenter, spacing=0, selectable=True, **kwargs
            )

    return FlowApp()


def _tree() -> tuple[FlowModel[Row], dict[str, object]]:
    """a / a1 (a1x) / a2 · b / b1 — two groups, one nested two deep."""
    m: FlowModel[Row] = FlowModel()
    a = m.append(Row("a"))
    a1 = a.append_child(Row("a1"))
    a1x = a1.append_child(Row("a1x"))
    a2 = a.append_child(Row("a2"))
    b = m.append(Row("b"))
    b1 = b.append_child(Row("b1"))
    return m, dict(a=a, a1=a1, a1x=a1x, a2=a2, b=b, b1=b1)


def _texts(entries) -> list[str]:
    return [e.item.text for e in entries]


# -- structure --------------------------------------------------------------


def test_document_order_is_preorder() -> None:
    m, _ = _tree()
    assert _texts(m) == ["a", "a1", "a1x", "a2", "b", "b1"]


def test_depth_parent_children() -> None:
    m, n = _tree()
    assert [e.depth for e in m] == [0, 1, 2, 1, 0, 1]
    assert n["a1x"].parent is n["a1"]
    assert n["a"].parent is None
    assert _texts(n["a"].children) == ["a1", "a2"]
    assert _texts(n["a1x"].ancestors()) == ["a1", "a"]
    assert _texts(n["a"].descendants()) == ["a1", "a1x", "a2"]


def test_insert_index_is_among_siblings() -> None:
    m, n = _tree()
    m.insert(1, Row("a1.5"), parent=n["a"])
    assert _texts(n["a"].children) == ["a1", "a1.5", "a2"]
    # top level is unaffected, and document order stays preorder
    assert _texts(m) == ["a", "a1", "a1x", "a1.5", "a2", "b", "b1"]


def test_insert_many_under_a_parent_is_one_notification() -> None:
    m, n = _tree()
    seen: list[int] = []

    class Spy:
        def on_flow_insert_many(self, entries, index) -> None:
            seen.append(len(entries))

        def __getattr__(self, _name):
            return lambda *a, **k: None

    m._attach(Spy())
    m.extend([Row("b2"), Row("b3")], parent=n["b"])
    assert seen == [2]
    assert _texts(n["b"].children) == ["b1", "b2", "b3"]


def test_removing_a_parent_removes_its_subtree() -> None:
    m, n = _tree()
    n["a"].remove()
    assert _texts(m) == ["b", "b1"]
    assert not n["a"].alive and not n["a1"].alive and not n["a1x"].alive
    assert n["b"].alive


# -- collapse ---------------------------------------------------------------


def test_collapse_hides_the_whole_subtree_but_not_the_header() -> None:
    m, n = _tree()
    n["a"].collapse()
    assert _texts(m.visible_entries()) == ["a", "b", "b1"]
    assert n["a"].visible and not n["a1"].visible and not n["a1x"].visible
    n["a"].expand()
    assert _texts(m.visible_entries()) == ["a", "a1", "a1x", "a2", "b", "b1"]


def test_nested_collapse_state_is_remembered() -> None:
    m, n = _tree()
    n["a1"].collapse()          # fold the inner group
    n["a"].collapse()           # then the outer
    assert _texts(m.visible_entries()) == ["a", "b", "b1"]
    n["a"].expand()             # inner stays folded — its own state is intact
    assert _texts(m.visible_entries()) == ["a", "a1", "a2", "b", "b1"]


def test_collapsed_and_hidden_are_orthogonal() -> None:
    m, n = _tree()
    n["a"].collapse()
    n["a1"].hide()              # a filter hides a1 while the group is folded
    n["a"].expand()             # unfolding must not resurrect the filtered one
    assert _texts(m.visible_entries()) == ["a", "a2", "b", "b1"]
    n["a1"].show()
    assert _texts(m.visible_entries()) == ["a", "a1", "a1x", "a2", "b", "b1"]


def test_hidden_parent_hides_its_subtree() -> None:
    m, n = _tree()
    n["a"].hide()
    assert _texts(m.visible_entries()) == ["b", "b1"]
    assert not n["a1x"].visible


def test_a_leaf_records_the_fold_but_draws_nothing() -> None:
    """Folding something with no subtree changes no pixels, so it must not
    notify — but the state is still recorded, which is how "starts folded" is
    declared before the first child exists."""
    m, n = _tree()
    seen: list[int] = []

    class Spy:
        def on_flow_collapse(self, entries, collapsed) -> None:
            seen.append(len(entries))

        def __getattr__(self, _name):
            return lambda *a, **k: None

    m._attach(Spy())
    n["a2"].collapse()
    assert n["a2"].collapsed is True     # intent recorded
    assert seen == []                    # but nothing to redraw
    assert len(m.visible_entries()) == 6


def test_a_group_can_start_folded_before_its_first_child() -> None:
    m: FlowModel[Row] = FlowModel()
    group = m.append(Row("group"))
    group.collapse()                     # declared at registration time
    child = group.append_child(Row("c1"))
    assert child.visible is False, "a child of a folded parent is born folded"
    assert _texts(m.visible_entries()) == ["group"]
    group.expand()
    assert _texts(m.visible_entries()) == ["group", "c1"]


def test_gaining_or_losing_a_child_re_presents_the_parent() -> None:
    """The parent's body may draw `entry.children` — a chevron, a count — so
    becoming or growing a group is a content change for it."""
    m: FlowModel[Row] = FlowModel()
    group = m.append(Row("group"))
    assert group.revision == 0
    child = group.append_child(Row("c1"))
    assert group.revision == 1
    group.append_child(Row("c2"))
    assert group.revision == 2
    child.remove()
    assert group.revision == 3


def test_set_collapsed_many_batches_and_skips_noops() -> None:
    m, n = _tree()
    seen: list[tuple[int, bool]] = []

    class Spy:
        def on_flow_collapse(self, entries, collapsed) -> None:
            seen.append((len(entries), collapsed))

        def __getattr__(self, _name):
            return lambda *a, **k: None

    m._attach(Spy())
    m.set_collapsed_many([n["a"], n["a1"], n["a2"], n["b"]], True)
    assert seen == [(3, True)]          # a2 is a leaf -> skipped
    m.set_collapsed_many([n["a"], n["b"]], True)
    assert len(seen) == 1               # already collapsed -> no notification


# -- view -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_folding_never_re_presents_and_reflows_once() -> None:
    m: FlowModel[Row] = FlowModel()
    presenter = RowPresenter()
    parent = m.append(Row("group"))
    for i in range(50):
        parent.append_child(Row(f"child{i}"))

    async with _app(m, presenter).run_test(size=(40, 20)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        baseline = presenter.calls
        assert baseline > 1

        parent.collapse()
        await pilot.pause()
        assert len(view._viewport.entries) == 1
        # only the header re-presents (its body may draw the chevron); the 50
        # children it folded away are not touched
        assert presenter.calls == baseline + 1

        parent.expand()
        await pilot.pause()
        # the children kept their presentations, so unfolding costs the header
        assert presenter.calls == baseline + 2


@pytest.mark.asyncio
async def test_fold_without_a_stable_gutter_costs_a_width_change() -> None:
    """Folding below the viewport height drops the scrollbar, which widens the
    body and invalidates every presentation. Not fold-specific (hide() does it
    too), but folding makes it easy to hit — hence the CSS advice in the docs."""
    m: FlowModel[Row] = FlowModel()
    presenter = RowPresenter()
    parent = m.append(Row("group"))
    for i in range(50):
        parent.append_child(Row(f"child{i}"))

    class Bare(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=m, presenter=presenter, spacing=0)

    async with Bare().run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        baseline = presenter.calls
        parent.collapse()
        await pilot.pause()
        parent.expand()
        await pilot.pause()
        assert presenter.calls > baseline


@pytest.mark.asyncio
async def test_fold_keys() -> None:
    m, n = _tree()
    async with _app(m, RowPresenter()).run_test(size=(40, 20)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        view.set_current(n["a1x"])          # deep inside group a

        # za on a leaf folds the enclosing group (a1), as in vim
        await pilot.press("z", "a")
        await pilot.pause()
        assert n["a1"].collapsed
        assert view.current is n["a1"], "cursor lands on the folded header"

        await pilot.press("z", "o")         # unfold it again
        await pilot.pause()
        assert not n["a1"].collapsed

        await pilot.press("z", "M")         # fold everything
        await pilot.pause()
        assert _texts(view._viewport.entries) == ["a", "b"]

        await pilot.press("z", "R")         # unfold everything
        await pilot.pause()
        assert len(view._viewport.entries) == 6


@pytest.mark.asyncio
async def test_collapsed_message_is_posted_per_header() -> None:
    m, n = _tree()
    posted: list[tuple[str, bool]] = []

    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=m, presenter=RowPresenter(), spacing=0)

        def on_flow_view_collapsed(self, event: FlowView.Collapsed) -> None:
            posted.append((event.entry.item.text, event.collapsed))

    async with FlowApp().run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        m.set_collapsed_many([n["a"], n["b"]], True)
        await pilot.pause()
        assert posted == [("a", True), ("b", True)]


@pytest.mark.asyncio
async def test_folding_holds_the_scroll_anchor() -> None:
    m: FlowModel[Row] = FlowModel()
    tops = []
    for g in range(40):
        parent = m.append(Row(f"g{g}"))
        for i in range(5):
            parent.append_child(Row(f"g{g}c{i}"))
        tops.append(parent)

    async with _app(m, RowPresenter()).run_test(size=(40, 20)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        view.scroll_to_entry(tops[30], animate=False)
        await pilot.pause()
        vp = view._viewport
        top = vp.entries[vp.locate(view.scroll_y)[0]]

        m.set_collapsed_many(tops[:10], True)   # fold well above the viewport
        await pilot.pause()

        assert vp.entries[vp.locate(view.scroll_y)[0]] is top
        assert view.scroll_y == vp.offset_of(top)


# -- animations & tracked resources under a fold ----------------------------


@pytest.mark.asyncio
async def test_folding_pauses_animations_in_the_subtree() -> None:
    """A folded entry is off screen, so `animate_entry` must stop ticking and
    `track_visibility` must fire on_hide — otherwise folding a noisy group
    would leave its timers burning the event loop invisibly."""
    m: FlowModel[Row] = FlowModel()
    group = m.append(Row("group"))
    kids = [group.append_child(Row(f"c{i}")) for i in range(3)]
    ticks: dict[int, int] = {}
    hidden: list[int] = []
    shown: list[int] = []

    async with _app(m, RowPresenter()).run_test(size=(40, 20)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        for kid in kids:
            ticks[kid.id] = 0
            view.animate_entry(
                kid, 0.01, lambda e: ticks.__setitem__(e.id, ticks[e.id] + 1)
            )
            view.track_visibility(
                kid, on_show=lambda e: shown.append(e.id),
                on_hide=lambda e: hidden.append(e.id),
            )
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert all(v > 0 for v in ticks.values()), "should tick while visible"

        group.collapse()
        await pilot.pause()
        folded = dict(ticks)
        await asyncio.sleep(0.12)
        await pilot.pause()
        assert all(ticks[k] == folded[k] for k in ticks), "folded: must not tick"
        assert sorted(set(hidden)) == sorted(k.id for k in kids)

        group.expand()
        await pilot.pause()
        resumed = dict(ticks)
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert all(ticks[k] > resumed[k] for k in ticks), "unfolded: must resume"
        assert sorted(set(shown)) == sorted(k.id for k in kids)


@pytest.mark.asyncio
async def test_folding_an_outer_group_pauses_deeper_descendants() -> None:
    m: FlowModel[Row] = FlowModel()
    outer = m.append(Row("outer"))
    inner = outer.append_child(Row("inner"))
    deep = [inner.append_child(Row(f"d{i}")) for i in range(3)]
    ticks: dict[int, int] = {}

    async with _app(m, RowPresenter()).run_test(size=(40, 20)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        for kid in deep:
            ticks[kid.id] = 0
            view.animate_entry(
                kid, 0.01, lambda e: ticks.__setitem__(e.id, ticks[e.id] + 1)
            )
        await asyncio.sleep(0.1)
        await pilot.pause()
        assert all(v > 0 for v in ticks.values())

        outer.collapse()          # two levels above the animating entries
        await pilot.pause()
        folded = dict(ticks)
        await asyncio.sleep(0.12)
        await pilot.pause()
        assert all(ticks[k] == folded[k] for k in ticks)


@pytest.mark.asyncio
async def test_removing_a_folded_parent_releases_the_subtree_s_timers() -> None:
    m: FlowModel[Row] = FlowModel()
    group = m.append(Row("group"))
    kids = [group.append_child(Row(f"c{i}")) for i in range(3)]

    async with _app(m, RowPresenter()).run_test(size=(40, 20)) as pilot:
        view = pilot.app.query_one(FlowView)
        await pilot.pause()
        for kid in kids:
            view.animate_entry(kid, 0.01, lambda e: None)
        assert len(view._animations) == 3

        group.collapse()
        await pilot.pause()
        group.remove()            # takes the whole subtree with it
        await pilot.pause()
        assert view._animations == {}
        assert view._observers == {}
