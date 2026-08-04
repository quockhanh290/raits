"""check_mym_offset.py — verify actual per-bar gap at rollover vs recent period."""
import sys; sys.path.insert(0, ".")
import pandas as pd

PARQUET = "data/cache/futures/YM_continuous_1m_8y.parquet"

df = pd.read_parquet(PARQUET)
if df.index.tz is not None:
    df.index = df.index.tz_convert("America/New_York").tz_localize(None)
df = df.sort_index()
df.columns = [c.lower() for c in df.columns]

# ── A. Daily close quanh rollover Jun 6 ─────────────────────────────────────
print("A. Daily close (parquet) quanh rollover Jun 6:")
daily = df["close"].resample("1D").last().dropna()
window = daily.loc["2026-05-28":"2026-06-16"]
diffs = window.diff()
for dt, cl in window.items():
    d = diffs[dt]
    flag = "  ← JUMP" if abs(d) > 50 and not pd.isna(d) else ""
    print(f"  {str(dt.date())}  close={cl:.1f}  day_chg={d:+.1f}{flag}")

# ── B. Price level của recent bars (Jul 2026) ──────────────────────────────
print()
print("B. Daily close Jul 2026 (parquet):")
jul = daily.loc["2026-07-01":"2026-07-28"]
for dt, cl in jul.items():
    print(f"  {str(dt.date())}  close={cl:.1f}")

# ── C. Xem bar đầu tiên mà IBKR đã append (sau parquet gốc Databento) ──────
print()
print("C. Metadata parquet:")
print(f"  Total bars : {len(df):,}")
print(f"  First bar  : {df.index[0]}")
print(f"  Last bar   : {df.index[-1]}")

# Xem 5 ngày đầu và cuối của series để hiểu coverage
print()
print("  First 3 days close:")
first3 = daily.head(3)
for dt, cl in first3.items():
    print(f"    {str(dt.date())}  {cl:.1f}")
print("  Last 3 days close:")
last3 = daily.tail(3)
for dt, cl in last3.items():
    print(f"    {str(dt.date())}  {cl:.1f}")
