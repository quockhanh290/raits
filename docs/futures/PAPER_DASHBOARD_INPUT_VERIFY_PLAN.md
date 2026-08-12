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
   - C1 means and N from `trade_log.jsonl` plus tick specs.
   - B3/STP/TWS evidence from logs.
   - P&L vs backtest from `live_state_data.js`.
   - Fill quality from `trade_log.jsonl`.
   - Current protection from `live_positions.json`.
   - Open incidents from `open_issue_reader`.

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

6. Add malformed-input tests
   - Malformed `trade_log.jsonl`, `paper_history.json`, and `live_state_data.js`.
   - Endpoint still returns valid JSON.
   - Malformed counts/errors appear in diagnostics.

7. Verify frontend render
   - Browser opens `/paper`.
   - Text includes `Evidence ledger` and `Paper observability`.
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
