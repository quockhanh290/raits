# Stage 5H0 — missed-surfaces audit before Stage 5I

**2026-08-23 · audit only · no scheduler started or stopped, no IBKR connection, no order, no
dashboard runtime write, no `STOP_TRADING`, no confirmation file, no commit, no production
behaviour changed.**

---

## Verdict: **PROCEED_TO_5I_PROVIDER_WIRING** — with its scope widened

No gap blocks *writing* the provider wire, so 5I may start. But **a provider-only 5I would
reproduce exactly the pattern this audit exists to break.** Two new defects were found, and both
would corrupt the very evidence a shadow period is started to collect.

> **Stage 5I is not "add `--bar-provider`". It is "make a shadow day produce evidence worth
> keeping."** Its definition of done must cover G-A, G-B and G-D as well as G-C.

---

## The method, because it is why the new gaps surfaced

The three known defects — `record_window_observation`, `track1_bootstrap.write`,
`build_bar_provider` — were all "declared but never called". Grepping for that one symbol at a
time is what let three of them ship. So this audit asked the question mechanically:

**what does a real slot actually execute?** Two traces, both of the shipped entry point:

1. The exact slot command as the scheduler issues it. It enters **4 modules** and stops at
   `no_bar_provider` — so it cannot reveal anything downstream.
2. The same slot with a **stub provider injected**, which is the state Stage 5I will create.

The second trace is where the new findings are.

---

## What a slot reaches, with a provider

```
entered : run_live_day_track1 · track1_calm_a · track1_intraday ·
          track1_live_frame · track1_live_source · track1_slots · window_ledger

NEVER   : track1_signal_layer · track1_freshness · track1_explain · track1_switch ·
          track1_params · track1_normal_r4 · track1_stress_mnq · track1_bootstrap · …
```

Confirmed independently by parsing the two functions' call graphs:

| call | `observe_live_slot` | `run_shadow` |
|---|---|---|
| `fresh.evaluate` | **no** | yes |
| `run_candidates` (admission) | **no** | yes |
| `make_guard` (caps) | **no** | yes |
| `emit_explanations` | **no** | yes |

---

## G-A — the live slot bypasses admission, caps, freshness and the audit trail

**NEW · MUST_FIX_BEFORE_SHADOW_START**

The replay path runs the freshness gate, builds the cap guard, runs the admission layer and
emits explanations. **The live-shadow slot runs none of them.**

Today that is invisible, because the slot refuses at `no_bar_provider` before it could matter.
Add the provider — which is precisely what Stage 5I does — and slots begin recording
`decided=true` having applied **no cluster cap, no family cap, no same-symbol suppression, no
Stress displacement, and no freshness gate**, and leaving **no explanation record**.

The consequence is not a wrong trade — nothing trades. It is worse for the purpose at hand: a
shadow period would collect evidence describing a route that is **not the route that would
trade**. Precondition 5 would go green on the strength of it.

Note this also silently undoes Stage 5AB-G1 in practice: that stage made freshness *binding* for
`live`/`live-shadow` modes, and the live slot never evaluates freshness at all.

## G-B — every Track 1 ledger row is stamped `route: "legacy"`

**NEW · MUST_FIX_BEFORE_SHADOW_START**

The scheduler sets `RAITS_ROUTE=legacy` in the slot's child environment.
`window_ledger.route()` reads that variable, so every row a Track 1 slot writes carries
`route: "legacy"`:

```
window_open     route='legacy'  route_hint='track1_candidate'
slot_observed   route='legacy'  route_hint=None
window_closed   route='legacy'  route_hint=None
```

Only `window_open` carries a hint; `slot_observed` and `window_closed` carry **no route identity
at all**. So the coverage evidence for precondition 5 is filed under legacy, and any downstream
split by route folds Track 1 in — the documented *"route field added but downstream aggregation
folds Track1 into legacy"* pattern, found in the wild.

Cheap to fix, and cheapest to fix **before** 5I writes tests that bake the wrong expectation in.

---

## Inventory

| # | surface | expected contract | check run | status | priority |
|---|---|---|---|---|---|
| 1 | scheduler registration | 60/84 jobs, 25 slots, Calm 1 @10:00, Stress 24 @5min, legacy entries 23, only `stop_repair_1220` removed, parity OFF/ON | built both schedulers, never started; step between Stress slots verified; `parity_report` both modes | **covered** | — |
| 2 | scheduler argv | `--source live-shadow --sleeve --slot-id --regime-csv`; no `--allow-orders`/`--window`/`--port` | **monkeypatched `_run` and invoked the real job closures** | **covered** (`--bar-provider` absent → G-C) | — |
| 3 | CLI / main | every passed arg parsed and used; mode derived; no replay default | parsed `add_argument` actions; parsed `main()`'s call graph | **covered** except G-C | — |
| 4 | env propagation | `RAITS_SLOT_ID`, `RAITS_ROUTE`, telemetry dir inherited not invented; ledger dir required | captured the child env via a fake `subprocess.run` | **G-B** — `RAITS_ROUTE=legacy` | MUST_FIX_BEFORE_SHADOW_START |
| 5 | STOP_TRADING / pre-start | legacy entries blocked, exits run; `.track1` separate; `_catch_up_maxhold` reads broker | read `runner.py` D5 and the pre-`start()` hook | **covered** (G-F operator note) | OPERATOR_ONLY |
| 6 | order gate / broker boundary | B1 only; exit 2; `NoOrderBroker` raises; no path to `send_order` | ran `--allow-orders`; called all three `NoOrderBroker` methods; parsed the slot's call graph | **covered** — all three raise, slot reaches neither `send_order` nor a broker | — |
| 7 | live source / provider | guard-routed; no real IBKR; detector still bites | `live_frame_wiring()` released; fake-broker factory; synthetic bad route still refused | **G-C, G-D** | MUST_FIX_BEFORE_SHADOW_START |
| 8 | freshness / causality | live binds, replay context, mode cannot drift | Stage 5AB-G1 suite green — **but the live slot never calls freshness (G-A)** | **G-A** | MUST_FIX_BEFORE_SHADOW_START |
| 9 | signal decisions | Calm at 10:00, Stress 10:35–12:30, named refusals | Stage 5E/5F suites; slot trace enters `track1_calm_a` + `track1_intraday` | **covered** | — |
| 10 | explain / audit trail | every decision explainable | slot never enters `track1_explain` | **G-A** | MUST_FIX_BEFORE_SHADOW_START |
| 11 | risk / caps / same-symbol | qty per candidate; family cap; same-symbol | qty verified on the candidate; **caps never consulted on the live path** | **G-A** | MUST_FIX_BEFORE_SHADOW_START |
| 12 | checkpoint / resume | route-scoped; written only after a complete window | slot run: window incomplete → "checkpoint: NOT written" | **covered** | — |
| 13 | window ledger | open/observed/closed; decided vs ran; no ledger = refusal | temp-dir run wrote all three; unset dir → `ledger_not_configured` | **covered**; G-B on route, G-E on filename | see G-B / G-E |
| 14 | runtime / health | p95 unmeasured until shadow | no scheduler running (0 processes) | **covered** — no claim made | — |
| 15 | dashboard / monitor | parity; no runtime write | parity true both modes; `live_state_data.js` unchanged 08-21 13:59 | **covered**; G-H out of scope | OUT_OF_SCOPE |
| 16 | docs consistency | no stale "starting fixes 5/6", no "can trade today", blocker named | parsed the runbook | **covered** — the one "can trade today" line is the negation; Stage 5H correction present; `no_bar_provider` named | — |

---

## Gaps by priority

**MUST_FIX_BEFORE_5I:** none. Nothing prevents the provider wire from being written.

**MUST_FIX_BEFORE_SHADOW_START**
- **G-A** live slot bypasses admission / caps / freshness / explain — *new*
- **G-B** ledger rows stamped `route: legacy` — *new*
- **G-C** no `--bar-provider` wiring — *known, confirmed*
- **G-D** no disconnect path for a connected broker — *known*

**MUST_FIX_BEFORE_PAPER_LIVE** — G-G broker-flat and orphan-STP checks (need IBKR).
**DOC_ONLY** — G-E ledger filename is UTC while records are ET session day.
**OPERATOR_ONLY** — G-F `_catch_up_maxhold` reads the broker before `start()`.
**OUT_OF_SCOPE** — G-H the `monitor/` guard test from another session.

---

## What Stage 5I must include

1. `--bar-provider {none,ibkr}` parsed **and used** by the live-shadow branch (G-C).
2. The broker released in a `finally` (G-D).
3. Either the live slot exercising the **same** freshness gate, cap guard and admission layer the
   replay does — or an explicit, written decision that a shadow day deliberately measures
   detection only, in which case preconditions 5 and 6 must say so (G-A).
4. Track 1 ledger rows carrying `route=track1_candidate` (G-B).

Doing (1) alone produces a shadow route that decides without caps, without freshness, without an
audit trail, and files its evidence under legacy.

---

## Checks run

Scheduler built twice and discarded · `_run` monkeypatched and the real Calm and Stress job
closures invoked to capture exact argv · child env captured through a fake `subprocess.run` ·
`track1_gates` called directly · `parity_report` OFF and ON · a live-shadow slot run against a
temporary ledger directory, with and without a stub provider · both runs traced with
`sys.settrace` to record every Track 1 function actually entered · AST call-graph comparison of
`observe_live_slot` against `run_shadow` · `add_argument` actions parsed · `build_bar_provider`
call sites searched · `NoOrderBroker` methods called · route-module guard parse · runbook parsed
for stale claims · confirmation and `STOP_TRADING` files checked absent.

No test suites were re-run in this audit; the suites behind the closed stages are recorded in the
Stage 5G and 5H reports. `global_index/test_event_playback.py` was not run.

---

## No side effects

No scheduler started or stopped (0 `run_scheduler` processes). No IBKR connection — the provider
path was exercised with a fake broker class only. No order (`send_order calls: 0`, and all three
`NoOrderBroker` methods raise). No dashboard runtime write — `live_state_data.js` unchanged at
08-21 13:59. No `STOP_TRADING`, no `STOP_TRADING.track1`, no `track1_go_live_confirmation.json`.
`TRACK1_ORDERS_APPROVED` unset. No commit. **No production behaviour changed** — the only files
written are this report and its JSON, both under `scratch/`.

---

Stage 5H0 complete: proceed to Stage 5I provider wiring; do not start shadow scheduler yet.
