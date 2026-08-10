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


def test_release_drops_cache_but_keeps_last_known_height() -> None:
    # release() is for an entry still in the model whose cached render became
    # unreachable: forget the render, keep the height so the layout stays put.
    layout: FlowLayout[str] = FlowLayout()
    layout.store(7, 80, 0, _p(3))
    layout.store(7, 100, 0, _p(4))
    layout.store(9, 80, 0, _p(2))
    layout.release(7)
    assert len(layout) == 1                        # both widths dropped
    assert layout.last_known_height(7) == 4        # ...but the height survives
    assert layout.last_known_height(9) == 2


def test_discard_forgets_the_height_too() -> None:
    layout: FlowLayout[str] = FlowLayout()
    layout.store(7, 80, 0, _p(3))
    layout.discard(7)
    assert layout.last_known_height(7) is None


def test_index_stays_in_sync_across_store_discard_release_retain() -> None:
    # The per-entry index makes store/discard/release proportional to one
    # entry's keys instead of the whole cache; it must not drift from _cache.
    layout: FlowLayout[str] = FlowLayout()
    layout.store(1, 80, 0, _p(3))
    layout.store(1, 100, 0, _p(4))
    layout.store(2, 80, 0, _p(2))

    def consistent() -> bool:
        indexed = {k for keys in layout._by_entry.values() for k in keys}
        return indexed == set(layout._cache)

    assert consistent()
    layout.store(1, 80, 1, _p(5))          # supersede a revision
    assert consistent() and len(layout) == 3
    layout.release(1)
    assert consistent() and len(layout) == 1
    layout.store(1, 80, 2, _p(6))
    layout.discard(1)
    assert consistent() and len(layout) == 1
    layout.store(3, 100, 0, _p(1))
    layout.retain_width(80)
    assert consistent()
    layout.clear()
    assert consistent() and layout._by_entry == {}
