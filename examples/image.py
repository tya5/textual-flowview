"""textual-flowview image demo — real-pixel images in the feed, mixed with text.

Each message is ONE entry whose body composes an **image + text** with plain Rich
layout: a `Table.grid` puts a round avatar beside the name/body, and a caption
sits under a picture via `Group`. The image is a Rich renderable
([textual-image](https://github.com/lnqs/textual-image)) dropped straight into a
`Presentation` — no FlowView changes, and it **virtualizes and scrolls** like any
row.

⚠️ The image renderable is chosen **explicitly**, never via
`textual_image.renderable.Image` — twice over:

1. That auto-selects **Sixel** first wherever the terminal supports it, and Sixel
   cannot work in a virtualized painter: it draws pixels relative to the cursor
   instead of occupying cells, so the rendered row contains *zero cells* and
   FlowView has no way to position or clip it (measured: 0 cells for Sixel vs
   120 placeholder cells for the Kitty renderable).
2. Kitty *placeholder* mode is only known-good on **Kitty itself**. WezTerm and
   Konsole report Kitty-graphics support but don't render the placeholders — they
   show up as visible characters over the image — and
   `tgp.query_terminal_support()` doesn't test for that. So this example gates on
   the terminal and otherwise uses half-blocks, which are approximate but render
   correctly everywhere.

Requires:  pip install textual-image pillow
Run:       PYTHONPATH=src python examples/image.py     (real pixels in Kitty)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation

try:
    from PIL import Image as PILImage
    from PIL import ImageDraw

    # Cell-based renderables ONLY — see the note above. Placeholder mode is
    # known-good on Kitty; everywhere else half-blocks, which always render.
    if os.environ.get("TERM") == "xterm-kitty":
        from textual_image.renderable.tgp import Image as CellImage
    else:
        from textual_image.renderable.halfcell import Image as CellImage
except ModuleNotFoundError:  # pragma: no cover
    raise SystemExit(
        "This example needs textual-image + pillow:  pip install textual-image pillow"
    ) from None


def _avatar(rgb: tuple[int, int, int], initial: str) -> PILImage.Image:
    """A little round avatar with an initial — generated, so no image files."""
    size = 96
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill=(*rgb, 255))
    d.text((size // 2 - 18, size // 2 - 30), initial, fill=(255, 255, 255, 255))
    d.text((size // 2 - 17, size // 2 - 29), initial, fill=(255, 255, 255, 255))
    return img


def _picture(w: int, h: int) -> PILImage.Image:
    img = PILImage.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 255) // w, (y * 255) // h, 160)
    return img


@dataclass
class Message:
    name: str
    body: str
    color: tuple[int, int, int]
    picture: bool = False
    _avatar: object = field(default=None, repr=False)

    def avatar(self) -> PILImage.Image:
        if self._avatar is None:
            self._avatar = _avatar(self.color, self.name[0].upper())
        return self._avatar


class MessagePresenter:
    def __init__(self) -> None:
        self._probe = Console()

    async def present(self, item: Message, width: int) -> Presentation:
        style = f"bold rgb({item.color[0]},{item.color[1]},{item.color[2]})"
        # avatar (3 cell-rows) beside name + body — one entry, image + text mixed
        avatar = CellImage(item.avatar(), width=6, height=3)
        text = Group(Text(item.name, style=style), Text(item.body, style="grey85"))
        grid = Table.grid(padding=(0, 1))
        grid.add_column()          # avatar
        grid.add_column(ratio=1)   # message
        grid.add_row(avatar, text)

        body: RenderableType = grid
        if item.picture:
            # a wide picture with a caption underneath, stacked vertically
            pic = CellImage(_picture(160, 60), width=max(1, width - 8), height=8)
            body = Group(grid, Text(""), pic, Text("↑ an inline picture", style="grey50"))

        height = len(self._probe.render_lines(body, self._probe.options.update_width(width)))
        return Presentation(height=height, renderable=body)


MESSAGES = [
    Message("Ada", "Morning! Pushed the render_line refactor.", (90, 160, 240)),
    Message("Bo", "Real pixels in Kitty; half-blocks elsewhere.", (240, 120, 90)),
    Message("Ada", "Yep — cell-based placeholders, so they scroll and clip.", (90, 160, 240)),
    Message("Cy", "Here's the latency chart:", (120, 200, 120), picture=True),
    Message("Bo", "Ship it.", (240, 120, 90)),
]


class ImageApp(App):
    TITLE = "textual-flowview"
    SUB_TITLE = "images + text in the feed"
    CSS = "FlowView { height: 1fr; padding: 0 1; }"

    def compose(self) -> ComposeResult:
        self.model: FlowModel[Message] = FlowModel()
        for _ in range(6):
            for m in MESSAGES:
                self.model.append(m)
        self.flow: FlowView[Message] = FlowView(
            model=self.model, presenter=MessagePresenter(), spacing=1, estimated_height=4
        )
        yield self.flow


if __name__ == "__main__":
    ImageApp().run()
