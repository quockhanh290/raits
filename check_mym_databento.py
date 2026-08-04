"""
check_mym_databento.py — reconcile MYM via Databento continuous data
=====================================================================
Fetch MYM.v.0 (volume-roll continuous) từ Databento cho 62 ngày gần nhất,
apply cùng back-adjustment (diff/additive) như khi build parquet, chạy
backtest_swing_tf, so sánh với --print-signals.

Mục đích: confirm/deny MYM SHORT Jul27 bằng data source hoàn toàn độc lập
với IBKR (Databento = cùng nguồn gốc với parquet → kết quả phải match).

Usage:
    cd d:\\raits
    python check_mym_databento.py --api-key db-xxxx
    # hoặc:
    set DATABENTO_API_KEY=db-xxxx && python check_mym_databento.py
"""
import argparse, datetime, os, sys
sys.path.insert(0, ".")

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import REGIME, SWING_TF_PARAM
from futures.swing_tf_harness import backtest_swing_tf
from futures.swing_tf import costs_for_basket
from global_index.fetch import back_adjust, fetch

HMM_FIT_END = REGIME["hmm_fit_end"]
EMA  = SWING_TF_PARAM["ema_period"]           # 30
MULT = SWING_TF_PARAM["chandelier_atr_mult"]  # 2.5
HOLD = SWING_TF_PARAM["max_hold_days"]        # 5

_TODAY = datetime.date.today()
_START = (_TODAY - datetime.timedelta(days=65)).isoformat()   # 65D buffer
# Databento free tier cutoff for CME (GLBX.MDP3): ~19:59 UTC = 15:59 ET today.
# TF window ends 15:55 ET = 19:55 UTC → safely within free tier.
# Use 19:58 UTC to avoid the boundary.
_END   = _TODAY.strftime("%Y-%m-%dT19:58:00Z")


def main():
    ap = argparse.ArgumentParser(description="Reconcile MYM via Databento continuous data")
    ap.add_argument("--api-key",    default=os.environ.get("DATABENTO_API_KEY"),
                    help="Databento API key (fallback: DATABENTO_API_KEY env var)")
    ap.add_argument("--roll",       default="v", choices=["v", "c", "n"],
                    help="Roll rule: v=volume (default, same as parquet), c=calendar, n=OI")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--symbol",     default="MYM",
                    help="Databento root symbol (default: MYM for Micro Dow Jones)")
    a = ap.parse_args()

    if not a.api_key:
        ap.error("Cần Databento API key: --api-key db-xxxx hoặc set DATABENTO_API_KEY=db-xxxx")

    print(f"Fetching {a.symbol}.{a.roll}.0  {_START} → {_END}  (GLBX.MDP3 ohlcv-1m)...")
    raw_df = fetch(a.symbol, _START, _END, a.api_key, roll=a.roll)
    print(f"  Raw: {len(raw_df):,} bars  {raw_df.index[0]} → {raw_df.index[-1]}")

    # Cùng back-adjustment với parquet (diff = additive/Panama, anchor = newest contract)
    adj_df = back_adjust(raw_df, method="diff")
    print(f"  Rolls detected: {sum(adj_df.get('raw_close', adj_df['close']) != adj_df['close'])} adjusted bars")

    # UTC → ET naive (cùng convention với parquet)
    adj_df.index = adj_df.index.tz_convert("America/New_York").tz_localize(None)
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in adj_df.columns]
    adj_df = adj_df[keep].sort_index()

    print(f"  Adjusted: {len(adj_df):,} bars  {adj_df.index[0]} → {adj_df.index[-1]}")
    print(f"  Close range: {adj_df['close'].min():.1f} – {adj_df['close'].max():.1f}")

    # Regime labels (identical với production)
    bench  = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
    cost   = costs_for_basket()[a.symbol]

    # Backtest → open position
    _, pos = backtest_swing_tf(
        adj_df, labels, cost,
        ema_period=EMA, chandelier_atr_mult=MULT,
        max_hold_days=HOLD, return_open=True,
    )

    today_str = _TODAY.isoformat()
    today_ts  = pd.Timestamp(today_str).normalize()

    print()
    print("=" * 68)
    print(f"{a.symbol} DATABENTO RECONCILE — {a.roll}-roll, diff back-adjust")
    print(f"  source : Databento GLBX.MDP3 {a.symbol}.{a.roll}.0")
    print(f"  range  : {adj_df.index[0]} → {adj_df.index[-1]}")
    print(f"  bars   : {len(adj_df):,}")
    print()

    if pos is None:
        print("  open_pos : None")
        guard_ok = False
    else:
        ed       = pos.get("entry_day", "?")
        entry_ts = pd.Timestamp(ed).normalize() if ed != "?" else None
        guard_ok = (entry_ts == today_ts)
        guard    = "PASS ✓" if guard_ok else f"BLOCKED ({pd.Timestamp(ed).date()} ≠ {today_str})"
        print(f"  open_pos : dir={pos['dir']}  entry={pos['entry']:.2f}"
              f"  stop={pos['stop']:.2f}")
        print(f"  entry_day: {pd.Timestamp(ed).date()}  [{guard}]")

    print()
    print("Compare với --print-signals (ground truth):")
    print(f"  {a.symbol}: SHORT  entry=52212.00  stop=52269.36  entry_day=2026-07-27  [PASS]")
    print()

    if pos and pos["dir"] == "SHORT" and guard_ok:
        print("=> MATCH ✓ — Databento confirms --print-signals signal")
    elif pos and pos["dir"] == "SHORT" and not guard_ok:
        print("=> PARTIAL — direction SHORT đúng nhưng entry_day khác")
    elif pos and pos["dir"] == "LONG":
        print("=> MISMATCH ✗ — Databento cho LONG, --print-signals cho SHORT")
        print("   Nguyên nhân có thể: back-adjust khác, gap data, roll date khác")
    else:
        print("=> MISMATCH ✗ — Databento cho None, --print-signals cho SHORT")

    print("=" * 68)


if __name__ == "__main__":
    main()
