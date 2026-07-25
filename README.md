# textual-flowview

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

## Scroll anchoring

```python
from textual_flowview import Anchor

FlowView(model=..., presenter=..., anchor=Anchor.CURRENT)          # default
FlowView(model=..., presenter=..., anchor=Anchor.STICKY_BOTTOM)    # chat / log
```

`STICKY_BOTTOM` follows new items **only while the user is already at the
bottom** — scrolling up to read history stops the auto-follow (Slack / Discord
/ Claude Code behaviour).

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

## Public API (widget)

| Method | Effect |
| :- | :- |
| `scroll_to_top()` / `scroll_to_bottom()` | Jump to either edge. |
| `scroll_to_entry(entry)` | Put `entry` at the top. |
| `ensure_visible(entry)` | Scroll the minimum to reveal `entry`. |
| `select(entry)` / `clear_selection()` | Change selection. |

## License

MIT
