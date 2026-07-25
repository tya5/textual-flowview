from __future__ import annotations

from rich.text import Text

from textual_flowview import Anchor, FlowModel, Presentation
from textual_flowview._layout import FlowLayout
from textual_flowview._viewport import Viewport


def _p(height: int) -> Presentation:
    return Presentation(height=height, renderable=Text("x"))


def _make(n: int, anchor: Anchor = Anchor.CURRENT, height: int = 10, width: int = 80):
    m: FlowModel[str] = FlowModel()
    entries = [m.append(f"item-{i}") for i in range(n)]
    layout: FlowLayout[str] = FlowLayout()
    vp: Viewport[str] = Viewport(layout, anchor=anchor, estimated_height=1, overscan=0)
    vp.set_entries(entries)
    vp.set_size(width, height)
    return m, entries, layout, vp


def _present_all(entries, layout: FlowLayout, width: int, height: int) -> None:
    for e in entries:
        layout.store(e.id, width, e.revision, _p(height))


def test_estimated_height_before_present() -> None:
    _, entries, layout, vp = _make(100)
    # nothing presented yet → estimate 1 each → total 100
    assert vp.total_height == 100


def test_total_height_uses_real_heights_when_present() -> None:
    _, entries, layout, vp = _make(10)
    _present_all(entries, layout, 80, 5)
    vp.invalidate_heights()
    assert vp.total_height == 50


def test_visible_range_basic() -> None:
    _, entries, layout, vp = _make(100, height=10)
    _present_all(entries, layout, 80, 5)  # each 5 rows
    vp.invalidate_heights()
    vp.scroll_to_offset(0)
    vr = vp.visible_range()
    # viewport 10 rows, each item 5 → items 0,1 visible (offsets 0,5; 10 excluded)
    assert vr.start == 0
    assert vr.stop == 2
    assert vr.first_offset == 0


def test_visible_range_scrolled() -> None:
    _, entries, layout, vp = _make(100, height=10)
    _present_all(entries, layout, 80, 5)
    vp.invalidate_heights()
    vp.scroll_to_offset(23)  # 23..33 → items covering rows: item4 starts 20, item5 25, item6 30
    vr = vp.visible_range()
    assert vr.entries[0] is entries[4]
    assert entries[6] in vr.entries


def test_overscan_expands_range() -> None:
    m: FlowModel[str] = FlowModel()
    entries = [m.append(f"i{i}") for i in range(100)]
    layout: FlowLayout[str] = FlowLayout()
    vp: Viewport[str] = Viewport(layout, estimated_height=1, overscan=3)
    vp.set_entries(entries)
    vp.set_size(80, 10)
    for e in entries:
        layout.store(e.id, 80, e.revision, _p(5))
    vp.invalidate_heights()
    vp.scroll_to_offset(50)  # items 10,11 in fold
    vr = vp.visible_range()
    # overscan 3 rows pulls in neighbours above/below
    assert vr.start < 10


def test_max_scroll_and_clamp() -> None:
    _, entries, layout, vp = _make(10, height=10)
    _present_all(entries, layout, 80, 5)
    vp.invalidate_heights()
    # total 50, viewport 10 → max_scroll 40
    assert vp.max_scroll == 40
    vp.scroll_to_offset(999)
    assert vp.scroll_y == 40


def test_sticky_bottom_follows_when_at_bottom() -> None:
    m: FlowModel[str] = FlowModel()
    entries = [m.append(f"i{i}") for i in range(10)]
    layout: FlowLayout[str] = FlowLayout()
    vp: Viewport[str] = Viewport(layout, anchor=Anchor.STICKY_BOTTOM, estimated_height=1)
    vp.set_entries(entries)
    vp.set_size(80, 10)
    for e in entries:
        layout.store(e.id, 80, e.revision, _p(5))
    vp.invalidate_heights()
    vp.scroll_to_bottom()
    assert vp.is_at_bottom()

    # append a new item at bottom
    state = vp.capture_anchor()
    new = m.append("i10")
    entries.append(new)
    layout.store(new.id, 80, new.revision, _p(5))
    vp.set_entries(entries)
    vp.restore_anchor(state)
    assert vp.is_at_bottom()  # followed


def test_sticky_bottom_does_not_follow_when_scrolled_up() -> None:
    m: FlowModel[str] = FlowModel()
    entries = [m.append(f"i{i}") for i in range(10)]
    layout: FlowLayout[str] = FlowLayout()
    vp: Viewport[str] = Viewport(layout, anchor=Anchor.STICKY_BOTTOM, estimated_height=1)
    vp.set_entries(entries)
    vp.set_size(80, 10)
    for e in entries:
        layout.store(e.id, 80, e.revision, _p(5))
    vp.invalidate_heights()
    vp.scroll_to_offset(5)  # user scrolled up, not at bottom
    assert not vp.is_at_bottom()

    state = vp.capture_anchor()
    new = m.append("i10")
    entries.append(new)
    layout.store(new.id, 80, new.revision, _p(5))
    vp.set_entries(entries)
    vp.restore_anchor(state)
    # position preserved to the same top entry, not yanked to bottom
    assert not vp.is_at_bottom()


def test_current_anchor_preserves_top_entry_under_height_growth_above() -> None:
    m: FlowModel[str] = FlowModel()
    entries = [m.append(f"i{i}") for i in range(20)]
    layout: FlowLayout[str] = FlowLayout()
    vp: Viewport[str] = Viewport(layout, anchor=Anchor.CURRENT, estimated_height=1, overscan=0)
    vp.set_entries(entries)
    vp.set_size(80, 10)
    for e in entries:
        layout.store(e.id, 80, e.revision, _p(5))
    vp.invalidate_heights()
    vp.scroll_to_entry(entries[10], top=True)  # top entry = i10 at offset 50
    assert vp.scroll_y == 50

    # entry above the fold grows: i2 goes 5 -> 15 (+10 rows above)
    state = vp.capture_anchor()
    entries[2].update()
    layout.store(entries[2].id, 80, entries[2].revision, _p(15))
    vp.invalidate_heights()
    vp.restore_anchor(state)
    # top entry i10 kept at same screen position → scroll shifted by +10
    assert vp.scroll_y == 60


def test_scroll_to_entry_ensure_visible() -> None:
    _, entries, layout, vp = _make(100, height=10)
    _present_all(entries, layout, 80, 5)
    vp.invalidate_heights()
    vp.scroll_to_entry(entries[50])  # offset 250, ensure visible
    vr = vp.visible_range()
    assert entries[50] in vr.entries
