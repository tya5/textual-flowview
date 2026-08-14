# Callbacks, messages and the event loop

Everything FlowView calls into runs on the Textual event loop — the same thread
that handles input, painting and animation. FlowView never moves your code to a
thread. So anything that blocks freezes the whole UI for that long: keys stop
responding, spinners stop spinning, nothing repaints.

The practical question is *where to put slow work*, and FlowView gives you two
very different kinds of extension point.

## The two kinds

| | **Messages** | **Callbacks** |
| :- | :- | :- |
| Examples | `Highlighted`, `Selected`, `Clicked`, `ReachedTop` / `ReachedBottom`, `FollowChanged`, `OverlayFinished` | `present`, `decorate`, `separator`, `sticky_header`, `search_text`, `clipboard`, `on_show` / `on_hide`, `animate_entry` |
| How you receive it | a handler on your app/widget (`on_flow_view_highlighted`) | a function you hand to FlowView |
| **May be `async`** | **yes** — `async def` handlers are a Textual feature and work out of the box | only `present` and `clipboard` |
| When it runs | **later**, off FlowView's call stack (posted to the message pump) | **inline**, inside FlowView's call stack |

**Put slow work in a message handler.** That is where the reactive things
naturally live anyway — "the reader moved to this entry, load its detail", "they
committed a selection, run the thing", "they reached the top, fetch older
history" — and there you can simply `await`.

Measured: an `async def on_flow_view_highlighted` that awaits 150 ms and then
mutates the entry works exactly as written — `set_current()` returns in **0.5 ms**
(the handler runs afterwards, never re-entering FlowView), and the UI heartbeat
keeps ticking through the await.

```python
class MyApp(App):
    async def on_flow_view_highlighted(self, event: FlowView.Highlighted) -> None:
        if event.entry is not None:
            detail = await fetch_detail(event.entry.item)   # UI stays live
            event.entry.set_item(detail)                     # content change is fine
```

## The trap: "it's in a worker" is not "it's on a thread"

Presentation is driven by a Textual **worker**, and it is natural to read that as
"off the UI thread". It isn't: `run_worker` with an async callable creates an
`asyncio` task on the *same* loop. A coroutine only yields at an `await`, and a
typical `present` is pure CPU with no `await` in it — so it holds the loop from
start to finish.

Measured, for a 300 ms body inside `run_worker`:

| worker body | UI heartbeat during it |
| :- | --: |
| I/O-bound (`await asyncio.sleep`) | **29 / 30** ticks — the loop stays live |
| CPU-bound (no `await`) | **3 / 33** ticks — the loop is held |
| `thread=True` (blocking call) | **35 / 35** ticks |

So `await` is what frees the loop, not "being in a worker". And four 250 ms
CPU-bound `present` calls starved a 10 ms heartbeat to **10** ticks where a free
loop would manage ~121.

The dangerous shape isn't one slow call — it's per-call work that grows with your
content. Re-rendering an entire large Markdown body on every streamed chunk keeps
each call "small" while the loop never gets a turn.

## Callback reference

| Callback | Async? | Frequency | Notes |
| :- | :- | :- | :- |
| `FlowPresenter.present(entry, width)` | **yes** (`async def`) | per entry, per revision, per width — **the hot one** | `await`ing here frees the loop; a pure-CPU body does not |
| `clipboard(text)` | **yes** (sync or async accepted) | per yank | its result is reported back, so it can't be fired and forgotten — hence async support |
| `FlowDecorator.decorate(...)` (left/right) | no — painting is synchronous | per entry whose gutter state/size changed; every `animation_fps` tick | must not wait for anything |
| `separator(above, below)` | no — painting | per adjacent pair drawn (cached) | |
| `sticky_header(entry)` | no — painting | per candidate while resolving the pinned header (memoised) | |
| `search_text(item)` | no | **per entry in the model**, until a match | must be a cheap attribute read, not a re-parse |
| `on_show` / `on_hide` | no | per entry entering/leaving the viewport, i.e. while scrolling | see below |
| `animate_entry(callback)` | no | your interval, while the entry is visible | |
| `find(predicate)` | no | per entry, per call | |

### `clipboard=` may be async

```python
async def copy(text: str) -> bool:
    proc = await asyncio.create_subprocess_exec("pbcopy", stdin=asyncio.subprocess.PIPE)
    await proc.communicate(text.encode())
    return proc.returncode == 0

FlowView(..., clipboard=copy)      # awaited; the UI stays live meanwhile
```

A sync hook still works, but if it shells out, `subprocess.run` blocks the UI for
the lifetime of that process.

### `on_show` / `on_hide` are sync — start slow work, don't wait for it

FlowView doesn't use their return value and doesn't await them, so **you** own
the scheduling. Doing the slow thing inline blocks scrolling:

```python
def on_show(entry):
    view.run_worker(load_image(entry), group=f"img-{entry.id}", exclusive=True)

view.track_visibility(entry, on_show=on_show, on_hide=...)
```

`run_worker` returns immediately (measured: 0.14 ms), and if the coroutine
`await`s, the loop stays live while it runs. Scheduling stays on your side
deliberately: a show can be followed by a hide before the work lands, and only
you know whether to cancel, ignore or serialise that — `exclusive=True` with a
per-entry group is usually what you want. Note that a *CPU-bound* worker still
blocks (see the table above); for that, `thread=True` — your code, your call.

### The paint hooks cannot be async at all

`decorate`, `separator` and `sticky_header` are called while a row is being
painted, and painting must produce a row synchronously — there is nowhere to
await. Whatever they draw must already be in memory. If a gutter wants data it
doesn't have: draw a placeholder, fetch it off the paint path (as above), and
call `refresh_gutter(entry)` when it lands.

## Getting heavy *rendering* off the loop

Turning a renderable into cells is FlowView's own work, but it *runs your code* —
rendering calls the renderable's `__rich_console__`. So FlowView will not move it
to a thread: code written for a single-threaded UI is entitled to assume it is
called on the main thread, in order, and quietly breaking that would be worse
than being slow.

The seam is the other way round: **hand FlowView already-rendered rows** and it
does no rendering at all.

```python
Presentation(height=len(strips), strips=strips)   # instead of renderable=...
```

You produce those `Strip`s wherever you like — a thread, a process pool, a cache,
precomputed at ingest — because it is your renderable and only you know whether
it can run off the main thread. FlowView just blits them (paint becomes a lookup
plus a width fit). `Entry.patch_rows(start, strips)` is the same seam for
streaming: append rendered rows without re-rendering the body.

## Streaming specifically

The failure mode that shows up first in an AI-agent or log TUI is a stream whose
per-chunk cost is O(size of the message so far): each chunk is affordable, the
sum is not, and the UI is frozen for the whole reply.

- Use `Entry.patch_rows(start, strips)` to append rendered rows instead of
  re-rendering the whole body — O(tail) per chunk instead of O(size). See the
  README for the safe-watermark contract (it is *not* safe to apply naively to
  Markdown).
- Or throttle: render at a fixed rate rather than per chunk.
- **Coalesce your own updates.** If a producer outruns the display, collapse the
  backlog to its latest state and update once rather than calling `update()` for
  every queued item, and make sure your consumption loop yields between chunks.
  FlowView already coalesces its side — the present loop converges to the newest
  revision — but the queue on your side needs the same.

## Rules of thumb

- **Slow and reactive → a message handler**, where you can `await`.
- **Keep callbacks bounded and independent of total content size.** Rendering a
  handful of Rich renderables is microseconds; re-rendering a 30 KB Markdown body
  every chunk is not.
- **Never block on I/O in a callback** — network, disk, `subprocess.run`.
- **Do expensive work before the item reaches the model.** Fetch, parse and
  decode up front; let `present` do layout only.
- **`await` frees the loop; being in a worker does not.**

## Diagnosing a freeze

Add a heartbeat and watch whether it keeps time while you exercise the app:

```python
self._beats = 0
self.set_interval(0.01, lambda: setattr(self, "_beats", self._beats + 1))
```

If the count falls far short of `elapsed / 0.01`, something on the loop is
blocking; the table above is the list of suspects. A memory profiler won't show
this — it's time, not memory — so bisect by stubbing callbacks out until the
heartbeat recovers.
