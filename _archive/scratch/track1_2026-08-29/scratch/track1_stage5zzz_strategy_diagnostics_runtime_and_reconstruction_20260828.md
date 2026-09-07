# Stage 5ZZZ-B — the variables a sleeve decided on

**Route:** `track1_candidate` · **Date:** 2026-08-28 · **Orders:** never enabled, still impossible

---

## The answers

| question | answer |
|---|---|
| Written as **runtime evidence** | NKD and Swing, at every slot, from the next slot onward |
| **Reconstructed** for earlier today | NKD and Swing (the same four variables), plus Stress's gate and levels |
| Still **unavailable** | Calm's two phases; the runtime store is empty until a slot runs |
| Any trading decision changed | **No** — asserted across both sleeves and two sessions |
| Any gate / order / runtime trading file changed | **No gate.** Two runtime files gained observability-only blocks |
| `orders_possible` | **False** — `PAPER_SHADOW_EVIDENCE` |

---

## 1. Where the numbers come from

Stage 5ZZR named the four things NKD and Swing decide on and had to print *"Not reported by
detector"* beside every one. The values existed the whole time: `_scan_window` computes the trend
filter, the ATR and the ten-bar average volume for every bar it evaluates, and threw them away.

`track1_normal_r4` now takes an optional **observer**. `detect_entry_for_slot` reports each gate
it passes or stops at; `_scan_window` reports what it computed per bar. The listener's return is
discarded and its exceptions are swallowed inside the detector.

**Nothing in this stage computes a strategy value.** That is not a stylistic preference — the
detector's own docstring says *"A second implementation of an entry rule proves nothing about the
first"*, and an EMA recomputed in a diagnostics module would drift from the one the committed
artifacts were generated with.

### It changed no decision

```text
detect_entry_for_slot(...)              vs    detect_entry_for_slot(..., observer=obs)
  MES  2026-08-27, 2026-08-28                   identical setup / no-setup
  MNKD 2026-08-27, 2026-08-28                   identical
  and with an observer that RAISES on every event — identical again
```

---

## 2. What is reconstructed for earlier today

```text
global_nkd    EMA 10   66,281.71   close 65,905.00   Δ -376.71   ATR 105.71   vol 1.63×   Calm
roska4_swing  EMA 50    7,754.68   close  7,739.75   Δ  -14.93   ATR   8.12   vol 1.43×   —
```

Both report **no setup**, and both say why in words the detector produced:

- `global_nkd` — *"regime 'Calm'; this sleeve trades ['Normal']"*
- `roska4_swing` — the regime for today is not published yet; the 13:45 pre-flight is what adds
  today's SPY row, so before it there is no label to hand the detector.

Those are the nearest-failed-condition the brief asks for, and they are the detector's own gate,
not a sentence written here.

### It stops at the instant it was asked about

```text
asked at 09:00 ET   0 bars    last bar none        (the window has not opened)
asked at 14:20 ET   3 bars    last bar 14:20:00    (stops exactly there)
asked at 23:00 ET  22 bars    last bar 15:55:00    (the window is complete)
a day in the future  0 bars
```

Threading `now` from `build()` was a real gap found while writing this: the reconstruction had
hardcoded the present, which would have made "stops at now" untestable — no test could ask it
about any moment other than the one it ran in.

### When a gate stops the detector before the bars

On a Calm morning "this sleeve trades Normal" is a complete answer about the **decision** and
tells an operator nothing about the instrument. So when the detector stops at a gate before
reaching any bar, the window is walked again through **the same `_scan_window`**, deciding
nothing and discarding the result, purely so the four variables can be shown. The gate that
refused stays refused and stays reported.

---

## 3. Runtime evidence

Wired as a **third observability block** in the slot, placed and wrapped exactly like the two
already there (Stage 5ZD's signal row, Stage 5ZO's data observation): after the coverage row,
because that row is the evidence the audit counts and nothing below it may be the reason a slot
loses it. The store is append-only and dated, like every other evidence stream on this route.

The live source collects the block on the candidate path and the slot persists it. Both halves
are wrapped, and the observer factory falls back to `None` if the diagnostics module cannot even
be imported — this runs where entries are found, and an observability import must not cost a
sleeve its candidates.

**Nothing has been written yet**, and that is expected: no slot has run since the change. The
directory appears at the next one (NKD 01:10 ET Monday). A reader prefers `recorded_runtime` over
`reconstructed_today` for the same slot; a day with no runtime record reads as empty rather than
raising, which is what every historical day is.

---

## 4. What remains unavailable, and why

| | |
|---|---|
| **Calm DECIDE / OBSERVE** | Not wired. The two-phase contract says DECIDE must never be shown a value OBSERVE produced, and the live path reaches the detector through that contract rather than through `detect_entry_for_slot`. Wiring it without the phase separation would leak exactly what the contract exists to prevent, so it is left unwired rather than wired wrongly — the same judgement Stage 5ZZP recorded for the same sleeve. |
| **Runtime blocks for today** | No slot has run since the change. |
| **The Regime panel** | Already served by the existing regime record — label, posterior, runner-up, margin, entropy, the two real features, fit end, and "No published shift threshold". Untouched here. |

---

## 5. A severe regression I introduced, and caught

The first working version made the polled market-view endpoint **57 seconds per warm request**.
It had been ~0.02s.

```text
read_parquet (3,375,148 rows)    0.15s      not the problem
_cache_for (EMA/ATR pass)       14.31s      and NOT internally memoised
                                            × 4 calls (2 sleeves × detect + observe) = 57s
```

Shortening the frame is not available as a fix: the EMA is recursive over full history, so a
truncated frame produces different numbers than the detector saw — and a reconstruction that does
not match what the detector would see is worth nothing.

So the answer is served **stale-but-usable and refreshed out of band** — the pattern
`schedule_status._running_schedulers` already uses for the process scan, for the same reason.

```text
after:   cold 66s once, then 0.03s warm
```

The cache key is deliberately **stable** (sleeve, day, store) rather than including the clock or
the file's mtime: a key that changed every bar would have nothing to serve stale, so every append
would pay the full minute inline. Freshness is the TTL's job, and `last_bar_ts` says exactly which
bar the answer used. A caller that names an instant bypasses the cache and gets that instant.

Finding this needed one more correction: `build()` was passing its own derived `ref` rather than
the caller's `now`, so every request looked like a caller naming an instant and skipped the cache
entirely.

---

## 6. Results

| | |
|---|---|
| New suite | **31 passed** |
| Adjacent suites re-run after the fixes | **70 passed** |
| Caused by this stage | 3 tests, all deliberately superseded |

### Tests changed, and why

Three Stage 5ZZR tests asserted that these values read *"Not reported by detector"*. That was an
accurate description of the panel and an indictment of it; this stage inverts them. What survives
is the property underneath: **a card never shows a blank** — it carries a value or names the
reason there is none, and those are the only two shapes allowed.

Two tests **I wrote earlier today** pinned states the clock moves — "Stress and Swing have not run
yet", true when written and false eight hours later, and an exact set of failing readiness checks
that clears the moment a fifth judgeable day lands. Both now assert the property rather than the
hour. **That is the third time this session**, and it is worth naming as a pattern rather than
three accidents.

### Failures that are not this stage's

The market-view UI was rewritten (`mv2-*` markup) between stages, before this one began. Five
tests written against the older markup fail on the new Regime Monitor wording and structure, and
one is the long-standing rule-grid assertion. I also spent a patch attempt matching remembered
5ZZR markup rather than the file — the file is the authority, and it had moved.

### Safety

```text
orders_possible False · blocking ['PAPER_SHADOW_EVIDENCE'] · scheduler pid 3000, not restarted
track1_runtime/orders ABSENT · live_positions.track1.json ABSENT · TRACK1_ORDERS_APPROVED unset
confirmation file untouched · no broker connection · gates, thresholds and schedules unchanged
```

A test asserts by import graph that neither `track1_gates`, `track1_paper_readiness` nor
`track1_shadow_acceptance` reads the diagnostics module — a reconstruction must never satisfy a
readiness gate, an audit verdict or an order gate, and the cheapest way to keep that true is for
none of them to be able to see it.

**Runtime trading files changed:** `track1_normal_r4.py` (an optional observer parameter,
defaulting to None), `track1_live_source.py` and `run_live_day_track1.py` (observability blocks,
wrapped, after the coverage row). No decision path was altered, and the equivalence tests above
are the evidence.

---

## 7. Still open

- **Calm's two phases**, for the reason in §4.
- **The first runtime block** lands at the next slot; nothing has exercised that write end to end
  on real data yet, only its unit path.
- **A 66-second cold request** every five minutes' idle. It is bounded and served stale, but the
  underlying cost is `_cache_for` being un-memoised on a 3.3-million-row frame, and memoising it
  inside the detector would help every caller rather than just this one.
- The five UI tests against the rewritten market view.
