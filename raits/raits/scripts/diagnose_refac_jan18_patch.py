"""
Monkey-patch REFAC engine to trace exactly what decide() does at 2019-01-18 14:00.

Captures:
  - trading_allowed (coordinator state)
  - active strategies
  - coordinator.effective_hmm_state
  - entries/exits returned by decide()
  - pending_entries at CVX check time (_position_ok intercept)

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_refac_jan18_patch.py
"""
import sys, os, pickle, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import yaml

from raits.backtest.data_types import BacktestConfig
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.strategies.universe_scanner import CANDIDATE_POOL

UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1 = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2 = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
PE_EXPANSION = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C", "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP", "CAT", "DE", "BA", "GE", "PYPL", "PANW", "NOW",
]
SECTOR_ETFS = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS = (
    ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION
)

PICKLE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "final_params.yaml")

with open(_PARAMS_PATH) as _f:
    _params = yaml.safe_load(_f)

TARGET_TS  = pd.Timestamp("2019-01-18 14:00:00")
JAN18_DATE = pd.Timestamp("2019-01-18").date()
SHORT_END  = "2019-01-25"


def make_config() -> BacktestConfig:
    return BacktestConfig(
        account_equity=50_000.0,
        start_date="2017-01-03",
        end_date=SHORT_END,
        universe=UNIVERSE + PHASE1 + PHASE2,
        orb_universe=list(CANDIDATE_POOL),
        vwap_universe=["SPY", "QQQ", "IWM"],
        orb_range_minutes=_params["orb_range_minutes"],
        vwap_bb_std=_params["vwap_bb_std"],
        ema_period=_params["ema_period"],
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
        enable_costs=True,
        enable_pdt_guard=True,
        hmm_retrain_weekly=True,
        allow_swing_hold=True,
        max_hold_days=5,
        stress_size_fraction=0.5,
        log_level="WARNING",
    )


def install_patches():
    """Monkey-patch DecisionUnit to trace the 14:00 bar on Jan 18."""
    import raits.decision.decision_unit as _du

    # ── Patch 1: decide() — capture trading_ok, active, entries at TARGET_TS ──
    _orig_decide = _du.DecisionUnit.decide

    def _patched_decide(self, ctx):
        is_jan18 = (ctx.bar_ts.date() == JAN18_DATE)
        is_target = (ctx.bar_ts == TARGET_TS)

        if is_jan18:
            try:
                coord_state = str(self.coordinator.state)
                trading_ok_pre = self.coordinator.trading_allowed
                eff = self.coordinator.effective_hmm_state
                layer0 = self._check_layer0(ctx.spy_history)
            except Exception:
                coord_state, trading_ok_pre, eff, layer0 = "?", "?", "?", "?"
            print(f"[JAN18] bar={ctx.bar_ts}  state={coord_state}  trading_ok={trading_ok_pre}"
                  f"  eff={eff!r}  layer0={layer0}")

        result = _orig_decide(self, ctx)

        if is_jan18:
            print(f"        -> override_active={result.override_active}"
                  f"  entries={len(result.entries)}  exits={len(result.exits)}")
            if result.entries:
                for e in result.entries:
                    print(f"           ENTRY: {e.ticker} {e.strategy} {e.direction}")

        if is_target:
            print(f"\n{'='*60}")
            print(f"[PATCH] bar={ctx.bar_ts} (exact match)")
            print(f"  entries: {[(e.ticker, e.strategy, e.direction) for e in result.entries]}")
            print(f"{'='*60}\n")

        return result

    _du.DecisionUnit.decide = _patched_decide

    # ── Patch 2: _position_ok() — log CVX checks ──────────────────────────────
    _orig_position_ok = _du.DecisionUnit._position_ok

    def _patched_position_ok(self, ticker, strategy, open_trades, pending_entries):
        result = _orig_position_ok(self, ticker, strategy, open_trades, pending_entries)
        if ticker == "CVX" and strategy == "TREND_FOLLOW":
            open_tickers = {t.ticker for t in open_trades} | {e.ticker for e in pending_entries}
            total = len(open_trades) + len(pending_entries)
            from raits.decision.decision_unit import STRATEGY_CAPS
            strat_count = (
                sum(1 for t in open_trades if t.strategy == strategy)
                + sum(1 for e in pending_entries if e.strategy == strategy)
            )
            print(f"[PATCH] _position_ok(CVX, TF):")
            print(f"  open_trades     = {[(t.ticker, t.strategy) for t in open_trades]}")
            print(f"  pending_entries = {[(e.ticker, e.strategy) for e in pending_entries]}")
            print(f"  CVX in open_tickers? {ticker in open_tickers}")
            print(f"  total={total} (max={8})")
            print(f"  strat_count={strat_count} (cap={STRATEGY_CAPS.get(strategy, 2)})")
            print(f"  -> _position_ok = {result}")
        return result

    _du.DecisionUnit._position_ok = _patched_position_ok

    # ── Patch 3: _attempt_entry() — log CVX TF attempts ──────────────────────
    _orig_attempt_entry = _du.DecisionUnit._attempt_entry

    def _patched_attempt_entry(self, signal, ticker, strategy, bar_ts, ctx, pending_entries, entries, gf_stop_dist=None):
        if ticker == "CVX" and strategy == "TREND_FOLLOW":
            print(f"[PATCH] _attempt_entry(CVX, TF) called at {bar_ts}")
            print(f"  signal: {signal}")
        _orig_attempt_entry(self, signal, ticker, strategy, bar_ts, ctx, pending_entries, entries, gf_stop_dist)
        if ticker == "CVX" and strategy == "TREND_FOLLOW":
            cvx_entries = [e for e in pending_entries if e.ticker == "CVX" and e.strategy == "TREND_FOLLOW"]
            print(f"  -> CVX in pending_entries after attempt: {len(cvx_entries) > 0}  ({cvx_entries})")

    _du.DecisionUnit._attempt_entry = _patched_attempt_entry

    print("Patches installed for DecisionUnit.decide, _position_ok, _attempt_entry")


def main():
    print("=" * 60)
    print("REFAC Trace — CVX TF 2019-01-18 14:00 (Monkey-patch)")
    print("=" * 60)

    install_patches()

    print("\nLoading 5-min data...")
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)
    market_data_full = {t: df for t, df in all_data.items() if t in TICKERS}

    print("Loading daily data...")
    with open(PICKLE_DAILY, "rb") as f:
        daily_data = pickle.load(f)

    market_data_short = {
        t: df[
            (df.index >= pd.Timestamp("2017-01-03"))
            & (df.index <= pd.Timestamp(SHORT_END))
        ]
        for t, df in market_data_full.items()
    }

    print(f"\nRunning REFAC engine 2017-01-03 to {SHORT_END}...")
    config = make_config()
    t0 = time.time()
    engine = RefactoredBacktestEngine(config)
    result = engine.run(market_data_short, daily_data)
    elapsed = time.time() - t0
    refac_trades = result.trade_log
    print(f"Done in {elapsed:.1f}s — {len(refac_trades)} trades total")

    # Show ALL Jan 18 REFAC trade entries (not just open at 14:00)
    jan18_entries = [
        t for t in refac_trades
        if pd.Timestamp(t.entry_time).date() == TARGET_TS.date()
    ]
    print(f"\nAll REFAC entries on Jan 18: {len(jan18_entries)}")
    for t in sorted(jan18_entries, key=lambda x: x.entry_time):
        print(f"  {t.ticker:6s} {t.strategy:12s} {t.direction:5s} entry={t.entry_time}  "
              f"exit={t.exit_time}  reason={t.exit_reason}")

    jan17_entries = [
        t for t in refac_trades
        if pd.Timestamp(t.entry_time).date() == pd.Timestamp("2019-01-17").date()
    ]
    print(f"\nAll REFAC entries on Jan 17 (for context): {len(jan17_entries)}")
    for t in sorted(jan17_entries, key=lambda x: x.entry_time):
        print(f"  {t.ticker:6s} {t.strategy:12s} {t.direction:5s} entry={t.entry_time}")


if __name__ == "__main__":
    main()