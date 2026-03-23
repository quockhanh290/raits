# raits/backtester/__init__.py
#
# Single-day session replayers for each strategy.
# These are the "car" that the Week 9 strategy engines drive.
#
# Week 10:  orb_session.py     — ORB single-day replay
# Week 12:  vwap_session.py    — VWAP_MR single-day replay  (when built)
# Week 14:  trend_session.py   — Trend single-day replay     (when built)
# Week 18:  full_backtest.py   — all strategies, multi-year  (Phase 1D)
#
# NOTE: These replayers are intentionally simple and bar-by-bar.
# VectorBT Pro (the production backtest engine) will be wired in Phase 1D
# for the WFO run. The replayers here serve two purposes:
#   1. Integration testing (verifying correct next-bar-open entry logic)
#   2. Manual inspection of individual trade setups during development
