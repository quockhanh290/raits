"""Stage 5Q-4 probe A — READ-ONLY look at the tail of every Track 1 parquet.

    python scratch/track1_stage5q4_probe_parquet_tail_20260824.py

Opens nothing but the parquet files, writes one JSON summary beside itself in `scratch/`, and
mutates nothing. No broker, no scheduler, no order.

The question: is the MNQ bar at 2026-08-21 13:45 ET the LAST bar in the file, and does it look
like a bar that was written while its minute was still open?
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

import pandas as pd

from global_index import run_live_day_track1 as R
from global_index import track1_live_source as src

DISPUTED = pd.Timestamp("2026-08-21 13:45:00", tz="America/New_York")
OUT = Path("scratch/_track1_stage5q4_parquet_tail.json")


def main() -> int:
    paths = R.default_data_paths()
    report: dict = {"probe": "parquet_tail", "read_only": True, "paths": paths,
                    "disputed_instant_et": str(DISPUTED), "instruments": {}}

    for inst, path in paths.items():
        p = Path(path)
        entry: dict = {"path": path, "exists": p.exists()}
        if not p.exists():
            report["instruments"][inst] = entry
            print(f"{inst:6s} MISSING {path}")
            continue
        entry["size_bytes"] = p.stat().st_size
        entry["mtime"] = str(pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC")
                             .tz_convert("America/New_York"))
        # The SAME loader the route uses, so the frame measured here is the frame the slot
        # reads -- not a second reading of the same file through a different door.
        df = src.frozen_frame(inst, path)
        idx = pd.DatetimeIndex(df.index)
        entry["rows"] = int(len(df))
        entry["columns"] = list(df.columns)
        entry["tz"] = str(idx.tz)
        entry["first_bar"] = str(idx[0])
        entry["last_bar"] = str(idx[-1])
        entry["last_bar_is_the_disputed_one"] = bool(idx[-1] == DISPUTED)

        tail = df.tail(6)
        entry["tail"] = [
            {"ts": str(t), **{c: (None if pd.isna(v) else float(v))
                              for c, v in row.items()}}
            for t, row in tail.iterrows()]

        # Is the LAST bar shaped like a bar written mid-minute? A complete 1-minute futures bar
        # normally has volume comparable to its neighbours and a low <= open/close. A partial
        # one is not malformed -- it is simply a snapshot taken before the minute finished, so
        # its EXTREMES are the tell: the low can only fall further as the minute runs.
        last = df.iloc[-1]
        prev = df.iloc[-31:-1]
        entry["last_bar_shape"] = {
            "volume": float(last["volume"]),
            "prev30_volume_median": float(prev["volume"].median()),
            "volume_ratio_vs_median": (float(last["volume"] / prev["volume"].median())
                                       if float(prev["volume"].median()) else None),
            "range": float(last["high"] - last["low"]),
            "prev30_range_median": float((prev["high"] - prev["low"]).median()),
        }
        if DISPUTED in set(idx):
            row = df.loc[DISPUTED]
            entry["disputed_bar"] = {c: float(row[c]) for c in df.columns}
            entry["disputed_position_from_end"] = int(len(idx) - 1 - idx.get_loc(DISPUTED))
        report["instruments"][inst] = entry

        print(f"{inst:6s} rows={entry['rows']:>8}  last={entry['last_bar']}  "
              f"last_is_disputed={entry['last_bar_is_the_disputed_one']}")
        print(f"        mtime={entry['mtime']}")
        if "disputed_bar" in entry:
            print(f"        disputed bar: {entry['disputed_bar']}  "
                  f"({entry['disputed_position_from_end']} bars from the end)")

    # Which sessions does the tail cover -- one file appended once at 13:45, or many?
    print()
    print("last bars, all instruments:")
    for inst, e in report["instruments"].items():
        if e.get("last_bar"):
            print(f"  {inst:6s} {e['last_bar']}   vol={e['last_bar_shape']['volume']:.0f} "
                  f"(prev30 median {e['last_bar_shape']['prev30_volume_median']:.0f}, "
                  f"ratio {e['last_bar_shape']['volume_ratio_vs_median']})")

    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
