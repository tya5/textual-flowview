# textual-flowview

[![CI](https://github.com/tya5/textual-flowview/actions/workflows/ci.yml/badge.svg)](https://github.com/tya5/textual-flowview/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![Textual](https://img.shields.io/badge/built%20with-Textual-5a3fd6)](https://textual.textualize.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

*A virtualized Flow View widget for [Textual](https://textual.textualize.io/).*

`textual-flowview` displays **large collections of variable-height items**
efficiently — chat, timelines, git history, event logs, notifications, mail,
AI agent transcripts. None of these are special-cased. The widget only ever
deals with a **Model + Presenter**.

![Activity feed with a per-state gutter, streaming, and sticky-bottom](assets/showcase.svg)

<table>
<tr>
<td><img alt="Collapsible groups with a sticky header" src="assets/groups.svg"></td>
<td><img alt="Minimap replacing the scrollbar, errors visible at a glance" src="assets/minimap.svg"></td>
</tr>
</table>

## Why virtualize? (measured)

The same list built two ways — a Textual `VerticalScroll` with one `Static`
widget per row vs a `FlowView` — at N rows (`examples/benchmark.py`, mid-range
laptop):

| rows | build (container → flowview) | widgets (container → flowview) | full re-layout / resize |
| ---: | :-- | :-- | :-- |
|  100 | 120 → **84 ms** | 101 → **1** | 138 → 138 ms |
|  400 | 278 → **86 ms** | 401 → **1** | 299 → **135 ms** |
| 1000 | 583 → **96 ms** | 1001 → **1** | 553 → **150 ms** |
| 2000 | 1155 → **117 ms** | 2001 → **1** | 1123 → **171 ms**  _(6.6× faster)_ |

The container mounts one widget per row — O(N) DOM, layout, and memory that grows
with the list. FlowView **paints** the visible rows, so it is O(viewport): **one
widget regardless of N**, a flat build and re-layout, and scrolling that stays
smooth.

`examples/compare.py` shows it live with an FPS meter on the same 1500-row list.
Flip `c` / `f` for the backend and `d` for the content:

![The same 1500-row list: a Static-per-row container vs a FlowView, with a live FPS meter](assets/compare.gif)

- **static** rows (plain text, rendered once): the container drops to **~14 FPS
  with 1500 widgets** while FlowView holds **~60 FPS with 3** — a full re-layout
  every scrolled frame vs painting the viewport.
- **dynamic** rows (a rich `ProgressBar` re-rendering every frame) narrow the gap
  — both sides then spend most of the frame re-rendering the visible bars — but
  FlowView still leads and never grows past its viewport-sized widget count.

For a true visual side-by-side, run each pane in its own process (its own render
loop) — a 2×2 split covers both axes:

```bash
PYTHONPATH=src python examples/compare.py flowview  static
PYTHONPATH=src python examples/compare.py container static
PYTHONPATH=src python examples/compare.py flowview  dynamic
PYTHONPATH=src python examples/compare.py container dynamic
```

## Core ideas

- **`FlowModel[T]`** owns an ordered collection of items and knows nothing
  about the UI.
- **`Entry`** is the single stable handle to a displayed item — the only way
  to update or remove it.
- **`FlowPresenter`** is the only component that knows the concrete item type;
  it turns an item into a **`Presentation`** (height + renderable).
- **`FlowView`** draws `Presentation`s and manages the viewport. It never sees
  your data type.

## Handle-based API

`append` / `insert` return an `Entry`. There is no `model.update(item)` — the
entry *is* the identity, which keeps mutable and in-place-mutated items safe:

```python
from textual_flowview import FlowModel

conversation = FlowModel()

entry = conversation.append(ChatMessage(role="assistant", text=""))
entry.item.text += "Hello"
entry.update()                 # bumps revision → re-present
entry.item.text += " World"
entry.update()

entry.remove()                 # no-op if already removed
```

## Body & Gutter (state / metadata)

Each row is split into a **gutter** and a **body**:

```text
┌────────┬──────────────────────────────┐
│ Gutter │             Body             │
└────────┴──────────────────────────────┘
```

* The **body** is what `FlowPresenter` produces.
* The **gutter** is what a `FlowDecorator` produces — status markers, icons,
  badges, timestamps.

They update **independently**. Changing an entry's state or metadata redraws
only the gutter — the body is *not* re-presented and nothing re-layouts, so
high-frequency status updates stay cheap:

```python
from textual_flowview import EntryState, StateDecorator

flow = FlowView(
    model=model,
    presenter=ChatPresenter(),
    decorator=StateDecorator(),   # gutter markers per EntryState
    gutter_width=2,
)

entry = model.append(msg)
entry.set_state(EntryState.RUNNING)   # gutter only  ✻
entry.update()                        # body re-presented
entry.set_state(EntryState.SUCCESS)   # gutter only  ✓
entry.set_metadata("time", "09:31")   # gutter only, arbitrary data
```

`EntryState` provides `DEFAULT / RUNNING / SUCCESS / ERROR / CANCELLED`. Write
your own decorator for full control:

```python
class MyDecorator:
    def decorate(self, entry, width, height):
        return Text("●" if entry.metadata.get("unread") else " ", style="cyan")
```

A presenter exception both renders an error body and flips the entry to
`EntryState.ERROR` (so the gutter shows it) without crashing the app.

## Collapse & group collapse

Two kinds of collapse fall out of the design:

**Per-item collapse** is purely a presenter concern — no library feature
needed. Keep a `collapsed` flag on your item; present a compact renderable when
set; call `entry.update()` to reflow:

```python
async def present(self, item, width):
    if item.collapsed:
        return Presentation(height=1, renderable=Text(f"▸ {item.title}"))
    return Presentation(height=full, renderable=Panel(...))   # ▾ expanded
```

**Group collapse** uses the library's entry-visibility primitive. Hidden
entries stay in the model and keep their cached presentation (showing them
again is instant and never re-presents), but contribute no height and aren't
drawn:

```python
entry.hidden          # bool
entry.hide()          # exclude from the view
entry.show()          # re-include
entry.set_hidden(True)
```

A collapsible header is then just hiding a run of child entries — see
`examples/groups.py`:

```python
def collapse_group(header, children):
    header.item.collapsed = True
    header.update()                 # redraw the ▸ chevron
    for child in children:
        child.hide()                # the group-collapse primitive
```

Which entries belong to a group is up to you — grouping policy varies by app,
so the library ships the visibility primitive rather than a fixed hierarchy.

## Sticky headers

Pin the current group's header to the top while scrolling through it. Tell
FlowView which entries are headers with a predicate; the pinned header swaps as
you cross group boundaries, and the next header pushes the previous one up:

```python
FlowView(
    model=model,
    presenter=presenter,
    sticky_header=lambda e: e.item.kind == "header",
)
```

Style the pinned rows via the `flowview--sticky-header` component class. See
`examples/groups.py`.

## Minimap (scrollbar replacement)

`FlowMinimap` is a thin overview strip that **replaces the scrollbar**: it
compresses the whole flow into one column, painting each row in the colour of
its most notable state (red = error) and highlighting the on-screen range as
the "window" (a content-aware scroll thumb). Click or drag it to jump.

```python
from textual.containers import Horizontal
from textual_flowview import FlowView, FlowMinimap

def compose(self):
    self.view = FlowView(model=m, presenter=p)
    with Horizontal():
        yield self.view
        yield FlowMinimap(flow_view=self.view)

# hide the native scrollbar so the minimap stands in for it:
# CSS:  FlowView { scrollbar-size-vertical: 0; }
```

State→colour is overridable (`FlowMinimap(..., colors={EntryState.ERROR: "magenta"})`)
and the window band is themed via the `flowminimap--window` component class.
See `examples/minimap.py` (a 400-line scan log — errors are visible at a glance).

## Keys & focus

FlowView is **unopinionated about keys** — it defines no `BINDINGS` of its own,
so it never conflicts with your app's shortcuts. The only keys it responds to
are the standard scroll keys (arrows, Home/End, PageUp/PageDown) inherited from
Textual's `ScrollableContainer`, and only while the widget is focused — Textual
resolves keys through the focus chain, so FlowView never globally captures them.
<kbd>Ctrl</kbd>+<kbd>C</kbd> copy is Textual's own Screen binding, not ours.

Customize with any standard Textual mechanism:

- override keys in your `App` / `Screen` / a `FlowView` subclass via `BINDINGS`;
- set `flow.can_focus = False` so it never grabs scroll keys (wheel still works);
- bind your own keys to the public methods (`scroll_to_bottom`, `find_next`,
  `copy_entry`, …).

The library never binds a key to an action for you — that's your app's call.

## Spacing & full-row background

`FlowView(spacing=1)` puts blank rows **between** entries (default `1`; set `0`
to pack them). The gap is real layout — scrolling, hit-testing, and the minimap
all account for it.

Give an entry a **full-row background** — painted edge to edge across the
gutter, body, and trailing padding — via `Presentation.background`, so a
message reads as one continuous coloured block (no hand-rolled full-width grid,
no gutter-colour coordination):

```python
async def present(self, item, width):
    body = Text(item.text)
    return Presentation(
        height=..., renderable=body,
        background="#2b2f37" if item.role == "user" else None,
    )
```

## Scroll anchoring

```python
from textual_flowview import Anchor

FlowView(model=..., presenter=..., anchor=Anchor.CURRENT)          # default
FlowView(model=..., presenter=..., anchor=Anchor.STICKY_BOTTOM)    # chat / log
```

`STICKY_BOTTOM` follows new items **only while the user is already at the
bottom** — scrolling up to read history stops the auto-follow (Slack / Discord
/ Claude Code behaviour).

For a **newest-on-top** feed, prepend with `model.insert(0, item)` and use
`Anchor.STICKY_TOP` — the mirror of `STICKY_BOTTOM`: it stays pinned to the top
(showing the newest) while the user is at the top, and stops following once
they scroll down. `CURRENT` also works for prepend, but keeps the current
position instead of following the top.

## Smooth scrolling (overscan & read-ahead)

FlowView only presents what's on (or near) screen. Two knobs control how much
it prepares ahead of time so scrolling reveals real content, not placeholders:

```python
FlowView(model=..., presenter=..., overscan=4, read_ahead=None)
```

- **`overscan`** — extra rows presented above *and* below the viewport (a
  static cushion around the visible range).
- **`read_ahead`** — extra rows pre-presented *in the direction you're
  scrolling*, on top of overscan. `None` (default) uses one viewport height;
  `0` disables it. Larger = smoother fast scrolling at the cost of presenting
  more up front.

## Selection

Single-entry click selection (v0.3). The selection lives on the view, not the
item, and posts a message you can react to:

```python
class MyApp(App):
    def on_flow_view_selected(self, event: FlowView.Selected) -> None:
        entry = event.entry            # the selected Entry, or None
        ...

flow.select(entry)         # programmatic
flow.clear_selection()
flow.selected              # -> Entry | None
```

Style the highlight via the `flowview--selected` component class:

```css
FlowView > .flowview--selected { background: $accent 30%; }
```

## Rich renderables, indicators & animation

An entry's view is a plain **`rich.console.RenderableType`** — the same type a
Textual widget returns from `render()`. So any Rich/Textual renderable drops
straight into a `Presentation`: `Panel`, `Table`, `Syntax`, `Markdown`, and the
built-in indicators `rich.spinner.Spinner` and `rich.progress_bar.ProgressBar` —
no custom drawing.

Because a `Presentation` carries an **explicit height**, renderables whose height
a `Static` can't auto-measure — a `rich.progress_bar.ProgressBar` is the classic
one, it collapses to zero rows in a bare `Static` — just work in a `FlowView`.
You tell FlowView the height; there's no per-widget `styles.height` to remember.

FlowView caches an entry's render, so animation needs a clock. There is **one
animation primitive** — `animate_entry` — and the callback decides *what* to
re-render, so the gutter and the body animate the same way:

```python
view.animate_entry(entry, interval, callback)   # ticks only while on screen
```

`animate_entry(entry, interval, callback)` ties a timer to the viewport: FlowView
**pauses it when the entry scrolls off screen and resumes it when it scrolls
back**, so off-screen entries do no work. `stop_entry_animation(entry)` (or the
returned handle's `.stop()`) cancels it; removal cleans it up. The callback
re-renders whichever part changed:

```python
# body — content that changes over time (progress bar, "thinking…")
def advance(e):
    e.item.progress = min(1.0, e.item.progress + 0.05)
    e.update()                       # re-present the body
    if e.item.progress >= 1.0:
        view.stop_entry_animation(e)
view.animate_entry(entry, 1 / 15, advance)

# gutter — a time-based decorator (rich.spinner.Spinner().render(time))
view.animate_entry(entry, 1 / 12, view.refresh_gutter)   # re-derive the gutter
```

`refresh_gutter(entry)` is the gutter counterpart of `entry.update()` (re-derives
the gutter, never the body). And a plain `entry.update()` on an **off-screen**
entry is cheap too: FlowView **defers** the re-present and reflow until it
scrolls into view.

**Shorthand:** `FlowView(animation_fps=12)` auto-drives the gutter for *all*
visible entries (equivalent to `refresh_gutter` on each, with no per-entry
registration) — handy for "every RUNNING entry spins" with a time-based
decorator.

See `examples/progress.py` (a gutter spinner via `animation_fps`, body progress
via `animate_entry`).

### Viewport-scoped resources (the general hook)

`animate_entry` is a convenience over the general primitive: **tie any
resource's lifecycle to whether an entry is on screen**. `track_visibility`
runs `on_show` when the entry enters the viewport and `on_hide` when it leaves —
and also on stop / removal, so a resource is always released:

```python
view.track_visibility(
    entry,
    on_show=lambda e: e.item.stream.subscribe(),    # acquire when visible
    on_hide=lambda e: e.item.stream.unsubscribe(),  # release when hidden
)
```

Use it for anything scoped to visibility — a data subscription, a video, a
lazily-loaded image, a timer. Returns a `VisibilityHandle`; `.stop()`
unregisters (releasing if currently shown).

> Interactive Textual **widgets** (`Button`, `Select`, `Input`) are a different
> thing — FlowView paints renderables rather than mounting child widgets, so
> those aren't hosted per entry. For clickable controls, draw them and hit-test
> `FlowView.Clicked` (below).

## Interaction & content replacement

`FlowView` paints Rich renderables — it doesn't mount a real widget per row.
To build **clickable controls inside the flow** (buttons, option chips, an
intervention selector), draw them in the presenter and hit-test the click:
`FlowView.Clicked` reports the entry *and the position within it*, so you know
which control was pressed.

```python
class MyApp(App):
    def on_flow_view_clicked(self, event: FlowView.Clicked) -> None:
        entry, col, row = event.entry, event.x, event.y   # x,y local to the entry body
        ...
```

Replace a specific item's content at any time — mutate it and `entry.update()`,
or swap the whole object with `entry.set_item(new)` (handy for immutable items
via `dataclasses.replace`). Either re-presents just that entry. See
`examples/intervention.py` for a clickable selector that resolves via
`set_item`.

### Design: interactive widgets live *outside* the flow

FlowView **paints renderables; it does not mount a Textual widget per entry** —
that's what keeps it O(viewport) instead of O(N) and lets it scroll thousands of
variable-height items smoothly. As a deliberate consequence, real interactive
widgets (`Input`, `Select`, `Button`) are **not embedded in the flow**. Instead:

- **Display / light interaction lives in the flow** — presenter renderables plus
  `FlowView.Clicked` hit-testing (option chips, buttons drawn as text).
- **Real editing widgets live outside the flow** — dock a normal Textual widget
  (a composer, an editor, a modal) and wire it to the flow through the existing
  messages: `Clicked` / `Selected` flow *out*, and `model.append()` /
  `entry.set_item()` drive updates back *in*.

```python
def compose(self):
    yield self.view                 # FlowView (history)
    yield Input(id="editor")        # real interactive widget, docked outside

def on_flow_view_clicked(self, ev: FlowView.Clicked):
    self._editing = ev.entry                       # app state: which entry
    editor = self.query_one("#editor", Input)
    editor.value = ev.entry.item.text              # drive the external widget
    editor.focus()

def on_input_submitted(self, ev: Input.Submitted):
    self._editing.set_item(replace(self._editing.item, text=ev.value))  # update the entry
```

So the library provides the flow↔app plumbing (`Clicked`/`Selected` out,
`append`/`update`/`set_item` in); interactive widgets are the app's own,
external, and updated dynamically through it. The only thing this rules out is a
real editing widget rendered *inline and scrolling with a specific entry*; if a
UX needs that, dock or modal it instead (see
[issue #1](https://github.com/tya5/textual-flowview/issues/1)). `examples/reyn_poc/`
follows this pattern (a docked composer over a painted conversation).

## Search

Query entries with a predicate (over the item, state, or metadata) and jump to
hits. Search covers the whole model — including hidden entries inside collapsed
groups — and `reveal()` un-hides a hit before scrolling to it:

```python
errors = flow.find(lambda e: e.state is EntryState.ERROR)

hit = flow.find_next(lambda e: "TODO" in e.item.text)   # after the selection, wraps
flow.find_previous(predicate)
if hit:
    flow.reveal(hit)        # un-hide if collapsed, then scroll into view
```

## Public API (widget)

| Method | Effect |
| :- | :- |
| `scroll_to_top()` / `scroll_to_bottom()` | Jump to either edge. |
| `scroll_to_entry(entry)` | Put `entry` at the top. |
| `ensure_visible(entry)` | Scroll the minimum to reveal `entry`. |
| `reveal(entry)` | Un-hide if collapsed, then ensure visible. |
| `select(entry)` / `clear_selection()` | Change selection. |
| `find(pred)` / `find_next(pred)` / `find_previous(pred)` | Search entries. |
| `entry_text(entry)` / `copy_entry(entry)` | Get / copy an entry's rendered text. |

Clipboard copy uses Textual's own `App.copy_to_clipboard` (OSC 52):
`entry_text(entry)` returns the entry's rendered body as plain text, and
`copy_entry(entry)` copies it and returns it. Bind it to a key for a copy
action (see `examples/showcase.py`, `y`).

### Mouse text selection

FlowView plugs into **Textual's native text selection**: drag to select across
entries, and <kbd>Ctrl</kbd>+<kbd>C</kbd> copies (Textual's built-in binding).
It works by stamping each rendered cell with its content offset and
implementing `get_selection`, so selections are stable across scrolling and use
the standard `screen--selection` style. No configuration needed — it's on by
default (`ALLOW_SELECT`).

## Examples

```bash
PYTHONPATH=src python examples/dashboard.py       # 400 live hosts, viewport-scoped animation
PYTHONPATH=src python examples/showcase.py       # live AI-agent activity feed
PYTHONPATH=src python examples/groups.py          # collapsible groups + sticky headers
PYTHONPATH=src python examples/intervention.py    # clickable in-flow selector
PYTHONPATH=src python examples/progress.py        # Rich Spinner + ProgressBar in entries
PYTHONPATH=src python examples/minimap.py         # minimap replacing the scrollbar
PYTHONPATH=src python examples/chat.py            # streaming chat
PYTHONPATH=src python examples/compare.py         # live FPS: VerticalScroll vs FlowView
PYTHONPATH=src python examples/benchmark.py       # prints the benchmark table above
```

`showcase.py` demonstrates variable-height panels, a colored per-state gutter,
streaming updates, and sticky-bottom auto-follow in one screen.

## License

MIT
