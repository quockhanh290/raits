# Task 2 Report: DecisionUnit

## Files Created
- `d:\raits\raits\decision\decision_unit.py` (1293 lines)

## Import Test Result
```
python -c "from raits.decision.decision_unit import DecisionUnit; print('OK')"
OK
```
(Run from `d:\raits` project root; also works with `d:/raits` on sys.path.)

## Commit Hash
`6eec11f` — feat: implement DecisionUnit — extracts per-bar decision orchestration from BacktestEngine

## Deviations from Plan

1. **VWAP F2 filter (8. VWAP MR section):** The plan used `ctx.spy_history` (list of pd.Series) to construct a DataFrame via `pd.DataFrame(_spy_pre)`. Per the task instructions, replaced with `ctx.day_stocks.get("SPY") or ctx.stress_stocks.get("SPY")` to get a proper DataFrame, then slice with `.loc[index <= bar_ts]`. This matches how the engine does it using `day_spy.loc[:bar_ts]`.

2. **GAP_FILL and GF_SHORT SPY VWAP checks (sections 8b and 8c):** The plan used `ctx.spy_history` list → DataFrame conversion. Applied the same fix: use `ctx.day_stocks.get("SPY") or ctx.stress_stocks.get("SPY")` as the primary source, with a fallback to `ctx.spy_history` list if SPY is not in those dicts. The engine uses `day_spy.loc[:bar_ts]` (a DataFrame slice) directly.

3. **File location discovery:** The `raits` package root is `d:\raits\raits\` (not `d:\raits\raits\raits\`). The `raits/decision/` subpackage is at `d:\raits\raits\decision\` alongside `raits/backtest/`, `raits/hmm/`, etc. Initial write went to wrong path; corrected by moving the file.

## Confirm engine.py Untouched
```
git diff HEAD raits/backtest/engine.py
(no output — zero changes)
```
