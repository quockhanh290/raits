"""
Minimal trace: which gate rejects CVX from TF on 2019-01-18 14:00?

Loads Jan 18 5-min bars directly, runs scanner + generate_signal for CVX,
reports the exact rejection reason. Also shows all tickers that DO pass,
and tests all three HMM states to identify which blocks CVX.

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_cvx_tf_gates.py
"""
import sys, os, pickle, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yaml

from raits.strategies.trend_follow import TrendFollowStrategy

# Enable strategy debug logging so we see rejection reasons
logging.basicConfig(level=logging.DEBUG,
                    format="%(name)s — %(message)s",
                    stream=sys.stdout)
logging.getLogger("RAITS.TrendFollow").setLevel(logging.DEBUG)

PICKLE_5MIN  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")
ORIG_CACHE   = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")
_PARAMS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "configs", "final_params.yaml")

with open(_PARAMS_PATH) as f:
    _params = yaml.safe_load(f)

EMA_PERIOD = _params["ema_period"]   # 30
TARGET_DATE = pd.Timestamp("2019-01-18")
TARGET_TS   = pd.Timestamp("2019-01-18 14:00:00")

UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1 = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2 = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]

TREND_ELIGIBLE = UNIVERSE + PHASE1 + PHASE2


def compute_atr(bars, period=14):
    """Mirror of engine._compute_atr."""
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def build_candidates(day_stocks, bar_ts, universe):
    """Replicate _build_trend_candidates exactly."""
    candidates = []
    for ticker in universe:
        if ticker not in day_stocks:
            continue
        bars = day_stocks[ticker].loc[:bar_ts]
        if len(bars) < 3:
            continue
        try:
            candidates.append({
                "ticker":              ticker,
                "current_price":       float(bars.iloc[-1]["close"]),
                "hod":                 float(bars["high"].max()),
                "lod":                 float(bars["low"].min()),
                "atr":                 compute_atr(bars),
                "avg_intraday_volume": float(bars["volume"].tail(10).mean()),
                "current_volume":      float(bars.iloc[-1]["volume"]),
                "sector_strength":     0.0,
            })
        except Exception as e:
            print(f"  Candidate error {ticker}: {e}")
    return candidates


def get_refac_hmm_state(all_data, daily_data):
    """
    Compute the REFAC HMM state for Jan 18 by running the actual HMM prediction.
    Uses the same logic as engine_refactored.py lines 648-666.
    """
    try:
        from raits.hmm.engine import HMMEngine
        from raits.backtest.engine import to_daily_close
    except ImportError:
        return None, "import error"

    spy_5min = all_data.get("SPY")
    if spy_5min is None:
        return None, "no SPY data"

    spy_data = spy_5min[spy_5min.index <= TARGET_TS]
    spy_daily = to_daily_close(spy_data[spy_data.index.normalize() <= TARGET_TS.normalize()])

    if len(spy_daily) < 21:
        return None, f"only {len(spy_daily)} daily bars"

    # Re-compute HMM state by training on all data BEFORE Jan 18
    # The last retrain would have been Friday Jan 11, 2019
    try:
        hmm = HMMEngine()
        # Training data: expanding from 2017-01-03 to Jan 11 (last Friday before Jan 18)
        train_through = pd.Timestamp("2019-01-11")
        spy_train = spy_5min[spy_5min.index.normalize() <= train_through.normalize()]
        train_daily = to_daily_close(spy_train)

        if len(train_daily) >= 21:
            hmm.fit(train_daily)

        # Predict on Jan 18's data slice
        state_idx = hmm.predict_current(spy_daily)
        state_name = hmm.state_name(state_idx)

        # Volatility override
        log_ret = np.log(spy_daily / spy_daily.shift(1)).dropna()
        rv = log_ret.rolling(5).std() * np.sqrt(252)
        rv = rv.dropna()
        if len(rv) >= 5:
            cur_vol = float(rv.iloc[-1])
            if cur_vol >= 0.50:
                state_name = "Crisis"
                return state_name, f"vol_override: rv={cur_vol:.2%}"

        return state_name, "HMM prediction"
    except Exception as e:
        return None, f"error: {e}"


def main():
    print("=" * 65)
    print("CVX TF Gate Trace — 2019-01-18 14:00")
    print(f"EMA period: {EMA_PERIOD}")
    print("=" * 65)

    # ── Load 5-min data ───────────────────────────────────────────
    print("\nLoading 5-min data...")
    with open(PICKLE_5MIN, "rb") as f:
        all_data = pickle.load(f)

    print("Loading daily data...")
    daily_data = None
    if os.path.exists(PICKLE_DAILY):
        with open(PICKLE_DAILY, "rb") as f:
            daily_data = pickle.load(f)

    # Build day_stocks for Jan 18 (full day data)
    day_stocks = {}
    for ticker in TREND_ELIGIBLE:
        if ticker not in all_data:
            continue
        df = all_data[ticker]
        day_bars = df[df.index.normalize() == TARGET_DATE]
        if not day_bars.empty:
            day_stocks[ticker] = day_bars

    print(f"  {len(day_stocks)} tickers have data on Jan 18")

    if "CVX" not in day_stocks:
        print("  ERROR: CVX has no 5-min data on Jan 18")
        sys.exit(1)

    # ── Get HMM states ─────────────────────────────────────────────
    print("\nLoading ORIG trade log for Jan 18 HMM state...")
    with open(ORIG_CACHE, "rb") as f:
        orig_trades = pickle.load(f)

    jan18_orig = [
        t for t in orig_trades
        if pd.Timestamp(t.entry_time).date() == TARGET_DATE.date()
    ]
    hmm_state_orig = jan18_orig[0].hmm_state if jan18_orig else "Normal"
    print(f"  HMM state on Jan 18 from ORIG trades: {hmm_state_orig!r}")
    if jan18_orig:
        print(f"  (from trade: {jan18_orig[0].ticker} {jan18_orig[0].strategy} "
              f"entry={jan18_orig[0].entry_time})")

    print("\nComputing REFAC HMM state for Jan 18...")
    refac_hmm_state, refac_hmm_note = get_refac_hmm_state(all_data, daily_data)
    print(f"  REFAC HMM state: {refac_hmm_state!r}  ({refac_hmm_note})")

    if refac_hmm_state and refac_hmm_state != hmm_state_orig:
        print(f"\n  !!! HMM STATE MISMATCH: ORIG={hmm_state_orig!r} vs REFAC={refac_hmm_state!r}")
        print(f"  → This could be the ROOT CAUSE if one state allows TF and the other doesn't")

    # ── Build candidates ──────────────────────────────────────────
    print(f"\nBuilding TF candidates at {TARGET_TS}...")
    candidates = build_candidates(day_stocks, TARGET_TS, TREND_ELIGIBLE)
    print(f"  {len(candidates)} candidates built")

    # CVX raw candidate data
    cvx_cand = next((c for c in candidates if c["ticker"] == "CVX"), None)
    if cvx_cand:
        print(f"\n  CVX candidate:")
        print(f"    current_price={cvx_cand['current_price']:.2f}")
        print(f"    hod={cvx_cand['hod']:.2f}  lod={cvx_cand['lod']:.2f}  atr={cvx_cand['atr']:.4f}")
        print(f"    current_volume={cvx_cand['current_volume']:,.0f}  "
              f"avg_intraday_volume={cvx_cand['avg_intraday_volume']:,.0f}")
        near_hod_pct = (cvx_cand['hod'] - cvx_cand['current_price']) / cvx_cand['hod'] < 0.03
        near_lod_pct = (cvx_cand['current_price'] - cvx_cand['lod']) / cvx_cand['lod'] < 0.03
        near_hod_atr = (cvx_cand['hod'] - cvx_cand['current_price']) < 2.0 * cvx_cand['atr']
        near_lod_atr = (cvx_cand['current_price'] - cvx_cand['lod']) < 2.0 * cvx_cand['atr']
        vol_ratio    = (cvx_cand['current_volume'] / cvx_cand['avg_intraday_volume']
                        if cvx_cand['avg_intraday_volume'] > 0 else 0.0)
        print(f"    near_hod_pct={near_hod_pct}  near_hod_atr={near_hod_atr}")
        print(f"    near_lod_pct={near_lod_pct}  near_lod_atr={near_lod_atr}")
        print(f"    vol_ratio={vol_ratio:.2f}  (min=1.5)")
    else:
        print("\n  CVX NOT in candidates (missing from day_stocks or too few bars)")
        sys.exit(1)

    # ── Run scanner ───────────────────────────────────────────────
    print("\n--- Running TF scanner (DEBUG output below) ---")
    # Suppress debug noise for non-CVX tickers
    logging.getLogger("RAITS.TrendFollow").setLevel(logging.WARNING)
    trend = TrendFollowStrategy()

    # Temporarily re-enable DEBUG only for CVX
    class CVXFilter(logging.Filter):
        def filter(self, record):
            return "CVX" in record.getMessage()

    for handler in logging.getLogger("RAITS.TrendFollow").handlers:
        handler.addFilter(CVXFilter())
    logging.getLogger("RAITS.TrendFollow").setLevel(logging.DEBUG)

    watchlist = trend.run_scanner(candidates)
    print(f"--- Scanner done ---")
    print(f"  Full watchlist ({len(watchlist)} tickers): {watchlist}")
    print(f"  CVX in watchlist: {'YES' if 'CVX' in watchlist else 'NO'}")
    if "CVX" in watchlist:
        print(f"  CVX intent: {trend.watchlist_directions.get('CVX')!r}")

    if "CVX" not in watchlist:
        print("\n  CVX REJECTED BY SCANNER")
        print(f"  Scanner filter values for CVX:")
        print(f"    vol_ratio={vol_ratio:.2f}  (needs ≥1.5)")
        print(f"    near_hod = {near_hod_pct or near_hod_atr}")
        print(f"    near_lod = {near_lod_pct or near_lod_atr}")
        if not (near_hod_pct or near_hod_atr) and not (near_lod_pct or near_lod_atr):
            print("  → REJECTED: price not near HOD or LOD")
        elif vol_ratio < 1.5:
            print(f"  → REJECTED: vol_ratio {vol_ratio:.2f} < 1.5")
        return

    # ── generate_signal for CVX with multiple HMM states ──────────
    bars = day_stocks["CVX"].loc[:TARGET_TS]
    ema_val    = trend.calculate_ema(bars, period=EMA_PERIOD)
    atr        = compute_atr(bars)
    avg_vol_10 = float(bars["volume"].tail(10).mean()) or 1.0
    pb_bar     = bars.iloc[-2]
    res_bar    = bars.iloc[-1]

    print(f"\n--- generate_signal for CVX ---")
    print(f"  bars count: {len(bars)}")
    print(f"  EMA({EMA_PERIOD}): {ema_val:.4f}")
    print(f"  pullback bar:  close={pb_bar['close']:.4f}  vol={pb_bar['volume']:,.0f}")
    print(f"  resume bar:    close={res_bar['close']:.4f}  vol={res_bar['volume']:,.0f}")
    print(f"  avg_vol_10:    {avg_vol_10:,.0f}")
    ema_dist_pct = abs(pb_bar['close'] - ema_val) / ema_val
    print(f"  EMA distance:  {ema_dist_pct:.4%}  (max 0.5%)")

    states_to_test = list({hmm_state_orig, refac_hmm_state or hmm_state_orig, "Normal", "Stress", "Calm"})
    print(f"\n  Testing with HMM states: {states_to_test}")

    for state in states_to_test:
        sig = trend.generate_signal(pb_bar, res_bar, ema_val, atr, state, avg_vol_10)
        print(f"  [{state:7s}] generate_signal → {sig}")

    print(f"\n--- Using ORIG state ({hmm_state_orig!r}) ---")
    sig_orig = trend.generate_signal(pb_bar, res_bar, ema_val, atr, hmm_state_orig, avg_vol_10)
    if sig_orig is None:
        print(f"  CVX REJECTED by generate_signal with HMM={hmm_state_orig!r}")
        print(f"  → Root cause: generate_signal gate (regime/EMA/volume pattern)")
    else:
        print(f"  CVX PASSES generate_signal with HMM={hmm_state_orig!r}")
        print(f"  Signal: direction={sig_orig.get('direction')}  entry={sig_orig.get('entry_price'):.2f}")
        print(f"\n  → CVX passes BOTH scanner and generate_signal with ORIG state.")
        print(f"  → If REFAC state differs: {refac_hmm_state!r} vs ORIG {hmm_state_orig!r}")
        if refac_hmm_state and refac_hmm_state != hmm_state_orig:
            sig_refac = trend.generate_signal(pb_bar, res_bar, ema_val, atr, refac_hmm_state, avg_vol_10)
            if sig_refac is None:
                print(f"  → CONFIRMED ROOT CAUSE: REFAC HMM state={refac_hmm_state!r} → signal=None")
            else:
                print(f"  → REFAC signal also passes: {sig_refac}")
                print(f"  → ROOT CAUSE is NOT HMM state mismatch; must be pending_entries ordering")
        else:
            print(f"  → HMM states are same ({hmm_state_orig!r})")
            print(f"  → ROOT CAUSE: some watchlist ticker before CVX fills TF cap in REFAC's pending_entries")
            print(f"     but NOT in ORIG's trade_log (e.g., different _attempt_entry behavior)")
            print(f"\n  Watchlist order and signals (to find pre-CVX TF conflicts):")
            for i, wl_ticker in enumerate(watchlist):
                t_bars = day_stocks.get(wl_ticker, pd.DataFrame()).loc[:TARGET_TS]
                if len(t_bars) < 3:
                    print(f"  [{i:2d}] {wl_ticker:6s} — too few bars")
                    continue
                t_ema = trend.calculate_ema(t_bars, period=EMA_PERIOD)
                t_atr = compute_atr(t_bars)
                t_avg_vol = float(t_bars["volume"].tail(10).mean()) or 1.0
                t_pb  = t_bars.iloc[-2]
                t_res = t_bars.iloc[-1]
                t_sig = trend.generate_signal(t_pb, t_res, t_ema, t_atr, hmm_state_orig, t_avg_vol)
                marker = " ← CVX" if wl_ticker == "CVX" else ""
                print(f"  [{i:2d}] {wl_ticker:6s}  signal={'PASS' if t_sig else 'None':4s}"
                      f"  dir={t_sig.get('direction','—') if t_sig else '—'}{marker}")


if __name__ == "__main__":
    main()