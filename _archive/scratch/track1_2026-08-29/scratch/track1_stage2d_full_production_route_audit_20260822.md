# Track 1 — Stage 2D: full production route audit

**Date:** 2026-08-22 (host clock Calgary MDT; market times in this document are ET unless stated)
**Contract:** READ-ONLY. No production file was edited. No scheduler or service was started. No IBKR
connection was opened. No dashboard write. Nothing committed.
**Purpose:** describe the production route in enough detail that Track 1 can be built alongside it,
naming for every component whether it is reused as-is, reused with a route dimension, wrapped,
incompatible, or legacy-only.

---

## 0. Measurement baseline

Everything in this document was read at this state. Any later number must be re-measured, not
inherited.

| | value | how measured |
|---|---|---|
| commit | `601970bf97e23b200b8eb06cbcf22a240897133a` | `git rev-parse HEAD` |
| branch | `future/incorporation` | git status snapshot |
| working tree | 504 changed/untracked entries | `git status --porcelain \| wc -l` |
| host clock at audit start | 2026-08-22 21:28 MDT (Saturday) | `date` |
| scheduler jobs registered | **60** | `make_scheduler(port=4002, dry_run=True).get_jobs()` — built, never started |
| the eight suites that must stay green | **156 passed, 0 failed, 0 skipped, 6.27 s** | one `pytest -q` run over the eight named files |
| live scheduler process | PID 36656, started **2026-08-20 06:35 MDT**, argv `pythonw -m global_index.run_scheduler --port 4002 --shadow-resume` | `Get-CimInstance Win32_Process` (read-only enumeration) |
| monitor backend process | PID 29432, started 2026-08-20 06:44, `monitor/start_backend.py --ibkr-port 4002 --api-port 5002` | same |
| Stage 2C mutation run | PID 11964, running during this audit | same |

**Measured, and it matters:** `global_index/run_scheduler.py` was last modified **2026-08-22
09:46**, which is *after* the running scheduler started. The live scheduler process is therefore
executing the pre-telemetry version of that module. Consequences, stated exactly:

* the child environment stamping (`RAITS_SLOT_ID`, `RAITS_ROUTE`) is on disk but **not in the
  running parent**, so any telemetry a child writes today carries an empty slot id;
* the parent-side skip records (`skipped_mutex`, `skipped_preflight`) are **not being written at
  all** by the running process;
* `run_live_day.py` changes *are* live, because every slot is a fresh `python -m` subprocess.

The dashboard already models this: `monitor/backend/schedule_status.py:155` computes
`stale_code = started < code_mtime`. This is a warning, not a blocker, but any telemetry collected
before the scheduler is restarted is partial and must not be treated as a clean legacy baseline.

---

## A. Executive verdict

**Verdict: the shadow (no-order) Track 1 route can be built now. An order-sending Track 1 route is
BLOCKED on four decisions that are design decisions, not coding tasks.**

None of the four is a defect in the current system. Each is a place where the current system made a
single-route assumption that a second route breaks.

### Blockers

**BLOCK-1 — one IB Gateway login is one position book, and there is no account dimension anywhere.**
`IBKRBroker.__init__` (`global_index/ibkr_broker.py:496`) takes `host, port, client_id,
bar_duration` and nothing else. `get_positions()` reads `ib.positions()` unfiltered
(`ibkr_broker.py:981`); `get_equity()` reads `NetLiquidation` from `ib.accountValues()` unfiltered
(`ibkr_broker.py:1038`). Two routes holding MES/MNQ/MYM/M2K in the same account net to a single
signed quantity at IBKR. The startup reconcile compares the file's `(inst, direction) → contracts`
against the broker's (`runner.py:~530`), so a legacy LONG 1 and a Track 1 SHORT 1 on the same
symbol read as broker×0 with two file rows — `B3 MISMATCH`, and entries halt **for both routes**.
This is the exact mechanism that caused STRESS_MID's 10:20 cron to be switched off; the note is at
`run_scheduler.py:684-702`. A second route on the same account re-creates it deliberately.
*Decision required:* separate IBKR account/login for Track 1, or Track 1 stays order-free until
legacy is retired. A different `client_id` does **not** solve this — it changes who may cancel an
order, not whose positions are counted.

**BLOCK-2 — the 10:20→14:05 no-run invariant forbids the Track 1 windows on the legacy entry point.**
`run_scheduler.py:672` carries an explicit invariant: no slot may call `run_live_day` between 10:20
and 14:05 ET. The mechanism is real and I traced it: `_mark_held_unchanged` is never called for the
stress cluster, so `diff_desired_vs_held` (`signal_layer.py:97`, the loop at lines 118-121) finds
the `(inst, roska4_stress)` key absent from `desired` and emits an exit on the **next** run. Track 1
needs a 10:00 slot (Calm A) and 10:35–12:30 slots (Stress). Both land inside the forbidden band.
*Decision required:* Track 1 gets its **own entry-point script** with its own signal layer. Adding a
`--clusters calm` flag to `run_live_day` and scheduling it at 10:00 would breach this invariant on
the first slot, because the legacy `generate_today_signals` runs for whatever clusters are active and
the held-position sweep is global.

**BLOCK-3 — Track 1's windows open before the day's own pre-flight, so the freshness gate cannot mean
what it means for Rổ 4.** `_live_day_body_inner` fails closed on a missing pre-flight flag
(`run_scheduler.py:822-846`). Pre-flight runs at 13:45 ET (`run_scheduler.py:~741`). Calm A at 10:00
and Stress from 10:35 both run *before* it, exactly like the NKD night slots, so they must use
`prev_preflight=True` and the freshest data update available to them is **13:45 ET the previous
business day**. That is a different data-freshness contract from the one every Track 1 backtest
number was produced under. *Decision required:* either accept D-1 13:45 as the Track 1 data
contract and state it in the invariants, or add a second pre-flight before 10:00 — which is a new
IBKR-touching job and needs its own fail-closed reasoning.

**BLOCK-4 — quantity has no cluster dimension, and Stress-MNQ is 7 lots.** Size is read as
`n = self.contracts.get(t["inst"], 1)` in both entry passes (`runner.py:1883` and `runner.py:2054`)
and again in `decide_day` (`live_decision.py:~139`). `run_live_day.py` builds
`contracts_by = {n: 1 for n in list(BASKET) + [NKD_INST]}`. Track 1 wants **MNQ = 1 under
`roska4_swing` and MNQ = 7 under `roska4_stress` on the same day**. There is no key that can express
that. The fat-finger cap (`max_contracts_per_order=10`, `runner.py:843`) would pass 7, so this fails
silently as "entered 1 lot instead of 7" rather than loudly. *Decision required:* make size a
property of the candidate (`t["contracts"]`) rather than of the instrument, or wrap the runner for
Track 1. Changing `contracts_by_inst` to a `(inst, cluster)` key touches legacy call sites and is
the more invasive of the two.

### Warnings — build proceeds, but eyes open

| # | warning | evidence |
|---|---|---|
| W1 | **The three new Track 1 modules are not wired to anything.** `route_checkpoint.py`, `route_params.py`, `window_ledger.py` have **zero** importers outside `scratch/`. `slot_telemetry.py` *is* wired (`run_scheduler.py:70`, `run_live_day.py:77`). | grep for importers across the tree |
| W2 | **The dashboard keeps a hand-written copy of the scheduler's slot table.** `schedule_status.py:167-181` re-declares R4 slots, NKD slots, fixed pipeline slots, stop-repair slots and the Sunday sweep. Its own comment at line 273 says an unmirrored slot makes the dashboard "coi nó là slot lạ và dựng incident giả mỗi tuần". Track 1 slots will do exactly that until this file is updated. | read |
| W3 | **`roska4_calm` does not exist in production.** `MultiClusterGuard.DEFAULT_CLUSTERS` has three budgets (`net_exposure_multi.py:~150`); `_cluster_of` **raises KeyError** for an unknown cluster, and `decide_day` does not catch it. A Calm A candidate reaching legacy `decide_day` kills the slot. `_ARM_BY_CLUSTER` (`runner.py:144`) and `dump_state`'s `_cl_keys` (`runner.py:3124`) are likewise three-cluster. | read |
| W4 | **The family cap Track 1 measures with does not exist in production.** `family_admits` lives only in `scratch/combined_repaired_replay_20260822.py:60`. `MultiClusterGuard.admits` checks the proposed position against *its own cluster only* — clusters are independent by design (`net_exposure_multi.py` docstring). | read |
| W5 | **Stage 2C left two mutations unproved.** `scratch/track1_breaker_mut4.log`: M5 (a carried position in the wrong cluster) and M5b (carried risk ×20) both MATCH where they should DIVERGE, i.e. the bootstrap's cluster and risk fields are **not proved load-bearing on the floor window**. This is a *bootstrap* gate, separate from the production-wiring gate this document covers. It does not block wiring; it blocks trusting a resumed Track 1 book. | read the log |
| W6 | **Two different Stress candidates exist in the tree.** `futures/stress_liquidation_1020.py` (untracked) enters at **10:20** with variants `breadth3`/`wide_range3` and says of itself that it is "deliberately not wired". The Track 1 stack is `mnq_only_g3_q7`, entry window **10:35–12:30** (`scratch/stress_switch_full_replay_20260822.py:44`). `window_ledger.WINDOWS["roska4_stress"]` already encodes 10:35–12:30 / 24 slots. Whoever ports the sleeve must take the scratch one, not the `futures/` one. | read both |
| W7 | **`deploy_sim.py` — the backtest reference — has uncommitted changes** adding `--stress-engine liquidation1020`, `--stress-variant`, `--stress-instruments`, `--stress-cap`. Anyone re-deriving a baseline must know which version produced it. | `git diff` |

---

## B. Production route map

```
APScheduler (BlockingScheduler, tz=America/New_York, 60 jobs)
  │  threading.Lock _slot_lock  → one run_live_day at a time IN THIS PROCESS
  │  preflight flag (disk)      → fail-closed if today's (or prev bday's) flag is not True
  ▼
subprocess:  python -m global_index.run_live_day  --data-dir --nkd-parquet --regime-csv
             --live-state-path --clusters --port [--shadow-resume] [--shadow-verify]
             [--stress-entry]        env: RAITS_SLOT_ID, RAITS_ROUTE=legacy (+inherited)
  │
  ├─ frozen manifest size check (verify_frozen.quick_check_manifest) — WARN only, never blocks
  ├─ parquet load: futures/_validated_core.load_parquet → tz-aware US/Eastern
  │                global_index/_core.load_parquet for NKD → tz_convert(Asia/Tokyo)
  ├─ HMM labels: benchmark_daily(spy_daily_live.csv) → label_regimes(train 2018-01-01,
  │              3 states, fit_end 2024-12-31) ; NKD wrapped in RegimeLabels(lag_days=1)
  ├─ engines: SwingTFEngine(ema30, mult2.5, hold5) ; SwingTFEngine(ema10,...) for MNKD ;
  │           StressMidEngine (constructed, never fed — stress_bars_1015={} unless --stress-entry)
  ├─ E1 PID lock (runner.pid) taken BEFORE connecting
  ▼
IBKRBroker.connect(127.0.0.1:4002, clientId=1)
  ▼
FuturesRunner.__init__      B1 load state → B3 reconcile vs broker → B4 naked-stop sweep
  ▼
FuturesRunner.run_day(today)
     _retry_pending_exits → _handle_rollover_if_needed → D5 kill-switch read
     fetch_bars(through=day+23:59) per instrument
     signal_fn:  _splice_live / _splice_nkd_live  →  [shadow resume compare]
                 → generate_today_signals → diff_desired_vs_held  → (candidates, exits)
     gates: E3 clock skew → D5 → B3 halt → G1/G2 stale guard
     decide_day: exits booked → breaker start_day/update → priority sort → guard.admits
     execute: CLOSE exits → same-day pairs → H4/M5 broker reconcile → breaker re-check
              → multi-day OPENs → STP (deferred for swing/NKD, immediate otherwise)
     _persist_state → _audit_working_stops (B5) → dump_state
  ▼
state: live_positions.json · trade_log.jsonl · slip_stats.json · runner_events_YYYYMMDD.jsonl
       replay_checkpoint.json · global_index/live_state_data.js · paper_history.json
  ▼
monitor backend (Flask, :5002) reads those files — never imports the runner
```

### B.1 The measured job table (60 jobs)

Built by calling `make_scheduler` and enumerating; the scheduler was **not** started.

| ET time | day | job id | what it does | class |
|---|---|---|---|---|
| every minute | all week | `heartbeat` | bounds `Event.wait`, measures sleep stalls | maintenance-only |
| 00:20 | mon-fri | `stop_repair_0020` | `run_stop_repair` — builds a runner, B1–B5 only | **trade-affecting** (B4 places stops) |
| 01:10–01:55 (10) | mon-fri | `nkd_night_01xx` | `run_live_day --clusters nkd`, `prev_preflight=True` | **trade-affecting** |
| 02:00–02:55 (12) | mon-fri | `nkd_night_02xx` | same; 02:55 also `--shadow-verify` | **trade-affecting** |
| 04:20 06:20 08:20 | mon-fri | `stop_repair_0x20` | stop repair | **trade-affecting** |
| 09:31 | mon-fri | `maxhold_exit` | `run_maxhold_exit`, closes hold ≥ 5 d; also arms deferred stops via B4 | **trade-affecting** |
| 10:20 12:20 | mon-fri | `stop_repair_1020/1220` | stop repair | **trade-affecting** |
| 13:45 | mon-fri | `preflight` | `update_ibkr_daily` then `update_spy_csv`; sets the day's flag | **gate** (blocks all later slots on failure) |
| 14:05 | mon-fri | `live_day` | `run_live_day` all clusters, `first_slot=True` | **trade-affecting** |
| 14:10–15:55 (22) | mon-fri | `live_day_xxxx` | continuous slots; 15:55 also `--shadow-verify` | **trade-affecting** |
| 16:20 18:20 20:20 22:20 | mon-fri | `stop_repair_xx20` | stop repair | **trade-affecting** |
| 18:30 | sun | `stop_repair_sun_1830` | CME reopen sweep | **trade-affecting** |
| 23:55 | mon-fri | `session_report_fallback` | report safety net if the last job never ran | dashboard/log-only |
| *(event-driven)* | mon-fri | listener on `stop_repair_2220` | `session_report` then `flex_pull` + `paper_pnl_compare` | dashboard/log-only |
| *(startup)* | — | `_catch_up_maxhold` | runs 09:31's job if the scheduler came up after it | **recovery/catch-up** |

`_LAST_JOB_ID` is computed from the schedule, not hard-coded (`run_scheduler.py:1038`); it resolves
to `stop_repair_2220` today, which is what the session report hangs off.

Timing constants, measured: `SLOT_MISFIRE_GRACE_SECS = 300` (`:363`), `_SLOT_TIMEOUT_SECS = 1200`
(`:231`), `_INFLIGHT_STUCK_SECS = 1500`.

`_ENTRY_WINDOWS = [((1,0),(2,55)), ((14,0),(15,55))]` (`:931`) — stop-repair slots at `:20` that
fall inside these are dropped, which is why 02:20 and 14:20 are absent.

**Route dimension today:** the only route field anywhere in the scheduler is
`_env.setdefault("RAITS_ROUTE", "legacy")` (`run_scheduler.py:~520`), which is identity only and
enables nothing. Slot ids, job ids, log lines, state files and dashboard readers have **no route
dimension at all**.

---

## C. Gate matrix

Order-affecting gates first. "State read/write" means process state and files, not market state.

| gate | where | order-affecting? | reads | writes | route dim needed | Track 1 decision |
|---|---|---|---|---|---|---|
| single-instance mutex | `run_scheduler.py:245` `_run_guarded` | yes (skips a slot) | `_slot_lock`, `_slot_started_at` | telemetry skip record | **yes** — a Track 1 slot must not be skipped because a legacy slot is running, and vice versa, unless they share a broker | **reuse with route dimension** (separate lock per route, or one lock if they share an account — which they must not, see BLOCK-1) |
| pre-flight fail-closed | `run_scheduler.py:802-846` | yes (skips the whole slot) | `preflight_state.json` keyed by ET date | telemetry skip record | **yes** — Track 1's own data contract | **reuse with route dimension**; must resolve BLOCK-3 first |
| PID lock E1 | `runner.py:222` `_acquire_lock` | yes (aborts the run) | `runner.pid` | `runner.pid` | **yes** — one file per route or the two routes lock each other out | **reuse with route dimension** (`--lock-path runner.track1.pid`) |
| B3 broker/file reconcile | `runner.py:~500-640` | yes — sets `_b3_halt_entries`, exits blocked in `run_day` at `:1675` | `live_positions.json`, `broker.get_positions()`, `get_order_status`, `find_execution` | books stop exits, trade log, sleeve ledger | **yes**, and it is the hardest one | **incompatible without a separate broker account** — see BLOCK-1 |
| B4 naked-stop sweep | `runner.py:~640-780` | yes — places stops | positions file, `get_working_stops()`, `unprotected_positions()`, `has_working_stop()` | `stop_order_id` on positions, orders at IBKR | yes | **reuse with route dimension**; Calm A/Stress need `_stop_deferred → False`, which is already the default for unknown clusters |
| B5 end-of-run stop audit | `runner.py:2447` `_audit_working_stops` | reporting-only | positions, broker stop book | events | no | **reuse as-is** |
| D5 kill switch | `runner.py:1572`; file `STOP_TRADING` | yes — clears entries | file existence | event | **yes** — must be able to stop one route without stopping the other | **reuse with route dimension** (`--stop-path STOP_TRADING.track1`, plus a global one) |
| E3 clock-skew | `runner.py:1612-1636` | yes — clears entries when last bar > 3 d old | bar index | event | no | **reuse as-is** |
| C1 signal_fn try/except | `runner.py:1640-1660` | yes — entries skipped, exits kept | — | event | no | **reuse as-is** |
| C4 per-cluster isolation | `signal_layer.py:229-330` | yes — a failed cluster keeps its held positions instead of exiting them | held list | `desired` | no | **reuse as-is**, and Calm/Stress must get the same treatment |
| G1 SPY-CSV staleness | `hmm_stale_guard.py`; wired `runner.py:1690-1745` | yes — hard-stale blocks entries | `spy_daily_live.csv` last date | guard flags, events | no (shared regime source) | **reuse as-is** |
| G2 model age | same | reporting-only (warn) | `fit_end` | flags | no | **reuse as-is** |
| circuit breaker HALT (15% DD) | `futures/circuit_breaker.py`; `live_decision.py:~125` | yes — halts all entries | system equity, persisted `peak_equity` | `live_positions.json` breaker block | **yes** — one equity ledger per route, or a Track 1 loss halts legacy | **reuse with route dimension** (own state file) |
| circuit breaker HALT_DAY (−4%) | same | yes | `_day_start_equity` | same | yes | **reuse with route dimension** |
| breaker re-check before multi-day OPENs | `runner.py:2029-2050` | yes | ledger equity | events | yes | **reuse with route dimension** |
| WARN / `size_multiplier` | `circuit_breaker.py` | **reporting-only by design** — `decide_day` reads only `allow_new_entries` | — | — | no | **reuse as-is**; do not wire `size_multiplier` (would invalidate every WFO number) |
| cluster gross/net cap | `net_exposure_multi.py:130` `admits` | yes — rejects entries | open positions of that cluster only | rejection counters, `rejected_details` | **yes** (`roska4_calm` budget missing; Track 1 stress cap 10% ≠ production 2.5%) | **reuse with route dimension** — pass a `clusters=` dict, exactly as `scratch/combined_repaired_replay_20260822.py:46` already does |
| family cap (swing+calm combined) | `scratch/combined_repaired_replay_20260822.py:60` | yes in Track 1 | swing+calm positions | counter | n/a | **port** — no production equivalent exists |
| same-symbol suppression (Normal ↔ Calm) | Track 1 loop, `scratch/track1_stage2c_book_bootstrap_20260822.py:~240,~290` | yes | open book | counters | n/a | **port** |
| Stress force-close of same-symbol Normal/Calm | same file, `cluster == "roska4_stress"` branch | yes — closes and re-enters | open book, price series | ledger, counters | n/a | **port**, and it needs a broker primitive that does not exist — see §F |
| opposite-direction / same-symbol conflict | **absent in production** | — | — | — | — | Track 1 makes at most one position per instrument across all sleeves by construction; that property must be asserted by a test, not assumed |
| max concurrent positions | **absent** — bounded only by cluster caps | — | — | — | — | inherit; state it explicitly |
| fat-finger cap F3 | `runner.py:843, 1883, 2054` | yes — blocks the order | `max_contracts_per_order` (10) | event | **yes** — 7 lots passes today, but a per-cluster size needs its own ceiling | **reuse with route dimension** |
| ATR-proxy sizing (`risk_sized`) | `signal_layer.py:68` `to_candidate`; raises on NaN/0 | yes — it is the cap denominator | daily ATR series, point value, contracts, mult | candidate dict | **yes** — Calm A uses a *true* ATR15 stop-risk, not `mult × ATR × pv` | **wrap for Track 1**: Calm A's risk must come from the disaster-stop distance, which `to_candidate` cannot express |
| admission risk vs held-exposure drift | — | — | — | — | — | **Not modelled anywhere.** `admits` uses `risk_dollars` frozen at entry; the position's real stop distance moves after the roll (`_roll_stop` shifts `stop_price` but never `risk_dollars`). Same in Track 1's replay. Inherited limitation — record it, do not silently fix it |
| broker/account halt states | none — a disconnect raises `IBKRConnectionError` and the slot fails | — | — | — | — | inherit |

**Read carefully:** `MultiClusterGuard._cluster_of` raises `KeyError` for an unknown cluster and
`decide_day` has no handler, so a `roska4_calm` candidate reaching the legacy brain takes the whole
slot down. That is a fail-closed direction, which is the safe one, but it means Track 1 cannot share
`decide_day` without first giving the guard a fourth budget.

---

## D. Rollover matrix

| aspect | production behaviour | file:line | route dimension | Track 1 |
|---|---|---|---|---|
| trigger | first step of `run_day`, before `fetch_bars`; per open position | `runner.py:1403`, called at `:1566` | no — schedule-driven | reuse |
| schedule source | `ROLL_SCHEDULE` keyed by **IBKR** symbol; `get_roll_event` resolves the runner name first | `ibkr_broker.py:248` | no | reuse as-is |
| contract detection | `_current_front_month` walks the same table; `_month_contract` qualifies and **raises** if `conId` is unset | `ibkr_broker.py:283, 433` | no | reuse as-is |
| two-clock guard | `session_month_conflict` refuses to roll when the session day and wall clock imply different months | `ibkr_broker.py:324`, enforced `:1621` | no | reuse as-is |
| close-confirm-enter | CLOSE front month (market, `outsideRth`, `tif=DAY`, 120 s) → verify `Filled` → **only then** OPEN next month (30 s) | `ibkr_broker.py:1652-1745` | no | see below |
| stop cancel/recreate | after a successful roll: cancel old STP (confirmed, not assumed), then `_roll_stop` shifts the level by the measured close→open spread and re-places — unless the position is still inside its deferral window, in which case the level is recorded and B4 arms it later | `runner.py:1516-1537`, `runner.py:2323` | no | reuse |
| order ids | client-side `orderId` string; only a status IBKR actually returned counts as acceptance | `ibkr_broker.py:1209` `_await_stop_accepted` | no | reuse as-is |
| position/state update | `pos.contract_month = open_fill.contract_month`, then `_persist_state()` immediately | `runner.py:1502`, `:1537` | **yes** — separate state file | reuse with route dimension |
| dashboard/log event | `_emit_event("INFO"/"CRITICAL", "ROLLOVER", …)` → `runner_events_YYYYMMDD.jsonl` + `live_state_data.js` `meta.events` | `runner.py:1478-1500` | **yes** | see §I |
| failure: roll raises | caught per position, position left on its current month, CRITICAL, loop continues | `runner.py:1425-1444` | no | reuse as-is |
| failure: CLOSE not filled | roll aborted, position unchanged, CRITICAL | `runner.py:1446-1460` | no | reuse |
| failure: OPEN not filled after CLOSE filled | **position is flat at IBKR**; removed from state, `_persist_state()` immediately, CRITICAL | `runner.py:1462-1481` | no | reuse — and this is the branch Track 1's Stress switch will inherit |
| timeout | close 120 s (`EXIT_FILL_TIMEOUT_SECS`), open 30 s (`ENTRY_FILL_TIMEOUT_SECS`) | `ibkr_broker.py:1668, 1720` | no | reuse |
| interaction with open stops | the roll cancels the old STP explicitly; a failed cancel is CRITICAL and names the risk (an orphan SELL STP fills into an unwanted short) | `runner.py:1516-1535` | no | reuse |
| interaction with max-hold | `run_maxhold_exit` does **not** run the rollover step; it passes `contract_month` from the book so a 09:31 exit addresses the month actually held | `runner.py:1338-1344` | no | reuse — Track 1 must do the same |
| interaction with pre-flight / done flags | none — rollover has no done flag; it is idempotent because `get_roll_event` only fires on the exact roll date | — | no | inherit; note that a roll date crossed by a **catch-up** run is guarded only by `session_month_conflict` |

### D.1 Can Track 1's Stress switch reuse the close-confirm-enter primitive?

**No, not as it stands — but the shape is right and should be generalised rather than re-written.**

What `_handle_rollover` does that the Stress switch also needs:
* place the CLOSE, wait for a **verified** terminal status (not a bare `Cancelled` — see
  `_verified_status`, `ibkr_broker.py:919`),
* refuse to place the second leg unless the first actually filled,
* an explicit "we are now flat at the broker and the book must be corrected immediately" branch.

What is hard-wired and wrong for the switch:
* it is gated on `get_roll_event` returning a roll date — a Stress switch has no roll date;
* the two legs are the **same symbol, same direction, same quantity, different month**. The switch
  is same symbol, *possibly different direction*, **different quantity** (1 → 7), same month;
* both `Fill` objects are stamped with `front_month`/`next_month`, which the switch must not do;
* it returns `(close_fill, open_fill)` and the caller (`_handle_rollover_if_needed`) interprets them
  through a rollover-specific state update (`pos.contract_month = …`, `_roll_stop(shift)`), which is
  meaningless for a cluster switch.

**Recommendation:** extract a broker-level `close_then_open(inst, close_leg, open_leg)` primitive
from `_handle_rollover` lines 1652-1745, leaving `_handle_rollover` as its first caller so the
existing rollover tests keep exercising the same code. Do **not** hand-copy the sequence into a
Track 1 module: this project has already paid for a second copy of a decision rule more than once,
and the failure branches here are the ones that leave a position flat.

---

## E. State artifact matrix

| artifact | writer | reader | key schema | route dim today | corruption / lost-update risk | atomic? | two routes in one process? | separate file needed? |
|---|---|---|---|---|---|---|---|---|
| `live_positions.json` | `runner._persist_state` (`:1188`) | runner B1/B3, `run_maxhold_exit`, `run_stop_repair`, `monitor/backend/runner_positions_reader.py` | `{schema_version, positions[], breaker{}}`; position key is `(inst, cluster)` **implicitly** — the list has no unique key | **none** | whole-file rewrite; two writers = lost update | yes (`.tmp` → `os.replace`) | **no** | **yes** |
| `runner.pid` | `_acquire_lock` | same | single PID | none | same-PID re-acquire is exempted on purpose (`runner.py:227`) | write-then-read, not atomic | no | **yes** |
| `global_index/preflight_state.json` | scheduler | scheduler | `{ "YYYY-MM-DD": bool }`, last 7 kept | none | torn file reads as "no record" → fail-closed | yes | no | **yes** if Track 1's freshness contract differs (it does — BLOCK-3) |
| `global_index/maxhold_state.json` | scheduler | `_catch_up_maxhold` | `{ "YYYY-MM-DD": bool }` | none | torn file → re-run an idempotent job | yes | no | yes |
| `global_index/replay_checkpoint.json` | `run_live_day._shadow` via `replay_checkpoint.save` | same | `{schema_version:1, instruments:{INST:{last_day,fingerprint,params,pos}}}` | **none — instrument-keyed only** | `save()` rewrites the whole dict → a second writer is a lost update | `.tmp` → replace | **no** | **yes** — this is precisely why `route_checkpoint.py` (schema 2, `routes/<route>/sleeves/<sleeve>/instruments/<inst>`, `_FileLock`, `ScopeViolation`) exists |
| `global_index/replay_checkpoint.track1.json` | `route_checkpoint.save_route` | `route_checkpoint.load` | schema 2, route-scoped, locked, scope-asserted | **yes** | designed against lost update | yes | yes | already separate |
| `trade_log.jsonl` | `_append_trade` / `_append_trade_raw` from six paths | `paper_evidence_reader`, `execution_quality_reader` | one JSON object per line; `CLOSE_RECORD_FIELDS` is the declared union (`runner.py:76`) | **none** | append-only | O_APPEND | yes, but rows become indistinguishable | **add a `route` field** rather than a second file — see §I |
| `slip_stats.json` | `_persist_slip_stats` | runner | running sums | none | whole-file rewrite | not atomic | no | yes |
| `runner_events_YYYYMMDD.jsonl` | `_append_event_log` (`runner.py:2658`) | `monitor/backend/runner_event_reader.py` | `{ts, level, category, message, context?}`; file name derived from the **event's own ET timestamp** | **none** | checks the last byte is `\n` before appending; one failure disables the channel for the process | O_APPEND + short-write check | yes | **no — add a `route` field**; a second file per route would split the operator's one timeline |
| `global_index/live_state_data.js` | `dump_state` (`:3114`) | `runner_state_reader`, `paper_evidence_reader`, dashboard | `window.LIVE_DATA = {runner_health, meta, snapshots[]}`, snapshots capped at 500 | **none** | whole-file rewrite each slot | `.tmp` → replace | **no** | **yes** for a Track 1 route; the dashboard shows one system |
| `global_index/paper_history.json` | `_record_paper_day` | `paper_evidence_reader` | daily equity marks | none | whole-file rewrite | — | no | yes |
| `monitor/paper_pnl_compare.json` | `monitor/paper_pnl_compare.py` (22:20 job) | `paper_evidence_reader` | broker-vs-ledger comparison | none | rewritten nightly | — | no | route-aware later; legacy-only for now |
| `scheduler_MMDD.log` / `live_day_MMDD.log` | scheduler / `run_live_day` | `schedule_status`, `job_journal_reader`, `paper_evidence_reader` | free text; parsed by `[SLOT_ID]` prefix | **none** | append-only | — | interleaved but distinguishable by slot id | **no** — reuse, but Track 1 slot ids must be prefixed so parsers can split them |
| `slot_timing_YYYYMMDD.jsonl` | `slot_telemetry._write` | nothing yet | `{ts, route, slot_id, pid, outcome, runtime_s, phases, …}` | **yes** (`route` field) | append-only, disabled on first failure | — | yes | already route-aware; off unless `RAITS_TELEMETRY_DIR` is set |
| `window_coverage_YYYYMMDD.jsonl` | `window_ledger._write` | `window_ledger.read/status` | `{ts, schema, route, sleeve, date, event, …}` | **yes** | append-only | — | yes | **written by nobody today** (W1) |

**The rule that falls out of this table:** every artifact whose writer *rewrites the whole file*
must be per-route. Every artifact that is *append-only* can be shared, provided the record carries a
`route` field. That splits cleanly: `live_positions.json`, `runner.pid`, the checkpoints, the
pre-flight/max-hold flags, `slip_stats.json`, `live_state_data.js` and `paper_history.json` go
per-route; `trade_log.jsonl`, `runner_events_*.jsonl`, the logs and the two new JSONL channels stay
shared with a route field.

---

## F. Order lifecycle and broker safety

### F.1 What the broker layer actually guarantees

* **A bare `Cancelled` is not believed.** `_verified_status` (`ibkr_broker.py:919`) exists because
  ib_insync mutates `orderStatus.status` client-side on any code missing from its `warningCodes`
  set; three OPENs reported Cancelled 18 ms after submission on 2026-08-03 and all three filled.
* **A stop id is only real if IBKR reported a status.** `_await_stop_accepted` (`:1209`) polls up
  to 5 s and accepts only `PreSubmitted`/`Submitted`; anything else returns `""` so B4 sees a naked
  position rather than a fabricated id.
* **Stops are snapped to the tick grid, away from the market** (`_round_stop_to_tick`, `:1182`).
  Off-grid prices are rejected by IBKR with code 110 and used to be reported as success.
* **A cancel is confirmed, not assumed.** `cancel_order` (`:1238`) uses `reqAllOpenOrders`, then
  polls up to 5 s for a terminal status, and on failure names the owning `clientId` — IBKR accepts
  a cancel only from the client that placed the order. **This is why every entry point uses
  `client_id=1`.**
* **Positions are read until two consecutive reads agree** (`get_positions`, `:981`), max ~8 s.
* **Equity retries up to 4× (~14 s)** and raises rather than returning 0 (`get_equity`, `:1038`).

### F.2 Ordered steps

**Normal entry (multi-day)**
1. `decide_day` admits the candidate and appends an `OpenPos` **before any order goes out**.
2. `n = contracts_by_inst[inst]`; F3 fat-finger check.
3. `send_order(OPEN)` → `session_month_conflict` refuse-check → `_front_month_contract` (raises if
   unresolved) → MarketOrder, `outsideRth=True`, `tif=DAY`, poll ≤ 30 s.
4. `FILLED`/`PARTIAL` → write `entry_price` and `contract_month` onto the position from the fill.
5. Not filled → **C2 ghost removal**: the position `decide_day` already booked is taken back out of
   `open_positions` (`runner.py:2073-2110`). This branch used to test `== "FAILED"`, which an entry
   never returns, so the book kept positions the broker never opened.
6. `_append_trade` OPEN row; `_emit_event`.
7. Stop: record `stop_price` **always**; place the STP only if `_stop_deferred` is False.

**Normal exit (signal)**
1. `send_order(CLOSE, contract_month=p.contract_month)` — the month the **book** holds, never the
   calendar's.
2. Filled → `_book_realised`, slippage stats, CLOSE row, event.
3. `FAILED` → `exit_pending=True`, position restored, **and the `pnl_sized` credit reversed**
   (`runner.py:1855-1875`, the L4 fix). Retried at the next `run_day`.
4. Success → cancel the GTC stop, and report the cancel result honestly (`_report_stop_cancel`).

**Stop exit** — happens at IBKR with no process running. Discovered on the next startup by B3:
`get_order_status == FILLED` → `find_execution` → book at the real fill; if the execution record has
aged out, book at the placed level and mark the row `estimated: True`
(`source="B3_STP_NO_EXEC_RECORD"`). If `NOT_FOUND` **and** broker qty is 0, it does **not** infer —
it verifies via `reqExecutions` or halts entries.

**Max-hold exit** — separate process at 09:31, `clientId=1`, PID lock taken before connecting,
`contract_month` from the book, cancel the stop, book, write the CLOSE row, persist. On failure:
`exit_pending=True` for the 14:05 retry.

**Rollover** — §D.

**Proposed Track 1 Stress force-close-then-enter** (does not exist yet):
1. Compute the Stress candidate; run the cluster cap **and** the breaker **before touching
   anything** — the handoff doc's rule is "close same-symbol Normal MNQ *only after* Stress passes
   cap/breaker", and the Track 1 replay implements exactly that ordering
   (`track1_stage2c_book_bootstrap_20260822.py`, `cluster == "roska4_stress"` branch: `guard.admits`
   against the *survivors* list first, `continue` on reject **before** any close).
2. Cancel the Normal position's working stop and **confirm** the cancel. If the cancel fails, do not
   proceed — an orphan SELL STP under a new SHORT is a doubling order, not a protective one.
3. `send_order(CLOSE)` for the Normal leg with its recorded `contract_month`; require a verified
   `Filled`.
4. Only then `send_order(OPEN)` for the Stress leg, 7 lots.
5. If step 4 fails: the account is **flat on that symbol**. Remove the Normal position from the book
   and persist immediately — the same branch `_handle_rollover_if_needed` already has at
   `runner.py:1462`. Do not retry the Stress entry later in the window at a moved price.
6. Place the Stress stop immediately (`_stop_deferred` is False for any cluster outside
   `_ARM_BY_CLUSTER` — the correct behaviour for a same-session sleeve).

**Risks specific to this sequence, all inherited and all real:**
* between steps 3 and 4 the account is flat and unprotected. `_handle_rollover` has the same window
  and accepts it; a 7-lot leg makes it more expensive.
* if the process dies between 3 and 4, the next startup sees file = Normal position, broker = flat,
  stop id NOT_FOUND, no execution matching the *stop* — that is the `B3 HALT` branch. Entries stop
  until someone edits the file. That is the correct fail direction and it must be documented as an
  expected operator event, not a bug.
* IBKR nets same-symbol: after step 3 the account genuinely holds nothing on MNQ, so step 4's 7 lots
  are unambiguous. **This is why the Track 1 switch design is netting-safe where STRESS_MID was
  not** — the two never coexist. Assert that property in a test rather than trusting it.

### F.3 Standing risks in the current path (inherited, not introduced by Track 1)

| risk | status |
|---|---|
| naked stop between entry and the next session's arm time | **deliberate**, measured: STP at fill −$10,832 vs next session +$47,166 over 2018-2026 (`runner.py:2393` docstring). Track 1's Calm/Stress sleeves must **not** inherit the deferral |
| duplicate settlement | detected, not prevented: `booked[tid] > 1` in the Track 1 replay; in production `_book_realised` is called once per exit path and the paths are disjoint by branch |
| exit timeout | 120 s, then `FAILED` → `exit_pending` → retry next run. No escalation counter is implemented despite the docstring's "3× consecutive fails" design note (`ibkr_broker.py:722`) — **documented but not built** |
| reconnect mid-run | none. A dropped connection raises `IBKRConnectionError` and the slot fails; the next slot is a fresh process. `reconnect()` + `reconcile_positions()` exist but no production path calls them |
| force-close support | **none.** There is no "close everything now" entry point. The kill switch stops entries only |

---

## G. Recovery and missed-window policy

| scenario | current production behaviour | evidence | desired Track 1 | catch-up valid? |
|---|---|---|---|---|
| machine sleeps | APScheduler's wait timer does not advance while Windows sleeps; every job in the window is missed and later ones pushed back. The heartbeat bounds the wait to 60 s and reports the stall as a number | `run_scheduler.py:325-360` module comment, measured 2026-08-06 | same detection, **plus** a `window_ledger` record so "nobody looked" is distinguishable from "nothing to do" | n/a — detection only |
| scheduler restart mid-day | pre-flight state and max-hold state are restored from disk; `_catch_up_maxhold` runs 09:31's job if it has not run today | `run_scheduler.py:1132` | Track 1 needs its own catch-up decision per sleeve, and for Calm A the answer is **no catch-up** | see below |
| IBKR disconnect | slot fails, `_run` logs the tail, next slot is a fresh process | `run_scheduler.py:481-590` | same | yes for state sleeves |
| missed 09:31 max-hold | caught up at startup; if the scheduler is already up and the slot simply misfired, `misfire_grace_time=300` covers 5 minutes, past that the exit happens at 14:05 — 4 h 40 late | `run_scheduler.py:363`, `:1132` | unchanged (legacy) | yes — the position is already open, later is worse but not wrong |
| **missed 10:00 Calm A** | does not exist today | — | **fail closed. Do not enter late.** Entry is the 10:00 open and exit is the 15:55 open; a 10:20 entry is a different trade at a price that has moved. Set `misfire_grace_time` small (≤ 60 s) and write `window_ledger.window_closed(outcome=incomplete)` | **invalid** |
| **missed 10:35–12:30 Stress slots** | does not exist today | — | the *window* tolerates missed slots (the break can be detected on any later slot inside it) but **must not** enter after 12:30, and must not enter on a bar whose break happened materially earlier. The `window_ledger` `expected_slots=24` contract is what makes "we observed 9 of 24" reportable | partially valid **inside the window only** |
| stale data | pre-flight fail-closed skips the slot; G1 hard-stale blocks entries; E3 blocks entries on >3 d bar skew | §C | same, with BLOCK-3 resolved | n/a |
| no checkpoint | shadow resume logs a WARNING and skips the comparison for that instrument — deliberately not ERROR | `run_live_day.py:~560` | `route_checkpoint` returns a typed `Refusal` with one of seven codes instead of a bare `None` — this is the improvement Stage 1A already delivered | n/a (shadow only) |
| checkpoint mismatch after `--shadow-verify` | the checkpoint is **not advanced**, so the same comparison re-runs tomorrow from the same anchor | `run_live_day.py:~548-560` | same rule | n/a |
| partial order fill | `PARTIAL` is treated as a fill for booking and stop placement; the ordered-vs-filled pair is written to the trade log | `runner.py:2119-2131` | same | n/a |
| stop placement failure | `place_stop` returns `""`, position left with `stop_price` recorded and `stop_order_id=None`; B4 re-places on the next runner construction; B5 shouts at end of run | §C | same | yes — idempotent |
| dashboard unavailable | no effect on trading; `dump_state` failures are logged and swallowed | `runner.py:3290` | same | n/a |

**The general rule for Track 1, and it differs by sleeve:**

* `roska4_swing` and `global_nkd` are **state** models — `diff_desired_vs_held` is idempotent, so a
  missed slot costs entry latency and nothing else. Catch-up is valid.
* `roska4_calm` is a **one-shot event** at 10:00. Catch-up is invalid. The absence of a
  `window_closed` record is the signal, exactly as `window_ledger.status` already implements
  (`"no window_closed record — absence is the signal"`).
* `roska4_stress` is an **event inside a window**. Catch-up is valid within 10:35–12:30 and invalid
  outside it.

---

## H. Telemetry and observability

### What exists

* `slot_telemetry` — wired into both entry points, **off unless `RAITS_TELEMETRY_DIR` is set**.
  Emits one record per slot with `route`, `slot_id`, `pid`, `outcome`, `runtime_s`, `phases`.
  Phases currently instrumented in `run_live_day`: `frozen_check`, `data_load`, `hmm_labels`,
  `setup`, `ibkr_connect`, `runner_init`, `run_day`, plus a `shadow_replay` timer. Outcomes:
  `ok / error / dry_run / print_signals / lock_held / incomplete / skipped_mutex /
  skipped_preflight`.
* `runner_events_*.jsonl` — categories `STATE, SIGNAL, GUARD, EXEC, ORDER, ROLLOVER, RISK, SYSTEM,
  RECONCILE`. No route field.
* `live_state_data.js` — `meta.events` capped at 500, `snapshots` capped at 500
  (`LIVE_SNAPSHOT_LIMIT`, `runner.py:191`).
* `window_ledger` — complete implementation, **zero writers**.

### What is missing before shadow

| need | where it must land | why |
|---|---|---|
| a `route` field on every runner event | `_emit_event` base dict, `runner.py:2645` | without it the operator's one timeline cannot be split, and every existing reader keeps working because a new key is additive |
| `window_ledger.window_open / slot_observed / window_closed` actually called | the Track 1 entry point | this is the only thing that distinguishes "the window produced no signal" from "nobody looked", and it is the single most important new signal for a one-shot sleeve |
| checkpoint refusal reason emitted, not just logged | Track 1 entry point, using `route_checkpoint.Refusal.code` | seven codes already exist; today they would only reach a log line |
| slot runtime for the new windows | `RAITS_TELEMETRY_DIR` set in the scheduler's environment | 10:35–12:30 is 24 slots; without runtime you cannot tell overlap from stall |
| scheduler restarted so parent-side skip records are written | operational | see §0 — the running scheduler predates that code |

### What is additionally required before paper (orders)

| need | where |
|---|---|
| broker order lifecycle events with a route field: submitted / verified-status / partial / cancelled / rejected | a new `ORDER` sub-category, or a `route` + `stage` field on the existing one |
| forced-close lifecycle: `switch_requested → cap_passed → stop_cancelled → close_filled → open_filled` (and every failure branch) | the new `close_then_open` primitive; each step must emit before the next begins, or a crash between two steps is unattributable |
| cap rejection reason at Track 1 granularity — `cap_gross`, `cap_net`, `family_cap`, `same_symbol_suppressed`, `stress_switch_declined` | `rejected_details` already carries `reason`/`detail` (`live_decision.py:~146`); extend the vocabulary |
| rollover status per route | existing `ROLLOVER` events + route field |
| the per-route equity ledger and breaker level in `live_state_data` | a route-scoped state file |

---

## I. Dashboard / monitor contract

The backend never imports the runner; it reads files. That is the property that makes a parallel
route survivable, and it must be preserved.

| reader | reads | expects | breaks on a new route? |
|---|---|---|---|
| `runner_state_reader` | `global_index/live_state_data.js` | starts with `window.LIVE_DATA =`, ends `;`, parses as an object | no — but it reads **one** path, so a Track 1 state file is invisible until a route is added to the API |
| `runner_positions_reader` | `live_positions.json` | `{positions:[…]}` or a bare list; projects an **allow-list** of 10 keys | **an unknown key is silently dropped** — a `route` field on a position would not appear until this list is extended |
| `runner_event_reader` | `global_index/runner_events_YYYYMMDD.jsonl` | every line a dict with `ts`; anything else counts as malformed | **safe** — extra keys pass through untouched, so a `route` field is additive |
| `schedule_status` | `scheduler_*.log` + its own hard-coded slot table (`:167-181`) | slot ids matching `LIVE_DAY_*`, `NKD_NIGHT_*`, `STOP_REPAIR_*`, `MAX_HOLD_EXIT`, `PREFLIGHT` | **yes — this is the one that breaks.** An unmirrored slot becomes an "unexplained overdue" / fake incident. Its own comment says so |
| `job_journal_reader` | `scheduler_*.log` | `_LAUNCH = -m (global_index\|monitor)\.` for a launch line; `_job_type` and `_job_id_from_name` are prefix/name tables | a Track 1 job launched as `python -m global_index.<something>` is recognised as a launch, but `_job_type` returns `"other"` and `_job_id_from_name` returns `None` unless the job's `name=` follows one of the existing patterns |
| `paper_evidence_reader` | `live_state_data.js`, `paper_history.json`, `trade_log.jsonl`, `monitor/paper_inputs.json`, `monitor/paper_pnl_compare.json`, `scheduler_*.log`, `live_day_*.log` | a single-system view of paper evidence | **yes, silently**: Track 1 CLOSE rows in a shared `trade_log.jsonl` would be counted into legacy fill-quality and P&L gates. This is the same failure mode already recorded — a `--dry-run` that wrote `live_day_*.log` created a phantom B3 episode |

### Safe logging plan for Track 1

**Allowed into the existing channels, because every reader tolerates unknown keys:**
* a `route` field on every `runner_events_*.jsonl` record;
* a `route` field on every `trade_log.jsonl` row — **but only together with a reader change**, because
  `paper_evidence_reader` aggregates the whole file and would fold Track 1 rows into legacy gates. If
  the reader cannot be changed in the same step, Track 1 writes its **own** trade log.

**Must go to a new side-channel:**
* slot timing → `slot_timing_*.jsonl` (already route-aware);
* window coverage → `window_coverage_*.jsonl` (already route-aware);
* Track 1 positions, equity, breaker and dashboard state → a route-scoped
  `live_state_data.track1.js` / `live_positions.track1.json`.

**Must not change:**
* the `window.LIVE_DATA = {…};` wrapper and the `meta` / `snapshots` / `runner_health` shape;
* the position projection keys in `runner_positions_reader` (extend, never rename);
* the scheduler log line format `[SLOT_ID] …`, `completed OK`, `thoat OK nhung …`,
  `exited with code N`, `SKIPPED — …` — three readers parse those exact strings, and one of them
  (`schedule_status.CLEAN_EXIT_TOKENS` / `DEBT_EXIT_TOKENS`) already carries a comment about two
  readers holding two copies of the same token set;
* the argv of the legacy `run_live_day` invocation. `_run` logs the command one line above and the
  telemetry identity was deliberately put in the **environment** for exactly this reason
  (`run_scheduler.py:~508`).

**Route-specific dashboard display is not required before shadow.** It **is** required before paper:
without it, a Track 1 order shows up in the operator's one position panel as an unexplained position,
which is the condition B3 exists to make loud.

---

## J. Required implementation sequence

Each step is verifiable on its own and none of them can send an order until step 7.

1. **Restart the scheduler** so the running process matches the code on disk, and set
   `RAITS_TELEMETRY_DIR` in its environment. Collect one clean week of legacy telemetry as the
   comparison baseline. *(Operational, not code.)*
2. **Give `MultiClusterGuard` a `roska4_calm` budget and make the cap set injectable per route.**
   The mechanism already exists (`clusters=` parameter); only the default set is three-cluster.
   Legacy keeps the current defaults byte-for-byte.
3. **Extract `close_then_open` from `_handle_rollover`**, leaving rollover as its first caller.
   No behaviour change; the existing rollover tests are the proof.
4. **Add the `route` field to `_emit_event`** and to `slot_telemetry`'s consumers. Additive only.
5. **Write the Track 1 signal layer** — a sibling of `signal_layer.py`, not a modification of it —
   covering: Normal-R4 filtered (with the SPY short gate), MNKD current, Calm A PCLoc, Stress-MNQ
   `mnq_only_g3_q7`, the same-symbol suppression rules, and the family cap.
6. **Write the Track 1 entry point** (`run_live_day_track1.py` or equivalent) with its own state
   file, lock file, checkpoint (`route_checkpoint`), kill switch and window ledger calls — and a
   hard-coded `--no-orders` default so it physically cannot place one.
7. **Add the Track 1 slots to the scheduler and mirror them in `schedule_status.py` in the same
   change.** 10:00, and 10:35–12:30 every 5 minutes. Add `((10,35),(12,30))` to `_ENTRY_WINDOWS` so
   the 12:20 stop-repair sweep does not land inside the Stress window. Run shadow for a measured
   period.
8. **Only then** decide BLOCK-1 (separate IBKR account) and enable orders.

Steps 2–4 touch production files and are the only ones that do before step 7. Each is additive and
each has an existing test that must stay green.

---

## K. Required tests before any patch

### New tests, per step above

| step | test | what makes it able to go red |
|---|---|---|
| 2 | legacy default cluster set is unchanged | assert the exact three names and their four cap numbers; mutate one → red |
| 2 | a `roska4_calm` candidate no longer raises `KeyError` in `decide_day` | remove the budget → red |
| 3 | `close_then_open` refuses the second leg when the first does not fill | inject a non-`Filled` close → the open must never be placed |
| 3 | rollover behaviour is byte-identical after the extraction | anchor on values measured **before** the refactor, not on the refactored function |
| 4 | every emitted event carries a route | assert the list is non-empty first, then that every record has the key |
| 5 | Track 1 signal layer reproduces the scratch replay **trade for trade, in order** | compare the ordered event list, not counts or sums — `track1_stage2c_book_bootstrap` already establishes that counting lets two different books pass as equal |
| 5 | at most one position per instrument across all four Track 1 sleeves | drive a day where Normal, Calm and Stress all want MNQ |
| 5 | the SPY short gate is causal D-1 | the mutation already used in the three-blockers report: scale SPY close at D by 10 and assert the value at D is unchanged and D+1 moves |
| 6 | Track 1 writes nothing under a legacy path | run it in a tmp cwd and assert `live_positions.json`, `replay_checkpoint.json`, `runner.pid`, `live_state_data.js` are untouched — the `mtime` of each, not just existence |
| 6 | the entry point refuses to send an order without an explicit flag | assert the broker's `send_order` was never called |
| 6 | checkpoint refusal returns a **code**, and every one of the seven codes is reachable | already covered by the Stage 1A suite; extend to the entry point |
| 6 | route isolation of state: two routes writing concurrently do not lose an update | spawn two real processes, not two objects in one process — `_acquire_lock` exempts the same PID on purpose |
| 7 | scheduler slot table and `schedule_status` slot table agree | derive both from one source in the test and assert set equality; adding a slot to one file only → red |
| 7 | a missed 10:00 Calm A slot does **not** enter late | drive the slot 25 minutes late and assert zero entries and a `window_closed` record with `outcome=incomplete` |
| 7 | a missed Stress slot inside the window still enters; one after 12:30 does not | two drives, opposite verdicts |
| 7 | dashboard readers survive Track 1 events | feed a route-tagged event file to `runner_event_reader` and assert `malformed_lines == 0` |

### Tests that must stay green, unchanged

Measured together at this commit: **156 passed, 0 failed, 0 skipped, 6.27 s.**

```
scratch/test_track1_stage2_equivalence_bootstrap_20260822.py
scratch/test_track1_route_checkpoint_stage1_20260822.py
scratch/test_slot_telemetry_20260822.py
global_index/test_slot_overlap.py
global_index/test_log_hygiene.py
global_index/test_scheduler_heartbeat.py
global_index/test_dashboard_live_snapshot.py
global_index/test_scheduler_shadow_verify.py
```

`global_index/test_event_playback.py` was **not** run — it is known to hang.

Command, ready to paste:

```powershell
cd d:\raits
python -m pytest scratch/test_track1_stage2_equivalence_bootstrap_20260822.py scratch/test_track1_route_checkpoint_stage1_20260822.py scratch/test_slot_telemetry_20260822.py global_index/test_slot_overlap.py global_index/test_log_hygiene.py global_index/test_scheduler_heartbeat.py global_index/test_dashboard_live_snapshot.py global_index/test_scheduler_shadow_verify.py -q
```

---

## L. Do-not-touch legacy invariants

Breaking any of these changes legacy behaviour, and each one has a recorded cost.

1. **No `run_live_day` slot between 10:20 and 14:05 ET.** `run_scheduler.py:672`. Stress positions
   are closed by `diff_desired_vs_held` on the next run; a slot in between turned +$12,850 into
   −$450 in the recorded case. The stated wrong fix — adding `_mark_held_unchanged` for stress —
   leaves the position open overnight instead.
2. **The STP deferral window.** Swing and NKD arm their stop at 14:00 in the sleeve's **own**
   timezone on the day after entry (`_ARM_BY_CLUSTER`, `runner.py:144`). Placing at fill measured
   −$10,832 against +$47,166. B4 and B5 must keep asking `_stop_deferred` before calling a position
   naked.
3. **One `clientId` (1) for every process that touches an order.** IBKR accepts a cancel only from
   the placing client. `run_live_day`, `run_maxhold_exit` and `run_stop_repair` all default to 1 and
   all say why in their argparse help.
4. **One shared `runner.pid` across those three entry points.** Separate lock files would let each
   process lock only itself.
5. **The argv of the legacy `run_live_day` invocation stays byte-identical.** Three log readers parse
   it. Anything new travels in the environment.
6. **`configs/final_params.yaml` is sealed.** Do not modify or re-run.
7. **`BACKTEST_CALMAR_FLOOR = 1.65` is not to be copied without its paragraph.** It sits inside the
   noise band of the measurement that produced it (five seeds spread 1.56–1.72, two below the
   floor); a single reading under it is not evidence of degradation.
8. **The pre-flight gate fails closed.** A missing flag means skip, never "assume fresh".
9. **`decide_day`'s ordering — exits, then `start_day`, then entries — is deliberate.**
   `live_decision.py:~110` records the decision (2026-08-08) and the reason: changing it would move
   the brake in the backtest too and invalidate every baseline figure.
10. **`size_multiplier` stays dead.** Wiring the WARN level's 0.5 would change sizing and require
    re-validating WFO and the vault.
11. **Never delete `.parquet` or `data/cache/`.** 2–3 hours to rebuild from Polygon.
12. **`monitor/paper_inputs.json` is human attestation, not data.** The nightly refresh job
    deliberately does not regenerate it, and deliberately does not regenerate the backtest baseline
    either — 21 go-live threshold bands are frozen off that curve.

---

## M. What this audit did NOT establish

Kept separate from the findings above, per the three-label rule.

**Verified (reproduced, with a number):** the 60-job schedule; the 156-test baseline; the absence of
importers for `route_checkpoint`, `route_params` and `window_ledger`; the scheduler process running
code older than the file on disk; the two failing mutations in the Stage 2C log; the absence of an
account parameter on `IBKRBroker`; the absence of a `roska4_calm` budget, arm-time entry and
dashboard cluster key.

**Reasoned from reading the code path, not executed:** every claim about what would happen if a
Track 1 slot ran between 10:20 and 14:05; the `KeyError` path for an unknown cluster in
`decide_day`; the netting behaviour of two routes in one account. These follow from code that was
read end to end, but no run was made to demonstrate them — and this project's own record says a
plausible reading is not a measurement.

**Not examined at all:** `paper_evidence_reader` beyond its input list (3,498 lines);
`session_event_reader`, `open_issue_reader`, `execution_quality_reader`, `entry_time_reader`
internals; the dashboard front-end; `futures/_validated_core.backtest_swing_tf` internals; whether
the Track 1 scratch replay's fill law matches what `send_order` would actually achieve — the
three-blockers report measured both laws offline, but no live-fill comparison exists.

**Deliberately out of scope:** Stage 2C. Its two unproved mutations are a *bootstrap* gate — they
say the resumed Track 1 book's cluster and risk fields have not been shown to change an outcome on
the floor window. That is a different question from the *production wiring* gate this document
answers, and neither substitutes for the other.

---

# ADDENDUM 1 — 2026-08-22, written at the start of Stage 3

Appended, not merged. Nothing above this line was rewritten; where this addendum contradicts an
earlier section, this addendum is the later reading and the earlier text stands as the record of
what was known at the time.

## 1. W5 is superseded — the Stage 2C bootstrap gate is CLOSED

Section A listed **W5**: two mutations (M5, "a carried position in the wrong cluster", and M5b,
"carried position risk ×20") came back MATCH where they had to DIVERGE, so the bootstrap's
`cluster` and `risk` fields were *not proved load-bearing* on the floor window. That reading was
taken from `scratch/track1_breaker_mut4.log` while the mutation run was still in flight.

**W5 is now stale.** Stage 2C has since closed:

* the cut was moved from a calendar day to an **absolute instant** (`cut_instant`). The day-keyed
  cut was not a prefix of the event sequence — a Tokyo-dated MNKD event can carry the next local
  date while occurring earlier than that afternoon's ET events — and on the floor window it left
  two events on 2022-01-10 in neither half, which is what made a resumed book skip a Stress
  override;
* the bootstrap schema now **carries `cut_instant`, and a bootstrap written by the old day-keyed
  cut is refused** rather than silently resumed;
* with the cut fixed, `open_pos`, `equity`, `peak_equity`, `risk`, `day_start_equity` and
  `cluster` are all **proved load-bearing** — each mutation diverges;
* `booked` is confirmed **not an admission input**. It is a double-settlement counter only, so a
  mutation of it correctly matches and that match is a control, not a gap.

The two rows that read FAIL in `mut4.log` were the pre-`cut_instant` behaviour. They do not
describe the current bootstrap.

**Consequence for Stage 2D's conclusions:** none of the four blockers changes. W5 was a warning
about trusting a *resumed* Track 1 book, and that warning is withdrawn. Blockers BLOCK-1 through
BLOCK-4 are untouched by this — they are about the broker account, the schedule invariant, the
data-freshness contract and per-sleeve quantity, and Stage 2C says nothing about any of them.

## 2. What this unblocks, stated narrowly

**The shadow / no-order Track 1 route build may proceed.** That was already Stage 2D's verdict; the
only thing W5 held back was trusting resume, and resume is now gated by a schema that refuses the
old bootstrap.

**Order sending remains blocked, and remains blocked on the same four things.** Nothing in Stage 2C
touched them. Enabling orders requires explicit approval, and before that approval the four
decisions in section A have to be made by the project owner, not inferred by an implementer.

## 3. One correction to the state-artifact table

Section E lists `global_index/paper_history.json`. An earlier existence check in this session
looked for `paper_history.json` at the repository root and reported it missing. The file exists at
the path the table names. The table was right; the throwaway check was looking in the wrong place.
No conclusion in this document depended on it.

## 4. A late finding that Stage 3 must carry forward

The Track 1 route parameters written by the Stage 2B bootstrap
(`scratch/track1_bootstrap_checkpoint_20260822.py`) pin the Normal sleeve as
`ema_period=30, stop_basis=chandelier_atr, stop_multiple=2.5, ratchet=True`. Those are the
**legacy** engine's settings, which is correct for what that bootstrap did — it seeded a checkpoint
from the legacy engine running on parquet.

The Track 1 Normal-R4 sleeve is a different engine: **ema 50, a fixed entry-anchored stop at
2.0 × daily ATR, ratchet off, armed 14:05 the next session**, plus two context filters. So the
existing `replay_checkpoint.track1.json` describes a strategy Track 1 does not run.

This is not a defect — it is the mechanism working. `route_params.params_hash` covers
`ema_period`, `stop_basis`, `stop_multiple`, `stop_anchor`, `ratchet`, the arming pair and the
filter fields, so a Track 1 Normal sleeve asking to resume from that entry gets a
`PARAMS_MISMATCH` refusal naming the setting that moved, rather than a fast wrong answer. Stage 3
must not "fix" this by loosening the identity; it must re-bootstrap under the Track 1 params when
the Track 1 Normal engine is promoted.

---

# ADDENDUM 2 — 2026-08-22, written during Stage 3B

Appended, not merged. This addendum **corrects Addendum 1**, which is left in place as the
record of what was believed at the time.

## 1. Correction — Addendum 1 stated something I had not measured

Addendum 1 said, of Stage 2C:

> "with the cut fixed, `open_pos`, `equity`, `peak_equity`, `risk`, `day_start_equity` and
> `cluster` are all **proved load-bearing** — each mutation diverges"

**I took that from the handoff and did not measure it.** Stage 2C's own artifacts say the
opposite about two of those fields. `scratch/track1_breaker_mutation_mut4.log` and both
`track1_stage2c_breaker_mutation_*.json` files record two rows failing at every cut Stage 2C
tried — the cut at 2022-11-07 and the intraday cut at 2022-01-10:

    M5   one carried position in the wrong cluster      match   (must DIVERGE)
    M5b  carried position risk x20                      match   (must DIVERGE)

Stage 2C reported that honestly, as "NOT PROVED load-bearing on this window". Addendum 1
overwrote an honest "not proved" with an unmeasured "proved". That is the more damaging
direction, and it is the correction that matters here.

## 2. What the measurement actually shows — and it is better news

Measured in Stage 3B with an independent implementation of the resume path, sweeping cuts
rather than picking one:

**Every carried field IS load-bearing. Stage 2C's cuts were the problem, not its fields.**

A carried position's `cluster` and `risk_dollars` are read by exactly one thing: the cap gate,
when a **same-cluster candidate arrives while that position is still open**. Stage 2C placed
its cuts to make the breaker's `peak_equity` bind — a few sessions before the deepest drawdown
— and at those instants no same-cluster candidate followed before the carried position exited.
Measured directly at one such cut: both carried positions had **zero** same-cluster candidates
arrive before they exited. The fields were carried, restored, and never consulted.

With a cut that does consult them, every mutation diverges. Cuts found by sweep, on all three
windows:

| carried field | vault2026 | vault2025 | floor |
|---|---|---|---|
| `cluster` | 2026-01-26 14:30 | 2025-01-21 14:15 | 2018-10-31 14:35 |
| `risk_dollars` | 2026-01-26 14:30 | 2025-02-03 15:25 | 2018-02-22 14:45 |
| `day_start_equity` | 2026-01-26 14:30 | 2025-02-05 14:20 JST | 2018-02-22 14:45 |
| `peak_equity` | any cut carrying anything | " | " |
| `positions` | any cut carrying anything | " | " |
| `equity` | 2026-06-29 14:55 | 2025-05-22 14:20 | any floor cut tested |

`equity` deserves its own line: resetting it to the account base only bites once the book has
**grown** enough that the reset manufactures a drawdown crossing a breaker threshold. At an
early cut the book is still near its base and the reset changes nothing. "Binds at any cut"
was the wrong claim for it too.

The condition is now written down in code — `track1_bootstrap.binding_cuts()` returns the
instants where a carried position's cluster is consulted again — so a future mutation test
picks a cut that can bind instead of hoping an arbitrary one does.

## 3. What this changes about the earlier verdicts

Nothing in Stage 2D's four blockers, and nothing in Stage 3's shadow verdict. The correction
is confined to how the carried state was described.

The useful part is the general shape, and it is worth carrying forward: **"the mutation did
not diverge" is a statement about the experiment before it is a statement about the code.**
Stage 2C said so and was right to; Addendum 1 rounded that off into a claim; Stage 3B measured
it and the field was fine all along. The wrong move at each step would have been to accept
the round-off.
