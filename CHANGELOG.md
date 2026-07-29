# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Empty state: `empty` (a renderable shown across the viewport when there are no
  entries — empty model or all hidden) with `empty_align` (`"top"` / `"middle"`
  / `"bottom"`) for vertical placement. Horizontal alignment / styling live in
  the renderable. Distinct from the per-entry `placeholder`; both re-render each
  paint, so a `Spinner` animates when `animation_fps` > 0.
- `scroll_to_entry(entry, align=...)` — where the entry lands in the viewport:
  `"start"` (top, default), `"center"`, `"end"` (bottom), or `"nearest"` (the
  minimal scroll, same as `ensure_visible`). `center` is handy for search hits.
- Opt-in keyboard cursor (`cursor=True`): ↑/↓ move a highlighted "current entry"
  item-by-item (the view follows), PageUp/PageDown by a page, Home/End to the
  ends, Enter/Space activate it. Exposed as public actions/methods
  (`move_cursor`, `cursor_to`, `cursor_first`/`cursor_last`, `activate`, the
  `cursor` property) with `Highlighted` / `Activated` messages; keys are only
  focus-scoped, overridable defaults (the product owns keybinding policy). The
  cursor row is the unstyled `flowview--cursor` component class. See
  `examples/cursor.py`. Default (`cursor=False`) is unchanged — arrows scroll.
- Infinite scroll: `FlowView` posts `ReachedTop` / `ReachedBottom` when an edge
  comes within `reach_threshold` rows (edge-triggered, re-arms on retreat) so a
  handler can lazy-load more.
- `FlowModel.insert_many(index, items)` and `extend(items)` — batch inserts that
  reflow once. Prepending a page of older items above the viewport keeps the
  scroll position (the row you're reading stays put). See `examples/infinite.py`
  and `docs/feature-gap-analysis.md`.
- `examples/scroll_anim.py` — demonstrates the animated jump API: smooth jumps
  to any entry / the ends, mid-flight redirect (a fresh jump supersedes), and
  `stop_scroll_animation()` to halt in place.

## [0.5.0] - 2026-07-29

### Added

- Animated jumps: `scroll_to_entry`, `ensure_visible`, `reveal`,
  `scroll_to_top`, and `scroll_to_bottom` now accept `animate=True` and an
  optional `duration` for a smooth scroll (content presents as it scrolls past).
  The default stays instant, so existing calls are unchanged. A fresh animated
  jump supersedes one in flight; `stop_scroll_animation()` halts an in-flight
  animated scroll where it is.
- Public read-only `body_width` (the width passed to the presenter — content
  width minus both gutters, hidden counting as 0), plus
  `left_gutter_effective_width` / `right_gutter_effective_width`. Lets consumers
  assert gutter width accounting, which `region.width` cannot observe (#2).

### Documentation

- `FlowDecorator.decorate` now documents two load-bearing contract properties:
  `height` is the body's post-wrap presented height at the current width, and
  the returned renderable is clamped to `width` (over-wide content is silently
  truncated, never overflowed) (#3).

## [0.4.0] - 2026-07-27

### Added

- Toggle each gutter's visibility at runtime: `show_gutter(side)`,
  `hide_gutter(side)`, `toggle_gutter(side)`, `set_gutter_visible(side, visible)`,
  and the `left_gutter_visible` / `right_gutter_visible` properties. A hidden
  gutter keeps its configured width and hands it back to the body (the list
  reflows). `examples/gutters.py` binds `[` / `]` to toggle them.

## [0.3.0] - 2026-07-26

First public release.

### Added

- **Core** — `FlowView[T]`, a virtualized flow of variable-height items built on
  Textual's `ScrollView`. Paints only the visible rows (O(viewport)), mounting a
  single widget regardless of item count. The widget is item-type-agnostic; only
  a `FlowPresenter` knows about `T`.
- **Model & entries** — `FlowModel[T]` with `append` / `insert` returning an
  `Entry` handle; `entry.update()` (mutate + re-present), `set_item()`,
  `set_state()`, `set_metadata()` / `update_metadata()`, `hide()` / `show()`,
  `remove()`. Off-screen `entry.update()` is deferred until the entry scrolls in.
- **Body & gutter split** — `FlowPresenter` fills the body, `FlowDecorator` fills
  the gutter; state/metadata changes redraw only the gutter (no body re-present,
  no reflow). Built-in `StateDecorator` + `EntryState`
  (`DEFAULT/RUNNING/SUCCESS/ERROR/CANCELLED`).
- **Two gutters** — an optional **right** gutter via `right_decorator` /
  `right_gutter_width`, independent of the left one.
- **Separators** — a `separator` drawn in the `spacing` gap between entries:
  any renderable (a plain string works) or a `callable(above, below)` for
  contextual dividers (return `None` to leave a gap blank).
- **Scroll anchoring** — `Anchor.CURRENT` / `STICKY_BOTTOM` / `STICKY_TOP`.
- **Sticky headers** — pin a group header while scrolling via `sticky_header`.
- **Spacing & background** — inter-entry `spacing` (real layout) and a full-row
  `Presentation.background` painted edge to edge.
- **Dynamic content, viewport-scoped** — `animate_entry(entry, interval, cb)`,
  `track_visibility(entry, on_show, on_hide)`, `refresh_gutter(entry)`, and the
  `animation_fps` shorthand; all work is scoped to visible entries and released
  off-screen. `AnimationHandle` / `VisibilityHandle` to stop them.
- **Selection** — opt-in single-entry selection via `selectable=True`
  (default `False`): click-to-select, `select()` / `clear_selection()` /
  `selected`, and a `Selected` message. `Clicked` fires on every click (with the
  in-entry position) for hit-testing presenter-drawn controls.
- **Text selection & copy** — native Textual text selection across entries,
  stable across scrolling (content-offset stamping); spans the whole virtual
  list including **select-all** (`Ctrl+A`). Clipboard helpers `entry_text()` /
  `copy_entry()`.
- **Minimap** — `FlowMinimap`, a scrollbar-replacing state-heat overview.
- **Search** — `find` / `find_next` / `find_previous` / `reveal`.
- **Read-ahead** — directional prefetch (`read_ahead`) for smoother scrolling.
- **Examples** — showcase, chat, groups, minimap, intervention, progress,
  dashboard, gutters, and a `benchmark` / `compare` pair (with FPS meter).
- **CI** — ruff + mypy (strict) + pytest matrix, wheel build.

### Notes

- `FlowView` ships **no colours of its own**: the `flowview--selected` and
  `flowview--sticky-header` component classes are unstyled by default, and text
  selection defers to Textual's `screen--selection`. Style them in your app.

[Unreleased]: https://github.com/tya5/textual-flowview/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/tya5/textual-flowview/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/tya5/textual-flowview/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/tya5/textual-flowview/releases/tag/v0.3.0
