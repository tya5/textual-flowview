# reyn × textual-flowview — conversation-pane de-risking PoC

Standalone PoC. Not part of reyn's source tree; not part of textual-flowview's
public API surface — just an example app under `examples/`. Evaluates whether
`FlowView` fits as a drop-in replacement for reyn's TUI **conversation pane**
(reyn's current TUI is a `prompt_toolkit` + `rich` inline REPL, not Textual).

## Run it

```bash
PYTHONPATH=/Users/yasudatetsuya/Workspace/textual-flowview/src \
    python examples/reyn_poc/reyn_chat_poc.py
```

(from the `textual-flowview` repo root). On launch it hydrates the
conversation pane from `conversation.json` (a reyn-flavored fixture — see
below), then you can:

- type in the bottom `Input` and press Enter to add a user turn + streamed
  assistant reply,
- press `ctrl+d` to trigger a demo streamed reply without typing,
- **resize your terminal window** — both the conversation pane and the input
  box should reflow live.

Regenerate the SVG snapshots (headless, no TTY needed):

```bash
cd examples/reyn_poc
PYTHONPATH=/Users/yasudatetsuya/Workspace/textual-flowview/src:. python gen_snapshots.py
```

## Files

| File | What |
|---|---|
| `reyn_chat_poc.py` | The PoC app: `ReynChatPoc` (Textual `App`), `ReynPresenter` (renders message / tool_call / ask_user items), `ReynGutter` (reuses `StateDecorator`), hydration from `conversation.json`. |
| `conversation.json` | A hand-written fixture mimicking a reyn session's persisted conversation — see caveat below. |
| `gen_snapshots.py` | Headless SVG snapshot generator, run via `App.run_test()` pilots. |
| `snapshot_wide.svg` | Hydrated conversation at 100×40. |
| `snapshot_narrow.svg` | The *same running app*, live-resized (`pilot.resize_terminal`) from 100×40 down to 60×40 — proves resize-follow, not just "renders fine at a fixed width". |
| `snapshot_restored.svg` | Fresh mount at 100×40, snapshotted immediately after `on_mount` hydration, before any new interaction — proves restore-on-restart. |

## The 5 requirements — how shown / reyn integration point

1. **Claude-Code-like layout, preserved.**
   Shown how: `ReynChatPoc.compose()` yields exactly three widgets — a 1-line
   `StatusLine` (`dock: top`, plain `Static`, no rich content), the `FlowView`
   (`height: 1fr`, the only rich widget), and an `Input` (`dock: bottom`). No
   multi-panel dashboard. `anchor=Anchor.STICKY_BOTTOM` gives chat-style
   auto-follow (Slack/Discord/Claude-Code behavior — follows new entries only
   while already scrolled to bottom).
   Reyn integration point: this compose() would replace reyn's current
   prompt_toolkit inline-REPL screen composition; the status line takes over
   reyn's existing top-of-screen session/model/turn indicators.

2. **Only the conversation pane is "rich".**
   Shown how: `StatusLine` is a bare `Static` (one line of plain text,
   `.update()` on turn count changes only); `Input` is stock Textual. `FlowView`
   is the sole widget backed by a presenter producing Rich renderables
   (`Panel`, `rich.markdown.Markdown`, `Text`).
   Reyn integration point: reyn's audit-event stream / tool-call surfaces are
   exactly the kind of variable-height, state-tagged content `FlowView` is
   built for; the rest of the screen chrome stays as plain Textual widgets.

3. **★★ HEADLINE — conversation-pane resize-follow.**
   Shown how: `gen_snapshots.py`'s `snapshot_live_resize()` mounts one
   `ReynChatPoc` at 100×40, calls `pilot.resize_terminal(60, 40)` on the
   *same running app* (not a fresh remount), then exports
   `snapshot_narrow.svg`. Directly verified: the SVG `viewBox` width changes
   from `1238` (100-col mount) to `750` (after live resize to 60 cols), and a
   string that appears as one contiguous glyph run at 100 cols
   (`self_test.py` in a tool-call line) no longer appears contiguous at 60
   cols — it wrapped. This is `FlowView`'s width-keyed presentation cache
   reacting to Textual's `on_resize` (`src/textual_flowview/_view.py:169`),
   exactly as advertised in the library README.
   Reyn integration point: this is the owner's #1 pain point — today's
   inline-REPL conversation pane does not reflow on terminal resize at all.
   `FlowView` gives this for free from the library's own resize handling; no
   reyn-side reflow logic would be needed.

4. **★ Input box resize-follow.**
   Shown how: `Input` is a stock Textual widget in a normal Textual layout
   (`dock: bottom`); Textual widgets reflow on resize by construction — this
   is not something `FlowView` or this PoC add, it's baseline Textual
   behavior. Not separately screenshotted beyond what's visible in
   `snapshot_wide.svg` / `snapshot_narrow.svg` (the input row is present and
   full-width in both at its respective width). This requirement is the
   least novel of the five — it follows from "use Textual at all", not from
   `textual-flowview` specifically.
   Reyn integration point: none needed beyond adopting Textual for the shell;
   Input reflow is not a textual-flowview capability, it's a Textual one.

5. **★ Conversation restore on restart.**
   Shown how: `hydrate_model()` reads `conversation.json` and does
   `model.append(item)` + `entry.set_state(...)` per record inside
   `on_mount()`, before any user interaction. `snapshot_restored.svg` is
   exported immediately after `pilot.pause()` following mount — confirmed via
   direct assertion in `gen_snapshots.py` (`len(app.conversation) > 0`) and
   a standalone run that printed all 11 hydrated entries with their
   kind/role/text/state before any new turn was added.
   Reyn integration point: **reyn already persists this** — the P6 audit-event
   log (`.reyn/events`) plus session/state replay (see
   `docs/concepts/runtime/events.md`, `docs/concepts/runtime/time-travel.md`)
   is reyn's source of truth for a session's history. The real integration
   is "hydrate the `FlowModel` from a replay of `.reyn/events` on TUI
   startup" — structurally the same shape as `hydrate_model()` here, just
   fed by reyn's audit-event replay instead of a static JSON fixture. reyn's
   current inline-REPL does **not** do this today (no restore-on-launch), so
   this would be new behavior enabled by, but not exclusive to, adopting
   `FlowView`.

## Fixture caveat

`conversation.json` is a **hand-written fixture**, not something extracted
from a real reyn session. Its shape (role/kind/text/state per entry) is
chosen to mirror the fields a real `.reyn/events` replay would produce for
message / tool-call / `ask_user` entries, but no reyn code was run to
generate it and no reyn source was modified to produce it.

## Content mapping to reyn concepts

- `message` items (`user`/`assistant`, Markdown body) — reyn's
  `user_message_received` / assistant turn content.
- `tool_call` items with `state: running|success|error` — reyn's Control-IR
  op audit-events (`read_file`, `grep`, `sandboxed_exec_started`, etc.); the
  gutter marker is `StateDecorator`'s stock `EntryState.RUNNING/SUCCESS/ERROR`
  mapping, which lines up with reyn's present-layer / audit-event phases.
- `ask_user` item with clickable option chips (`examples/intervention.py`'s
  pattern: presenter draws chip spans, `FlowView.Clicked` hit-tests them via
  the same `chip_spans()` helper, resolution is `entry.set_item(...)`) — reyn's
  `ask_user` intervention flow / `user_intervention_received`.

## Inline mode vs alt-screen — investigated, not fully hands-on-testable here

This matters because the Claude-Code layout goal implies preserving terminal
**scrollback** — an inline app draws under the prompt and leaves prior
terminal output alone, vs. an alt-screen app that takes over the whole
screen and restores it on exit.

**What I actually did**: read the installed Textual 8.2.7 source directly
(`textual/app.py`, `textual/drivers/linux_inline_driver.py`,
`textual/screen.py`), because this is a headless background agent with no
TTY — `App.run_test()` (the only way to drive a Textual app here) **always**
constructs a `HeadlessDriver` regardless of an `inline=` argument: in
`App._get_driver_class`, `if headless: driver_class = HeadlessDriver` is
checked *before* the `elif inline: ... LinuxInlineDriver` branch, and
`run_test()`'s `headless` parameter defaults to (and in this session was
always) `True`. So **inline mode could not be exercised live in this
environment**, and I'm not claiming otherwise — the finding below is
research from source, not an observed run.

**What the source says**:

- Inline mode is a distinct driver (`LinuxInlineDriver` on Linux/macOS; not
  supported on Windows) that draws the app in a bounded region under the
  cursor instead of switching to the alternate screen buffer.
- The inline region's height is **not** automatically "a few lines" — it's
  computed by `Screen._get_inline_height()`
  (`textual/screen.py`): if the screen's CSS `height` is `auto`, the height
  is the natural content height; otherwise it resolves the explicit height
  style, then clamps to `app.size.height` (full terminal height) as an
  upper bound. Our `ReynChatPoc` screen has **no explicit height** set (the
  default `Screen` CSS is effectively full-height, and `FlowView` itself is
  `height: 1fr`), so as written, inline mode on this app would resolve to
  the **full terminal height** — i.e. functionally indistinguishable from
  alt-screen from a "how much of the screen does it use" standpoint, even
  though technically drawn via the inline driver.
- To get genuine Claude-Code-style inline behavior (small fixed-height
  viewport under a growing scrollback, e.g. 10–15 rows), the screen would
  need an **explicit bounded height** (e.g. `Screen { height: 15; }`), and
  `FlowView` would then virtualize *within* that small viewport — which is
  exactly what it's designed to do (it only ever presents what's visible +
  overscan, regardless of viewport size). Nothing in `FlowView`'s
  implementation appears to assume alt-screen or a specific height; it reads
  its content height from the widget's allocated size like any Textual
  scrollable.
- I did **not** find anything in `FlowView`'s source
  (`src/textual_flowview/_view.py`) that special-cases or breaks under
  `LinuxInlineDriver` — the virtualization is driven by `on_resize` /
  `virtual_size`, which are Textual's own screen-geometry primitives, not
  alt-screen-specific. This is an inference from reading `_view.py`, not a
  live-tested claim.

**Honest bottom line**: inline mode + a bounded-height `FlowView` looks
compatible **on paper** (no code path in either Textual's inline driver or
FlowView's implementation appears to conflict), but this PoC has **not**
run that combination live — running headless-only tools cannot drive the
`LinuxInlineDriver` at all. Verifying inline-mode + scrollback preservation
+ FlowView virtualization together needs a real TTY, which was not available
to this agent. Treat this as the single most important open question before
committing to `FlowView` for the "Claude-Code inline feel" goal specifically
(as opposed to the resize-follow and restore-on-restart goals, which this
PoC does verify directly).

## Requirement status summary

| # | Requirement | Status |
|---|---|---|
| 1 | Claude-Code-like layout | Fully demonstrated (headless run + snapshots) |
| 2 | Only conversation pane is rich | Fully demonstrated |
| 3 | ★★ Conversation resize-follow | Fully demonstrated (live-resize snapshot pair, verified via SVG viewBox + text-wrap diff) |
| 4 | ★ Input resize-follow | Demonstrated structurally (stock Textual behavior); not separately isolated in a snapshot beyond the input row being present/full-width in both size snapshots |
| 5 | ★ Restore on restart | Fully demonstrated (hydration verified programmatically + via snapshot) |
| — | Inline mode + scrollback | **Not directly testable here** (no TTY); researched from Textual 8.2.7 source, reported as a finding with explicit confidence caveats above |
