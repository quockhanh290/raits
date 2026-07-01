# raits/ — STOCK ENGINE (PRODUCTION)

The main RAITS equity backtesting package (installed editable via `pyproject.toml`).

**Status:** PRODUCTION — locked WFO params (`configs/final_params.yaml`: orb=20/bb=1.5/ema=30). Vault OOS 2023-2024 passed.

Key sub-packages:
- `hmm/` — regime detection (shared core; also used by futures/)
- `strategies/` — ORB, VWAP_MR, TREND_FOLLOW, CASH_DEFENSE
- `backtest/` — BacktestEngine + WFO
- `data/` — Polygon.io fetcher + Parquet cache

Do NOT modify `configs/final_params.yaml` — sealed post-vault.
