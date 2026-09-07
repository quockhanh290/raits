# Stage 5ZZZ-S — the dashboard was paying a full pass over the bar history on the request path

**Route:** `track1_candidate` · **Date:** 2026-08-29 · **Orders:** never enabled, still impossible

---

## 1. Half the premise was my own measurement error

Stage 5ZZZ-R reported >300s and ~23s **"on both cold and warm calls, so not just warmup"**. The
first thing this stage did was re-measure on a quiet machine:

| endpoint | median | range |
|---|---:|---|
| `track1-market-view` | **1.20s** | 1.16 – 1.24 |
| `track1-runtime` | **1.77s** | 1.38 – 3.51 |

Nothing like 23s. The two "warm" readings in 5ZZZ-R were taken while an **abandoned cold
market-view request was still executing server-side** — they measured contention, not the
endpoint. The "not just warmup" half of the premise was wrong, and it was mine.

What survived re-measurement was the other half, and it is real:

```text
build()  COLD (fresh process) : 71.17s
build()  warm                 :  1.12s      ← 63× cliff
```

I also tried to reproduce the contention deliberately and **failed the first time**: abandoning
a request that completes in 1.2s leaves nothing running. Under genuine concurrent load the
effect is plain — three concurrent market-view calls push `track1-runtime` from 1.77s to
**6.11s**, and the server is threaded but GIL-bound (3 concurrent runtime calls = 3.42s wall
against a 1.77s single call).

## 2. Root cause

Profiled cold, 127s total:

```text
_strategy                          106.6s
  _recon_cached / reconstruction   101.2s
    _swing_cache                   100.6s
      resample_5m  × 11,410         85.1s   ← full-history 5-minute resample per instrument
calm_blocks                         15.0s
_label_map → label_regimes          12.8s   ← an HMM fit
stress daily_slices                  9.7s
```

`_swing_cache` is keyed on `id(df)`, so a fresh process recomputes everything and a warm one
hits the cache. That is the whole cold/warm cliff.

The part that made it a *dashboard* bug rather than an arithmetic cost: **it ran inline on the
request path, and it blocked the entire payload** — every other sleeve, the regime block and the
levels note all waited behind a panel they do not depend on.

That was a **documented deliberate trade**, not code residue:

> *Nothing cached at all. Pay once rather than show an empty panel on first load.*

So I did not silently reverse it. The reasoning is recorded beside the change: an empty panel
says nothing, but a panel that says *what it is doing and that it will fill in* is not the thing
that trade was avoiding.

**No subprocess, no shell, no `ops.py`, no PowerShell, and no broker call** appears anywhere in
these two endpoint paths — checked in the source and measured on the running backend.

## 3. What changed — all of it read-only dashboard code

One file, `monitor/backend/track1_market_view.py`. **No runtime trading file was edited.**

1. **`_recon_cached` no longer computes inline on a cold miss.** It spawns the same background
   worker the aged-out branch already used, and claims the key *under the lock* — without that,
   every poll during a 71s warm-up would start its own worker, all recomputing the same thing.
2. **`_recon_state` added**, so the caller can tell *still computing* from *computed and it
   raised* and report the difference instead of collapsing both to empty.
3. **Calm phases deferred** through the same path (was 15.0s inline).
4. **Stress `daily_slices` deferred** (was 6.5s inline) — with its **mtime key kept exactly as
   it was**. Only *when* it is computed changed, never *what invalidates it*. A TTL there was
   considered and rejected upstream for a good reason, and this stage did not overturn it.
5. **`warm()` added** for tests and offline callers. The request path must never call it — a
   request that waits is the thing this stage removed.

One frontend change, `global_index/dash/realtime/realtime.js`: the panel only ever read
`strat.rules`, so during warm-up an empty list rendered **identically to a session with nothing
unmet** — two different facts wearing the same face. It now shows a muted *"Rule values
pending"* chip carrying the reason the backend already sends. Display only; it decides nothing.

## 4. Before and after

Measured on the backend actually serving the final code.

| | before | after |
|---|---:|---:|
| market-view, **warm** | 1.20s | **0.02s** |
| market-view, **cold** (HTTP, fresh backend) | >300s *(5ZZZ-R)* / 71.2s in-process | **18.3s** |
| runtime, **warm** | 1.77s | **1.89s** |
| runtime, **cold** | — | 39.7s |

**Targets:** market-view under 5s — met comfortably (0.02s). runtime under 2s — met (median
1.89s, range 1.33–1.91). See §6 for why it is not lower.

The 39.7s runtime cold reading was taken while the market-view warm-up workers were saturating
the CPU. That is the same contention effect that produced the 5ZZZ-R numbers, and I am labelling
it rather than presenting it as the endpoint's cost.

## 5. Did anything become unavailable?

**Warm: no.** The payload was compared key-by-key against the pre-fix capture — **0 keys lost, 0
keys added**, and every sleeve status identical (`no_setup` / `missing_bars` / `no_setup`). Swing
and NKD still report `regime_basis: previous session (lag 1)`, so Stage 5ZZZ-Q's guarantee
survives.

**During the cold window only**, the deferred panels report `not_available` with a sentence
saying it is still being computed and will fill in on a later poll. No value is invented, nothing
reads as a `PASS`, and the panels do fill in — measured at ~85s after a cold start.

## 6. What I did not fix, and why

`track1-runtime` warm sits at 1.89s. Its dominant cost is the **order gate's wiring scan**: 160
`ast.parse` calls and 382,088 `ast.walk` calls per request, 1.85s, because `_gates()` calls both
`as_ledger()` and `may_enable_orders()` and each re-measures every blocker.

I did not fix it, for two reasons rather than one:

- It lives in `global_index/track1_gates.py`, a **runtime trading file this stage may not edit**.
- Caching it dashboard-side would mean serving a **safety display stale**, and deriving
  `orders_possible` from the ledger myself would be recomputing a gate differently from the slot
  code — which the brief explicitly rules out.

**The correct fix, which needs authorisation:** memoise `_identifiers` on `(path, mtime, size)`.
It is a pure function of file content, so the memo is behaviour-preserving, and it would speed up
*every* gate consumer rather than only the dashboard.

## 7. Tests

**13 new, all passing. Six mutations, six caught, none survived** — including restoring the
original inline computation (the exact regression), collapsing `_recon_state` to always-ready,
removing the single-worker guard, and a worker that never writes its value. The two source scans
were themselves checked against a deliberately bad source to prove they can detect a
`subprocess` or broker import rather than passing on nothing.

**Regression: 461 passed, 5 failed** across ten suites, plus **89 passed** in the two JavaScript
suites and a `node --check` on the edited file.

### I broke something, and an existing test caught it

The stress branch **ignored an explicitly-named `now`** — a caller asking for a specific instant
got the deferred warming state instead of that instant computed. That is the route's own
convention and I had broken it. Five tests in the Stage 5ZZZ-F UI-contract suite failed on it;
after the fix that suite is **38/38**. This is precisely what those tests exist for, and it is
worth saying plainly rather than folding into a pass count.

### The five remaining failures are pre-existing — proven, not assumed

Three are in Stage 5ZZZ-B. I first assumed they were mine and added a `warm()` call to their
fixture; that **did not fix them**. So I re-ran them with the **pre-stage inline behaviour
restored at runtime** by monkeypatch — they **fail there too**, which settles it.

Two are in Stage 5ZZP and are stale in the same way the 5M-D suite was in 5ZZZ-R:

- one forbids the name `label_regimes` in the module, but Stage 5ZZQ **deliberately added it**
  with an mtime cache — a later stage superseded the earlier rule;
- one expects `NOT_COMPUTED_UNTIL_ENTRY` for NKD and Swing, but Stage 5ZZZ-B **wired** those two
  sleeves, so that branch is now unreachable for them.

**Left failing, not re-pinned.** Re-pinning asserts the new values are correct, which is the
operator's call.

One of my own tests failed on its first run for a real reason: it raced its own stub. A reader
that returns instantly can legitimately finish before the caller re-reads the cache, so asserting
`None` was wrong. The stub now sleeps.

---

## 8. Answers

| question | answer |
|---|---|
| Before/after, market-view | warm **1.20s → 0.02s**; cold **>300s → 18.3s** |
| Before/after, runtime | warm **1.77s → 1.89s**; unchanged in substance |
| Root cause | a full-history 5-minute resample (11,410 `resample_5m` calls) computed **inline on the request path**, blocking the whole payload |
| What was cached/deferred | the sleeve reconstructions, the calm phases and the stress daily slices — all moved to background workers |
| Did data become unavailable | **No** when warm; during warm-up only, with an explicit reason |
| Backend restart required | **Yes, and done three times** — a read-only dashboard fix cannot be served by a process holding the old module |
| Scheduler | **UNTOUCHED**, pid 34564, unchanged since 09:11:11 |

### Safety

```text
orders_possible          False
blockers                 ['PAPER_SHADOW_EVIDENCE']
orders sent              ZERO
orders dir               ABSENT
TRACK1_ORDERS_APPROVED   unset
confirmation             untouched, sha16 67504a1c8a31a6a4, dated 2026-08-27
swing paper override     present, valid, grants nothing
broker calls from these endpoints   ZERO   (the backend's one persistent read-only IBKR
                                            connection belongs to a different reader and
                                            predates every poll; 20 polls created no new
                                            connection and spawned no child process)
scheduler                pid 34564, track1-only-shadow, NOT restarted this stage
params · gates · thresholds · strategy logic   untouched
runtime trading files edited                   NONE
```

**One thing worth keeping.** The number that started this stage was partly an artefact of how I
measured it, and the way it was caught was cheap: re-measure on a quiet machine before believing
a performance figure. The underlying problem was real, but it was a *cold-start* problem the
whole time, and I had reported it as a steady-state one.
