"""Stage 5M-A probe — what the two fill laws do AT THE ARMING INSTANT. Read-only.

Normal-R4 holds overnight with an unarmed stop and arms it at 14:05 ET the next session. That
is the sleeve's structural exposure, and it is exactly where the fill law decides a price.

The question this measures rather than reasons about: when the first bar eligible for the stop
already trades beyond it, which price does each law book?

Nothing is written. No broker, no scheduler, no state file.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_track1_stage4_production_clean_20260823 as s4  # noqa: E402

from global_index import track1_normal_r4 as NR            # noqa: E402
from global_index import track1_normal_filters as NF       # noqa: E402
from futures.swing_tf import costs_for_basket           # noqa: E402


def run(window: str, law: str) -> dict:
    frames = s4._frames(window, clipped=True)
    lab = s4._labels(window)
    costs = costs_for_basket(slippage_ticks=2.0)
    short = NF.short_days_from_csv("spy_daily_live.csv")
    out = {}
    for inst in s4.R4:
        trades, _stats = NR.run_instrument(
            frames[inst], lab, costs[inst],
            NR.NormalR4Params(fill_law=law), short_days=short,
            apply_context_filter=True)
        out[inst] = trades
    return out


def key(t):
    g = (lambda k: t.get(k) if isinstance(t, dict) else getattr(t, k, None))
    return (str(g("entry_time") or g("entry_ts") or g("entry_day")),
            str(g("exit_time") or g("exit_ts") or g("exit_day")))


def field(t, k):
    return t.get(k) if isinstance(t, dict) else getattr(t, k, None)


def main() -> int:
    window = "vault2026"
    art = run(window, NR.FILL_ARTIFACT)
    prod = run(window, NR.FILL_PRODUCTION)

    print(f"window={window}  instruments={list(art)}")
    total_a = sum(len(v) for v in art.values())
    total_p = sum(len(v) for v in prod.values())
    print(f"trades: artifact={total_a}  production={total_p}")
    assert total_a and total_p, "no trades at all — the comparison would prove nothing"

    n_diff = 0
    for inst in art:
        a = {key(t): t for t in art[inst]}
        p = {key(t): t for t in prod[inst]}
        for k in sorted(set(a) | set(p)):
            ta, tp = a.get(k), p.get(k)
            if ta is None or tp is None:
                n_diff += 1
                print(f"  {inst} ONLY IN {'production' if ta is None else 'artifact'}: {k}")
                continue
            ra, rp = field(ta, "exit_reason"), field(tp, "exit_reason")
            xa, xp = field(ta, "exit_price"), field(tp, "exit_price")
            if ra != rp or (xa is not None and xp is not None and abs(float(xa) - float(xp)) > 1e-9):
                n_diff += 1
                print(f"  {inst} DIFFERS {k}")
                print(f"      artifact  : reason={ra} price={xa} pnl={field(ta,'pnl')}")
                print(f"      production: reason={rp} price={xp} pnl={field(tp,'pnl')}")

    print(f"\ntrades differing between the two laws: {n_diff}")

    # The mechanism, checked directly rather than inferred: is the bar at the arming instant
    # ever flagged gap-eligible under the production law?
    frames = s4._frames(window, clipped=True)
    df = frames["MES"]
    cache_p = NR._cache_for(df, NR.NormalR4Params(fill_law=NR.FILL_PRODUCTION))
    cache_a = NR._cache_for(df, NR.NormalR4Params(fill_law=NR.FILL_ARTIFACT))
    import numpy as np
    import pandas as pd
    arm_eligible_prod = arm_eligible_art = sessions = 0
    for day, ts in (cache_p.get("ts") or {}).items():
        if ts is None or not len(ts):
            continue
        naive = ts.tz_localize(None) if getattr(ts, "tz", None) is not None else pd.DatetimeIndex(ts)
        at = np.where(naive >= pd.Timestamp(day).normalize() + pd.Timedelta(hours=14, minutes=5))[0]
        if not len(at):
            continue
        sessions += 1
        i = int(at[0])
        if i < len(cache_p["hl"][day][3]):
            arm_eligible_prod += int(bool(cache_p["hl"][day][3][i]))
            arm_eligible_art += int(bool(cache_a["hl"][day][3][i]))
    print(f"\nMES sessions with a 14:05 bar: {sessions}")
    print(f"  that bar gap-eligible under PRODUCTION law: {arm_eligible_prod}")
    print(f"  that bar gap-eligible under ARTIFACT  law: {arm_eligible_art}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
