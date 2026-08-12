"""textual-flowview image demo — images in the feed, mixed with text.

Each message is ONE entry whose body composes an **image + text** with plain Rich
layout: a `Table.grid` puts a round avatar beside the name/body, and a caption
sits under a picture via `Group`. No FlowView changes, and it **virtualizes and
scrolls** like any row.

⚠️ **No image library is needed — and the popular one is a trap here.** FlowView
paints rows as *cells*, so it can only place an image that occupies cells:

1. **Sixel is unusable.** It draws pixels relative to the cursor instead of into
   cells, so the rendered row holds *zero cells* and FlowView cannot position or
   clip it. `textual_image.renderable.Image` **auto-selects Sixel first** where
   the terminal supports it, so the convenient import is the broken one.
2. **Kitty placeholders can't be relied on.** They work on Kitty, but WezTerm and
   Konsole report Kitty-graphics support and then draw the placeholders as
   visible glyphs (verified on WezTerm 20240203) — and there is no query for
   "do placeholders draw", so it can't be detected at runtime.

∴ what's left is coloured **half-block cells**, which need no protocol machinery
at all. A renderable is a *Rich* concept, not a Textual one, so this example
writes its own in ~15 lines (`HalfBlockImage` below) — no `textual-image`, no
`rich-pixels`. It renders on every terminal; the only cost is resolution.

Requires:  pip install pillow          (only to *make* the demo images)
Run:       PYTHONPATH=src python examples/image.py
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.console import Console, Group, RenderableType
from rich.measure import Measurement
from rich.segment import Segment
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult

from textual_flowview import FlowModel, FlowView, Presentation

try:
    from PIL import Image as PILImage
    from PIL import ImageDraw
except ModuleNotFoundError:  # pragma: no cover
    raise SystemExit("This example needs pillow:  pip install pillow") from None


class HalfBlockImage:
    """A Rich renderable for an image, built from nothing but Segments.

    Each text row carries two pixel rows: the upper half-block glyph is drawn in
    the upper pixel's colour over the lower pixel's colour as background. That
    makes it ordinary coloured *cells*, which is exactly what FlowView needs to
    place and clip — and what every terminal can draw.
    """

    def __init__(self, image: PILImage.Image, width: int, height: int) -> None:
        # height is in TEXT rows; sample two pixel rows per text row
        self._img = image.convert("RGB").resize((width, height * 2))
        self._w, self._h = width, height * 2

    def __rich_console__(self, console: Console, options: object):
        px = self._img.load()
        for y in range(0, self._h - 1, 2):
            for x in range(self._w):
                top, bottom = px[x, y], px[x, y + 1]
                yield Segment(
                    "\u2580",
                    Style(color=f"rgb({top[0]},{top[1]},{top[2]})",
                          bgcolor=f"rgb({bottom[0]},{bottom[1]},{bottom[2]})"),
                )
            yield Segment("\n")

    def __rich_measure__(self, console: Console, options: object) -> Measurement:
        return Measurement(self._w, self._w)


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
        avatar = HalfBlockImage(item.avatar(), width=6, height=3)
        text = Group(Text(item.name, style=style), Text(item.body, style="grey85"))
        grid = Table.grid(padding=(0, 1))
        grid.add_column()          # avatar
        grid.add_column(ratio=1)   # message
        grid.add_row(avatar, text)

        body: RenderableType = grid
        if item.picture:
            # a wide picture with a caption underneath, stacked vertically
            pic = HalfBlockImage(_picture(160, 60), width=max(1, width - 8), height=8)
            body = Group(grid, Text(""), pic, Text("↑ an inline picture", style="grey50"))

        height = len(self._probe.render_lines(body, self._probe.options.update_width(width)))
        return Presentation(height=height, renderable=body)


MESSAGES = [
    Message("Ada", "Morning! Pushed the render_line refactor.", (90, 160, 240)),
    Message("Bo", "No image library — just Segments and colour.", (240, 120, 90)),
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
