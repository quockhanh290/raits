# Stage 5I — live-shadow evidence wiring

**2026-08-23 · no scheduler started or stopped, no real IBKR connection, no order, no dashboard
runtime write, no `STOP_TRADING`, no `STOP_TRADING.track1`, no confirmation file, no commit.**

---

## Verdict: **READY_FOR_OPERATOR_STOP_TRADING_AND_SHADOW_START**

**Shadow only.** B1 still blocks orders, and **no broker provider has ever been connected** —
every test injects a fake. This says a shadow day would now collect evidence worth keeping, not
that Track 1 can trade.

All four Stage 5H0 gaps are closed, and each is proved by execution rather than by reading.

---

## G-C — the provider selector

`--bar-provider {none,ibkr}`, default **`none`** so a manual run still cannot open IBKR by
accident. The live-shadow branch builds it and hands it to the slot; the scheduler slots pass
`ibkr`. The captured argv, taken by invoking the real job closure:

```
-m global_index.run_live_day_track1 --source live-shadow --sleeve roska4_calm
   --slot-id TRACK1_CALM_1000 --bar-provider ibkr --regime-csv spy_daily_live.csv
```

Still no `--allow-orders`, no `--port`, no `--window`.

## G-D — the broker is released

A `finally` disconnects whenever the broker exposes `disconnect()`. A fake broker driven through
`main()` is **connected once and disconnected once**. A failed disconnect is reported and does
not mask the slot's result.

**And the ledger check runs first.** With `RAITS_WINDOW_LEDGER_DIR` unset, `main()` refuses with
`ledger_not_configured` and **no broker is constructed at all** — asserted by checking that the
fake class was never instantiated. A slot that could not record its own run must not open a
connection to discover that.

## G-B — route identity on every row

`_run` now takes an explicit `route`; the Track 1 slot passes `track1_slots.EVENT_ROUTE_VALUE`.

| row | before | now |
|---|---|---|
| `window_open` | `legacy` | **`track1_candidate`** |
| `slot_observed` | `legacy` | **`track1_candidate`** |
| `window_closed` | `legacy` | **`track1_candidate`** |

Legacy is untouched: its children still stamp `legacy`, and an operator-exported `RAITS_ROUTE`
still wins there — the `setdefault` semantics are unchanged, only the Track 1 caller is explicit.

## G-A — the slot now runs the route's own decision machinery

This was the gap that mattered. The slot now calls the **same four** steps the replay path uses,
proved by `sys.settrace` on a real slot with a stub provider:

```
track1_freshness.evaluate        : YES
track1_signal_layer.make_guard   : YES
track1_signal_layer.run_candidates : YES
run_live_day_track1.emit_explanations : YES
```

The slot's ledger row and return now carry `candidates`, `freshness_allow`, `accepted`,
`rejected` and `explained`, so what the machinery decided is recorded rather than inferred.

### Freshness binds, and the safe direction is the observed one

Because the mode is `shadow_live`, freshness **binds**. Measured end to end on a fixture that
genuinely produces candidates:

```
candidates=2   accepted=2   freshness_allow=False
decided=False  reason=freshness_refused
window: incomplete 0/1
```

The route admitted two candidates through the caps; the freshness gate refused; the slot
recorded a **named refusal** and the window did **not** count toward coverage. Marking such a
slot `decided` would let precondition 5 go green on inputs the route itself refused.

**So a shadow day now collects route-level evidence, not detection-only evidence** — the
preferred path in the task, not the fallback.

---

## A defect of mine, caught by another session's guard

The first draft passed `out_dir=SHADOW_DIR` to `emit_explanations` from inside the slot — a
constant, not a parameter. So **merely running a test wrote into the real
`scratch/track1_shadow/explanations/`**. It was caught by the Stage 5Z guard
`test_the_real_shadow_directory_is_not_written_by_this_suite`, which is exactly the sort of test
that earns its keep.

`out_dir` and `root` are now parameters on `observe_live_slot`; tests redirect with `root=`, the
way the 5Y/5Z wiring tests already did. The stray directory was inspected, removed, and the
directory verified clean afterwards.

It took two passes to clear: after fixing the 5I, 5E and 5F suites the directory came back, and
bisecting the four slot suites one at a time showed **5D** was still calling the slot without a
redirect. That is the only reason it was caught — a single "is it clean?" check after one fix
would have reported success.

Worth noting the redirect had to be `root=` alone, not a bare `out_dir` pointing at a temp
folder: the writer refuses anything outside `<root>/scratch/track1_shadow`. That bound worked
exactly as designed and rejected my first attempt at redirecting it.

---

## Order of checks inside a slot

ledger configured → bar provider present → frames joined **through the splice guard** →
intraday gate → candidates from the live source → **freshness evaluated** → **cap guard built**
→ **admission layer run** → **explanations emitted** → ledger row written → window closed on the
last slot.

`decided=true` is reached only after all of it.

---

## Preserved

| | |
|---|---|
| `live_frame_wiring()` | released |
| `blocking()` | `['B1_broker_account_or_legacy_retirement']` |
| `self_check()` | `[]` |
| `--allow-orders` | exit **2** |
| confirmation file | absent |
| scheduler jobs OFF / ON | 60 / 84 |
| Track 1 slots | 25 |
| legacy entry slots under shadow | 23 |
| removed by shadow | `stop_repair_1220` only |
| dashboard parity OFF / ON | true / true |
| replay path | `mode=replay`, `freshness_binding=False`, writes no coverage, `send_order calls: 0` |

The G1 source/mode contract is intact: live and live-shadow bind, replay is context-only, a
mismatched mode is refused.

---

## Tests

| suite | result |
|---|---|
| Stage 5I (new) | **19 passed** |
| Stage 5E · 5F | **60 passed, 1 skipped** |
| G1 · 5B · 5C · 4C · 3B · Stage 3 route · 5Y · 5Z | **298 passed, 2 skipped** |
| the four slot suites together (5D · 5E · 5F · 5I) | **97 passed, 1 skipped** |
| the canonical eight | **156 passed** |
| Stage 5Y wiring · 5Z freshness/root | **75 passed** |

`global_index/test_event_playback.py` was not run.

**Three tests adjusted, and why.** Two in 5F and one in 5E asserted `decided=True` for a slot on
a synthetic future date. Freshness now binds, and that date's regime CSV is necessarily stale, so
they refuse — correctly. Each was written to test the **window/ledger plumbing reaching
`complete`**, so each now injects an allowing freshness verdict to isolate that property. The
binding itself is tested directly in the 5I suite, against a fixture that genuinely produces
candidates. The assertions were not weakened to match the new behaviour.

**One known out-of-scope failure.** `test_slot_telemetry` fails only when `test_slot_overlap`
runs first — the pre-existing `rs._run` leak documented in Stage 5D. Run alone it passes 23.

---

## No side effects

No scheduler started or stopped. **No real IBKR connection** — every broker in every test is a
fake class, and neither `ib_insync` nor `global_index.ibkr_broker` is imported. No order
(`send_order calls: 0`, and `NoOrderBroker.send_order` raises if reached). No dashboard runtime
write. No `STOP_TRADING`, no `STOP_TRADING.track1`, no `track1_go_live_confirmation.json`.
`TRACK1_ORDERS_APPROVED` unset. No commit — `HEAD` unchanged at `601970b`. The real
`scratch/track1_shadow` holds only its pre-existing replay artefacts.

---

## Still open

1. **B1** — legacy retirement or a separate account. The only thing holding the order gate.
2. **The broker provider has never been connected.** Stage 5I wired it and proved the wiring
   with fakes; whether `IBKRBarProvider` returns usable bars from a live session is untested and
   cannot be tested offline.
3. **Operator**: `STOP_TRADING` before any scheduler start; `RAITS_WINDOW_LEDGER_DIR` exported
   into the scheduler's environment.

Not claimed: ready for live orders.
