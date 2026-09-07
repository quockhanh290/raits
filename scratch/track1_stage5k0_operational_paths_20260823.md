# Stage 5K0 — operational evidence is not scratch

**2026-08-23 · no scheduler started, no IBKR connection, no order, no dashboard runtime write,
no `STOP_TRADING`, no `STOP_TRADING.track1`, no confirmation file, no commit.**

---

## Verdict: **READY_FOR_5K_OPS_STARTUP_INTEGRATION**

---

## The problem, in one sentence

Stage 5J told the operator to export `RAITS_WINDOW_LEDGER_DIR` into `scratch\track1_ledger`, and
live-shadow explanations defaulted to `scratch/track1_shadow`. **A multi-day shadow period would
have kept its only copy inside the directory this project treats as disposable** — and that
evidence is *not reproducible*: nobody can re-observe a window that has closed. One tidy-up
between the shadow period and the go-live gate would have deleted the thing the gate is read
from.

---

## The split

| root | holds | why there |
|---|---|---|
| `scratch/track1_shadow/` | **replay and test** output | reproducible from the measured windows; losing it costs a re-run |
| `global_index/track1_runtime/` | **live-shadow operational evidence** — `window_coverage/`, `slot_timing/`, `shadow/explanations/` | **not reproducible**, and it is what the go-live gate is read from |

`global_index/track1_runtime/` was chosen over a new top-level directory because this repo
**already** keeps route runtime state under `global_index/`: `live_state_data.js`,
`preflight_state.json`, `maxhold_state.json`, and Track 1's own
`replay_checkpoint.track1.json`. The new directory follows an existing convention rather than
starting a second one.

---

## Inventory

| path / env | writer | kind | was | now |
|---|---|---|---|---|
| `RAITS_WINDOW_LEDGER_DIR` → `window_coverage_*.jsonl` | `window_ledger._write` | **operational** | runbook said `scratch/track1_ledger` | **`global_index/track1_runtime/window_coverage`** |
| `RAITS_TELEMETRY_DIR` → `slot_timing_*.jsonl` | `slot_telemetry` | **operational** | unset (off) | **`…/slot_timing`** recommended; still opt-in |
| `observe_live_slot` explanations | `emit_explanations` | **operational** | `scratch/track1_shadow` | **`…/shadow`** |
| `run_shadow` output | `run_shadow` | replay/test | `scratch/track1_shadow` | **unchanged — deliberate** |
| explanation path guard | `write_shadow` | guard | one root | **`APPROVED_ROOTS`, a set of two** |
| `live_positions.track1.json` | route checkpoint writer | operational | **not gitignored** | gitignored |
| `runner.track1.pid` | route lock | operational | **not gitignored** | gitignored |
| `global_index/replay_checkpoint.track1.json` | `track1_bootstrap.write` | operational | **not gitignored** | gitignored |
| `STOP_TRADING.track1` | operator | switch | **not gitignored** | gitignored |
| `track1_go_live_confirmation.json` | operator | **the file that ARMS the route** | **not gitignored** | gitignored |
| `trade_log.jsonl`, `runner_events_*`, `live_state_data.js` | legacy | legacy | ignored | unchanged — Track 1 writes none of them |
| `monitor/ops.py` logs | monitor | legacy | — | untouched (`test_ops.py` 8 passed) |

---

## The guard was widened to a set, not loosened

`_resolve_shadow` bounded exactly one root. It now bounds `APPROVED_ROOTS` — the scratch root and
the operational root — and **refuses everything else**, with the refusal naming both. There is a
parametrised test for each of `global_index/`, `scratch/`, `global_index/track1_runtime` (the
runtime root itself, one level above the permitted shadow subtree), `monitor/backend`, `.` and a
bare filename.

That distinction is the point. The guard exists because a writer that can be aimed at a legacy
path once manufactured a paper-evidence episode attributed to a different session. Widening it to
a set of two named destinations does not reopen that.

---

## `.gitignore`

Six entries added. Their **legacy counterparts were already ignored** — `live_positions.json`,
`replay_checkpoint.json`, `trade_log.jsonl` — and the Track 1 twins simply had never been added,
so a shadow run would have offered route state for commit.

The one that matters most is `track1_go_live_confirmation.json`: it is the file that **arms the
route**, and ignoring it means a checkout can never create one.

Verified **both directions**: eight runtime paths now ignored, and five source/doc/test paths
confirmed *still visible* — an over-broad rule that swallowed a module would be worse than the
gap it closed.

---

## Tests

| suite | result |
|---|---|
| Stage 5K0 (new) | **27 passed** |
| Stage 5I · explain · explain-wiring · 5Z | **204 passed** (+1 out-of-scope) |
| Stage 5B · 5K0 · 5I | **68 passed** |
| slot telemetry · log hygiene · dashboard snapshot | **40 passed** |
| `monitor/test_ops.py` | **8 passed** |
| 5D · 5E · 5F · G1 · 3B | **181 passed, 2 skipped** |

The 5Z root-bound suite passing unchanged is the meaningful one: it is the suite that owns the
guard, and widening the bound did not disturb what it asserts.

`global_index/test_event_playback.py` was not run. The one out-of-scope failure is
`test_no_monitor_or_dashboard_file_mentions_the_module`, caused by a `monitor/` file another
session created; `monitor/` was not touched.

---

## Docs

`docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md` gains **section 3b**, append-only, stating the split
and the ignore policy. The Stage 5J operator runbook's step 3 now exports the ledger into
`global_index\track1_runtime\window_coverage`, carries the correction and the reason, and adds
the optional `RAITS_TELEMETRY_DIR` — which is what the p95 gate is judged from, so it is worth
setting on the first day.

---

## No side effects

No scheduler started or stopped. No IBKR connection. No order. No dashboard runtime write. No
`STOP_TRADING`, no `STOP_TRADING.track1`, no `track1_go_live_confirmation.json`. No commit.
**`global_index/track1_runtime/` was not created by any test** — the tests assert the real roots
stay absent, and `scratch/track1_shadow/explanations/` was verified absent too.

Stage 5J's `READY_FOR_MANUAL_SHADOW_START` stands, with the corrected paths.

---

Stage 5K0 complete: operational evidence no longer defaults to scratch; proceed to Stage 5K ops/dashboard startup integration.
