# Stage 5D — giving the shadow slots something true to record

**2026-08-23 · no scheduler started, no IBKR connection, no order, no dashboard write, no
`STOP_TRADING`, no confirmation file, no commit.**

---

## Verdict: **BLOCKED_BY_LIVE_SOURCE**

The wiring Stage 5C found missing is built and proved end to end. What still holds preconditions
5 and 6 shut is **precondition 2b**, and that is now visible in the records rather than hidden
in a replay.

> **Not claimed:** that Track 1 can trade, that 5 or 6 can pass today, or that the live
> candidate source exists. It does not.

---

## 1. What was wrong, re-confirmed before anything was changed

| finding | measured |
|---|---|
| Track 1 slot argv had no `--source` | true — so the entry point took `--source replay --window vault2026` |
| `record_window_observation` call sites | **0** (a definition and a comment) |
| `track1_bootstrap.write` call sites | **0** anywhere in `global_index/` |
| ledger is opt-in via `RAITS_WINDOW_LEDGER_DIR` | true — unset means a silent no-op |
| `load_source("live").candidates()` | raises |
| probe `safe_to_start_shadow` | false |

Twenty-five slots a day, each re-running the same window from months ago, writing nothing that
could ever satisfy the preconditions they would have been started to satisfy.

---

## 2. What the slots do now

Each Track 1 slot runs with `--source live-shadow --sleeve <sleeve> --slot-id <id>` — still no
`--allow-orders`, still no broker port. The slot:

1. **Refuses outright if the ledger is not configured.** `RAITS_WINDOW_LEDGER_DIR` unset is a
   hard stop, not a quiet success. A shadow run whose entire purpose is to leave evidence must
   not run silently when it cannot leave any — the ledger could not tell that apart from a
   window nobody watched.
2. Joins today's session onto history through the guarded adapter and runs the sleeve's
   intraday gate.
3. Asks the live source for candidates.
4. **Writes its own ledger row either way**, carrying whether it decided and, if not, which of
   four named reasons stopped it: `no_bar_provider`, `live_source_not_ready`, `gate_refused`,
   or `ledger_not_configured`.
5. On the last slot of the window, closes it — **counting only the slots that actually
   decided** — and writes the route checkpoint **only if the window completed**.

`track1_bootstrap.write` now has its first caller. So does the ledger.

### The rule that keeps this honest

**A slot counts toward coverage only when it decided.** While the live source raises, every
slot records `decided=false, reason=live_source_not_ready`, the window closes `incomplete`, and
no checkpoint is written.

That is deliberate. Counting an undecidable slot as observed would manufacture exactly the
evidence the ledger was built to withhold, and would let precondition 5 turn green on a route
that cannot trade. The wiring is finished; the route is not; the records say so.

Measured, both directions:

| case | outcome | checkpoint |
|---|---|---|
| ledger not configured | refused before anything ran | — |
| no bar provider | `slot_observed decided=false reason=no_bar_provider`, window `incomplete 0/1` | not written |
| real source, gate allows | `decided=false reason=live_source_not_ready`, `gate=true` | not written |
| **stub source injected** | `decided=true`, window **`complete 1/1`** | **written and accepted** |
| 24 stress slots, one without a provider | `incomplete 23/24` | not written |
| replay, ledger switched on | `window_ledger: "not driven"`, **zero coverage files** | not written |

The stub row is what proves the mechanism can reach green. Without it this suite would only
have shown the route failing, which is not the same as showing the plumbing works.

---

## 3. What is left for precondition 2b

Not faked, not stubbed into production. The slot fails closed and names it:

- today's regime label for the live session
- a cost object per instrument
- Calm A's **true stop-risk sizing** — the disaster-stop distance, not the ATR proxy
- a bar provider handed to the slot: `IBKRBarProvider` wrapping the runner's existing broker
- `track1_sleeves.load_source("live").candidates()` returning instead of raising

The first two are computable offline today. The third is real work. The fourth needs a broker at
runtime and is the only one that cannot be tested without one.

---

## 4. Legacy is untouched

| | shadow OFF | shadow ON |
|---|---|---|
| jobs | 60 | 84 |
| removed by shadow | — | `stop_repair_1220` only |
| legacy entry slots | 23 | **23** |

The Track 1 slot argv changed; nothing else did. `--track1-shadow` still does not isolate Track
1, so `STOP_TRADING`-before-any-start remains necessary and remains in the runbook.

---

## 5. Runbook correction

Section 2's paragraph said **"starting is what fixes them"** about preconditions 5 and 6. I
wrote that in Stage 5, repeated it in Stage 5B, and put it in the runbook. It was reasoned from
how the route was meant to work and never checked against the call sites. Measured, it was
false at any length of run.

It is now retracted in place, with the mechanism named — the replay default, the two recorders
with zero callers — and the status rows rewritten to say **2b comes first, then the shadow run,
then 5 and 6 turn green on their own.**

The Stage 5B test that asserted the old sentence was pinning my error in place. It now asserts
the retraction and the reason.

---

## 6. A pre-existing defect this stage exposed but did not cause

Running `test_slot_overlap.py` **before** `test_slot_telemetry_20260822.py` makes four telemetry
tests fail with `KeyError: 'args'`. The cause is in `global_index/test_slot_overlap.py:165`:

```python
rs._run = lambda *a, **k: ran.append(k.get("label"))       # replaced below anyway
```

It assigns the module attribute and never restores it — the restore two blocks later covers a
different assignment. Every later suite in the same pytest session then calls the stub instead
of the real `_run`, and a test that drives production code silently drives a lambda.

**Not mine and not new:** the file is unmodified and last committed at `46d15bd`. The canonical
eight-suite command runs `slot_telemetry` *before* `slot_overlap`, so the leak has never bitten
— that order still passes **156**. I put them the other way round today and it surfaced.

Not fixed here: it is a legacy test file and outside this stage's scope. The fix is one line —
restore `rs._run` in a `finally`, or use `monkeypatch.setattr` as the neighbouring test does.

---

## 7. A defect of mine, caught by this stage's own test

`write_route_checkpoint` hard-coded the book path to the route's live positions file. A test
that carefully redirected the *checkpoint* to a temp directory still wrote real route state into
the repo — `live_positions.track1.json` appeared, a file this stage was told not to create.

It was caught by the suite's own "the route state this stage must not create is absent" check,
which is the only reason anyone noticed. `book_path` is now a parameter, the test redirects both,
and the stray file was inspected (an empty book, untracked) and removed. Verified absent at the
end of the run.

---

## 8. Tests

| suite | result |
|---|---|
| Stage 5D shadow-live wiring (new) | **18 passed** |
| Stage 5C shadow readiness | **11 passed** |
| Stage 5B runbook fix | **22 passed** |
| Stage 4C live source | **46 passed** |
| Stage 3B blockers | **72 passed, 1 skipped** |
| the canonical eight | **156 passed** |
| Stage 4 production-clean | **25 passed, 1 skipped** (7:18) |

The all-window Stage 4 run was not repeated: Stage 4C measured it at 32 passed and this
stage changed no sleeve, generator or identity code — only the slot argv, the entry
point's live-shadow path and two ledger read helpers, all covered by the suites above.

`global_index/test_event_playback.py` was not run.

---

## 9. Next action

1. **Precondition 2b.** It is now the only thing between the route and a shadow period that
   collects anything. The slot already fails closed naming exactly what it needs.
2. **Then** the manual sequence, unchanged: settle why the scheduler is down, place
   `STOP_TRADING` before any start, export `RAITS_WINDOW_LEDGER_DIR`, start with
   `--track1-shadow`, and let the windows close themselves.
3. Fix the `test_slot_overlap` leak when convenient, so suite order stops being load-bearing.

Orders remain impossible throughout: `blocking()` returns `B1` alone, no confirmation file
exists, and `TRACK1_ORDERS_APPROVED` is unset.
