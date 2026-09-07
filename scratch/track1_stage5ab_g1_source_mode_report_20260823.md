# Stage 5AB-G1 — making `decision_mode` impossible to mismatch

**2026-08-23 · no scheduler started, no IBKR connection, no order, no confirmation file, no
`STOP_TRADING`, no legacy retirement, no commit.** `TRACK1_ORDERS_APPROVED` was never set — the
armed branch is exercised with a stub gate.

---

## 1. G1, exactly

`run_shadow()` took **two independent arguments with two independent defaults**:

```python
def run_shadow(*, window, source_name="replay", ..., mode=tx.REPLAY)
```

and `main()` passed only the first:

```python
run_shadow(window=a.window, source_name=a.source, ...)      # no mode=
```

So `--source live` produced a run whose records were stamped `decision_mode="replay"`.

That is not a cosmetic label. Stage 5Z made binding a function of the **mode**:

```python
binding = mode in tx.FRESHNESS_BINDING_MODES        # {"shadow_live", "armed"}
```

With the mode stuck at `replay`, `binding` was False, and `explanations_for` would never raise
`FreshnessRefused` — **the freshness gate stopped binding on exactly the kind of run where Stage
5Z decided it must bind.** The failure was silent and the records looked well-formed.

### The call graph as found

```
main()
  --source {replay|live|live-shadow}  ->  a.source
  gate = OrderGate(a.allow_orders)             # shadow | armed_but_refused | armed
  [--source live-shadow returns early: observe_live_slot(), no explanations at all]
  run_shadow(source_name=a.source, order_gate=gate)        <-- mode never passed
      mode = tx.REPLAY                                     <-- independent default
      emit_explanations(..., mode=mode)
          explanations_for(..., mode=mode)
              binding = mode in FRESHNESS_BINDING_MODES    <-- decided here
              decision_record(decision_mode=mode)
```

Two things reached the same records from different places, and nothing made them agree.

---

## 2. The contract now

A pure helper, and a named refusal:

| source | gate | mode | freshness |
|---|---|---|---|
| `replay` | any | `replay` | context |
| `live` / `live-shadow` | not armed (`shadow`, `armed_but_refused`) | `shadow_live` | **binding** |
| `live` / `live-shadow` | armed | `armed` | **binding** |

- `decision_mode_for(source_name, order_gate)` — total over the sources the CLI accepts; an
  unknown source is a `ValueError`, not a default.
- `resolve_decision_mode(source_name, order_gate, mode=None)` — derives, and raises
  **`DecisionModeMismatch`** when a caller insists on a different one. Refused rather than
  resolved: preferring either side silently would change whether the freshness gate has to hold.
- `run_shadow(..., mode=None)` — the independent default is **gone**; it derives through
  `resolve_decision_mode`, so an explicit mode is still allowed and an explicit *wrong* one stops
  the run.
- `main()` passes `mode=decision_mode_for(a.source, gate)` rather than relying on any default.

Note `armed_but_refused` — the state the route actually sits in while B1 is open — resolves to
`shadow_live`, i.e. **binding**. Only a genuinely armed gate reaches `armed`, and that is the
safe direction: a refused gate binds.

### One more mislabel, fixed while here

The decision record carried `inputs_summary={"source": mode, ...}` — a field named *source*
holding the *mode*. Harmless while the two coincided in replay; misleading the moment they
stopped, which is the whole subject of this stage. It is now keyed `decision_mode`. The record
already carried `candidate_source` separately, so nothing was lost. No test pinned the old key.

---

## 3. Tests

New: `scratch/test_track1_stage5ab_g1_source_mode_20260823.py` — **23 passed**.

It proves the table above in both directions; that a refused gate binds; that every live mode is
in `FRESHNESS_BINDING_MODES` and replay is not; that five distinct mismatches are refused by
name; that `run_shadow`'s `mode` default is `None` (the signature shape that was the defect);
that `main()` reaches `run_shadow` with `mode=decision_mode_for(a.source, gate)` — read by
parsing the shipped source, since running `--source live` reaches a source that still refuses;
that a live run cannot be stamped `replay` under any of four gate states; that a replay run still
records `replay` and does not bind; and that binding modes still raise `FreshnessRefused`.

| suite | result |
|---|---|
| Stage 5AB-G1 (new) | **23 passed** |
| Stage 5Y wiring | **passed** (75 with 5Z below) |
| Stage 5Z freshness/root | **passed** |
| `test_dashboard_live_snapshot` + `test_log_hygiene` | **passed** (127 with explain) |

`global_index/test_event_playback.py` was not run.

---

## 4. Three failures that are NOT this stage's, and one of them matters

Running the wider set surfaced three reds. None is caused by the G1 change — verified by
parsing, not asserted: the only function in this file referencing a flagged broker name is
`build_bar_provider()` at line 212, and neither `decision_mode_for` nor `resolve_decision_mode`
references any.

### The one that matters: the measured gate has re-shut

```
LIVE_FRAME_ADAPTER_VERIFICATION  ->  live bars are obtained without the splice guard in:
                                     run_live_day_track1 (IBKRBroker)
```

`build_bar_provider()` was added to this file at **10:17 today** by another session. It
constructs an `IBKRBroker` and wraps it as a bar provider. The Stage 4B/5D measurement asks: does
any Track 1 module obtain live bars, and does every module that does import
`global_index/track1_live_frame`? This module now does the first and not the second, so the gate
closed by itself — **which is precisely what it was built to do.**

Substantively the bars still travel through the guard: `IBKRBarProvider` lives in
`track1_live_source`, and every frame reaches a sleeve through `live_frames` → `splice`. The
measurement is deliberately per-module and does not accept "it goes through eventually" — that
reasoning is what it exists to refuse.

**Not fixed here, on purpose.** It is a real decision with an owner: either this module imports
the guard so the structural claim is true, or the rule is revisited for modules that only
*construct* a provider. Papering over it by adding an import would silence a gate that has just
done its job correctly, and `build_bar_provider` is another session's work minutes old.

Consequence today: `blocking()` returns **two** entries, so two of this session's older
assertions that "orders remain impossible" now see `['B1…', 'LIVE_FRAME_ADAPTER_VERIFICATION']`
instead of one. Orders are *more* impossible, not less — but the assertions were written as
equality and are now wrong about the count.

### The other two

- `scratch/test_track1_stage5e_live_source_20260823.py::test_orders_remain_impossible` and
  `..._stage5d_...::test_orders_are_still_impossible` — the same equality-on-one-blocker
  assertions, red for the reason above.
- `scratch/test_track1_explain_20260823.py::test_no_monitor_or_dashboard_file_mentions_the_module`
  — a new file `monitor/test_schedule_status_track1_20260823.py` mentions `track1_explain`, which
  trips the 5Y session's own guard. `monitor/` is outside this stage's allowed edits and was not
  touched.

---

## 5. Answers

**Live source remains unexercised.** Nothing in this stage runs it. `main(--source live)` was
tested by parsing the call, not by executing it, and the armed branch used a stub object whose
only property is `allow_orders`. No broker was constructed, no connection opened, and
`TRACK1_ORDERS_APPROVED` was never set.

**Legacy and dashboard behaviour did not change.** The only file edited is
`global_index/run_live_day_track1.py`, which is the Track 1 entry point and is untracked — no
legacy path imports it. `monitor/backend/schedule_status.py`, the dashboard files,
`global_index/track1_explain.py` and the scheduler runtime were not touched, and the real
`scratch/track1_shadow` was not written: every run in these tests relocates with `root=`.

**Replay behaviour and explanation counts are preserved** — the Stage 5Y and 5Z suites are green
unchanged, and a replay run still reports `mode=replay` with `freshness_binding=False`.

---

## 6. Verdict

- **G1 closed?** **Yes.** The mode derives from the source and the gate; the independent default
  is gone; `main()` passes it; a mismatched explicit mode is refused by name.
- **Can a live source be stamped `replay`?** **No.** Asserted over `live` and `live-shadow`
  across four gate states, and `main()`'s call is pinned by parsing the shipped source.
- **Freshness binding preserved?** **Yes.** Binding modes still raise `FreshnessRefused`; replay
  still treats freshness as context and does not cite `GATE.FRESHNESS`.
- **Legacy/dashboard changed?** **No.**

**Next step, and it is not mine to take:** decide the `build_bar_provider` question. Either
`run_live_day_track1` imports `track1_live_frame` so the per-module claim is true, or the
measurement's rule is revisited for a module that constructs a provider without joining frames
itself. Until then `LIVE_FRAME_ADAPTER_VERIFICATION` blocks — correctly — and the two
"orders remain impossible" assertions in the 5D/5E suites need updating to match the true
blocker set rather than assuming one.
