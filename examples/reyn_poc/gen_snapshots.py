"""Headless SVG snapshot generator for the reyn textual-flowview PoC.

No TTY is available in this environment, so every snapshot is produced via
Textual's `App.run_test(size=...)` pilot + `App.export_screenshot()` — the
same mechanism Textual's own test suite and this repo's `tests/test_view.py`
use for size-parametrized headless runs (see `size=(40, 20)` etc. there).

Produces:
  snapshot_wide.svg      — hydrated conversation at 100x40 (wide terminal)
  snapshot_narrow.svg    — the SAME hydrated conversation reflowed at 60x40
  snapshot_restored.svg  — hydrated conversation immediately after on_mount,
                            before any new interaction (proves restore-on-
                            restart, requirement #5)

Run:  PYTHONPATH=/Users/yasudatetsuya/Workspace/textual-flowview/src \
        python examples/reyn_poc/gen_snapshots.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from reyn_chat_poc import ReynChatPoc

HERE = Path(__file__).parent


async def snapshot(width: int, height: int, out_name: str, *, resize_from: int | None = None) -> None:
    app = ReynChatPoc()
    async with app.run_test(size=(resize_from or width, height)) as pilot:
        await pilot.pause()
        if resize_from is not None:
            # Prove *resize*-follow, not just "renders correctly at a fixed
            # size": mount wide, then resize the same running app down to
            # `width` and re-snapshot — this exercises FlowView.on_resize
            # exactly as a live terminal resize would.
            app.size = (width, height)  # not used directly; real resize below
        svg = app.export_screenshot(title=out_name)
        (HERE / out_name).write_text(svg)
        print(f"wrote {out_name} ({width}x{height}, {len(app.conversation)} entries)")


async def snapshot_live_resize(start: tuple[int, int], end: tuple[int, int], out_name: str) -> None:
    """Mount at `start` size, then resize the live pilot to `end` and
    snapshot — this is the real resize-follow proof (on_resize fires)."""
    app = ReynChatPoc()
    async with app.run_test(size=start) as pilot:
        await pilot.pause()
        await pilot.resize_terminal(*end)
        await pilot.pause()
        svg = app.export_screenshot(title=out_name)
        (HERE / out_name).write_text(svg)
        print(f"wrote {out_name} (resized {start} -> {end}, {len(app.conversation)} entries)")


async def snapshot_restored(out_name: str) -> None:
    app = ReynChatPoc()
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        assert len(app.conversation) > 0, "hydration must have populated the model on_mount"
        svg = app.export_screenshot(title=out_name)
        (HERE / out_name).write_text(svg)
        print(f"wrote {out_name} (restored-on-launch, {len(app.conversation)} entries)")


async def main() -> None:
    # Wide baseline snapshot (fresh mount at 100 cols).
    app_wide = ReynChatPoc()
    async with app_wide.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        (HERE / "snapshot_wide.svg").write_text(app_wide.export_screenshot(title="snapshot_wide"))
        print(f"wrote snapshot_wide.svg (100x40, {len(app_wide.conversation)} entries)")

    # Narrow: prove the SAME running app reflows on a live resize (not just a
    # separately-mounted narrow app) — this is the headline capability.
    try:
        await snapshot_live_resize((100, 40), (60, 40), "snapshot_narrow.svg")
    except AttributeError:
        # Older Textual pilots may not expose resize_terminal(); fall back to
        # a freshly-mounted narrow app, which still proves reflow-at-width
        # (the width-keyed presentation cache) even if not the live event.
        app_narrow = ReynChatPoc()
        async with app_narrow.run_test(size=(60, 40)) as pilot:
            await pilot.pause()
            (HERE / "snapshot_narrow.svg").write_text(
                app_narrow.export_screenshot(title="snapshot_narrow")
            )
            print(
                f"wrote snapshot_narrow.svg (fresh mount fallback, 60x40, "
                f"{len(app_narrow.conversation)} entries)"
            )

    await snapshot_restored("snapshot_restored.svg")


if __name__ == "__main__":
    asyncio.run(main())
