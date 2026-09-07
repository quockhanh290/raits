"""Stage 5Q-4 probe B — READ-ONLY: is the partial boundary bar a one-off or written every day?

    python scratch/track1_stage5q4_probe_boundary_bars_20260824.py

Reads parquet only. Writes one JSON summary into `scratch/`. No broker, no scheduler, no order,
no mutation of any data file.

Why this probe exists
---------------------
`update_ibkr_daily` appends `new_bars[new_bars.index > last_existing]` — STRICTLY newer. The bar
that was last in the file is therefore never rewritten, so if it was a snapshot taken while its
minute was still open, it stays partial for ever. That is a property of the append, not of one
Friday, and it predicts ONE partial bar per instrument per trading day at whatever minute the
13:45 fetch reached.

The control, and why the first version of this probe was wrong
--------------------------------------------------------------
The first version compared each bar's volume to its NEIGHBOURS in the same day and flagged
anything under 60%. It flagged 76-99 bars across 29-34 days — two or three a day, every day,
in every instrument. That is not a defect appearing daily; that is a threshold catching the
ordinary lunchtime lull, and a result that full should make you suspect the tool before the
data.

The discriminator has to control for TIME OF DAY. 13:45 is a quiet minute in every session, so
the question is not "is this bar quieter than 13:30" but "is this 13:45 quieter than other
13:45s". Each bar is therefore compared with the SAME clock-minute across the surrounding
trading days. A bar holding a small fraction of what that minute normally trades is partial;
a bar holding a normal fraction is simply a quiet minute.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")

import pandas as pd

from global_index import run_live_day_track1 as R
from global_index import track1_live_source as src

OUT = Path("scratch/_track1_stage5q4_boundary_bars.json")

#: The band the 13:45 pre-flight's fetch lands in. Wide enough to cover a slow write.
BAND = ("13:40", "13:55")

#: Share of the SAME MINUTE's usual volume below which a bar is called partial. Deliberately
#: far from the ordinary spread: the numbers below come out either near 1.0 or near 0.1, so
#: nothing sits near this line and no tuning is doing any work.
PARTIAL_RATIO = 0.35

DAYS = 45


def measure(inst: str, path: str) -> dict:
    df = src.frozen_frame(inst, path)
    idx = pd.DatetimeIndex(df.index)
    df = df.assign(_day=idx.normalize(), _min=idx.strftime("%H:%M"))
    days = sorted(set(df["_day"]))[-DAYS:]
    recent = df[df["_day"].isin(days)]

    # The control: what this clock-minute usually trades, across the days examined.
    per_minute_median = recent.groupby("_min")["volume"].median()

    out = {"path": path, "days_examined": len(days), "last_bar": str(idx[-1]),
           "control": "same clock-minute median across the days examined", "flagged": []}
    band = recent.between_time(*BAND)
    for ts, row in band.iterrows():
        base = float(per_minute_median.get(row["_min"], 0.0))
        if base <= 0:
            continue
        ratio = float(row["volume"]) / base
        if ratio < PARTIAL_RATIO:
            out["flagged"].append({"ts": str(ts), "minute": row["_min"],
                                   "volume": float(row["volume"]),
                                   "same_minute_median": base, "ratio": round(ratio, 3),
                                   "is_file_last_bar": bool(ts == idx[-1])})
    out["flagged_count"] = len(out["flagged"])
    out["days_with_a_flag"] = len({f["ts"][:10] for f in out["flagged"]})
    out["flags_per_day"] = round(out["flagged_count"] / max(1, len(days)), 2)

    # And the raw table for one minute, so a reader can see it rather than trust the ratio.
    m1345 = recent[recent["_min"] == "13:45"][["volume"]].tail(12)
    out["volume_at_1345_last_12_sessions"] = [
        {"ts": str(t), "volume": float(v)} for t, v in m1345["volume"].items()]
    return out


def main() -> int:
    paths = R.default_data_paths()
    report = {"probe": "boundary_bars_v2", "read_only": True, "band_et": list(BAND),
              "partial_ratio_threshold": PARTIAL_RATIO, "days": DAYS,
              "control": "same clock-minute across days", "instruments": {}}
    for inst, path in paths.items():
        if inst == "MNKD":
            continue          # Tokyo clock; its own boundary is a separate question
        print(f"--- {inst}")
        m = measure(inst, path)
        report["instruments"][inst] = m
        print(f"    {m['flagged_count']} flagged over {m['days_examined']} days "
              f"= {m['flags_per_day']} per day")
        for f in m["flagged"]:
            print(f"      {f['ts']}  vol={f['volume']:.0f}  "
                  f"this minute usually {f['same_minute_median']:.0f}  ratio={f['ratio']}"
                  f"{'   <-- FILE LAST BAR' if f['is_file_last_bar'] else ''}")
        print(f"      volume at 13:45, last 12 sessions: "
              f"{[int(v['volume']) for v in m['volume_at_1345_last_12_sessions']]}")
    OUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
