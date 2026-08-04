"""
check_mym_ema_compare.py — so sánh daily close + EMA30 giữa parquet và Databento
==================================================================================
In bảng daily close / EMA30 cho cả hai sources trong 15 ngày gần nhất,
để xem chính xác tại sao Jul 27 cho direction khác nhau.

Usage:
    cd d:\\raits
    python check_mym_ema_compare.py --api-key db-xxxx
    set DATABENTO_API_KEY=db-xxxx && python check_mym_ema_compare.py
"""
import argparse, datetime, os, sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

from global_index.fetch import back_adjust, fetch

PARQUET = "data/cache/futures/YM_continuous_1m_8y.parquet"
EMA_SPAN = 30
_TODAY = datetime.date.today()
_START = (_TODAY - datetime.timedelta(days=65)).isoformat()
_END   = _TODAY.strftime("%Y-%m-%dT19:58:00Z")


def daily_ema(df: pd.DataFrame, span: int) -> tuple:
    """Return (daily_close_series, ema_series) from 1-min bars."""
    d = df.resample("1D").agg({"close": "last"}).dropna()
    ema = d["close"].ewm(span=span, adjust=False).mean()
    return d["close"], ema


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", default=os.environ.get("DATABENTO_API_KEY"))
    ap.add_argument("--days",    type=int, default=15,
                    help="Number of recent days to print (default: 15)")
    a = ap.parse_args()

    if not a.api_key:
        ap.error("Cần Databento API key: --api-key db-xxxx")

    # ── Load parquet ───────────────────────────────────────────────────────────
    df_pq = pd.read_parquet(PARQUET)
    if df_pq.index.tz is not None:
        df_pq.index = df_pq.index.tz_convert("America/New_York").tz_localize(None)
    df_pq.columns = [c.lower() for c in df_pq.columns]
    close_pq, ema_pq = daily_ema(df_pq, EMA_SPAN)

    # ── Fetch Databento ────────────────────────────────────────────────────────
    print(f"Fetching Databento MYM.v.0  {_START} → {_END} ...")
    raw = fetch("MYM", _START, _END, a.api_key, roll="v")
    adj = back_adjust(raw, method="diff")
    adj.index = adj.index.tz_convert("America/New_York").tz_localize(None)
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in adj.columns]
    adj = adj[keep].sort_index()
    print(f"  {len(adj):,} bars  {adj.index[0]} → {adj.index[-1]}")
    close_db, ema_db = daily_ema(adj, EMA_SPAN)

    # ── Align and print ────────────────────────────────────────────────────────
    recent_dates = close_pq.index[-a.days:]

    print()
    print("=" * 90)
    print(f"{'Date':<12}  {'PQ close':>10} {'PQ EMA30':>10} {'PQ diff':>8}  "
          f"{'DB close':>10} {'DB EMA30':>10} {'DB diff':>8}  {'Agree?':>7}")
    print("-" * 90)

    for dt in recent_dates:
        pq_c = close_pq.get(dt, np.nan)
        pq_e = ema_pq.get(dt, np.nan)
        pq_d = pq_c - pq_e if not np.isnan(pq_c) and not np.isnan(pq_e) else np.nan

        db_c = close_db.get(dt, np.nan)
        db_e = ema_db.get(dt, np.nan)
        db_d = db_c - db_e if not np.isnan(db_c) and not np.isnan(db_e) else np.nan

        pq_dir = ("LONG" if pq_d > 0 else "SHORT") if not np.isnan(pq_d) else "?"
        db_dir = ("LONG" if db_d > 0 else "SHORT") if not np.isnan(db_d) else "?"
        agree  = "✓" if pq_dir == db_dir else "✗ FLIP"

        date_str = str(dt.date())
        def fmt(v): return f"{v:>10.2f}" if not np.isnan(v) else f"{'N/A':>10}"

        print(f"{date_str:<12}  {fmt(pq_c)} {fmt(pq_e)} {pq_d:>+8.2f}  "
              f"{fmt(db_c)} {fmt(db_e)} {db_d:>+8.2f}  {agree:>7}  "
              f"({pq_dir}/{db_dir})")

    print("=" * 90)
    print()
    print("Columns: PQ=parquet, DB=Databento 65D v-roll diff back-adjust")
    print("'diff' = close - EMA30 (positive = LONG, negative = SHORT)")


if __name__ == "__main__":
    main()
