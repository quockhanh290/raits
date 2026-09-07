# Stage 5G — closing the live-frame gate by moving the touchpoint, not the rule

**2026-08-23 · no scheduler started, no IBKR connection, no order, no dashboard write, no
confirmation file, no `STOP_TRADING`, no legacy retirement, no commit.**

---

## 1. Read before changing anything

`scratch/track1_stage5ab_g1_source_mode_report_20260823.md` ·
`scratch/test_track1_stage5ab_g1_source_mode_20260823.py` ·
`global_index/run_live_day_track1.py` · `global_index/track1_live_source.py` ·
`global_index/track1_live_frame.py` · `global_index/track1_gates.py` · the Stage 5D/5E/5F
blocker assertions.

The diagnosis was taken by **parsing the shipped modules**, not from the report:

```
run_live_day_track1 : imports guard = False
   build_bar_provider()  L212 : ['IBKRBroker']

track1_live_source  : imports guard = True
   live_frame()               : ['fetch_session_bars']
   fetch_session_bars()       : ['fetch_bars']
   fetch_session_bars_direct(): ['ib_insync', 'reqHistoricalData']
```

---

## 2. Root cause

`build_bar_provider()` was added to **`run_live_day_track1.py`** by another session and
constructs an `IBKRBroker`. `track1_gates.live_frame_wiring()` is a **per-module** rule: any
Track 1 module that obtains live bars must import `global_index/track1_live_frame`. This module
did the first and not the second, so the gate closed itself:

```
live bars are obtained without the splice guard in: run_live_day_track1 (IBKRBroker)
```

Reaching the guard transitively — through `track1_live_source` — deliberately does not count.
"It goes through eventually" is the reasoning the rule exists to refuse.

One useful fact: **`build_bar_provider` had no callers at all.** Not `main()`, not
`observe_live_slot`, not a CLI flag. The factory existed and nothing used it, which made moving
it low-risk.

---

## 3. The fix, and why this one

**Chosen: the preferred option — the provider construction moved into
`global_index/track1_live_source.py`.**

That module already owns every other live-bar primitive and already imports the splice guard, so
putting the `IBKRBroker` touchpoint beside them makes the structural claim **true**. The entry
point now re-exports the factory:

```python
build_bar_provider = _live_source_build_bar_provider
```

so any caller that reaches for it on the entry point still finds it, while the module holds no
broker primitive of its own.

**Rejected, and why:**

- *Importing the guard into `run_live_day_track1` to satisfy the check.* It would pass, and it
  would leave a broker primitive sitting in the entry point with an import placed there purely
  to quiet a detector. The gate's complaint was about where the primitive lives.
- *Dropping `IBKRBroker` from the detector vocabulary.* That is silencing the gate.
- *Relaxing `track1_gates`.* The problem was wiring, not the rule.

**Behaviour preserved exactly:** `kind="none"` returns `(None, None)` so a manual run cannot dial
out by accident; `kind="ibkr"` builds and connects with an injectable `broker_cls`; an unknown
kind is refused by name (`unknown_bar_provider`). Verified with a fake broker — `ib_insync` and
`global_index.ibkr_broker` are **not** imported.

---

## 4. Result

```
live_frame_wiring() -> released=True
   every live bar path on the route joins through track1_live_frame:
   track1_live_source (IBKRBroker, fetch_bars, fetch_session_bars, ib_insync, reqHistoricalData)

blocking() -> ['B1_broker_account_or_legacy_retirement']
self_check() -> []
```

`--allow-orders` still **exits 2**, names B1 and the unset `TRACK1_ORDERS_APPROVED`, and does
**not** mention `LIVE_FRAME_ADAPTER_VERIFICATION`.

The blocker ledger on disk was regenerated from the registry — it carried a stale `detail`
string. `blocking_now` was already B1-only; only the measurement's wording changed.

---

## 5. Stage 5AB-G1 contract, still held

Re-run and green, unchanged by this stage:

- `run_shadow(..., mode=None)` — no independent replay default
- `main()` derives `mode=decision_mode_for(a.source, gate)`
- `resolve_decision_mode()` raises `DecisionModeMismatch` on a forced wrong mode
- `live` / `live-shadow` bind freshness; `armed_but_refused` resolves to `shadow_live`
- `replay` stays context-only and does not cite `GATE.FRESHNESS`
- the record key is `decision_mode`, not a `source` field holding a mode

---

## 6. Four stale assertions, replaced with the property

Four suites asserted the blocker list **equals exactly one element**. That goes red the moment a
*measured* gate legitimately re-shuts — which is the mechanism working, not a regression. It is
also the wrong shape: it says "there is one blocker" when what matters is "orders are impossible
and B1 is one of the reasons".

They now assert:

- orders are impossible;
- `B1` is in the blocker set;
- any **extra** blocker must genuinely be holding — it must declare `blocks_orders` and not be
  released under no confirmations, so a bogus entry cannot slip in;
- and B1-only **only when `live_frame_wiring()` is released**, so the strong claim is made
  exactly when it is earned.

Changed in `test_track1_stage5b/5d/5e/5f`.

---

## 7. Tests

| suite | result |
|---|---|
| Stage 5AB-G1 + 5G (same file, 8 new tests) | **31 passed** |
| Stage 5B · 5C · 5D · 5E · 5F | **111 passed, 1 skipped** |
| Stage 5Y wiring + Stage 5Z freshness/root | **75 passed** |
| Stage 4C · 3B · dashboard-live-snapshot · log-hygiene | **118 passed, 1 skipped** |

New in this stage, beyond the release itself:

- **the detector still bites** — a synthetic route where a module imports `IBKRBroker` without
  the guard is measured and refused, so the move cannot be mistaken for weakening the rule;
- the entry point holds **no** name in `LIVE_BAR_NAMES`, asserted by parsing it;
- the factory delegates, opens nothing, and refuses an unknown kind by name;
- a live-shadow slot still hard-refuses on a missing `RAITS_WINDOW_LEDGER_DIR` **before** any
  provider is built — the ledger check comes first, so a slot that could not record its own run
  never reaches a broker.

`global_index/test_event_playback.py` was not run.

### One failure outside this stage

`scratch/test_track1_explain_20260823.py::test_no_monitor_or_dashboard_file_mentions_the_module`
fails because `monitor/test_schedule_status_track1_20260823.py`, created by another session,
mentions `track1_explain` and trips that session's own guard. `monitor/` is outside this stage's
scope and was not touched. Recorded, not mixed in.

---

## 8. Scheduler and dashboard

Not started, not written. The Track 1 slot argv is unchanged and still carries no
`--allow-orders` and no broker port; it selects `--source live-shadow`, so a production shadow
slot does not silently replay `vault2026`. Legacy jobs are untouched pending the B1 decision, and
the operator must still create `STOP_TRADING` before **any** scheduler start — shadow mode keeps
all 23 legacy entry slots.

---

## 9. Verdict

- **G1 still closed?** Yes — the whole contract re-run and green.
- **`LIVE_FRAME_ADAPTER_VERIFICATION` released again?** **Yes, by measurement**, and by making
  the structural claim true rather than by changing the rule.
- **`blocking()` now?** `['B1_broker_account_or_legacy_retirement']`.
- **Is B1 the only blocker?** Yes.
- **`--allow-orders`?** Still exits 2, because B1 is open.
- **Anything started, connected, sent, written or committed?** No.

**Remaining before a shadow scheduler:** the B1 decision; the operator placing `STOP_TRADING`
before any start; `RAITS_WINDOW_LEDGER_DIR` exported or every live-shadow slot hard-refuses; and
a real broker provider, which has still never been connected — this stage moved where it is
constructed, not whether it works.
