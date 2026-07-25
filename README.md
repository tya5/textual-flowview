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

> Status: **v0.3 (draft)** — core data layer implemented. The `FlowView`
> widget itself is the next milestone.

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

## Scroll anchoring

```python
from textual_flowview import Anchor

FlowView(model=..., presenter=..., anchor=Anchor.CURRENT)          # default
FlowView(model=..., presenter=..., anchor=Anchor.STICKY_BOTTOM)    # chat / log
```

`STICKY_BOTTOM` follows new items **only while the user is already at the
bottom** — scrolling up to read history stops the auto-follow (Slack / Discord
/ Claude Code behaviour).

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

## Examples

```bash
PYTHONPATH=src python examples/showcase.py   # live AI-agent activity feed
PYTHONPATH=src python examples/groups.py      # collapsible grouped pipeline
PYTHONPATH=src python examples/chat.py        # streaming chat
```

`showcase.py` demonstrates variable-height panels, a colored per-state gutter,
streaming updates, and sticky-bottom auto-follow in one screen.

## License

MIT
