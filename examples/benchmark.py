"""Head-to-head: the same list built two ways.

Builds N variable-height entries with (a) the "obvious" approach — a Textual
`VerticalScroll` with one `Static` widget per row — and (b) a `FlowView`, and
prints build time and DOM size for each. The point is the *scaling*: the
container mounts N widgets (O(N) DOM / layout), FlowView paints (O(viewport),
one widget regardless of N).

Run:  PYTHONPATH=src python examples/benchmark.py
"""

from __future__ import annotations

import asyncio
import gc
import time

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from textual_flowview import Entry, FlowModel, FlowView, Presentation

N_VALUES = [100, 400, 1000, 2000]
SIZE = (90, 30)


def _content(i: int) -> str:
    # Variable height: every 3rd row is taller.
    return f"row {i}\n  detail line" + ("\n  more detail" if i % 3 == 0 else "")


class Row:
    __slots__ = ("i",)

    def __init__(self, i: int) -> None:
        self.i = i


class RowPresenter:
    async def present(self, entry: Entry[Row], width: int) -> Presentation:
        item = entry.item
        text = _content(item.i)
        return Presentation(height=text.count("\n") + 1, renderable=Text(text))


async def _relayout_ms(pilot) -> float:
    # A resize forces a full re-layout — O(N) arrange for the container (every
    # child re-arranged), O(viewport) for FlowView. This is the per-frame cost
    # that makes a big live/scrolling list feel heavy.
    start = time.perf_counter()
    for w, h in ((SIZE[0] - 20, SIZE[1]), SIZE):
        await pilot.resize_terminal(w, h)
        await pilot.pause()
    return (time.perf_counter() - start) * 1000


async def bench_container(n: int) -> tuple[float, int, float]:
    class ContainerApp(App):
        def compose(self) -> ComposeResult:
            self.vs = VerticalScroll()
            yield self.vs

        async def on_mount(self) -> None:
            await self.vs.mount_all([Static(Text(_content(i))) for i in range(n)])

    gc.collect()
    app = ContainerApp()
    start = time.perf_counter()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.pause()
        build_ms = (time.perf_counter() - start) * 1000
        widgets = len(app.screen.query("*"))
        relayout = await _relayout_ms(pilot)
    return build_ms, widgets, relayout


async def bench_flowview(n: int) -> tuple[float, int, float]:
    gc.collect()
    start = time.perf_counter()
    model: FlowModel[Row] = FlowModel()
    for i in range(n):
        model.append(Row(i))   # O(1) each — no view attached yet

    class FlowApp(App):
        def compose(self) -> ComposeResult:
            yield FlowView(model=model, presenter=RowPresenter(), spacing=0)

    app = FlowApp()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.pause()
        build_ms = (time.perf_counter() - start) * 1000
        widgets = len(app.screen.query("*"))
        relayout = await _relayout_ms(pilot)
    return build_ms, widgets, relayout


async def main() -> None:
    print(f"{'N':>6} │ {'build: cont':>12} {'flow':>7} │ "
          f"{'widgets: cont':>14} {'flow':>5} │ {'re-layout: cont':>16} {'flow':>7} │ {'speedup':>7}")
    print("─" * 92)
    for n in N_VALUES:
        c_ms, c_widgets, c_relay = await bench_container(n)
        f_ms, f_widgets, f_relay = await bench_flowview(n)
        speedup = c_relay / f_relay if f_relay else float("inf")
        print(f"{n:>6} │ {c_ms:>9.0f}ms {f_ms:>5.0f}ms │ "
              f"{c_widgets:>14,} {f_widgets:>5,} │ {c_relay:>13.0f}ms {f_relay:>5.0f}ms │ {speedup:>5.1f}×")


if __name__ == "__main__":
    asyncio.run(main())
