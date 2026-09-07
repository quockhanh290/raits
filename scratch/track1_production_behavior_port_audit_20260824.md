# Track1 production behavior port audit - 2026-08-24

Read-only audit. I did not start/stop scheduler or backend, did not connect IBKR, did not send orders, did not create `track1_go_live_confirmation.json`, did not set `TRACK1_ORDERS_APPROVED`, and did not commit. The only writes are this report and the JSON summary requested beside it.

## Executive verdict

Track1 has been ported far enough for **track1-only shadow observation**, not far enough to enable paper/live orders.

The main blocker is still **B1: one IB Gateway login is one account-level position book**. This cannot be solved with route-scoped files: `IBKRBroker` has no account selector and `get_positions()` / `get_equity()` read the account/session net state. Track1 can either become the sole route after legacy is flat/retired, or use a separate confirmed IBKR account.

The second order-enabling blocker is **broker-required evidence**. The code has real broker paths for data, orders, stop placement, cancel-before-close, partial fills, timeouts, rollover, and route-scoped safety, but this audit did not and must not inspect the live broker. Anything depending on current IBKR positions, open orders, contract details, order permissions, or live feed behavior is **UNKNOWN_BROKER_REQUIRED**, not PASS.

## Classification

### 1. Already ported and tested

Scheduler/job inventory:
- Default/transitional/track1-only modes are explicit in `make_scheduler`; `track1_only` implies `track1_shadow`, removes legacy strategy jobs, keeps shared infra and legacy drain safety, and registers Track1 safety jobs. Evidence: `global_index/run_scheduler.py:642`, `global_index/run_scheduler.py:674`, `global_index/run_scheduler.py:1053`, `global_index/run_scheduler.py:1356`, `global_index/run_scheduler.py:1406`.
- Track1 owns 70 strategy slots: Calm 1, Stress 24, Normal-R4 23, NKD 22. Evidence: `global_index/track1_slots.py:112`, `global_index/track1_slots.py:125`, `global_index/track1_slots.py:144`, `global_index/track1_slots.py:166`, `scratch/track1_stage5p_full_four_sleeve_shadow_readiness_20260824.md:28`.
- Track1 safety is route-scoped in track1-only: `live_positions.track1.json`, `STOP_TRADING.track1`, `runner.track1.pid`, `maxhold_state.track1.json`, clientId 90. Evidence: `global_index/track1_slots.py:216`, `global_index/track1_slots.py:237`, `global_index/run_scheduler.py:1368`.
- Shared infra classification exists for preflight, heartbeat, and session-report fallback. Evidence: `global_index/track1_slots.py:415`, `global_index/run_scheduler.py:682`, `global_index/run_scheduler.py:830`, `global_index/run_scheduler.py:1322`.
- Heartbeat/stall detection and slot mutex/stuck reporting exist. Evidence: `global_index/run_scheduler.py:232`, `global_index/run_scheduler.py:348`, `global_index/run_scheduler.py:384`.
- Preflight state is persisted and Track1 reads the file. Evidence: `global_index/run_scheduler.py:203`, `global_index/run_scheduler.py:443`, `global_index/run_scheduler.py:510`, `global_index/track1_freshness.py:180`.

Strategy execution:
- All four sleeve generators are represented as computed-from-bars and marked live-ready in the code registry. Evidence: `global_index/track1_live_sleeves.py:42`, `global_index/track1_live_sleeves.py:60`, `global_index/track1_live_sleeves.py:83`, `global_index/track1_live_sleeves.py:113`, `global_index/track1_live_sleeves.py:138`.
- Slot windows are derived from `WINDOWS_ET`, not hand-copied. Evidence: `global_index/track1_slots.py:112`, `global_index/track1_slots.py:144`.
- First-signal and missed-slot semantics are encoded: Calm is one-shot; Stress/Normal/NKD are windows where the first admitted signal wins. Evidence: `global_index/track1_signal_layer.py:221`, `global_index/track1_signal_layer.py:224`, `global_index/track1_signal_layer.py:229`, `global_index/track1_normal_r4.py:441`.
- Checkpoint/resume uses route-scoped schema-2 checkpoint and refuses params mismatch. Evidence: `global_index/run_live_day_track1.py:250`, `global_index/run_live_day_track1.py:524`, `global_index/route_checkpoint.py`.
- Fill-law identity is centralized through `track1_params.LIVE_FILL_LAW`, not an engine default. Evidence: `global_index/run_live_day_track1.py:1025`.

Data/freshness:
- Track1 freshness explicitly models the before/after 13:45 contract through `required_data_through`. Evidence: `global_index/track1_freshness.py:103`, `global_index/track1_freshness.py:227`.
- SPY CSV update verifies HMM label stability after updating. Evidence: `global_index/update_spy_csv.py:72`, `global_index/update_spy_csv.py:126`.
- Live frame splice guard and NKD Tokyo-clock handling are ported in the live source adapter. Evidence: `global_index/track1_live_source.py:1`, `global_index/track1_live_source.py:131`, `global_index/track1_live_source.py:207`, `global_index/track1_live_source.py:326`.

State/files/dashboard:
- Track1 entrypoint declares route-scoped paths and legacy paths it must not write. Evidence: `global_index/run_live_day_track1.py:88`, `global_index/run_live_day_track1.py:120`.
- `NoOrderBroker` shadow path raises if a send/cancel call is reached. Evidence: `global_index/run_live_day_track1.py:201`.
- Dashboard backend has `/api/v1/track1-runtime` and labels legacy book as drain. Evidence: `monitor/backend/app.py:227`, `monitor/backend/app.py:238`, `monitor/backend/track1_runtime_reader.py:35`, `global_index/dash/realtime/realtime.js:1029`.
- Schedule-status health table drops legacy strategy slots in track1-only and counts Track1 health slots. Evidence: `monitor/backend/schedule_status.py:328`, `monitor/backend/schedule_status.py:367`.
- Shadow acceptance audit exists as a module and script, with `NOT_ENOUGH_DATA_YET` vs pass/fail semantics. Evidence: `global_index/track1_shadow_acceptance.py:1`, `global_index/track1_shadow_acceptance.py:122`, `global_index/track1_shadow_acceptance.py:253`, `scratch/track1_shadow_audit_20260824.py:55`.

Safety/risk:
- Track1 admission layer has caps, family cap, same-symbol suppression, and force-close/switch accounting. Evidence: `global_index/track1_signal_layer.py:15`, `global_index/track1_signal_layer.py:254`, `global_index/track1_signal_layer.py:391`, `global_index/track1_signal_layer.py:412`.
- Runner has stop placement/repair, deferred stop semantics, B3/B4/B5 broker/file reconciliation, fat-finger cap, circuit breaker and persisted state. Evidence: `global_index/runner.py:322`, `global_index/runner.py:477`, `global_index/runner.py:651`, `global_index/runner.py:841`, `global_index/runner.py:2052`, `global_index/runner.py:2457`.
- Stop repair and max-hold entrypoints accept route-scoped positions/stop/lock/client-id arguments. Evidence: `global_index/run_stop_repair.py:113`, `global_index/run_maxhold_exit.py:51`.

### 2. Ported but not tested on real IBKR feed

- `IBKRBarProvider` reuses `IBKRBroker.fetch_bars`, but the module itself says the real broker path had not been executed in that stage. Evidence: `global_index/track1_live_source.py:93`, `global_index/track1_live_source.py:131`.
- `build_bar_provider("ibkr")` connects with clientId 89 for data; track1-only scheduler uses `ibkr` providers. This is wired, but requires a real feed day to validate pacing, bar completeness, and disconnect behavior. Evidence: `global_index/track1_live_source.py:275`, `global_index/track1_slots.py:42`, `global_index/track1_slots.py:57`.
- Rollover is implemented and offline-testable, but `_handle_rollover` itself marks first real paper roll verification as pending. Evidence: `global_index/ibkr_broker.py:1593`, `global_index/ibkr_broker.py:1616`.
- Route-scoped Track1 safety jobs are wired, but not measured against live Gateway while a Track1 position exists. Evidence: `scratch/track1_stage5o_route_aware_safety_20260824.md:131`.

### 3. Not ported but not needed in Track1

- Legacy strategy entry jobs are not needed in track1-only. They are intentionally removed by `legacy_retirement_candidates`; legacy safety remains only as a drain for `live_positions.json`. Evidence: `global_index/track1_slots.py:445`, `global_index/run_scheduler.py:1356`.
- `STOP_TRADING` root switch is not the Track1 kill switch. Track1 reads `STOP_TRADING.track1`; root `STOP_TRADING` remains legacy/drain policy. Evidence: `global_index/run_live_day_track1.py:93`, `global_index/track1_slots.py:237`.
- Legacy `live_state_data.js` / `paper_history.json` are not Track1 state sinks during shadow. Track1 runtime goes under `global_index/track1_runtime/`. Evidence: `global_index/run_live_day_track1.py:105`, `monitor/backend/track1_runtime_reader.py:12`.

### 4. Not ported and blocking paper/live

None found as a pure code-port gap after Stage 5O/5P, except the order-gate decision itself. The blocking items are not "missing Track1 modules"; they are:
- account-level B1 confirmation/retirement not resolved;
- live broker/feed evidence not collected;
- shadow acceptance period not yet passed end-to-end with real Track1 runtime evidence;
- confirmation/order-arming artifacts deliberately absent.

### 5. Account-level behavior that cannot be route-scoped

- IBKR positions and equity are account/session-level. Two route books can be separate files, but IBKR returns one net position per contract. Evidence: `global_index/track1_gates.py:195`, `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md:17`.
- Broker-flat, orphan working STP detection, open order inventory, and actual account order permissions require a broker query. This audit did not perform it, so all are **UNKNOWN_BROKER_REQUIRED**.
- Circuit breaker / drawdown is account-level in effect even if route state is file-scoped; both routes on one account would share real losses and net exposure.

## Blocker table

| id | severity | production behavior | legacy implementation | Track1 implementation | evidence/source file | status | required fix/test |
|---|---:|---|---|---|---|---|---|
| B1 | CRITICAL | One IB login/account is one net position book | Legacy uses unfiltered IBKR account positions/equity | Track1 has route files but same IBKR account would still net positions | `global_index/track1_gates.py:195`, `docs/futures/TRACK1_SWITCHOVER_RUNBOOK.md:17` | BLOCKING_PAPER_LIVE | Retire legacy and verify broker-flat, or confirm dedicated Track1 account; then create valid confirmation file outside this audit |
| B2 | HIGH | Real live bar feed must produce causal complete frames | Legacy fetches via `IBKRBroker.fetch_bars` | Track1 provider wraps same broker and splice guard | `global_index/track1_live_source.py:131`, `global_index/track1_live_source.py:275` | UNKNOWN_BROKER_REQUIRED | Run track1-only shadow with IBKR feed; acceptance audit must pass |
| B3 | HIGH | Real broker order path readiness | Legacy `FuturesRunner` + `IBKRBroker.send_order` handles fills/timeouts | Track1 order gate can arm only after B1 + env + confirmation, but real path has not been exercised by Track1 | `global_index/run_live_day_track1.py:136`, `global_index/ibkr_broker.py:698` | BLOCKING_PAPER_LIVE | After B1 and shadow pass, run tightly scoped paper arming test; verify no `NoOrderBroker` and real broker fill lifecycle |
| B4 | HIGH | Close-confirm-open switch/force-close | Legacy runner has close/open and failure branches | Track1 admission can force-close in shadow; live valuer refuses without broker | `global_index/track1_signal_layer.py:391`, `global_index/track1_live_source.py:1035` | UNKNOWN_BROKER_REQUIRED | Paper test same-symbol/switch case or injected broker test under Track1 live mode |
| B5 | HIGH | Stop placement, repair, and cancel before close | Legacy stop repair/maxhold use `live_positions.json`, clientId 1 | Track1 safety uses route book, lock, stop switch, clientId 90 in track1-only | `global_index/track1_slots.py:216`, `global_index/run_scheduler.py:1368` | PORTED_NOT_LIVE_TESTED | Create controlled Track1 paper position, verify stop placed/repaired/cancelled on correct client and contract |
| B6 | HIGH | Rollover close/open/migrate position and stop | Legacy broker has `ROLL_SCHEDULE`, `_handle_rollover`, contract_month | Track1 would reuse same broker/runner primitives through real broker path | `global_index/ibkr_broker.py:197`, `global_index/ibkr_broker.py:1593`, `global_index/runner.py:1403` | UNKNOWN_BROKER_REQUIRED | Before paper/live across roll date, verify contract details/front month and run simulated or paper roll drill |
| B7 | MEDIUM | Post-window audit | Manual script/module exists | Not scheduled as 16:10 ET job | `global_index/track1_shadow_acceptance.py:253`, `scratch/track1_shadow_audit_20260824.py:55` | NOT_BLOCKING_SHADOW; RECOMMENDED_BEFORE_PAPER | Promote result writer under `global_index/track1_runtime/audits/` and optionally schedule 16:10 ET post-window audit |
| B8 | MEDIUM | Dashboard latest audit verdict | Track1 runtime endpoint exists | No first-class latest audit verdict integration found | `monitor/backend/track1_runtime_reader.py:159`, `global_index/dash/realtime/realtime.js:941` | GAP_OBSERVABILITY | Add reader for latest acceptance audit JSON and render verdict in Track1 panel |
| B9 | MEDIUM | Trade log / paper evidence route split | Legacy paper readers aggregate `trade_log.jsonl` | Track1 policy says separate trade log until readers split on route | `global_index/track1_slots.py:261`, `monitor/backend/paper_evidence_reader.py:240` | BLOCKING_IF_TRACK1_WRITES_SHARED_TRADE_LOG | Keep separate Track1 trade log or make paper readers route-aware before paper orders |
| B10 | MEDIUM | Broker-flat / orphan STP clean state before arming | Legacy tools/readers can inspect broker when connected | Track1 audit cannot infer broker cleanliness from files | `global_index/check_open_orders.py:216`, `global_index/ibkr_broker.py:1410` | UNKNOWN_BROKER_REQUIRED | Read-only IBKR inspection immediately before arming; require flat legacy account or no orphan stops |

## Required scope audit notes

Scheduler/job inventory:
- Default mode remains legacy-only; transitional adds Track1 slots; track1-only removes legacy strategy slots while keeping shared infra and safety/drain. Current track1-only count is 95 total jobs per Stage 5P: 70 strategy + 11 Track1 safety + 11 legacy drain safety + 3 shared infra.
- A 16:10 ET post-window audit job is not required to keep orders blocked, but is recommended before paper/live so daily evidence is written automatically and shown on dashboard.

Strategy execution:
- Calm A, Stress-MNQ, Normal-R4, NKD/MNKD are ported as computed-from-bars.
- Live-source is wired but needs real IBKR evidence. Replay-source cannot prove live feed behavior.
- Checkpoint/resume is ported; acceptance audit records checkpoint identity as `not_checked_here`, so identity verification should be run separately with frames.

Data/freshness:
- Preflight `required_data_through` handles pre/post 13:45. Before 13:45 it expects the previous completed preflight; after 13:45 it expects today's.
- Stale data gates are fail-closed. HMM label lag is represented through causal labels / lag-1 for NKD.

Order/execution:
- Orders remain blocked by B1, confirmation schema, and `TRACK1_ORDERS_APPROVED`.
- Shadow `NoOrderBroker` proves no orders were attempted; it does not prove real broker readiness.
- Partial fill and timeout handling exist in broker/runner, but must be classified broker-required for Track1 paper/live.

Positions/state:
- Track1 state is route-scoped. I found no intended Track1 writes to legacy state in the entrypoint.
- `scratch/track1_shadow/` is replay research output; operational shadow evidence is under `global_index/track1_runtime/`, which is the right durable path.

Safety/risk:
- Stop repair, max-hold, route kill switch, family cap, same-symbol suppression, fat-finger cap, net exposure guard, and broker/file reconcile exist.
- Broker-flat, orphan working stop detection, and actual stop repair after rollover cannot be passed without IBKR inspection.

Contract rollover:
- Track1 uses the existing broker/runner rollover mechanism if/when it uses the real broker path.
- Current/front month logic exists and includes MNK/MNKD mapping.
- Safety repair after rollover is implemented through `contract_month`-aware stop placement and `unprotected_positions`, but still needs a live roll drill before paper/live across a roll date.
- If rollover remains untested on the real paper account, it is not a code-port blocker for starting a non-roll shadow day, but it is a paper/live blocker before holding through a roll boundary.

Dashboard/monitor:
- `/api/v1/schedule-status` and `/api/v1/track1-runtime` are route-aware enough for track1-only shadow.
- Legacy/drain labels are present in backend/frontend.
- Latest acceptance audit verdict is not first-class yet; add it before paper/live.

Acceptance/audit automation:
- Current manual script: `scratch/track1_shadow_audit_20260824.py`.
- Core judge: `global_index/track1_shadow_acceptance.py`.
- Recommended promotion: write audit result JSON to `global_index/track1_runtime/audits/track1_shadow_audit_<YYYYMMDD>.json`, expose latest in `/api/v1/track1-runtime`, and optionally schedule a 16:10 ET post-window audit.
- Behavior when not enough data exists is correct: `NOT_ENOUGH_DATA_YET`, not fail.

## Recommended next-stage plan

1. **5Q - Shadow acceptance day(s), no restart unless already running wrong mode.**
   Keep track1-only shadow running. Do not arm orders. After windows close, run the read-only acceptance audit and save verdict under `global_index/track1_runtime/audits/`.

2. **5R - Dashboard audit verdict integration, backend-only restart if needed.**
   Add latest audit display to `/api/v1/track1-runtime` and realtime frontend. This can be done while shadow keeps running; only backend restart is needed to serve the new endpoint shape.

3. **5S - Broker read-only clearance.**
   With explicit permission, inspect IBKR: legacy broker-flat, no orphan working STPs, no unexpected open orders, contract details/front months for MES/MNQ/MYM/M2K/MNK. This blocks paper/live.

4. **5T - B1 resolution.**
   Choose and record either legacy retired or separate account confirmed. This requires operator decision and valid confirmation schema. It blocks paper/live.

5. **5U - Paper order arming drill.**
   Only after 5Q/5S/5T pass: set confirmation + env in a controlled session, allow one minimal paper order path, verify fill, state persist, stop placement, cancel-before-close, and dashboard route separation.

6. **5V - Rollover drill before holding across roll.**
   If paper/live could hold through a roll date, perform a paper/simulated rollover drill first. This blocks holding live positions across contract changes.
