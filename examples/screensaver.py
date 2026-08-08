"""textual-flowview screensaver — an idle-triggered viewport overlay.

Shows FlowView's **viewport overlay** API (`play_overlay` / `stop_overlay` /
`overlay_active` / `FlowView.OverlayFinished`) driving a random
[TerminalTextEffects](https://github.com/ChrisBuilds/terminaltexteffects) effect
after an idle timeout — applied to **the text the overlay is covering** (the
current screen), so the feed appears to dissolve/rain away. The overlay is
**screen-relative** (fills the visible window, doesn't scroll) and
**non-destructive**: any key/mouse dismisses it and the feed is exactly where you
left it.

FlowView stays TTE-agnostic — the app supplies a *frame factory*
`frames(width, height, covered)` where `covered` is the visible lines FlowView is
hiding (no scroll-offset math on the app's side); it converts each TTE frame (an
ANSI string) to a Rich renderable via `Text.from_ansi`. **Random selection + loop
are app policy**: `play_overlay(..., loop=True)` re-invokes the factory each cycle
(with the current screen + a fresh random effect). "Screensaver" (idle detection,
dismiss-on-input) lives entirely here, not in FlowView.

Requires:  pip install terminaltexteffects
Run:       PYTHONPATH=src python examples/screensaver.py
           (sit idle ~3s to start the saver; press any key to dismiss)
"""

from __future__ import annotations

import random
import time
from collections.abc import Iterator

from rich.console import RenderableType
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from textual_flowview import FlowModel, FlowView, Presentation

try:
    from terminaltexteffects.effects.effect_beams import Beams
    from terminaltexteffects.effects.effect_rain import Rain
    from terminaltexteffects.effects.effect_slide import Slide
    from terminaltexteffects.effects.effect_spray import Spray
except ModuleNotFoundError:  # pragma: no cover
    raise SystemExit(
        "This example needs TerminalTextEffects:  pip install terminaltexteffects"
    ) from None

EFFECTS = [Rain, Beams, Slide, Spray]
IDLE_SECONDS = 3.0


def dissolve_screen(
    width: int, height: int, covered: list[str]
) -> Iterator[RenderableType]:
    """Frame factory: apply a random TTE effect to **the text the overlay is
    covering** — the current screen, handed in as ``covered`` — so the feed
    appears to dissolve/rain away. Called each loop cycle (and on resize), so it
    always uses the current screen and a fresh random effect."""
    text = "\n".join(covered).rstrip() or "idle"
    effect = random.choice(EFFECTS)(text)
    effect.terminal_config.canvas_width = width
    effect.terminal_config.canvas_height = height
    for frame in effect:
        yield Text.from_ansi(frame)


class LinePresenter:
    async def present(self, item: str, width: int) -> Presentation:
        return Presentation(height=1, renderable=Text(item, style="grey62"))


class ScreensaverApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "idle screensaver demo"
    CSS = "FlowView { height: 1fr; }"

    def compose(self) -> ComposeResult:
        self.model: FlowModel[str] = FlowModel()
        for i in range(40):
            self.model.append(f"log line {i:02d} — sit idle to start the screensaver")
        yield Header()
        self.flow: FlowView[str] = FlowView(
            model=self.model, presenter=LinePresenter(), spacing=0, estimated_height=1
        )
        yield self.flow
        yield Footer()

    def on_mount(self) -> None:
        self._last_activity = time.monotonic()
        self.set_interval(0.4, self._check_idle)

    def _check_idle(self) -> None:
        if self.flow.overlay_active:
            return
        if time.monotonic() - self._last_activity >= IDLE_SECONDS:
            # loop=True: a fresh random effect each cycle, over the current screen
            self.flow.play_overlay(dissolve_screen, fps=30, loop=True)

    def _wake(self) -> None:
        self._last_activity = time.monotonic()
        if self.flow.overlay_active:
            self.flow.stop_overlay()  # dismiss; the feed is restored intact

    def on_key(self, event: events.Key) -> None:
        self._wake()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        self._wake()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self._wake()


if __name__ == "__main__":
    ScreensaverApp().run()
