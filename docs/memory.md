# Controlling memory

FlowView paints the visible rows instead of mounting a widget per row, so the
*widget* cost is O(viewport) regardless of how many entries you have. What can
still grow is the **render cache**. This guide explains what is cached, what it
costs, and the levers you have.

All figures below are measured (500 entries × 10 rows, 60-column view, macOS /
CPython 3.12) and are indicative rather than exact for your content.

## TL;DR

- **Entries you never scroll to cost nothing.** Presentation is lazy — appending
  100k entries and not scrolling presents only the handful in view.
- **Rendered rows are already bounded** to the visible band; they're released
  when an entry scrolls out (since 0.16.2).
- **Presentations are retained for every entry you have visited.** That's ~0.7
  KiB/entry for text — negligible — but ~42 KiB/entry for an image body.
- So: **plain text feeds need no tuning.** If your entries carry images or other
  heavy renderables, use one of the two levers below.

## What FlowView caches

| Cache | Holds | Created | Released |
| :- | :- | :- | :- |
| **Presentation** (`FlowLayout`) | the `Presentation` you returned — height + **your renderable** | lazily, when the entry first enters the band | on `remove()` / `clear()` / resize (other widths) / a superseded revision |
| **Rendered strips** | the entry rendered into terminal cells | on first paint | **automatically, when the entry leaves the band** |
| Gutter strips | the decorator's output | on paint | on decorator revision change / resize |

The "band" is the visible range plus overscan plus a read-ahead biased in the
scroll direction — wider than the viewport, so ordinary scrolling doesn't thrash.

Strips are a *per-frame* optimisation: `render_line` is row-granular while
rendering is entry-granular, so the cache collapses an entry's N row-requests
into one render. Off-band entries have no rows to collapse, which is why they can
be dropped with no downside — scrolling back re-renders them **synchronously**
from the retained `Presentation` (sub-millisecond, no placeholder).

The `Presentation` is kept precisely so that re-render stays synchronous.
Dropping it means an async re-`present()` and a brief placeholder, so FlowView
won't do that behind your back.

## What it costs

Per entry, after it has been visited:

| Body | Presentation | Strips (while on/near screen) |
| :- | --: | --: |
| plain text, 10 rows | ~0.7 KiB | ~34 KiB |
| image (half-block, 60×20) | ~42 KiB | ~268 KiB |

So a 10k-entry text transcript you have scrolled end-to-end holds roughly **7 MB**
of presentations — fine. The same transcript where every entry carries an image
would hold roughly **420 MB** — not fine.

Strips no longer scale with entries visited: after scrolling through 500 entries
the strip cache held **3** entries, and scrolling back repainted in **0.34 ms**
with real content.

## Levers

### 1. Remove entries you no longer need (frees everything)

The model is yours; dropping an entry frees its presentation, strips and heights:

```python
for entry in list(model)[:-2000]:   # keep the last 2000
    entry.remove()
```

This is the only lever that reclaims *everything*, and the right one for a
long-running log with a bounded retention policy.

### 2. Shed heavy bodies while they're off-screen

FlowView can't see inside a renderable — it cannot tell an image-bearing entry
from a text one — so *which* bodies are expensive is your call. The lever is the
ordinary one: swap the item for a light version and `update()`. Pair it with
`track_visibility` so it happens automatically:

```python
view.track_visibility(
    entry,
    on_hide=lambda e: (e.item.drop_image(), e.update()),     # -> "🖼 chart.png"
    on_show=lambda e: (e.item.restore_image(), e.update()),
)
```

The superseded presentation is released immediately even though the entry is
off-screen (fixed in 0.16.3), so the memory really comes back. The entry's height
is remembered, so nothing on screen shifts; when it scrolls back, `present()`
rebuilds from the item.

### 3. Don't hold the heavy object in the item

`present()` is called on a cache miss, so it's fine to *build* an expensive
renderable there and keep only a cheap reference (a path, a thumbnail, the raw
bytes you already need) on the item. Holding a decoded image *and* having
FlowView cache its rendered form doubles the cost.

For per-entry resources that are not the body — a subscription, a video, a
lazily-loaded asset — `track_visibility` is the general hook (see the README).

### Note: folded and hidden entries keep their presentation

Folding a group (`entry.collapse()`) and hiding entries (`entry.hide()`) both
deliberately retain the presentations of what they remove from view, so
unfolding is instant and never re-presents. The corollary is that folding frees
no body memory — only *paint* caches shrink, since those are trimmed to the
visible band. If a folded group is huge *and* expensive, remove its entries
rather than folding them, or swap their items for light ones and `update()`.

A group that has never been expanded costs nothing at all: its entries are
outside the laid-out set, so they are never presented in the first place.

## What FlowView deliberately does not do

**No byte budget or automatic eviction of presentations.** Both halves of that
turn out to be unworkable or wrong:

- **Process memory is not a usable control signal.** `resource.getrusage`
  reports *peak* RSS only — it never comes down, so it can't tell you an eviction
  worked. `tracemalloc` is accurate but ~38× slower with it enabled. `psutil`
  would add a dependency (FlowView's only runtime dependency is `textual`). And
  CPython does not necessarily return freed memory to the OS, so RSS lags and
  sticks — a controller driven by it over-evicts.
- **Entry counts are a poor budget unit** — measured ~9× difference per entry
  between text and image bodies — and byte-accurate sizing of an arbitrary Rich
  renderable is not cheaply possible.
- **FlowView can't identify the expensive entries** — renderables are opaque by
  design (the same reason `Presentation` carries an explicit `height`: FlowView
  can't measure your renderable, so you declare it).

Which is why the levers above put the *policy* with you — you know which entries
are heavy and when they stop mattering — while FlowView handles the mechanism it
can decide correctly on its own (releasing off-band strips).

## Diagnosing your app

The accurate measurement is `tracemalloc` around a representative scroll — slow,
but it's a diagnostic, not something you leave on:

```python
import tracemalloc
tracemalloc.start()
base = tracemalloc.take_snapshot()
...  # scroll / stream in your app
snap = tracemalloc.take_snapshot()
for stat in snap.compare_to(base, "lineno")[:10]:
    print(stat)
```

For a quick check of cache occupancy, `len(flow._layout)` (presentations
retained) and `len(flow._strip_cache)` (rendered rows retained) are useful —
these are internals and may change, so don't build on them. The first should
track the entries you have *visited*; the second should stay small and roughly
constant no matter how far you scroll. If the second grows, that's a bug worth
reporting.
