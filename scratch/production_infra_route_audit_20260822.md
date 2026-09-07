# Production Infrastructure — Route Audit before building Track 1 — 2026-08-22

READ-ONLY. No production file was modified, nothing was committed, no runner, scheduler, broker
connection or dashboard service was started. Every finding below comes from reading source.

---

## 0. Correction to the previous audit, up front

The Track 1 feasibility audit concluded that *"every slot in the scheduler today is one-shot… there
is no continuous-monitor execution shape in the runner at all."* **That is wrong.**

`run_scheduler.py:864-881` builds `_CONT_SLOTS` — **22 jobs at five-minute intervals from 14:10 to
15:55 ET** — and `run_scheduler.py:963-996` builds the NKD night slots the same way (01:10–02:55 ET).
The repeated-window execution shape already exists, is in production, and its rationale is documented
at `run_scheduler.py:16-31` with measured capture rates (14:05 alone → 0%, +14:10 → 22%, +14:30 →
50%, +15:55 → 100%).

**The Stress 10:35–12:30 window therefore needs no new execution shape** — it maps onto the same
pattern, 24 jobs at five-minute spacing. That materially cheapens the Track 1 build and changes the
sequencing recommendation. The rest of this audit is written on the corrected picture.

---

## 1. Entry points and process map

### Runtime entry points

| Entry point | File | Role |
|---|---|---|
| Scheduler (the only long-running process) | `global_index/run_scheduler.py` | APScheduler, `timezone="America/New_York"`, spawns every other job as a **run-and-exit subprocess** |
| Daily / continuous signal run | `global_index/run_live_day.py` | `IBKRBroker → FuturesRunner → run_day(today)`; docstring `run_live_day.py:1-16` |
| Max-hold close | `global_index/run_maxhold_exit.py` | 09:31 ET cron; closes positions at RTH open |
| Stop repair sweep | `global_index/run_stop_repair.py` | Builds a `FuturesRunner` and exits; `signal_fn` returns empty — no entries, no exits, only B1–B5 |
| Session report | `global_index/session_report.py` | fires when the day's last job finishes, not on a fixed cron (`run_scheduler.py:998-1000`) |
| Dashboard backend | `monitor/backend/app.py` (Flask), started by `monitor/start_backend.py` | serves `global_index/dash/**` and the reader APIs |
| Broker | `global_index/ibkr_broker.py`, class `IBKRBroker` (`:478`) | ib_insync wrapper |

### Start commands

```
python -m global_index.run_scheduler [--port 4002] [--dry-run]      # run_scheduler.py:47-50
pythonw -m global_index.run_scheduler --port 4002                   # background on Windows
```

Every job is launched by the scheduler as `[sys.executable, "-m", "global_index.<module>", …]`
(`run_scheduler.py:830-856`, `:920-926`).

### Live / paper / simulation switches

| Control | Where | Meaning |
|---|---|---|
| `--port` | `run_live_day.py:146-147`, printed at `:208` | **4002 = paper Gateway, 4001 = live**. Docstring at `:34-35` warns off 7496/7497 |
| `--client-id` | `run_live_day.py:148` | default **1** — and all entry points share it, which is why the slot mutex exists (`run_scheduler.py:751-753`) |
| `--dry-run` | `run_live_day.py:157`, scheduler `_run(..., dry_run=dry_run)` | scheduler-level: logs the command instead of spawning |
| `--print-signals` | `run_live_day.py:159` | |
| `--shadow-resume` / `--shadow-verify` | `run_live_day.py:164-171`; scheduler `:849-856` | **an already-existing decides-nothing shadow path** — "Logs a checkpoint-resumed target beside the one that trades, so the two can be compared on live data. Decides nothing" |
| `--clusters` | `run_live_day.py:181-186` | **an already-existing sleeve selector** — see §6 |
| `--stress-entry` | `run_live_day.py:172` | per-slot flag, only the morning slot gets it |
| `STOP_TRADING` file | `runner.py:71` `STOP_FILE_NAME` | operator kill switch, **global, not route-aware** |
| `POLYGON_API_KEY` | `run_scheduler.py:36-38` | missing → pre-flight fails → all 14:05–15:55 slots skip |

### Pre-flight gate — and the hole Track 1 would fall into

Pre-flight runs at **13:45 ET** and sets `_preflight_ok[date]` (`run_scheduler.py:699-733`). Slots
read it at `run_scheduler.py:788` and **fail closed** when the flag is `None`.

The night NKD slots avoid this with `prev_preflight=True` (`run_scheduler.py:991`), reading the
*previous* business day's flag because they run before that day's 13:45.

**Track 1's Calm A (10:00 ET) and Stress (10:35–12:30 ET) slots run before 13:45 as well.** Without
`prev_preflight=True` they would find `flag=None` and be skipped **every single day**, logging once
per family per date and DEBUG thereafter (`run_scheduler.py:809-826`). This is a silent-total-failure
mode with an existing, proven fix one keyword away.

---

## 2. Broker integration map

### The chain

```
signal_layer.generate_today_signals(..., active_clusters=…)   signal_layer.py:155,192
      → to_candidate(): risk_sized = contracts × mult × dailyATR × pv   signal_layer.py:68-94
          → runner.run_day → decide_day(day, state, candidates, guard, contracts)   runner.py:1760
              → MultiClusterGuard.admits()   net_exposure_multi.py:131
                  → broker.send_order(Order(inst, kind, direction, contracts, cluster, day, …))
                      IBKRBroker.send_order   ibkr_broker.py:698
                  → broker.place_stop(...)   ibkr_broker.py:1090
```

### Stop lifecycle

| Operation | Location |
|---|---|
| Create | `IBKRBroker.place_stop` `ibkr_broker.py:1090`, rounded to tick `:1182`, acceptance awaited `:1209` |
| Cancel | `IBKRBroker.cancel_order` `ibkr_broker.py:1238`; returns False on failure, does not raise |
| Replace after roll | `FuturesRunner._roll_stop` `runner.py:2323` — shifts the recorded level by the measured close/open spread |
| Deferred arming | `runner.py:121` `_DEFERRED_STOP_CLUSTERS = {"roska4_swing", "global_nkd"}`; `runner.py:144-145` `_ARM_BY_CLUSTER = {"roska4_swing": ("America/New_York",14,0), "global_nkd": ("Asia/Tokyo",14,0)}`; predicate `_stop_deferred` `runner.py:2393` |
| Audit working stops | `runner.py:2447` `_audit_working_stops`; `ibkr_broker.py:1354 has_working_stop`, `:1410 unprotected_positions`, `:1473 get_working_stops` |

### Close path and the roll close-confirm primitive

`ibkr_broker._handle_rollover` (`:1593`) is the only close-confirm-then-open sequence that exists:

1. `placeOrder(close)` `:1662`; poll `isDone()` against `EXIT_FILL_TIMEOUT_SECS = 120` (`:160`)
2. timeout → `cancelOrder` + CRITICAL + **roll ABORTED, position unchanged** `:1672-1687`
3. `_verified_status` `:919`; not FILLED → **ABORTED** `:1700-1708`
4. only then `placeOrder(open)` `:1718` against `ENTRY_FILL_TIMEOUT_SECS = 30` (`:159`)
5. OPEN timeout **after** a successful close → CRITICAL; that is the exposed window

Worst case 150 s — comfortably inside a 10:35–12:30 Stress window.

**The ordering defect stands.** `FuturesRunner.run_maxhold_exit` (`runner.py:1311`) sends the CLOSE
first (`:1336`) and cancels the stop afterwards (`:1349-1356`). Between the two the account can be
flat with a live stop still resting. For a Stress switch — which fires exactly when all four
instruments are below open and VWAP and gapping down — that resting sell-stop under a Normal MNQ long
is the order most likely to trigger and open an unwanted short.

### Duplicate-order safeguards

- Entry timeout 30 s then cancel, `Fill(status='CANCELLED')`, runner counts divergence and skips
  (`ibkr_broker.py:706-712`).
- Exit fail escalation at 3 consecutive failures → CRITICAL + halt new entries + manual_required
  (`:718-724`).
- `reconcile_positions` (`:600`) dedups runner state by **`(inst, cluster)`**, keeping the first.
- Scheduler slot mutex `_run_guarded` (`run_scheduler.py:235`) — one `run_live_day` at a time,
  because all children collide on clientId 1 (`:298`, `:751-753`).
- Single-instance PID lock `--lock-path runner.pid` (`run_live_day.py:152`).

### Account / position state, and B3

- Loaded from `--positions-path live_positions.json` (`run_live_day.py:150`); written atomically as
  `{"schema_version": 1, "positions": [...], "breaker": {...}}` (`runner.py:1214`, `:1219`).
- **B3 startup reconcile** `runner.py:474-620`: cross-checks the file against `broker.get_positions()`;
  `B3 EMPTY-WARN` at `:488`; STP-aware mismatch handling from `:509`; halts new entries via
  `_b3_halt_entries` (`runner.py:371`).
- **M5 ledger reconcile** `runner.py:1972-2012`: explains the account's own move against what the
  sleeve booked.

### The structural isolation limit

`IBKRBroker.get_positions` (`:981`) sets **`cluster="UNKNOWN"` — "IBKR has no cluster concept; B3
ignores"** (`:1010`), and B3 "compares only inst/direction/contracts" (`:1006`).

IBKR nets by contract. The runner's identity is `(inst, cluster)`. **Two routes holding MES on the
same account are one netted broker position, and nothing can attribute it back to a route.** A
different `--client-id` does not help: clientId separates *connections*, not *positions*.

**Isolation for a parallel route requires a separate paper account or a separate Gateway, not a
different clientId.** `IBKRBroker.__init__` (`:496`) takes only `host / port / client_id /
bar_duration / _raw_fetcher` — it is **not route-aware**, and the `Order` it receives carries
`cluster` but the broker never uses it to segregate.

---

## 3. Monitor / dashboard feed map

### Producers

| Artifact | Written by | Consumed by |
|---|---|---|
| `live_positions.json` | `runner.py:1214-1219` | `monitor/backend/runner_positions_reader.py` |
| `live_state_data.js` (`window.LIVE_DATA`) | `FuturesRunner.dump_state` `runner.py:3114-3117` | `monitor/backend/app.py:49` |
| `runner_events_YYYYMMDD.jsonl` | `_emit_event` `runner.py:2640` → `_append_event_log` `:2658` | `monitor/backend/runner_event_reader.py` |
| `paper_history.json`, `backtest_curve.json` | `runner.py:837`, `:2864` | dashboard |
| trade log rows | `_append_trade` `runner.py:1366` | `execution_quality_reader`, `paper_pnl_compare` |

Note `runner.py:362`: **`_event_log_dir` is derived from `live_state_path`.** One CLI flag therefore
moves both the dashboard state file and the event log — a ready-made isolation seam.

### Schema tolerance — what breaks and what does not

| Consumer | Behaviour on a new `route` field | Behaviour on a new cluster |
|---|---|---|
| `runner_event_reader.py:40-49` | **safe** — only requires `ts`, sorts on it, passes the rest through | safe |
| `runner_positions_reader.py:30-41` | **silently dropped** — it is an allow-list projection over exactly `inst, direction, contracts, cluster, entry_day, entry_price, stop_price, stop_order_id, contract_month` | cluster value passes through as a string |
| `dump_state` clusters block `runner.py:3265-3269` | n/a | **safe** — `{name: {max_gross_pct, max_net_pct}}` is derived from the guard, so a new cluster appears automatically |
| `global_index/dash/shared/live.js:4-11` | n/a | **BREAKS PRESENTATION** — `CL_ORDER = ['roska4_swing','roska4_stress','global_nkd']` plus hardcoded label and colour maps. `roska4_calm` renders unlabelled, uncoloured and out of order |
| `monitor/backend/paper_evidence_reader.py:95-96` | n/a | **second copy of the arm-time table**, duplicating `runner.py:144-145`. A new cluster must be added in both or the two drift |
| `monitor/paper_pnl_compare.py:609, 845, 1115` | n/a | **WORST BREAKAGE** — cluster is *inferred from instrument*: `"global_nkd" if inst == "MNKD" else "roska4_swing"`. Every Calm A leg and every Stress-MNQ leg would be mislabelled `roska4_swing` |

Two more assumptions worth naming: `dump_state` writes `"n_contracts": 1` as a literal
(`runner.py:3244`), which misreports Stress at qty 7; and `global_index/dash/paper/paper.js:1961`
carries a **third** copy of the arm-time strings as a fallback.

### Where a route field belongs

The event stream is the only channel that accepts a new field without any change:
`_emit_event(level, category, message, context)` (`runner.py:2640-2653`) — put `route` in `context`,
and every existing reader keeps working. For positions, `route` must be added to the allow-list in
`runner_positions_reader.py:30-41` or it is dropped silently.

### Precedent for the parallel-route pattern

`monitor/backend/app.py:72-78` already serves `/realtime-next` — *"Bản nháp thiết kế lại của
/realtime. Tồn tại để sửa giao diện mà không đụng vào route đang dùng thật."* Same shared CSS/JS, one
override layer, no forked copy of the base. That is exactly the shape being proposed here, applied to
the dashboard a level up.

---

## 4. Guard / risk / cap map

**Implementation:** `global_index/net_exposure_multi.py`.

- `Position(instrument, direction, contracts, risk_dollars, cluster)` `:69`
- `ClusterBudget(name, max_gross_pct, max_net_pct)` `:78`
- `DEFAULT_CLUSTERS` `:88-95`: `roska4_swing` 5% / 4.4%, `roska4_stress` 2.5% gross-only,
  `global_nkd` 6% / 6%
- `entry_priority_key` `:103` — sorts largest risk first
- `MultiClusterGuard.state()` `:117`, `.admits()` `:131`

**Exposure arithmetic** (`:120-124`, `:135-140`): per cluster, `long_r` and `short_r` are sums of
`risk_dollars`; `gross = max(long_r, short_r)`; `net = |long_r − short_r|`. `admits()` checks the
proposed position **only against its own cluster** — the docstring at `:132-133` states the clusters
are independent by design.

**Can the guard support what Track 1 needs?**

| Need | Answer |
|---|---|
| Route-specific caps | **Yes, already** — `clusters` is a constructor argument (`:107`), so each route can build its own guard with its own budgets |
| Family cap across clusters | **No.** There is no aggregate concept at any level. `admits()` filters `p.cluster == proposed.cluster` and nothing looks across clusters |
| Separate legacy and Track 1 books | **Yes at the guard level** — the guard is per-instance and stateless between calls; it receives `open_positions` from the caller |
| Shadow-only decisions | **Yes** — `admits()` is a pure function returning `(bool, str)`; calling it changes nothing |

**Global mutable state that could leak between routes**

| Symbol | Location | Risk |
|---|---|---|
| `_preflight_ok` | `run_scheduler.py:193`, persisted `:425`,`:463` | **date-keyed only** — a second route in the same scheduler process shares the flag |
| `_maxhold_done` | `run_scheduler.py:210`, set `:645`, persisted `:438` | **date-keyed only** — a Track 1 max-hold run would mark the day done and suppress the legacy one. Concrete leak; needs a route dimension |
| `_last_beat`, `_stall_outstanding` | `run_scheduler.py:324`, `:327` | heartbeat only |
| `_SWING_CACHE` | `futures/_validated_core.py:201` | keyed by `id(df)`; harmless across processes, a hazard if two routes ever share one process |
| `DEFAULT_CLUSTERS` | `net_exposure_multi.py:88` | `default_factory=lambda: dict(DEFAULT_CLUSTERS)` (`:107`) copies the dict, but **shallowly** — the `ClusterBudget` objects are shared. Safe today because nothing mutates them; would not survive per-route cap tuning in one process |
| `raits.strategies.trend_follow.DEFAULT_CONFIG` | module-level dict | production never mutates it; the scratch harness does. A route layer must reach ema 50 by **constructing** `SwingTFEngine(ema_period=50)`, never by mutating this dict |
| `STOP_TRADING` file | `runner.py:71` | one global kill switch. Arguably correct to keep shared — an operator halt should halt everything — but it must be a deliberate decision, not an accident |

---

## 5. Scheduler / session map

All jobs use `timezone="America/New_York"`; APScheduler handles US DST (`run_scheduler.py:39-40`).
Non-ET sleeves are expressed by converting to ET, not by a second scheduler timezone — the NKD
"14:00 JST" arm is expressed in the runner's own table (`runner.py:144-145`) while its *slots* are
ET-stated at 01:10–02:55.

| Slot | Where | Notes |
|---|---|---|
| every minute — heartbeat | `:589` | deliberately not weekday-gated (`:402`) |
| 09:31 — max-hold exit | `:633` | |
| 10:20 — STRESS_MID | `:689` | conditional, currently disabled |
| 13:45 — pre-flight | `:699` | sets `_preflight_ok` |
| **14:05 — first signal run** | `:857` | `first_slot=True` |
| **14:10 → 15:55 every 5 min (22 slots)** | `:864-881` | `_CONT_SLOTS`; last slot carries `verify=True` |
| every 2 h at :20 — stop repair | `:919-947` | excluded inside `_ENTRY_WINDOWS = [((1,0),(2,55)), ((14,0),(15,55))]` (`:917`) |
| Sun 18:30 — stop repair | `:949-961` | CME reopen |
| **01:10 → 02:55 every 5 min — NKD night** | `:963-996` | `clusters="nkd"`, `prev_preflight=True` |
| 23:55 | `:1100` | |
| session report | `:998+` | fires on last-job completion, not a fixed cron |

**Mapping Track 1's times onto this:**

| Track 1 need | Fits? |
|---|---|
| Calm A entry 10:00 ET | one new cron, same shape as 09:31 — **needs `prev_preflight=True`** |
| Stress setup known 10:35, entry 10:35–12:30 | **24 slots at 5-min spacing, exactly the `_CONT_SLOTS` pattern** — needs `prev_preflight=True`, and `_ENTRY_WINDOWS` must gain `((10,35),(12,30))` so the 12:20 repair sweep does not land inside it |
| Calm A / Stress exit 15:55 ET | 15:55 already exists as a `_CONT_SLOTS` member; an exit for these sleeves would ride it or take its own job |
| Normal-R4 arm 14:00 | already in `_ARM_BY_CLUSTER` |

---

## 6. Route abstraction feasibility

### What already exists

The codebase has **no `route` concept**, but it has four of the five pieces one would need:

1. **Cluster** — first-class: `Position.cluster`, `ClusterBudget`, `_ARM_BY_CLUSTER`,
   `_DEFERRED_STOP_CLUSTERS`, `(inst, cluster)` position identity.
2. **A sleeve selector at the process boundary** — `--clusters` (`run_live_day.py:181-186`),
   aliases at `:190-191` (`swing`/`nkd`/`stress`), resolved to `_active_clusters` at `:192-201` and
   forwarded into `generate_today_signals(active_clusters=…)` at `:647` → `signal_layer.py:192`.
   The night slots already use it in anger: `clusters="nkd"`.
3. **A decides-nothing shadow path** — `--shadow-resume` / `--shadow-verify`
   (`run_live_day.py:164-171`); the scheduler comment at `:849-852` says outright that it *"Decides
   nothing"* and exists so two paths can be compared on live data.
4. **Fully parameterised state paths** — `--positions-path`, `--live-state-path`, `--lock-path`,
   `--stop-path`, `--checkpoint-path`, `--data-dir`, `--nkd-parquet`, `--regime-csv`, `--port`,
   `--client-id`. Every file a route writes is already a flag, and `_event_log_dir` follows
   `live_state_path` automatically (`runner.py:362`).

What is missing is only the **name**: a single identifier that ties one invocation's cluster set, cap
table, state paths and event stream together, and appears in the telemetry.

### Minimal additive route layer

The cheapest shape that changes no legacy behaviour:

- One new flag `--route {legacy,track1_candidate}`, default **`legacy`**.
- A route registry — a plain dict, ideally a new module so no existing file's semantics move —
  mapping route name to: cluster set, `ClusterBudget` table, engine parameters (ema, stop basis),
  filter set, state-path prefix, and Gateway port/account.
- `route` echoed into `_emit_event(..., context={"route": …})` and into `live_positions.json` rows.
- Everything else stays: the scheduler already passes per-slot flags, the guard is already
  per-instance, the state paths are already flags.

The family cap is the one genuinely new *mechanism*, not just a new configuration value.

---

## 7. Side-effect inventory

| Component | read-only | writes logs | writes monitor state | sends broker orders | mutates globals | starts loops | singleton account state |
|---|---|---|---|---|---|---|---|
| `net_exposure_multi.MultiClusterGuard` | ✔ | | | | | | |
| `futures/_validated_core.backtest_swing_tf` | ✔ | | | | `_SWING_CACHE` (id-keyed) | | |
| `futures/swing_tf.SwingTFEngine.desired_position` | ✔ | | | | via engine cache | | |
| `signal_layer.generate_today_signals` | ✔ | | | | | | |
| `live_decision.decide_day` | ✔ | | | | | | |
| `FuturesRunner.__init__` | | ✔ | ✔ (via B1/B3) | **✔ B4 places stops** | `_b3_halt_entries` | | ✔ loads `live_positions.json` |
| `FuturesRunner.run_day` | | ✔ | ✔ | **✔** | | | ✔ |
| `FuturesRunner.run_maxhold_exit` | | ✔ | ✔ | **✔ CLOSE + cancel** | | | ✔ |
| `FuturesRunner.dump_state` | | | ✔ `live_state_data.js` | | | | |
| `_emit_event` / `_append_event_log` | | ✔ JSONL | ✔ (monitor reads it) | | bounded `_events` list | | |
| `IBKRBroker.connect` | | ✔ | | | | ✔ ib_insync event loop | ✔ clientId, account |
| `IBKRBroker.send_order` / `place_stop` / `cancel_order` | | ✔ | | **✔** | | | ✔ |
| `IBKRBroker.get_positions` / `get_equity` | ✔ (network read) | | | | | | ✔ |
| `run_stop_repair` | | ✔ | ✔ | **✔ B4 can place stops** | | | ✔ |
| `run_scheduler` | | ✔ | | indirectly, via children | `_preflight_ok`, `_maxhold_done` | ✔ **the only long-running process** | |
| `monitor/backend/app.py` | ✔ | ✔ | | | | ✔ Flask | |
| `deploy_sim.main` | ✔ | stdout | | | | | |

**Safe to clone and drive in a scratch/shadow context:** the guard, the engines, `signal_layer`,
`decide_day`, `deploy_sim`. **Never clone without isolation:** anything that constructs a
`FuturesRunner` — `__init__` alone runs B1–B5 and **B4 can place stops** — and anything holding an
`IBKRBroker`.

---

## 8. Legacy Invariance Gate

### Files and functions that must remain untouched

Byte-for-byte, until Stage 5:

```
global_index/runner.py            (FuturesRunner in its entirety)
global_index/ibkr_broker.py
global_index/live_decision.py
global_index/signal_layer.py
global_index/net_exposure_multi.py
futures/_validated_core.py
futures/swing_tf.py
futures/basket.py                 (SWING_TF_PARAM in particular)
futures/circuit_breaker.py
raits/strategies/trend_follow.py  (DEFAULT_CONFIG must never be mutated at runtime)
```

Additive-only, and only where the addition is provably inert on the default path:

```
global_index/run_scheduler.py     new jobs only; no change to existing job ids, times or bodies
global_index/run_live_day.py      new flags only, all defaulting to legacy behaviour
monitor/backend/*                 new readers/fields only
global_index/dash/**              new views only, the /realtime-next precedent
```

New files preferred for: the route registry, the family-cap mechanism, the Calm A signal, the Stress
detector, the R4 context filter and the SPY short filter.

### Proofs that legacy behaviour is unchanged

1. **Artifact reproduction.** `scratch/normal_promotion_regen_audit_20260821.py` drives
   `deploy_sim.main()` end to end and, re-run this session, reproduced all three promotion artifacts
   with **matching sha256**, its own internal anchors passing ($33,176 / $6,857 / $6,743). Re-run it
   after any change; a different hash means legacy moved.
2. **The existing test suite**, which already pins the behaviours at risk here:
   `global_index/test_arm_time_per_sleeve.py`, `test_slot_arms_which_sleeve.py`,
   `test_stop_deferral.py`, `test_stop_placement_time.py`, `test_cluster_gate.py`,
   `test_slot_overlap.py`, `test_scheduler_shadow_verify.py`, `test_stress_slot_invariant.py`,
   `test_maxhold*.py`, `test_rollover*.py`, `test_stp*.py`, `test_dashboard_live_snapshot.py`,
   `test_dashboard_stop_state.py`, `test_event_playback.py`.
3. **Scheduler job-table diff.** Enumerate `(id, name, trigger)` for every job with `--dry-run`
   before and after; every pre-existing tuple must be identical and only new ids may appear.
4. **Dry-run command diff.** `run_scheduler --dry-run` logs the exact child command per slot; the
   legacy slots' argv must be character-identical.
5. **Shadow-decision equality.** Stage 1 requires the cloned legacy route to produce the same
   `entry_candidates` and the same `decide_day` output as legacy on the same inputs, for N sessions,
   with zero differences.

### Fields that must stay byte-compatible

- `live_positions.json`: `schema_version` stays `1`; the existing keys keep their names, types and
  values (`runner.py:1214`), and the reader's allow-list (`runner_positions_reader.py:30-41`) keeps
  its current nine keys with the same meanings.
- Event records: `ts`, `level`, `category`, `message`, `context` (`runner.py:2645-2652`). A `route`
  key goes **inside `context`**, never at the top level, and never replaces an existing key.
- `live_state_data.js`: all keys currently in `dump_state` keep their names; `clusters` stays derived
  from the guard.
- Cluster name strings `roska4_swing`, `roska4_stress`, `global_nkd` must not be renamed — they are
  hardcoded in `dash/shared/live.js:4-11`, `paper_evidence_reader.py:95-96` and
  `paper_pnl_compare.py:609,845,1115`.
- Order and Fill field names as consumed by `execution_quality_reader` and `paper_pnl_compare`.

### Rollback selector that must exist before any live/paper route switch

1. `--route` defaulting to `legacy`, so an unflagged invocation is bit-identical to today.
2. A **route kill switch** — either per-route stop files (`STOP_TRADING.track1_candidate`) or a route
   field honoured by the existing global one. `runner.py:71` currently defines a single global name.
3. Separate state paths per route, already available as flags; a route must never inherit legacy's
   `live_positions.json`.
4. **A separate paper account or Gateway port for any route that sends orders.** A different
   `--client-id` is *not* isolation — `get_positions` returns netted positions with
   `cluster="UNKNOWN"` (`ibkr_broker.py:981-1010`) and B3 compares only inst/direction/contracts.
5. A one-line scheduler revert: the Track 1 jobs added in a single block that can be removed or
   flag-disabled without touching any legacy job.
6. `_maxhold_done` and `_preflight_ok` keyed by `(date, route)` before any second route runs in the
   same scheduler process — otherwise the new route silently suppresses legacy's max-hold.

---

## 9. Recommended build plan

**Stage 0 — route identifier, no behaviour change.**
Add `--route` (default `legacy`) and echo it into `_emit_event` `context` only. Nothing reads it.
Gate: artifact sha256 unchanged; full test suite green; scheduler job-table and dry-run argv diffs
empty. Rollback: revert one flag.

**Stage 1 — clone legacy as a no-op shadow, prove identical decisions.**
Run a second `run_live_day` invocation with `--route legacy_shadow`, its own state paths, and a
broker double that raises on any order. Compare `entry_candidates` and `decide_day` output against
the live run for N sessions; require **zero** differences. This reuses the existing
`--shadow-resume` comparison idea rather than inventing one. Gate: zero decision differences.
Rollback: stop scheduling the shadow job.

**Stage 2 — Track 1 signals, shadow only.**
New modules for Calm A, the Stress detector, the R4 context filter and the SPY short filter; a route
registry entry with Track 1's clusters, caps and engine parameters; the family cap as a new
mechanism. Still no orders. Gate: the shadow route's decisions reproduce
`scratch/track1_production_feasibility_audit_20260822.json` — 1,160 / 128 / 91 entries, 14 / 1 / 0
force-closes, zero invariant violations. Rollback: registry entry removed.

**Stage 2a — scheduler slots for the shadow route.** Calm A 10:00, Stress 10:35–12:30 as 24
`_CONT_SLOTS`-shaped jobs, 15:55 exits. **All with `prev_preflight=True`**, and `_ENTRY_WINDOWS`
extended with `((10,35),(12,30))`. Gate: legacy job tuples unchanged; no slot-lock starvation
measured over a full week.

**Stage 3 — monitor support.**
Add `route` to the positions reader allow-list; add `roska4_calm` to `CL_ORDER`, the label map and
the colour map in `dash/shared/live.js`; **fix `paper_pnl_compare.py`'s instrument→cluster inference**
(`:609`, `:845`, `:1115`) to read the recorded cluster instead of guessing; add `roska4_calm` to the
arm-time tables in `paper_evidence_reader.py:95-96` — or better, derive them from
`runner._ARM_BY_CLUSTER` so the third copy in `paper.js:1961` stops being a fourth source of truth.
Gate: `test_dashboard_live_snapshot.py`, `test_dashboard_stop_state.py` green; legacy dashboard views
pixel-unchanged. Rollback: readers are additive; revert the JS maps.

**Stage 4 — paper broker isolation.**
A **separate paper account or Gateway port** for the Track 1 route. Not a different clientId. Route
kill switch. `_maxhold_done` / `_preflight_ok` keyed by `(date, route)`. Gate: a full paper week with
zero B3 mismatches on either route, and legacy's event stream byte-identical in shape to the week
before. Rollback: point the Track 1 route back at the no-op broker.

**Stage 5 — live cutover with legacy fallback.**
Flip the route selector on the live slots; keep every legacy job defined and one flag away. Only
after the Normal-R4 parameter change (ema 30→50, chandelier→fixed 2.0 × daily ATR, ratchet off, plus
the two filters) has passed **its own** before/after gate — it changes a sleeve that is already
trading and must not ride in on a Track 1 patch.

### Rollback plan, all stages

- Every stage is additive and reverts by removing a registry entry, a scheduler block, or a default
  flag value. No legacy file is edited in Stages 0–2.
- The artifact sha256 reproduction is the single check that answers "did legacy move?" — run it at
  every stage boundary.
- The operator kill switch stays global until Stage 4 gives each route its own; until then, halting
  stops everything, which is the safe default.

---

## 10. Two things this audit could not settle

- **The Normal-R4 parameter change is out of scope here and remains the largest single risk.**
  Production runs ema 30 with the engine chandelier stop; Track 1 specifies ema 50 with a fixed
  2.0 × daily ATR stop and no ratchet. That is a change to a live sleeve, not an addition, and it
  needs its own measured before/after — not a route flag.
- **Slot-lock contention was not measured.** Adding 24 Stress slots and a Calm A slot to a scheduler
  whose mutex already serialises everything on clientId 1, with a measured ~5.5-minute run against
  5-minute spacing (`run_scheduler.py:747-749`), could starve slots. The existing comment already
  notes `STOP_REPAIR_1620` has **zero** minutes of clearance against the worst-case 15:55 slot
  (`run_scheduler.py:922-928`). This needs a scheduling simulation before Stage 2a, and no such
  simulation exists today.
