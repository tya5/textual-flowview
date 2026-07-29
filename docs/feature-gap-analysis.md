# Feature gap analysis — textual-flowview vs. the virtualized-list landscape

_Surveyed 2026-07-29. Reference points: [react-virtuoso] (richest feature set),
[TanStack Virtual] (headless standard), react-window, and terminal list widgets
(Textual `OptionList` / `DataTable`, urwid, prompt_toolkit)._

This is a point-in-time survey of what the general "flow view / virtualized
list" space offers, mapped against what textual-flowview implements, with the
gaps extracted and prioritized for this library's stated use cases (chat,
timelines, logs, notifications, mail, AI agent transcripts).

## Status matrix

| Feature | Status |
| --- | --- |
| Variable-height items, paint virtualization, overscan + read-ahead | ✅ implemented |
| Sticky group headers / group collapse / pinned-top | ✅ |
| Sticky-bottom follow (chat) | ✅ (`Anchor.STICKY_BOTTOM`) |
| Text selection + copy (incl. select-all), click hit-testing | ✅ |
| Single selection (opt-in), search (`find`/`find_next`/`reveal`), minimap | ✅ |
| Animated jumps / stop / mid-flight redirect | ✅ |
| Per-entry dynamic updates, animation, viewport-scoped resources | ✅ |
| Two independent gutters (toggle, effective-width introspection), separators | ✅ |
| **Infinite scroll — edge-reached callbacks to load more** | ✅ implemented — `ReachedTop` / `ReachedBottom` + `reach_threshold` (#1) |
| **Prepend older items without losing scroll position** | ✅ works via anchor capture/restore; `insert_many` / `extend` batch it into one reflow; tested + documented (#2) |
| Keyboard cursor navigation (↑↓/PgUp/PgDn/Home/End highlighted cursor, distinct from selection) | ✅ implemented — opt-in `cursor=True`, exposed as actions + overridable focus-scoped defaults (#3) |
| `scroll_to` alignment (center/end) | ✅ `scroll_to_entry(entry, align="start"/"center"/"end"/"nearest")` |
| index-based `scroll_to_index` / `model[i]` | ✗ not added (ergonomic only — index jump already works via `entries[i]` / `list(model)[i]` + `scroll_to_entry`) |
| Initial scroll position (`initialTopMostItemIndex` equivalent) | ✗ missing |
| Empty-state renderable (shown when the list has no entries) | ✅ `empty` + `empty_align` (vertical); horizontal/styling in the renderable |
| In-scroll header / footer (list title, "load more" footer, "start of history" marker) | ✗ missing (widgets can sit outside FlowView, not inside the scroll) |
| Aggregate visible-range / is-scrolling events (`RangeChanged`, `ScrollStateChanged`) | ⚠ partial (`track_visibility` gives per-entry show/hide; no aggregate event) |
| Live filter (`filter(predicate)` hiding non-matches) | ⚠ partial (do-able via `entry.hide()`; no dedicated API) |
| Automatic height measurement (presenter need not supply height) | ⚠ by design height is explicit (the trait that makes e.g. Rich `ProgressBar` "just work") |
| Multi-selection (range / shift / ctrl) | ✗ missing |
| Insert / remove transition animations | ✗ missing |
| Scroll-position save / restore across remounts | ✗ missing |
| Grid / masonry / horizontal / table layouts | ⛔ out of scope for a flow view (Textual has `DataTable`) |

## Extracted gaps, prioritized

**High (directly serves the target use cases)**

1. **Infinite scroll — `on_reach_top` / `on_reach_bottom`.** Scroll up to lazy-load
   older history, down for more. The staple of chat / log / feed views. Absent.
2. **Prepend preserving scroll position.** The partner of #1: inserting a batch of
   older items above the viewport must not jump the view. Already works via the
   `Anchor.CURRENT`-style anchor capture in `on_flow_insert`; make it a
   guaranteed, tested, documented contract.

**Medium**

3. ~~Opt-in keyboard cursor navigation~~ — **done** (`cursor=True`). Exposed as
   public actions/methods + messages; keys are focus-scoped, overridable
   defaults so the product keeps keybinding policy (arrows just scroll when
   `cursor=False`).
4. **Scroll alignment** — **done** (`scroll_to_entry(..., align="start"/"center"/
   "end"/"nearest")`). Index-based `scroll_to_index` / `initial_index` were
   declined as ergonomic-only (index jump already works via `entries[i]` +
   `scroll_to_entry`).
5. ~~Empty-state~~ — **done** (`empty` + `empty_align`).
6. **In-scroll header/footer**: list heading, a "load more" footer, a
   "start of history" marker.

**Low (use-case dependent)**

7. Aggregate `VisibleRangeChanged` / `ScrollStateChanged` (is-scrolling) events.
8. `filter(predicate)` live filtering.
9. Automatic height-measurement helper (trades against the explicit-height design).
10. Multi-selection; insert/remove transitions; scroll save/restore.

**Out of scope**

- Grid / masonry / horizontal / table layouts — not what a flow view is for.

## Decision

**#1 + #2 shipped** (infinite scroll + prepend stability) — see
`ReachedTop` / `ReachedBottom`, `reach_threshold`, and `FlowModel.insert_many` /
`extend`, with `examples/infinite.py`. Position-preservation on prepend was
already correct via the anchor capture/restore; the batch methods add a
single-reflow path for a page of load-more items.

Remaining candidates from the matrix above (keyboard cursor nav, scroll
alignment / index jumps, empty-state, in-scroll header/footer, …) are unstarted.

[react-virtuoso]: https://github.com/petyosi/react-virtuoso
[TanStack Virtual]: https://deepwiki.com/TanStack/virtual/4.4-sticky-headers-and-footers
