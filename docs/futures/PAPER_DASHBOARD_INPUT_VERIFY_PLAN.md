# Paper Dashboard Input Verification Plan

Scope: read-only Paper dashboard evidence. Do not change trading engine files.

1. Verify payload contract
   - `/api/v1/paper-evidence` returns `payload.gates`, `payload.coverage`, `payload.summary`, `payload.gaps`, and `payload.diagnostics`.
   - Every gate and coverage item has `key`, `title`, `status`, `evidence`, `sources`, and `metrics`.

2. Verify each input artifact
   - `global_index/live_state_data.js`
   - `global_index/paper_history.json`
   - `trade_log.jsonl`
   - `slip_stats.json`
   - `live_positions.json`
   - `scheduler_*.log`
   - `live_day_*.log`

3. Verify artifact-to-UI mapping
   - Observed days from `paper_history.json`.
   - Regimes from `trade_log.jsonl`.
   - Exit coverage from `trade_log.jsonl`.
   - C1 OPEN means and N from `trade_log.jsonl` plus tick specs.
   - C1 STP CLOSE means and N only from records with `exit_reason=STP` or `source=B3_STP_EXIT`.
   - Signal/market CLOSE rows are excluded from C1 because the runner does not persist a clean expected close reference; those exits are covered by Paper P&L vs backtest instead.
   - B3/STP/TWS evidence from logs.
   - P&L vs backtest from complete `live_state_data.js` values or reviewed `monitor/paper_inputs.json` daily compare records.
   - Fill quality from `trade_log.jsonl` plus `monitor/paper_inputs.json.fill_quality_spec`.
   - STP placement from `scheduler_*.log`/`live_day_*.log` plus `monitor/paper_inputs.json.stp_placement_spec`.
   - Current protection from `live_positions.json`.
   - Open incidents from `open_issue_reader`.

3a. Verify Fill quality semantics
   - Fill quality requires retained trade history; no history means `MISSING`, not pass.
   - Source: paper-epoch `OPEN`/`CLOSE` records from `trade_log.jsonl`.
   - Metrics: `fills`, `partials`, `partial_rate`, `failed_or_cancelled`, malformed trade-log lines, missing required field rows, and max contracts observed.
   - Status rules:
     - `MISSING`: no paper-epoch fill history.
     - `SPEC_GAP`: `fill_quality_spec` is absent or lacks pass thresholds.
     - `PENDING`: fills exist and have no breach, but `fills < min_fills`.
     - `PASS`: `fills >= min_fills`, failed/cancelled within limit, partial rate within limit, malformed lines are zero, and required fields are complete when enabled.
     - `BREACH`: failed/cancelled exceeds limit, partial rate exceeds limit, malformed lines exist, or required fields are missing when enabled.
   - Current paper sizing is contracts/quantity `1`; Fill quality must be retested before using this evidence for larger size.

3b. Verify STP placement semantics
   - STP placement is not "broker stop immediately after every OPEN" for swing/NKD.
   - Source: paper-epoch `place_stop: accepted`, `STP: place_stop FAILED`, and deliberate defer log lines from `scheduler_*.log` / `live_day_*.log`.
   - Metrics: accepted STP lines, failed STP lines, deliberate deferred lines, placement evidence rows, and the active defer rule.
   - Backtest divergence: validated backtest stop logic first tests a swing/NKD entry on the next day, so same-day/too-early paper/live broker STP would be a stricter live path. Dashboard must show this as expected divergence from immediate-live-stop behavior, not hide it inside a generic pass/fail count.
   - Active defer rule: stop arms 14 hours after the next session boundary in that sleeve's own timezone. `roska4_swing` arms at 14:00 America/New_York and the first normal trading slot is 14:05 ET; `global_nkd` arms at 14:00 Asia/Tokyo; `roska4_stress` is not deferred.
   - Status rules:
     - `MISSING`: no accepted, failed, or deferred STP placement evidence exists in the paper epoch.
     - `SPEC_GAP`: `stp_placement_spec` is absent or lacks `min_accepted`, `max_failed`, or defer-rule confirmation.
     - `PENDING`: placement/defer evidence exists and no failure breached limits, but accepted samples are below `min_accepted`.
     - `PASS`: `accepted >= min_accepted`, failed placements are within limit, and the spec confirms the 14h per-sleeve defer rule.
     - `BREACH`: trade-matched failed placement exceeds limit, or a non-deferred position is missing protection after its arm window. Failed log lines that do not match any paper OPEN trade are shown as unmatched review evidence, not counted as deferred-route failure.

4. Add a complete synthetic fixture test
   - Paper history with multiple days.
   - Trade log with Normal/Stress, OPEN/CLOSE, partial/failed, and STP/MAX_HOLD/CHANDELIER.
   - Live positions with protected/unprotected positions.
   - Logs with B3 match/mismatch, STP accepted/failed, rejection, and roll slippage.
   - Live state with `paper_vs_backtest` and `operational_status`.
   - Assert endpoint returns correct `gates`, `coverage`, and `summary`.

5. Add missing-input tests
   - Missing files must not crash.
   - Statuses become `MISSING`, `SPEC_GAP`, or `NEEDS_DECISION` as appropriate.
   - `diagnostics.*_error` records missing inputs.
   - UI still renders.

5a. Verify C1 scope
   - Active C1 input lives in `monitor/paper_inputs.json`.
   - Required C1 spec: `min_n=100`, `max_mean_ticks=5`, `scope=separate`, `close_scope=stp_only`, `use_absolute=true`.
   - `OPEN` samples use `expected_entry` vs `fill_price`.
   - `STP CLOSE` samples use `expected_stop` vs `fill_price`.
   - Signal/market CLOSE samples with stop-ref-derived `slip` must be counted as excluded, not folded into C1 close mean.
   - Any drift from excluded signal/market CLOSE samples is evaluated by `paper_vs_backtest`.

6. Add malformed-input tests
   - Malformed `trade_log.jsonl`, `paper_history.json`, and `live_state_data.js`.
   - Endpoint still returns valid JSON.
   - Malformed counts/errors appear in diagnostics.

7. Verify frontend render
   - Browser opens `/paper`.
   - Text includes `Paper observability`, `Evidence gaps`, and C1 `More Info`.
   - Main coverage panels appear.
   - No browser page errors.
   - C1 is not `--` when trade-log samples exist.

8. Verify runtime backend
   - After an approved backend restart, `/api/v1/paper-evidence` returns 200.
   - `/paper` returns 200.
   - Paper JS fetches `/api/v1/paper-evidence`.
   - DOM renders all sections.

9. Verify engine boundary
   - Diff is limited to `monitor/backend/*`, `global_index/dash/paper/*`, docs, and tests.
   - No diff in banned engine files.

10. Done criteria
   - Backend tests pass.
   - Paper JS syntax passes.
   - `git diff --check` passes.
   - Browser render passes.
   - Every panel has provenance.
   - Missing/spec gaps do not render as fake PASS.

## Input Audit - 2026-08-13

Current active input file: `monitor/paper_inputs.json`.

Verified and used:

| Input | Status | Evidence | Dashboard use |
| --- | --- | --- | --- |
| `c1_spec` | Present and active | `monitor/paper_inputs.json` has `min_n=100`, `max_mean_ticks=5`, `scope=separate`, `close_scope=stp_only`, `use_absolute=true`; backend source declares `paper_inputs` as operator-maintained JSON. | C1 compares OPEN and STP CLOSE separately, uses absolute mean, excludes signal/market CLOSE. |
| `fill_quality_spec` | Present and active | `monitor/paper_inputs.json` has `min_fills=100`, `max_partial_rate=0`, `max_failed_or_cancelled=0`, complete field checks enabled, and `max_contracts_tested=1`. | Fill quality can become PASS only after enough clean fill history at the tested size; it must be retested before scaling above 1 contract. |
| `stp_placement_spec` | Present and active | `monitor/paper_inputs.json` has `min_accepted=10`, `max_failed=0`, and `require_defer_rule=true`; defer rule documents 14h per-sleeve arm behavior. | Stop placement panel separates accepted/failed STP evidence from expected defer and explicitly shows divergence from immediate-live-stop behavior. |
| C1 OPEN observed samples | Used from artifact, not manual input | `trade_log.jsonl` contains OPEN rows with `expected_entry`, `fill_price`, `slip`; current reader summary: OPEN N=5 since epoch `2026-08-10`, mean `9.0` ticks. | C1 observed OPEN progress and trade details. |
| C1 raw cumulative stats | Used as observed raw context | `slip_stats.json` currently has `open_n=15`, `open_sum=6.9`, `close_n=7`, `close_sum=-1560.2`; reader displays this as cumulative context, not pass/fail evidence. | C1 More Info reconciliation against presented epoch-scoped data. |
| Current stop protection | Used as observed context, not STP pass input | `live_positions.json` has M2K LONG x1, `stop_price=3020.24`, `stop_order_id=288`; reader projects this as `OPEN_POSITION` / `PROTECTED`. | STP Verification trade detail context. |
| Paper duration days | Used from artifact | Reader summary reports epoch `2026-08-10` and 4 observed days: `2026-08-10` to `2026-08-13`. | 60-day progress. |
| Regime coverage | Used from artifact | Reader summary reports regimes `["Normal"]`. | Regime gate progress. |
| Paper P&L vs backtest | Partially present and active | `monitor/paper_inputs.json` has structured `paper_vs_backtest[]` for 2026-08-10..2026-08-12 from `global_index/backtest_curve.json` + `global_index/paper_history.json`; `monitor/paper_pnl_compare.json` audits account-window vs trade-filter conventions. | Paper P&L coverage observed through 2026-08-12; 2026-08-13 remains stale until backtest curve reaches that date. |

Observed but not safe to convert into `paper_inputs.json` automatically:

| Input candidate | Why not used as structured input yet | Evidence found |
| --- | --- | --- |
| `stp_verification[]` | Requires reviewed classification: `verified`, `false_halt`, `double_stp`. Logs show accepted/failed/halt evidence, but not a clean reviewed verdict. | Reader metrics: `stp_accepted=3`, `stp_failed=2`, `stp_verify_lines=0`, `stp_exit_lines=0`, `b3_halt_lines=0` since epoch. Raw scan also found old `scheduler_0810.log` B3/STP failure lines before the active epoch filter. |
| `tws_restart_spec.min_nights` | Present and active | `monitor/paper_inputs.json` has `min_nights=10`. | TWS restart gate target; current status stays PENDING until 10 structured nights are proven. |
| `tws_restart_nights[]` | Requires proof tuple per night: `restart_proven`, `runner_resumed`, `broker_verified`. Current logs provide connectivity/restart candidate lines, not reviewed restart-night proof. | Reader diagnostics: 242 candidate lines across `2026-08-10`, `2026-08-11`, `2026-08-12`, `2026-08-13`; `restart_nights=0`, required `10`. |
| `manual_interventions[]` | Requires operator-reviewed action, reason, resolution status, and post-action verification. Raw logs only expose candidates. | Reader diagnostics: 128 candidate lines on `2026-08-10`; no structured ledger. |
| `roll_slippage[]` | Requires reviewed roll event slippage. Raw C2 lines found are failure/halt style lines, not clean slippage evidence. | Raw scan found roll/C2 candidate lines mostly in `scheduler_0810.log`; reader gate remains missing/no usable structured records. |
| `paper_vs_backtest[]` current day | Requires complete daily compare: `date`, `actual_equity`, `expected_equity`, evidence. Live state currently has actual-only context for 2026-08-13 because backtest curve is stale through 2026-08-12. | Reader uses structured records through 2026-08-12; do not add 2026-08-13 until `global_index/backtest_curve.json` covers it. |

Need build / decide next:

| Gap | Needed input | Build target |
| --- | --- | --- |
| TWS restart proof records | Per night: restart happened, runner resumed, broker truth verified, evidence path/line. | Monitoring/operator input workflow; no engine edit required if entered manually. |
| STP false-halt verification | Per reviewed event/date: `verified`, `false_halt`, `double_stp`, evidence path/line. | Monitoring/operator input workflow; no engine edit required if entered manually. |
| Manual intervention ledger | Per action: timestamp, reason, action, resolution status, post-action verification, evidence. | Monitoring/operator input workflow; no engine edit required if entered manually. |
| Paper P&L vs backtest | Daily `actual_equity` + `expected_equity` compare and evidence path. | Add structured `paper_vs_backtest[]` records to `monitor/paper_inputs.json` or make `live_state_data.js` emit a complete expected value. |
