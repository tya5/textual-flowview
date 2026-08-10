# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.16.2] - 2026-08-11

### Fixed

- **The rendered-strip cache no longer grows with every entry ever scrolled
  past.** Strips are a *per-frame* optimisation — `render_line` is row-granular
  while rendering is entry-granular, so the cache collapses an entry's N
  row-requests into one render. Off-band entries have no rows to collapse, but
  their strips were never released (only on removal / resize / clear), so memory
  tracked *entries visited* rather than what's on screen. They're now dropped
  when an entry leaves the present band (visible + overscan + directional
  read-ahead), which the view already computes on every scroll.

  Measured on 500 entries × 10 rows, fully scrolled: strip cache **498 entries →
  3**, and scrolling back repaints in **0.34 ms** showing real content — the
  `Presentation` is retained, so strips re-render **synchronously** with no
  placeholder and no re-`present`. The band is wider than the viewport, so
  ordinary scrolling doesn't thrash, and a pinned sticky header keeps its strips
  even when it sits above the band (it's composed every frame).

## [0.16.1] - 2026-08-08

### Fixed

- The overlay's `covered` lines now match **what the overlay actually covers**:
  the rows exactly as painted, **gutters (and sticky header / separators)
  included**. They were built from `row_text`, which is deliberately body-only
  (selection offsets are body-relative), while the overlay paints the full
  content width — so an effect applied to `covered` was narrower than the region
  it replaced. `render_line` and the covered-lines capture now share one
  composition path, so the two can't drift apart.

  The factory signature is unchanged (`frames(width, height, covered)`, with
  `len(covered) == height`); only the string contents grow to include the gutter.
  `row_text` is unchanged and stays body-only.

## [0.16.0] - 2026-08-08

### Changed

- **`play_overlay`'s frame factory now receives the covered lines**:
  `frames(width, height, covered)` — `covered` is the body text of the rows the
  overlay is hiding right now (one string per visible row, top to bottom, scroll
  offset resolved). So an effect can act on the current screen (dissolve it, rain
  it away) without the caller recomputing it from `scroll_offset` + `row_text`.
  The overlay owns what it covers, so it hands it to the callback rather than
  exposing a standalone accessor. `examples/screensaver.py` now dissolves the
  actual on-screen text. (Breaking: the factory takes a third argument.)

## [0.15.3] - 2026-08-08

### Added

- `examples/gif.py` — an animated GIF playing in a feed entry. A GIF is just
  image frames advanced on a timer: render the current frame as a renderable and
  drive it with `animate_entry`, which ticks **only while the entry is on
  screen**, so an off-screen GIF stops animating automatically (and resumes on
  scroll-in). No core change; frames are half-blocks (rich-pixels), cheap per
  frame and terminal-agnostic — the fit for animation, vs real-pixel stills.

## [0.15.2] - 2026-08-08

### Added

- `examples/image.py` — images in the feed, composed with text in a single entry
  (avatar beside a message via `Table.grid`, an inline picture with a caption via
  `Group`). On Kitty / WezTerm they're **real pixels** via
  [textual-image](https://github.com/lnqs/textual-image)'s renderable (Kitty
  graphics protocol, Unicode-placeholder mode — cell-based, so it virtualizes and
  clips correctly while scrolling); other terminals fall back to a half-block
  approximation. No core change — an image is just a `RenderableType` in a
  `Presentation`; textual-image is an example-only dependency.

## [0.15.1] - 2026-08-08

### Documentation

- Spell out that the viewport-overlay API is **effect-library-agnostic**:
  FlowView's only runtime dependency is `textual` and it never imports an effects
  library — consumers install TerminalTextEffects (or any source) themselves and
  bridge each frame with `Text.from_ansi`, shown inline, with the rationale for
  not bundling it.
- Inline `examples/*.py` references in the README are now clickable links, so
  each feature section leads straight to its example.

## [0.15.0] - 2026-08-08

### Added

- **Viewport overlay** — `play_overlay(frames, *, fps=30, loop=False)` /
  `stop_overlay()` / `overlay_active` / the `overlay` property / the
  `OverlayFinished` message. Paints a full-viewport animation over everything,
  **screen-relative** (fills the visible window, doesn't scroll) and
  **non-destructive** (model / scroll / cursor untouched — stopping restores the
  exact prior view). `frames(width, height)` returns a per-frame iterator of Rich
  renderables sized to the viewport, re-invoked on resize and (with `loop=True`)
  each cycle. oneshot (`loop=False`) plays once then clears and posts
  `OverlayFinished`. Driven by FlowView's own animation timer.

  FlowView stays effect-agnostic: it owns *painting the viewport*, while the
  effect and any trigger policy (idle → screensaver, an intro, a transition) are
  the caller's. New `examples/screensaver.py` drives a random
  [TerminalTextEffects](https://github.com/ChrisBuilds/terminaltexteffects)
  effect on idle (`Text.from_ansi(frame)` bridges TTE frames to renderables).

## [0.14.0] - 2026-08-07

### Added

- **`FlowView.following` + `FlowView.FollowChanged`** expose sticky-edge follow
  state (#12). `following` is `True` while the view auto-follows its sticky edge
  (the tail for `STICKY_BOTTOM`, the head for `STICKY_TOP`); it posts
  `FollowChanged` on every flip. Handle it instead of inferring "has the reader
  left the tail?" from `max_scroll_y` / `scroll_offset`, which can't distinguish
  "parked at the bottom, following" from "scrolled up during early streaming".

### Fixed

- A reader's **scroll-up during early streaming** now releases sticky-bottom
  follow even when there's no room to move yet (`max_scroll_y` still ~0) (#12).
  The release was latched only in `watch_scroll_y`, which never fires when the
  scroll position can't change — so a wheel-up at the start of a stream was
  swallowed and new content kept yanking the reader back to the tail. The intent
  is now caught at the scroll event/action (wheel, PageUp/Home, arrow scroll),
  independent of available room.

## [0.13.1] - 2026-08-07

### Fixed

- `show_cursor()` / `toggle_cursor()` no longer move `current` (#11). Revealing
  the cursor is visibility-only. The regression: the cursor↔highlight sync only
  ran one way (cursor → highlight), so revealing dragged `current` to a stale
  `_tc_row` — landing on entry 0 when `current` had been moved by anything other
  than a keypress (streaming, `set_current`, a click). Now the text cursor is
  kept riding `current` at the mutation site (`set_current`), so reveal — and a
  relative move issued while the cursor is hidden — starts from where `current`
  is; a content-change reanchor never moves `current`.

## [0.13.0] - 2026-08-07

### Changed

- **Replaced "copy mode" with an always-available text cursor + visual mode.**
  There is no mode to enter/leave anymore. The vim movement keys are always
  live, `c` shows/hides the cursor block, and **visual mode** (`v`/`V` … `y`) is
  the only real mode. Rationale: the copy-mode on/off was a key-capture *gate*,
  not a real mode — the genuine "same key, two meanings" state is the visual
  selection (`v`), driven by the anchor.
  - **Two zoom levels, one cursor:** while the cursor is hidden, `j`/`k` (and
    `↑`/`↓`) move the **entry** cursor (`current`); with the cursor shown they
    move it at the **character/row** level. The text cursor is now **synced**
    with the entry highlight (moving it moves `current` and posts `Highlighted`)
    — except during a visual selection, when the anchor and highlight are frozen
    so content doesn't shift mid-select; on exit the highlight catches up to the
    cursor.
  - Char-level keys (`h`/`l`/`w`/`y`/…) **bubble to the app while the cursor is
    hidden**, so a plain feed doesn't steal them; `j`/`k` stay live.
  - `gg` → **`g`** (single key) to jump to the top.

### Removed

- `enter_copy_mode()` / `exit_copy_mode()` / `toggle_copy_mode()` / `copy_mode`
  and the `copy_mode=` flag → use `show_cursor()` / `hide_cursor()` /
  `toggle_cursor()` / `cursor_visible` and the `cursor=` constructor flag (`c`
  by default).
- `FlowView.CopyModeChanged` message.
- The `copy_` method prefix: `copy_cursor_move` → `cursor_move`, `copy_visual` →
  `visual`, `copy_yank` → `yank`, `copy_search*` → `search*`, `copy_scroll_*` →
  `cursor_scroll_*`, `copy_scrolloff` → `cursor_scrolloff`, etc.

## [0.12.0] - 2026-08-02

### Removed

- **Dropped the deprecated highlight/select aliases** added in 0.11.0 — the
  unified "current entry" cursor is now the *only* surface, so there is one
  obvious way to do it rather than two names for everything. Removed: the
  `highlight=` constructor flag (use `selectable=`), the `selected` /
  `highlighted` properties (use `current`), the `select()` / `clear_selection()`
  / `highlight_entry()` / `move_highlight()` / `highlight_first()` /
  `highlight_last()` methods (use `set_current()` / `move_current()` /
  `current_first()` / `current_last()` / `activate()`), the `Activated` message
  (handle `Selected`), and the `flowview--selected` component class (style
  `flowview--highlight`). Migration is a mechanical rename; see the *Current
  entry* section in the README.

## [0.11.0] - 2026-08-02

### Changed

- **Unified the keyboard highlight and mouse selection into one "current"
  entry**, like Textual's `ListView`. They were two separate features with two
  independently positioned cursors — confusing, and no consumer used both at
  once (each picked one). Now there is a single cursor driven by **both**
  keyboard and mouse, with two events: `Highlighted` when it **moves** (browse)
  and `Selected` when it's **committed** (Enter / Space / click). New canonical
  API: `current`, `set_current(entry)`, `move_current(delta)`, `current_first()`
  / `current_last()`, `activate()`.
  - **Back-compat via deprecated aliases** — existing code keeps working:
    `selectable=` / `highlight=` both enable it; `selected` / `highlighted` both
    read `current`; `select()` moves-and-commits; `highlight_entry()` /
    `move_highlight()` / `highlight_first()` / `highlight_last()` map onto the
    `current` methods; `Activated` is still posted alongside `Selected`;
    `flowview--selected` still styles the current row (synonym of
    `flowview--highlight`).
  - **Behaviour changes to note:** enabling the cursor (`selectable=` *or*
    `highlight=`) now enables **both** keyboard and mouse — previously
    `selectable=` was mouse-only and `highlight=` keyboard-only. `Selected` now
    fires on commit (every click / Enter), not on selection-change; clearing the
    cursor (click-away, remove, clear) posts `Highlighted(None)` rather than
    `Selected(None)`.

## [0.10.0] - 2026-08-02

### Added

- Copy mode gains vim-style **half-page and full-page scrolling**: `Ctrl-D` /
  `Ctrl-U` (half) and `Ctrl-F` / `Ctrl-B` (full, two rows of overlap), carrying
  the cursor with the view so it keeps its screen row. Public methods
  `copy_scroll_half_page_down` / `half_page_up` / `page_down` / `page_up`. This
  is the vim-idiomatic "scroll faster" — bigger-unit motions rather than a
  configurable `Ctrl-E` step (count prefixes only affect the first press, and
  hold-to-repeat speed is a terminal setting, not the app's).
- `FlowView(copy_mode=True)` starts in copy mode on mount — a
  **copy-cursor-first** widget with no toggle; motions and yank are live from
  the start. Copy mode was already fully opt-in (nothing enters it by default);
  this just makes "always on" declarative, alongside `highlight=` /
  `selectable=`. `Esc` still exits unless the consumer rebinds it.

## [0.9.0] - 2026-07-31

### Changed

- Streaming a single entry now reflows in **O(1)** instead of O(N). A height
  change from `update`/`patch_rows`/present only dirties the prefix-sum offsets
  from that entry's index onward (`Viewport.invalidate_height_of`) rather than
  rebuilding all N; the last entry — the streaming hot path — is constant-time.
  Measured flat ~0.04 ms/reflow from N=100 to N=20000 (was ~1.8 ms at N=5000).
  Structural changes (insert/remove/resize) still do a full rebuild. Pairs with
  `patch_rows`: `patch_rows` removes the O(size) render term, this removes the
  O(N) reflow term, so a long backlog no longer taxes each streamed chunk (#10).

### Added

- Incremental streaming: `Entry.patch_rows(start, strips)` replaces an entry's
  body rows from `start` onward with pre-rendered `Strip`s, keeping the frozen
  prefix as-is — O(tail) per chunk instead of the O(size) full re-present that
  `set_item`/`update` cost. The consumer computes the safe watermark and renders
  the hot tail (only it knows how far its renderable is stable); FlowView just
  splices, stays type-agnostic, and falls back to a full `present` on resize.
  `Presentation` gains a `strips=` field so a presenter can hand FlowView
  pre-rendered rows directly (#10).

### Fixed

- Text selection is confined to the **body** columns — the gutter is decoration,
  not selectable text (like a scrollbar). Selection offsets are now stamped
  body-relative and the gutter cells carry none, so neither a mouse drag nor copy
  mode can address them and a yank never carries gutter glyphs. `row_text(y)` and
  copy mode are body-only accordingly; CJK alignment and gutter-less rows are
  unchanged (#9).

## [0.8.0] - 2026-07-30

### Added

- Copy-mode clipboard is now pluggable: `FlowView(clipboard=...)` or an
  overridable `write_clipboard(text) -> bool`. The default still uses OSC 52
  (`App.copy_to_clipboard`), but a consumer can supply a reliable local sink
  (`pbcopy`/`xclip`/`wl-copy`) whose result is observable — a per-view seam
  instead of overriding app-wide copy. OSC 52's caveats (macOS Terminal, tmux,
  no ack) are now documented (#7).
- `FlowView.CopyModeChanged` message, posted on entering and leaving copy mode
  (`copy_mode` is the new state) — so app chrome can track the mode, including
  the `Esc` exit that happens inside the widget, without polling (#8).

## [0.7.0] - 2026-07-30

### Changed

- **Breaking:** the keyboard *cursor* (opt-in entry navigation from 0.6.0) is
  renamed to **highlight**, freeing "cursor" for a per-character text cursor.
  `cursor=` → `highlight=`; `move_cursor` → `move_highlight`; `cursor_to` →
  `highlight_entry`; `cursor_first`/`cursor_last` → `highlight_first`/
  `highlight_last`; the `cursor` property → `highlighted`; component class
  `flowview--cursor` → `flowview--highlight`. Messages (`Highlighted`,
  `Activated`) and `activate()` are unchanged. `examples/cursor.py` →
  `examples/highlight.py`.

### Added

- **Copy mode** — an opt-in vim-style text cursor over the rendered content:
  `enter_copy_mode()` / `exit_copy_mode()` / `copy_mode`, with the motions as
  public methods/actions (`copy_cursor_move`, word / line / top-bottom moves,
  `copy_visual()` / `copy_visual_line()`, `copy_yank()`, `copy_scroll_*`) and
  vim-like default bindings (`hjkl w b e 0 $ ^ gg G v V y zz zt zb Ctrl-E Ctrl-Y
  Esc`) that are live only while in copy mode and fully overridable. Yank copies
  exactly the highlighted text. `copy_scrolloff` keeps N rows of context around
  the cursor (999 pins it to the centre); `Ctrl-E`/`Ctrl-Y`
  (`copy_scroll_line_down`/`up`) scroll the view without moving the cursor row.
  See `examples/copy_mode.py`.
- `FlowView.row_count` and `row_text(y)` — the content-row count and per-row
  text (the string a selection `Offset.x` indexes into), the primitives copy
  mode is built on. `entry_at_row(y)` maps a content row to its entry.
- Copy mode: search the selection — `copy_search_selection()` (default `*`)
  searches for the visual selection (or the word under the cursor) and jumps to
  the next occurrence; `copy_search_next` / `previous` (`n` / `N`) repeat,
  wrapping; `copy_search(query)` for an arbitrary string. Plus `[` / `]`
  (`copy_cursor_entry_start` / `end`) jump within the current entry.
- Copy mode integrates with the entry highlight (`highlight=True`): it **starts**
  on the highlighted entry, and ↑/↓ move the text cursor by entry
  (`copy_cursor_entry`) while h/j/k/l move by character. The highlight itself is
  **held fixed** during copy mode — moving the cursor never moves it or posts
  `Highlighted` (a consumer may mutate content in that handler). The cursor is
  anchored to its entry, so it rides insert/remove/reflow instead of sliding to a
  stale row.

## [0.6.2] - 2026-07-30

### Fixed

- Mouse text selection on rows with **double-width glyphs** (CJK, emoji): the
  selection span is in character offsets but the highlight cropped in cells, so
  the highlighted columns drifted from the drag/copied text and glyphs were
  clipped mid-cell (characters appeared to vanish). Character offsets are now
  converted to cell columns before cropping; ASCII rows are unaffected.

## [0.6.1] - 2026-07-30

### Fixed

- `flowview--selected` / `flowview--cursor` / `flowview--sticky-header` now honour
  the documented "no colours by default" contract: an **undeclared** class paints
  nothing (previously it painted the widget's inherited fg/bg across the row —
  e.g. a permanent near-black block on the cursor row) (#5). A **declared**
  highlight background is applied as an override, so it wins over a row's
  `Presentation.background` instead of being silently swallowed on tinted rows
  (#6).

### Changed

- Repositioned the README, package description, and repo metadata to lead with
  the primary use case: AI-agent / chat / log TUIs (the widget is still a general
  variable-height virtualized list underneath).

## [0.6.0] - 2026-07-29

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

[Unreleased]: https://github.com/tya5/textual-flowview/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/tya5/textual-flowview/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/tya5/textual-flowview/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/tya5/textual-flowview/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/tya5/textual-flowview/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/tya5/textual-flowview/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/tya5/textual-flowview/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/tya5/textual-flowview/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/tya5/textual-flowview/releases/tag/v0.3.0
