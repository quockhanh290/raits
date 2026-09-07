"""Stage 5ZZZ-J — is there enough historical SPY intraday data to build a pre-14:00 proxy?

The gating question, asked before anything is designed. A proxy needs SPY bars up to 14:00 ET on
every session the Swing sleeve trades, across all three windows. If the coverage is not there,
the honest answer is that the proxy cannot be built for those windows - not a proxy fitted on
whatever happens to be present.
"""
from __future__ import annotations

import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd

WINDOWS = {"floor 2018-2024": ("2018-01-01", "2024-12-31"),
           "2025 OOS": ("2025-01-01", "2025-12-31"),
           "2026 OOS": ("2026-01-01", "2026-08-19")}


def main() -> int:
    files = sorted(Path(".").rglob("SPY_5min*.parquet")) + \
        sorted(Path(".").rglob("SPY_1min*.parquet"))
    print(f"found {len(files)} SPY intraday parquet files\n")

    frames = []
    for p in files:
        try:
            df = pd.read_parquet(p)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  UNREADABLE {p}: {type(exc).__name__}")
            continue
        idx = df.index if isinstance(df.index, pd.DatetimeIndex) else None
        if idx is None:
            for c in ("timestamp", "datetime", "time", "date"):
                if c in df.columns:
                    df = df.set_index(pd.DatetimeIndex(df[c]))
                    idx = df.index
                    break
        if idx is None or not len(idx):
            print(f"  NO INDEX {p}")
            continue
        print(f"  {str(p)[-72:]:72s} {len(df):>7,} rows  "
              f"{idx.min()} .. {idx.max()}  tz={idx.tz}")
        frames.append(df)

    if not frames:
        print("\nNO SPY INTRADAY DATA AT ALL")
        return 0

    all_idx = None
    for df in frames:
        i = df.index
        i = i.tz_convert("America/New_York") if i.tz is not None else i.tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT")
        all_idx = i if all_idx is None else all_idx.append(i)
    all_idx = pd.DatetimeIndex(all_idx).dropna().sort_values()
    days = sorted(set(all_idx.normalize()))

    print(f"\nunion: {len(all_idx):,} bars over {len(days):,} distinct sessions")
    print(f"       {all_idx.min()} .. {all_idx.max()}")

    print("\n=== coverage per window ===")
    for label, (lo, hi) in WINDOWS.items():
        m = (all_idx >= pd.Timestamp(lo, tz="America/New_York")) & \
            (all_idx <= pd.Timestamp(hi, tz="America/New_York") + pd.Timedelta(days=1))
        sub = all_idx[m]
        sessions = sorted(set(sub.normalize()))
        pre14 = sorted({t.normalize() for t in sub
                        if pd.Timestamp("13:30").time() <= t.time() <= pd.Timestamp("14:05").time()})
        span_years = (pd.Timestamp(hi) - pd.Timestamp(lo)).days / 365.25
        expect = int(252 * span_years)
        verdict = "OK" if expect and len(pre14) >= 0.9 * expect else "INSUFFICIENT"
        print(f"  {label:18s} sessions={len(sessions):>5}  with a ~14:00 bar={len(pre14):>5}  "
              f"expected~{expect:>5}   {verdict}")
        if sessions:
            print(f"                     first={sessions[0].date()}  last={sessions[-1].date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
