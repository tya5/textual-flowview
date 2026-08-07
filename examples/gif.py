"""textual-flowview animated-GIF demo — a moving image in a feed entry.

A GIF is just a sequence of image frames, so it animates with the same two pieces
you'd use for any moving content: render the current frame as a Rich renderable,
and advance frames on a timer. FlowView's `animate_entry` ties that timer to
visibility — **an off-screen GIF stops animating automatically** (no wasted CPU),
and resumes when it scrolls back in.

Here each frame is drawn as Unicode half-blocks via
[rich-pixels](https://github.com/darrenburns/rich-pixels) — cheap per frame and
works in any terminal, which suits animation. (For a *static* image you can get
real pixels on Kitty via textual-image; see `examples/image.py`. Real-pixel GIF
is possible too but re-transmits each frame, so it's heavier.) The GIF is
generated in memory so there's no asset to ship — swap in `Image.open("your.gif")`.

Requires:  pip install rich-pixels pillow
Run:       PYTHONPATH=src python examples/gif.py
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation

try:
    from PIL import Image, ImageDraw, ImageSequence
    from rich_pixels import Pixels
except ModuleNotFoundError:  # pragma: no cover
    raise SystemExit(
        "This example needs rich-pixels + pillow:  pip install rich-pixels pillow"
    ) from None


def _make_gif() -> io.BytesIO:
    """A tiny looping animation (a dot bouncing across), encoded as a real GIF."""
    w, h, n = 64, 16, 12
    frames = []
    for i in range(n):
        t = i / (n - 1)
        x = int(2 + t * (w - 12))
        im = Image.new("RGB", (w, h), (18, 18, 28))
        d = ImageDraw.Draw(im)
        d.ellipse([x, 3, x + 9, 12], fill=(240, 120, 90))
        frames.append(im)
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:], duration=70, loop=0
    )
    buf.seek(0)
    return buf


def _load_frames(gif: io.BytesIO) -> list[Image.Image]:
    return [f.convert("RGB").copy() for f in ImageSequence.Iterator(Image.open(gif))]


@dataclass
class Post:
    name: str
    body: str
    gif: bool = False
    _frames: list = field(default_factory=list, repr=False)
    frame: int = 0

    def frames(self) -> list[Image.Image]:
        if not self._frames:
            self._frames = _load_frames(_make_gif())
        return self._frames


class Presenter:
    async def present(self, item: Post, width: int) -> Presentation:
        header = Text.assemble((item.name, "bold cyan"), ("  ", ""), (item.body, "grey85"))
        if not item.gif:
            return Presentation(height=1, renderable=header)
        rows = 6
        frames = item.frames()
        img = frames[item.frame % len(frames)].resize((min(width, 64), rows * 2))
        # header text above the animated GIF, in one entry
        body: RenderableType = Group(header, Pixels.from_image(img))
        return Presentation(height=1 + rows, renderable=body)


class GifApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "animated GIF in the feed (scroll it off-screen → it pauses)"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"

    def compose(self) -> ComposeResult:
        self.model: FlowModel[Post] = FlowModel()
        self.model.append(Post("Ada", "check out this reaction:"))
        self.gif = self.model.append(Post("bot", "▶ bouncing.gif", gif=True))
        for i in range(40):
            self.model.append(Post("log", f"line {i} — scroll up past the gif"))
        self.flow: FlowView[Post] = FlowView(
            model=self.model, presenter=Presenter(), spacing=0, estimated_height=1
        )
        yield self.flow

    def on_mount(self) -> None:
        # animate_entry ticks only while the entry is visible (auto pause/resume)
        self.flow.animate_entry(self.gif, 1 / 15, self._advance)

    def _advance(self, entry) -> None:
        entry.item.frame += 1
        entry.update()


if __name__ == "__main__":
    GifApp().run()
