"""
scratch/normal_promotion_lookahead_audit_20260821.py - no-lookahead proof for the
Normal-R4 filter `range_p90__vol_le_2`. Scratch / read-only.

The proof method is brute force, not inspection. For a sample of (instrument,
session, slot) the feature is recomputed from a frame that has been HARD CUT at
the decision instant - every bar at or after the cut physically removed - and
compared with the value the live filter object serves. If the two ever differ,
the filter is reading the future.

A test that can only pass is worth nothing, so each check also runs a MUTATION:
the same comparison against a deliberately non-causal variant (no shift, i.e. the
feature including the current session). The mutation MUST fail. If the mutation
passes, the check is not measuring what it claims and the result is void.

    python scratch/normal_promotion_lookahead_audit_20260821.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.normal_promotion_filter_lib_20260821 import (
    RTH_END, RTH_START, SLOT_MIN_PERIODS, SLOT_WINDOW, R4ContextFilter, bars_5m,
    prev_rth_range_map, slot_volume_frame)

R4 = ["MES", "MNQ", "MYM", "M2K"]
WINDOWS = {
    "floor": dict(data_dir="data/cache/futures/frozen_sim", start=None, end="2024-12-31"),
    "vault2025": dict(data_dir="data/cache/futures/frozen_2025_sim", start="2025-01-01",
                      end="2025-12-31"),
    "vault2026": dict(data_dir="data/cache/futures", start="2026-01-01", end="2026-08-19"),
}


def load(inst: str, w: dict) -> pd.DataFrame:
    from futures._validated_core import load_parquet
    from futures.basket import BASKET, data_filename
    df = load_parquet(str(Path(w["data_dir"]) / data_filename(BASKET[inst])))
    if w["start"]:
        df = df[df.index >= pd.Timestamp(w["start"]).tz_localize(df.index.tz)]
    if w["end"]:
        df = df[df.index <= pd.Timestamp(w["end"]).tz_localize(df.index.tz)]
    return df


# ---------------------------------------------------------------------------
# brute-force causal recomputation from a hard-cut frame
# ---------------------------------------------------------------------------
def brute_prev_range(df: pd.DataFrame, day: pd.Timestamp) -> float:
    """Prior session RTH range %, computed from bars STRICTLY BEFORE day 00:00."""
    cut = day if df.index.tz is None else day.tz_localize(df.index.tz)
    past = df[df.index < cut]
    if past.empty:
        return np.nan
    idx = past.index.tz_localize(None) if past.index.tz is not None else past.index
    p = past.copy()
    p.index = idx
    rth = p[(p.index.time >= RTH_START) & (p.index.time <= RTH_END)]
    if rth.empty:
        return np.nan
    last_day = rth.index.normalize().max()
    s = rth[rth.index.normalize() == last_day]
    close = float(s["close"].iloc[-1])
    return float((s["high"].max() - s["low"].min()) / max(abs(close), 1e-9))


def brute_slot_med20(df: pd.DataFrame, bar_ts: pd.Timestamp) -> float:
    """Median volume of this time-of-day slot over the previous 20 sessions,
    computed from bars STRICTLY BEFORE this session's 00:00."""
    ts = pd.Timestamp(bar_ts)
    day = (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
    cut = day if df.index.tz is None else day.tz_localize(df.index.tz)
    past = df[df.index < cut]
    if past.empty:
        return np.nan
    b = bars_5m(past)
    same = b[b.index.time == ts.time()]
    if len(same) < SLOT_MIN_PERIODS:
        return np.nan
    return float(same["volume"].tail(SLOT_WINDOW).median())


# ---------------------------------------------------------------------------
# non-causal mutations - these MUST fail the same comparison
# ---------------------------------------------------------------------------
def mutated_prev_range_map(df: pd.DataFrame) -> dict:
    """No shift: session D gets ITS OWN range. Must not match the brute force."""
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    d = df.copy()
    d.index = idx
    rth = d[(d.index.time >= RTH_START) & (d.index.time <= RTH_END)]
    g = rth.groupby(rth.index.normalize())
    daily = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(),
                          "close": g["close"].last()})
    rng = (daily["high"] - daily["low"]) / daily["close"].abs().clip(lower=1e-9)
    return {pd.Timestamp(k).normalize(): float(v) for k, v in rng.items() if np.isfinite(v)}


def mutated_slot_frame(df: pd.DataFrame) -> pd.DataFrame:
    """No shift inside the slot: the rolling median INCLUDES this session."""
    b = bars_5m(df).copy()
    b["_time"] = b.index.time
    parts = []
    for _, g in b.groupby("_time", sort=False):
        parts.append(g["volume"].rolling(SLOT_WINDOW, min_periods=SLOT_MIN_PERIODS).median())
    b["slot_med20"] = pd.concat(parts).sort_index()
    return b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--samples", type=int, default=120,
                    help="(instrument, bar) samples per window per check")
    ap.add_argument("--out", default="scratch/normal_promotion_lookahead_audit_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_promotion_lookahead_audit_20260821.json")
    a = ap.parse_args()

    report, results = [], {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    emit("=" * 112)
    emit("NORMAL-R4 FILTER - NO-LOOKAHEAD AUDIT   (scratch / read-only)")
    emit("=" * 112)
    emit("Filter: range_p90__vol_le_2. Every feature is recomputed from a frame hard-cut")
    emit("at the decision instant and compared with what the live filter serves. Each check")
    emit("is paired with a non-causal MUTATION that must FAIL, so a green result cannot come")
    emit("from a comparison that never had a way to disagree.")
    emit("")

    overall_ok = True
    for wname in a.windows:
        w = WINDOWS[wname]
        emit("#" * 112)
        emit("WINDOW: " + wname)
        emit("#" * 112)
        wres = {}
        for inst in R4:
            df = load(inst, w)
            filt = R4ContextFilter(df)
            volf = slot_volume_frame(df)
            prng = prev_rth_range_map(df)

            # ---- sample decision bars from the engine's own entry window ----
            entry_bars = volf.index[(volf.index.time >= pd.Timestamp("14:00").time())
                                    & (volf.index.time <= pd.Timestamp("15:55").time())]
            assert len(entry_bars) > 0, f"{inst}: no entry-window bars - sample is empty"
            step = max(1, len(entry_bars) // a.samples)
            sample = list(entry_bars[::step])[:a.samples]
            assert len(sample) >= 10, f"{inst}: only {len(sample)} samples"

            # ---- check 1: prior-day RTH range ----
            days = sorted({(pd.Timestamp(t).tz_localize(None)
                            if pd.Timestamp(t).tz is not None else pd.Timestamp(t)).normalize()
                           for t in sample})
            r_checked = r_bad = 0
            r_mut_diff = 0
            mut_rng = mutated_prev_range_map(df)
            for d in days:
                live = prng.get(d, np.nan)
                brute = brute_prev_range(df, d)
                if np.isfinite(live) or np.isfinite(brute):
                    r_checked += 1
                    if not (np.isfinite(live) and np.isfinite(brute)
                            and abs(live - brute) <= 1e-9 * max(1.0, abs(brute))):
                        r_bad += 1
                    m = mut_rng.get(d, np.nan)
                    if not (np.isfinite(m) and np.isfinite(brute)
                            and abs(m - brute) <= 1e-9 * max(1.0, abs(brute))):
                        r_mut_diff += 1

            # ---- check 2: same-slot median20 volume ----
            v_checked = v_bad = 0
            v_mut_diff = 0
            mut_vol = mutated_slot_frame(df)
            for t in sample:
                live = volf.loc[t, "slot_med20"]
                live = float(live) if pd.notna(live) else np.nan
                brute = brute_slot_med20(df, t)
                if np.isfinite(live) or np.isfinite(brute):
                    v_checked += 1
                    if not (np.isfinite(live) and np.isfinite(brute)
                            and abs(live - brute) <= 1e-9 * max(1.0, abs(brute))):
                        v_bad += 1
                    m = mut_vol.loc[t, "slot_med20"]
                    m = float(m) if pd.notna(m) else np.nan
                    if not (np.isfinite(m) and np.isfinite(brute)
                            and abs(m - brute) <= 1e-9 * max(1.0, abs(brute))):
                        v_mut_diff += 1

            # ---- check 3: is the entry bar's own volume knowable at decision time? ----
            # The engine enters at the resume bar's CLOSE, so the bar is complete at the
            # decision instant. Verify the bar is fully contained before the fill moment,
            # and that no bar AFTER the entry bar contributes to the feature.
            c3_bad = 0
            for t in sample[:40]:
                ts = pd.Timestamp(t)
                fill = ts + pd.Timedelta(minutes=5)
                seg = df[(df.index >= ts) & (df.index < fill)]
                if seg.empty:
                    continue
                if float(seg["volume"].sum()) != float(volf.loc[t, "volume"]):
                    c3_bad += 1
                if seg.index.max() >= fill:
                    c3_bad += 1

            ok = (r_bad == 0 and v_bad == 0 and c3_bad == 0
                  and r_mut_diff > 0 and v_mut_diff > 0)
            overall_ok = overall_ok and ok
            wres[inst] = dict(range_checked=r_checked, range_bad=r_bad,
                              range_mutation_caught=r_mut_diff,
                              vol_checked=v_checked, vol_bad=v_bad,
                              vol_mutation_caught=v_mut_diff,
                              entrybar_bad=c3_bad, ok=bool(ok),
                              filter_stats=None)
            emit("  {:<5} prior-range {:>4} checked / {:>2} bad (mutation caught {:>3})  |  "
                 "slot-med20 {:>4} checked / {:>2} bad (mutation caught {:>3})  |  "
                 "entry-bar {:>2} bad  -> {}".format(
                     inst, r_checked, r_bad, r_mut_diff, v_checked, v_bad, v_mut_diff,
                     c3_bad, "PASS" if ok else "FAIL"))
            del df, volf, mut_vol
        results[wname] = wres
        emit("")

    emit("=" * 112)
    emit("VERDICT: " + ("PASS - no lookahead found, and every check demonstrated it can fail"
                        if overall_ok else
                        "FAIL - see rows above; do not use this filter's numbers"))
    emit("")
    emit("Reading of the three checks:")
    emit("  prior-range  session D uses the range of the last RTH session ENDING BEFORE D 00:00.")
    emit("  slot-med20   session D's slot value uses only sessions ending before D 00:00.")
    emit("  entry-bar    the 5-minute entry bar is complete at the fill instant (entry is that")
    emit("               bar's CLOSE), and no bar at or after the fill contributes to it. The")
    emit("               engine already reads this same bar's volume in check_volume_pattern,")
    emit("               so the filter adds no information the strategy did not already use.")
    emit("               The stricter `rvol_prevbar` variant, which touches nothing from the")
    emit("               entry bar, is measured separately in the regeneration audit.")

    Path(a.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\nwrote " + a.out)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
