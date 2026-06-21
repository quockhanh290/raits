"""
Diagnostic: ORBFadeUniverseScanner trả về gì mỗi ngày trong 2020/2021/2022?
Câu hỏi: tại sao 2022 có ít FADE trades?

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_scanner_diagnostic.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
from collections import defaultdict
from raits.strategies.universe_scanner import ORBFadeUniverseScanner

PICKLE_DAILY = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_daily.pkl")

WINDOWS = [
    ("2020-01-02", "2020-12-31", "2020"),
    ("2021-01-04", "2021-12-31", "2021"),
    ("2022-01-03", "2022-12-30", "2022"),
]


def div(label, w=68):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")


print("Loading daily data...")
with open(PICKLE_DAILY, "rb") as f:
    daily_data = pickle.load(f)

scanner = ORBFadeUniverseScanner(top_n=10)

# Get all trading days from SPY
spy = daily_data.get("SPY", pd.DataFrame())
spy.index = pd.DatetimeIndex(spy.index)
all_spy_days = sorted(spy.index.normalize().unique())

div("SCANNER OUTPUT STATS per YEAR")
for test_start, test_end, label in WINDOWS:
    ts, te = pd.Timestamp(test_start), pd.Timestamp(test_end)
    days_in_window = [d for d in all_spy_days if ts <= d <= te]

    n_days        = 0
    n_empty       = 0
    total_stocks  = 0
    ticker_counts = defaultdict(int)
    scores_by_day = []

    for day in days_in_window:
        prev_days = [d for d in all_spy_days if d < day]
        if not prev_days:
            continue
        scan_date = prev_days[-1]
        candidates = scanner.scan(daily_data, scan_date)
        n_days += 1
        total_stocks += len(candidates)
        if not candidates:
            n_empty += 1
        for t in candidates:
            ticker_counts[t] += 1
        scores_by_day.append(len(candidates))

    avg_n = total_stocks / n_days if n_days else 0
    print(f"\n  {label}: {n_days} trading days")
    print(f"    avg candidates/day : {avg_n:.1f}")
    print(f"    days with 0 cands  : {n_empty}")
    print(f"    days with <5 cands : {sum(1 for s in scores_by_day if s < 5)}")
    print(f"    days with 10 cands : {sum(1 for s in scores_by_day if s == 10)}")
    top10 = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    print(f"    most frequent picks: {[f'{t}({n})' for t,n in top10]}")

div("CANDIDATE COUNT DISTRIBUTION per YEAR")
print(f"\n  {'Year':<6} {'0':>5} {'1-3':>5} {'4-6':>5} {'7-9':>5} {'10':>5}")
print(f"  {'-'*32}")
for test_start, test_end, label in WINDOWS:
    ts, te = pd.Timestamp(test_start), pd.Timestamp(test_end)
    days_in_window = [d for d in all_spy_days if ts <= d <= te]
    counts = []
    for day in days_in_window:
        prev_days = [d for d in all_spy_days if d < day]
        if not prev_days:
            continue
        candidates = scanner.scan(daily_data, prev_days[-1])
        counts.append(len(candidates))
    if counts:
        c0   = sum(1 for c in counts if c == 0)
        c13  = sum(1 for c in counts if 1 <= c <= 3)
        c46  = sum(1 for c in counts if 4 <= c <= 6)
        c79  = sum(1 for c in counts if 7 <= c <= 9)
        c10  = sum(1 for c in counts if c == 10)
        print(f"  {label:<6} {c0:>5} {c13:>5} {c46:>5} {c79:>5} {c10:>5}")

div("REVERSAL RATE per TICKER per YEAR (quality of fade candidates)")
for test_start, test_end, label in WINDOWS:
    ts, te = pd.Timestamp(test_start), pd.Timestamp(test_end)
    # Use midpoint of year as scan date
    mid = ts + (te - ts) / 2
    candidates_raw = []
    for ticker in scanner.pool:
        if ticker not in daily_data:
            continue
        df = daily_data[ticker]
        df = df[df.index.normalize() <= mid]
        if len(df) < 61:
            continue
        window     = df.iloc[-61:]
        prev_close = window["close"].shift(1)
        gap_pct    = (window["open"] - prev_close).abs() / prev_close
        gap_dir    = (window["open"] - prev_close)
        intraday   = (window["close"] - window["open"])
        gap_pct    = gap_pct.iloc[1:]
        gap_dir    = gap_dir.iloc[1:]
        intraday   = intraday.iloc[1:]
        is_gap   = gap_pct >= 0.01
        gap_freq = float(is_gap.mean())
        if gap_freq < 0.05:
            continue
        followthrough = float(((gap_dir * intraday) > 0)[is_gap].mean()) if is_gap.any() else 0.0
        reversal_rate = 1.0 - followthrough
        score = gap_freq * reversal_rate
        candidates_raw.append({"ticker": ticker, "gap_freq": round(gap_freq, 3),
                                "reversal": round(reversal_rate, 3), "score": round(score, 4)})

    top = sorted(candidates_raw, key=lambda x: x["score"], reverse=True)[:10]
    bottom = sorted(candidates_raw, key=lambda x: x["score"])[:5]
    print(f"\n  {label} — top 10 by score (midpoint {mid.date()}):")
    for r in top:
        print(f"    {r['ticker']:<6} gap_freq={r['gap_freq']:.3f}  reversal={r['reversal']:.3f}  score={r['score']:.4f}")
    print(f"  {label} — bottom 5:")
    for r in bottom:
        print(f"    {r['ticker']:<6} gap_freq={r['gap_freq']:.3f}  reversal={r['reversal']:.3f}  score={r['score']:.4f}")
