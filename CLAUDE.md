# RAITS — Claude Working Guide

**Project:** Regime-Adaptive Intraday Trading System  
**Language:** Python 3.10+  
**Root:** `d:\raits\` — package is `raits/` (installed editable via `pyproject.toml`)

---

## Architecture

```
raits/
├── hmm/             # HMM regime detection (Calm / Normal / Stress / Crisis)
│   ├── engine.py    # GaussianHMM wrapper, 4-state, weekly retraining
│   ├── features.py  # Feature matrix builder
│   ├── state_sorting.py   # Label-switching safeguard
│   ├── retraining.py
│   └── volatility_override.py
│
├── strategies/      # One class per strategy
│   ├── orb.py           # Opening Range Breakout (9:35–10:15 ET)
│   ├── vwap_mr.py        # VWAP Mean Reversion (10:15–14:00 ET)
│   ├── trend_follow.py   # Trend Follow (14:00–15:55 ET)
│   ├── cash_defense.py   # Cash Defense (Stress/Crisis regime)
│   └── universe_scanner.py
│
├── coordinator/     # Regime state machine
│   ├── regime_coordinator.py   # Precedence: VolOverride > HMM > Manual
│   ├── strategy_router.py
│   └── conflict_resolver.py
│
├── backtest/        # Walk-Forward Optimization engine
│   ├── engine.py    # BacktestEngine — wired to real module interfaces
│   ├── wfo.py       # Rolling 3-yr train / 1-yr test windows
│   ├── wfo_grid.py  # 48-combo grid (orb_range × bb_std × ema_period)
│   ├── metrics.py
│   ├── data_types.py
│   ├── equity_tracker.py
│   └── trade_log.py
│
├── data/            # Polygon.io fetcher + local cache
│   ├── raits_polygon_fetcher.py   # Converts UTC ms → ET naive datetimes
│   ├── raits_data_cache.py        # Parquet cache (24-hour TTL)
│   ├── raits_data_pipeline.py
│   ├── raits_data_models.py
│   └── raits_mock_data.py
│
├── risk/            # Risk management
│   ├── circuit_breakers.py   # Daily -4% or 5 consecutive losses → SHUTDOWN
│   ├── pdt_guard.py
│   ├── position_sizer.py
│   └── portfolio.py
│
└── raits/scripts/   # Runnable scripts
    ├── wfo_real_run.py          # Full 10-year WFO (Polygon.io + Parquet cache)
    ├── per_strategy_diagnostic.py
    ├── window_debug.py          # --use-results-cache flag (see below)
    ├── hmm_regime_diagnostic.py
    └── fetch_daily_data.py
```

**Top-level utilities** (root `d:\raits\`): `diagnose_*.py`, `inspect_wfo.py`, `hmm_validate.py` — one-off diagnostic scripts, not package code.

---

## Stack

| Purpose | Library |
|---|---|
| Regime detection | `hmmlearn` (GaussianHMM) |
| Backtesting | `vectorbt` |
| Market data | `polygon-api-client` |
| Analytics | `quantstats` |
| Data | `numpy`, `pandas`, `scipy` |
| Testing | `pytest`, `hypothesis` |

---

## Key Conventions

**HMM state is passed in, never fetched.** Every strategy's `generate_signal()` receives `hmm_state` as a plain string (`"Calm"/"Normal"/"Stress"`). Strategies do NOT import HMMEngine. Only the RegimeCoordinator/router touches the HMM directly. This keeps strategies testable in isolation.

**Timestamps are ET naive datetimes.** Polygon.io returns UTC milliseconds. `raits_polygon_fetcher.py` converts them to `US/Eastern` naive datetimes immediately on ingestion. All time constants in the engine (9:30, 9:35, 15:55) are ET with no offset math.

**Config lives in `configs/`.**
- `configs/final_params.yaml` — production WFO params (locked during Vault test, DO NOT modify)
- `configs/wfo_report.json` — full WFO audit trail
- `config_private.py` — Polygon.io API key (gitignored, never commit)

**Three WFO hyperparameters only** (Blueprint §7.1): `orb_range_minutes`, `vwap_bb_std`, `ema_period`. Everything else is fixed. Grid = 4 × 4 × 3 = 48 combinations. Aggregation method: arithmetic mean.

**Blueprint references** are scattered throughout code comments (e.g. "Section 4.2", "§6.3"). These refer to the project design document — they define the behavioral spec, not the code structure.

**`--use-results-cache`** (window_debug.py): only valid when engine/strategy code is unchanged. Drop this flag whenever any backtest logic has been modified.

---

## Regime State Machine

States (coordinator): `ACTIVE` → `OVERRIDE_STRESS` → `COOLDOWN` → `SAFETY_MODE` → `SHUTDOWN`

Precedence hierarchy:
1. Volatility Override (real-time crash detection, 20-min min hold)
2. HMM State (weekly retrained)
3. Manual Override (not implemented)

Regime → active strategies:
- **Calm**: VWAP_MR, FADE
- **Normal**: ORB, TREND_FOLLOW, FADE
- **Stress**: TREND_FOLLOW only
- **Crisis**: none

---

## Running Scripts

Scripts expect to run from the `raits/raits/` directory (or with the project root on `sys.path`):

```powershell
# Full WFO run (~2-3 hours first run, <5 min cached)
cd d:\raits\raits
python raits\scripts\wfo_real_run.py

# Strategy diagnostics
python raits\scripts\per_strategy_diagnostic.py
python raits\scripts\window_debug.py

# HMM health check
python raits\scripts\hmm_regime_diagnostic.py
```

Data cache (Parquet) lives at `raits/data/cache/`. Models at `models/`.

---

## Anti-patterns to Avoid

- **Do not suggest changing WFO hyperparameters** (`orb_range_minutes`, `vwap_bb_std`, `ema_period`) based on observed backtest results — that is curve fitting. Let WFO decide. Only fix entry/exit logic and structural risk parameters.
- **Do not read entire files** when a specific function is the target — use partial reads.
- **Do not modify `configs/final_params.yaml`** during or after the Vault test period.
- **Do not commit `config_private.py`** — it contains the Polygon.io API key.

---

# Session & Context Management

## Rules (always follow, no exceptions)

At the **START** of every session:
1. Check if `TASK.md` exists in project root
2. If yes → read it, summarize status in 3-5 lines, then proceed
3. If no → ask: "No TASK.md found. What are we working on today?"

**During** the session:
- After completing each sub-task, update `TASK.md` immediately
- If you discover a gotcha, workaround, or key decision → append to `SCRATCHPAD.md`
- Never let more than ~20 turns pass without offering: "Context is getting long — want me to update TASK.md and clear?"

At the **END** of every session (when user says "done", "stop", "wrap up", "end session"):
1. Update `TASK.md` with completed items, current status, and next steps
2. Move any new gotchas/decisions to `SCRATCHPAD.md`
3. Confirm: "TASK.md updated. Safe to /clear or close session."

---

## TASK.md format

```
## Task: [name]
Status: IN PROGRESS | BLOCKED | DONE

### Completed
- [x] item

### In progress
- [ ] item — current state, edge cases

### Next steps
- [ ] item

### Key decisions
- decision and rationale

### Files touched
file1, file2
```

---

## SCRATCHPAD.md format

```
## Gotchas
- issue and fix

## Rejected approaches
- approach — why rejected

## Open questions
- question
```

---

## Token discipline

- Only read files explicitly needed for the current sub-task
- When asked to investigate a bug, read the specific file/function first before exploring broadly
- Prefer partial reads (limit to relevant lines) over full file reads
- If context feels heavy, say so and suggest /clear after updating TASK.md
