from __future__ import annotations

from dataclasses import dataclass

from textual_flowview import Anchor, Entry, FlowModel


@dataclass
class Msg:
    text: str


class RecordingListener:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def on_flow_insert(self, entry: Entry, index: int) -> None:
        self.events.append(("insert", entry.id, index))

    def on_flow_update(self, entry: Entry) -> None:
        self.events.append(("update", entry.id, entry.revision))

    def on_flow_remove(self, entry: Entry, index: int) -> None:
        self.events.append(("remove", entry.id, index))

    def on_flow_clear(self) -> None:
        self.events.append(("clear",))


def test_append_returns_entry_with_stable_id() -> None:
    m: FlowModel[Msg] = FlowModel()
    a = m.append(Msg("a"))
    b = m.append(Msg("b"))
    assert a.id != b.id
    assert [e.id for e in m] == [a.id, b.id]


def test_insert_positions_and_ordering() -> None:
    m: FlowModel[str] = FlowModel()
    a = m.append("a")
    b = m.append("b")
    c = m.insert(1, "c")
    assert [e.item for e in m] == ["a", "c", "b"]
    assert [e.id for e in m] == [a.id, c.id, b.id]


def test_insert_clamps_out_of_range_index() -> None:
    m: FlowModel[str] = FlowModel()
    m.insert(99, "a")
    m.insert(-5, "b")
    assert [e.item for e in m] == ["b", "a"]


def test_update_bumps_revision_and_notifies() -> None:
    m: FlowModel[Msg] = FlowModel()
    listener = RecordingListener()
    m._attach(listener)
    e = m.append(Msg(""))
    e.item.text += "Hello"
    e.update()
    e.item.text += " World"
    e.update()
    assert e.revision == 2
    assert ("update", e.id, 1) in listener.events
    assert ("update", e.id, 2) in listener.events


def test_remove_is_idempotent_and_kills_entry() -> None:
    m: FlowModel[str] = FlowModel()
    e = m.append("a")
    e.remove()
    assert not e.alive
    e.remove()  # no-op, must not raise
    assert len(m) == 0


def test_update_after_remove_is_noop() -> None:
    m: FlowModel[str] = FlowModel()
    e = m.append("a")
    e.remove()
    rev = e.revision
    e.update()  # no-op
    assert e.revision == rev


def test_clear_kills_all_entries() -> None:
    m: FlowModel[str] = FlowModel()
    a = m.append("a")
    b = m.append("b")
    m.clear()
    assert len(m) == 0
    assert not a.alive and not b.alive


def test_remove_reports_correct_index() -> None:
    m: FlowModel[str] = FlowModel()
    listener = RecordingListener()
    m._attach(listener)
    m.append("a")
    mid = m.append("b")
    m.append("c")
    mid.remove()
    assert ("remove", mid.id, 1) in listener.events


def test_set_item_replaces_and_bumps_revision() -> None:
    m: FlowModel[Msg] = FlowModel()
    listener = RecordingListener()
    m._attach(listener)
    e = m.append(Msg("old"))
    rev = e.revision
    e.set_item(Msg("new"))
    assert e.item.text == "new"
    assert e.revision == rev + 1  # re-presents
    assert ("update", e.id, rev + 1) in listener.events


def test_set_item_on_dead_entry_is_noop() -> None:
    m: FlowModel[Msg] = FlowModel()
    e = m.append(Msg("old"))
    e.remove()
    e.set_item(Msg("new"))
    assert e.item.text == "old"


def test_anchor_members() -> None:
    assert set(Anchor) == {Anchor.CURRENT, Anchor.STICKY_BOTTOM, Anchor.STICKY_TOP}
