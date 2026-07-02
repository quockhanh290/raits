# RAITS — Live Futures Pipeline Structure

Last updated: 2026-07-01 (post-runner checkpoint)

---

## Two separate systems

```
D:\raits\raits\          ← equity IS/WFO/OOS system (RAITS proper)
                           BacktestEngine, strategies/, hmm/, risk/
                           STATUS: Vault DONE, params locked in configs/final_params.yaml

D:\raits\futures\        ← futures validated engines (read-only production)
D:\raits\global_index\   ← futures live decision pipeline (evolving)
```

---

## Futures production pipeline (2 tầng)

### Tầng 1 — Validated engines (futures/)

```
futures/
├── _validated_core.py      backtest_swing_tf(), daily_atr_series(), load_parquet()
├── swing_tf.py             SwingTFEngine — desired_basket() + backtest_basket()
├── stress_mid.py           StressMidEngine — entry_signal() + backtest_basket()
├── circuit_breaker.py      CircuitBreaker — daily equity guard
├── basket.py               BASKET dict (MES/MNQ/MYM/M2K specs + point_values)
└── reconcile_nkd.py        Phase 1+2 reconcile script (one-off, keep for audit)
```

**DO NOT MODIFY** — any change invalidates the reconcile chain below.

### Tầng 2 — Live decision pipeline (global_index/)

```
global_index/
├── deploy_sim.py           Reference simulation (offline). replay() + size_combined()
│                           defines the canonical P&L and risk formulas.
│                           real_risk() = n × mult × daily_ATR14.asof(entry_day) × pv
│
├── live_decision.py        Risk brain — decide_day(). Applies cap/priority/circuit-breaker.
│                           replay_via_decision() proven == deploy_sim.replay()
│
├── signal_layer.py         Engine → candidates bridge.
│                           to_candidate(): risk_sized = daily_ATR × mult × pv × n
│                           generate_today_signals(): STATE (swing/NKD) + EVENT (stress)
│                           ROSKA4_MULT = NKD_MULT = 2.5 (matches deploy_sim defaults)
│
├── broker.py               Broker ABC + MockBroker (verify) + Order/Fill dataclasses.
│                           IBKRBroker: NOT YET WRITTEN — needed for paper/live.
│
└── runner.py               FuturesRunner — daily loop: fetch_bars → signal_fn
                            → decide_day → send_order (exits first, then entries).
                            run_history() → (daily_pnl_series, taken/rejected stats)
```

**Constants that must stay in sync across tầng 2:**
- `mult = 2.5` in signal_layer.py (ROSKA4_MULT, NKD_MULT) = `--roska4-mult 2.5 --nkd-mult 2.5` in deploy_sim
- `daily_atr_series` imported from `futures._validated_core` — do not reimplement
- Cluster names: `"roska4_swing"`, `"roska4_stress"`, `"global_nkd"` — must match net_exposure_multi

---

## Reconcile chain (5 tầng — all GREEN)

| # | Script | What it proves | Result |
|---|--------|---------------|--------|
| 1 | futures/reconcile_nkd.py Phase 1 | NKD backtest_swing_tf == harness field-by-field | 496t $0 diff |
| 2 | futures/reconcile_nkd.py Phase 2 | NKD desired_position boundary correct | 496t all OK |
| 3 | raits/data/recon_verify/* (gd0) | MES/MNQ/MYM/M2K swing TF == desired_position | 4×400+ trades OK |
| 4 | raits/data/recon_verify/* (stress) | StressMidEngine 112 Stress days | 46 enter match |
| 5 | (scratchpad) test_runner_vs_deploy_sim.py | FuturesRunner+MockBroker == deploy_sim | $34,731 diff=$0.00 |

**Scratchpad location** (not in repo): `C:\Users\quock\AppData\Local\Temp\claude\d--raits\...\scratchpad\`
Test harnesses were written there — not committed, not at root.

---

## Divergence closed

**Old:** `futures/runner.py` (2-cluster paper-trading runner, pre-global_index architecture)
**New:** `global_index/runner.py` (FuturesRunner, 3-cluster, wires decide_day + broker interface)

Old file archived: `_archive/superseded/futures_runner_2cluster.py`
`futures/runner.py` does NOT exist (verified False).

Note: `raits/live/runner.py` is a separate paper-trading runner for the equity RAITS system —
different domain, not the same as global_index/runner.py.

---

## What's left before paper trading

```
[ ] IBKRBroker(Broker) — implement Broker ABC for IB Gateway 7497 (ib_async)
[ ] Wire generate_today_signals as real signal_fn in FuturesRunner
[ ] Reconcile desired_position() path for swing TF (backtest_basket proven; desired_position is a different call)
[ ] Paper run: FuturesRunner(IBKRBroker(...)) in PAPER_ONLY mode
```

---

## Archive map (futures-related)

```
_archive/superseded/
└── futures_runner_2cluster.py   old 2-cluster runner (pre-global_index)

_archive/scratch/root/           (equity IS scratch — unrelated)
```
