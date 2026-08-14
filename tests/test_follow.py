from __future__ import annotations

import pytest
from rich.text import Text
from textual.actions import SkipAction
from textual.app import App, ComposeResult

from textual_flowview import Anchor, Entry, FlowModel, FlowView, Presentation


class P:
    async def present(self, entry: Entry[str], width: int) -> Presentation:
        item = entry.item
        return Presentation(height=1, renderable=Text(item))


class FollowApp(App):
    def __init__(self, n: int, anchor: Anchor = Anchor.STICKY_BOTTOM) -> None:
        super().__init__()
        self.model: FlowModel[str] = FlowModel()
        for i in range(n):
            self.model.append(f"row {i}")
        self._anchor = anchor
        self.events: list[bool] = []

    def compose(self) -> ComposeResult:
        self.flow = FlowView(
            model=self.model, presenter=P(), spacing=0, estimated_height=1,
            anchor=self._anchor,
        )
        yield self.flow

    def on_flow_view_follow_changed(self, event: FlowView.FollowChanged) -> None:
        self.events.append(event.following)


@pytest.mark.asyncio
async def test_early_scroll_up_releases_follow_with_no_room() -> None:
    # #12: a reader's scroll-up during early streaming must register as "leaving
    # the tail" even when max_scroll_y is still ~0 (nothing to move to). The
    # position doesn't change, so watch_scroll_y can't see it — the intent is
    # caught at the scroll event/action instead.
    app = FollowApp(3)  # all fit -> max_scroll_y == 0
    async with app.run_test(size=(30, 20)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        assert v.max_scroll_y == 0
        assert v.following is True

        try:
            v.action_scroll_up()  # no room, but the intent must register
        except SkipAction:
            pass  # Textual skips a no-op scroll; the follow release already ran
        await pilot.pause()
        assert v.following is False
        assert app.events == [False]  # FollowChanged posted once

        # streaming more content must NOT yank the reader back to the bottom
        for i in range(30):
            app.model.append(f"more {i}")
        await pilot.pause()
        await pilot.pause()
        assert v.following is False
        assert int(v.scroll_offset.y) == 0  # stayed where the reader left it


@pytest.mark.asyncio
async def test_scrolling_back_to_bottom_re_engages_follow() -> None:
    app = FollowApp(60)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        assert v.following is True  # starts pinned to the tail
        try:
            v.action_scroll_up()
        except SkipAction:
            pass
        await pilot.pause()
        assert v.following is False
        v.scroll_end(animate=False)  # back to the bottom
        await pilot.pause()
        assert v.following is True
        assert app.events == [False, True]


@pytest.mark.asyncio
async def test_following_is_false_for_non_sticky_anchor() -> None:
    app = FollowApp(5, anchor=Anchor.CURRENT)
    async with app.run_test(size=(30, 10)) as pilot:
        await pilot.pause()
        await pilot.pause()
        v = app.flow
        assert v.following is False  # only sticky anchors follow
        try:
            v.action_scroll_up()
        except SkipAction:
            pass
        await pilot.pause()
        assert app.events == []  # no FollowChanged churn for a non-sticky view
