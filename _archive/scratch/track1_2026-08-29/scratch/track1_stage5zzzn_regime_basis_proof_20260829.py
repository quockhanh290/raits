"""Stage 5ZZZ-N — proof that the reproduced Swing arm reads a CAUSAL D-1 regime label.

The regeneration's own probe happened to land on a session where the same-day and previous-day
labels agree, which proves nothing. This picks sessions where they DISAGREE and shows the object
handed to the engine returns the previous session's value on every one of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from global_index.regime import RegimeLabels


def main() -> int:
    # exactly as the regeneration builds them for the floor window
    bench = benchmark_daily("spy_daily_live.csv")
    bench = bench[bench.index <= pd.Timestamp("2024-12-31")]
    ser = pd.Series(label_regimes(bench, "2018-01-01", 3, "2022-12-31"))
    idx = pd.DatetimeIndex(ser.index)
    ser.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    ser = ser.sort_index()
    lagged = RegimeLabels(ser, lag_days=1)

    prev = ser.shift(1)
    disagree = [d for d in ser.index[1:] if str(ser.loc[d]) != str(prev.loc[d])]
    assert disagree, "no session where the label changed; this proof would be vacuous"

    checked, ok_prev, wrong = 0, 0, []
    for d in disagree:
        got = str(lagged.get(d))
        same_day = str(ser.loc[d])
        prev_day = str(prev.loc[d])
        checked += 1
        if got == prev_day and got != same_day:
            ok_prev += 1
        else:
            wrong.append({"day": str(d.date()), "same_day": same_day,
                          "previous": prev_day, "object_returned": got})

    sample = []
    for d in disagree[:5]:
        sample.append({"day": str(d.date()), "same_day_label": str(ser.loc[d]),
                       "previous_session_label": str(prev.loc[d]),
                       "object_returned": str(lagged.get(d))})

    print(f"label-change sessions in the floor window: {checked}")
    print(f"  object returned the PREVIOUS session's label on: {ok_prev}/{checked}")
    print(f"  mismatches: {len(wrong)}")
    for s in sample:
        print(f"    {s['day']}  same-day={s['same_day_label']:<7} "
              f"previous={s['previous_session_label']:<7} "
              f"object={s['object_returned']:<7}")
    assert ok_prev == checked and not wrong, wrong[:5]
    print("\nPROVEN: the labels object returns the PREVIOUS session's label, never the "
          "session's own - on every session where the two differ.")

    Path("scratch/track1_stage5zzzn_regime_basis_proof_20260829.json").write_text(
        json.dumps({
            "object": "RegimeLabels(lag_days=1)",
            "window": "floor 2018-2024, hmm_fit_end 2022-12-31",
            "label_change_sessions": checked,
            "returned_previous_session_label": ok_prev,
            "mismatches": wrong,
            "sample": sample,
            "verdict": "causal D-1 confirmed on every disagreeing session",
        }, indent=1), encoding="utf-8")
    print("wrote scratch/track1_stage5zzzn_regime_basis_proof_20260829.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
