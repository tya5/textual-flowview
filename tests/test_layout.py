from __future__ import annotations

from rich.text import Text

from textual_flowview import FlowModel, Presentation
from textual_flowview._layout import FlowLayout


def _p(height: int) -> Presentation:
    return Presentation(height=height, renderable=Text("x"))


def test_store_and_get_by_current_revision() -> None:
    m: FlowModel[str] = FlowModel()
    e = m.append("a")
    layout: FlowLayout[str] = FlowLayout()
    layout.store(e.id, 80, e.revision, _p(3))
    assert layout.height(e, 80) == 3
    assert layout.get(e, 80).height == 3


def test_miss_on_other_width() -> None:
    m: FlowModel[str] = FlowModel()
    e = m.append("a")
    layout: FlowLayout[str] = FlowLayout()
    layout.store(e.id, 80, e.revision, _p(3))
    assert layout.height(e, 100) is None


def test_stale_revision_is_a_miss() -> None:
    m: FlowModel[str] = FlowModel()
    e = m.append("a")
    layout: FlowLayout[str] = FlowLayout()
    layout.store(e.id, 80, e.revision, _p(3))
    e.update()  # revision now 1
    assert layout.get(e, 80) is None  # stored at revision 0


def test_new_revision_evicts_old_for_same_id_width() -> None:
    m: FlowModel[str] = FlowModel()
    e = m.append("a")
    layout: FlowLayout[str] = FlowLayout()
    layout.store(e.id, 80, 0, _p(3))
    layout.store(e.id, 80, 1, _p(5))
    assert len(layout) == 1


def test_discard_drops_all_widths_and_revisions() -> None:
    layout: FlowLayout[str] = FlowLayout()
    layout.store(7, 80, 0, _p(3))
    layout.store(7, 100, 0, _p(4))
    layout.store(9, 80, 0, _p(2))
    layout.discard(7)
    assert len(layout) == 1


def test_retain_width_drops_other_widths() -> None:
    layout: FlowLayout[str] = FlowLayout()
    layout.store(1, 80, 0, _p(3))
    layout.store(2, 100, 0, _p(4))
    layout.retain_width(80)
    assert len(layout) == 1
