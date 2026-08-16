"""
futures/verify_current_freeze.py — score the INCUMBENT model against its own floor
===================================================================================
Re-freeze asks "is the new fit good enough". This asks the question that comes first:
is the model currently in production still above the floor a replacement would have
to clear?

Why it exists. The registry records Calmar 2.744 for fit_C, measured 2026-07-06, and
refreeze.CALMAR_FLOOR is 2.38 -- a 13.3% degradation allowance. A separate measurement
on 2026-08-15 of the same system at 2-tick slippage came out near 2.30, which is below
that floor. Either the two measurements are not on the same basis, or the incumbent has
fallen through the bar its own replacement must clear. Those call for very different
decisions, and guessing between them is not one of the options.

This runs refreeze.run_verify itself -- the same function the promotion gate uses -- on
the labels production builds today, so the number is comparable by construction rather
than by argument.

Run from d:\\raits (takes a few minutes; it is a full deploy_sim replay):

    python futures/verify_current_freeze.py

Read-only: touches no registry, no model file, no state.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import REGIME
from futures.refreeze import CALMAR_FLOOR, FreezeRecord, current_freeze, run_verify

# The live path's own inputs. run_live_day.py:242 builds labels exactly this way, and
# generate_replay_snapshots.py uses the same CSV -- spy_daily.csv stops at 2024-12-31 and
# would silently truncate the regime series.
REGIME_CSV = str(ROOT / "spy_daily_live.csv")
DATA_DIR = str(ROOT / "data" / "cache" / "futures")
NKD_PARQUET = str(ROOT / "global_index" / "data" / "NKD_continuous_1m_8y.parquet")
ANCHOR = "2018-01-01"
N_COMPONENTS = 3


def main() -> int:
    record = current_freeze()
    if record is None:
        print("No current freeze in the registry — nothing to score.")
        return 1

    fit_end = REGIME["hmm_fit_end"]
    print(f"incumbent      {record.version}")
    print(f"  fit_end      {record.fit_end}   (runner uses REGIME['hmm_fit_end']={fit_end})")
    print(f"  frozen_at    {record.frozen_at}")
    print(f"  calmar (recorded at freeze time)  {record.calmar:.4f}")
    print(f"  promotion floor                   {CALMAR_FLOOR}")
    if record.fit_end != fit_end:
        print(f"  WARNING: registry fit_end {record.fit_end!r} != runner fit_end {fit_end!r}")

    print("\nbuilding production labels (same call as run_live_day.py:242) ...")
    bench = benchmark_daily(REGIME_CSV)
    labels = label_regimes(bench, ANCHOR, N_COMPONENTS, fit_end)
    days = sorted(labels)
    print(f"  {len(labels)} label(s)  {days[0]} .. {days[-1]}")
    counts = pd.Series(list(labels.values())).value_counts().to_dict()
    print(f"  distribution {counts}")

    print("\nrunning refreeze.run_verify (full deploy_sim replay) ...")
    started = time.monotonic()
    result = run_verify(record, labels, DATA_DIR, NKD_PARQUET)
    print(f"  took {time.monotonic() - started:.0f}s")

    print("\n--- verdict ---")
    print(f"  Calmar today   {result.calmar_new:.4f}")
    print(f"  floor          {result.calmar_floor}")
    print(f"  net            ${result.net_new:,.0f}")
    print(f"  detail         {result.detail}")
    drift = result.calmar_new - record.calmar
    print(f"  drift vs freeze-time record  {drift:+.4f} "
          f"({drift / record.calmar * 100:+.1f}%)")

    print()
    if not result.passed:
        print("  INCUMBENT IS BELOW ITS OWN PROMOTION FLOOR.")
        print("  A re-freeze cannot be judged against a floor the current model fails:")
        print("  either the floor no longer matches how Calmar is measured, or the")
        print("  system has degraded. Decide which before fitting anything new.")
    elif abs(drift) > 0.15:
        print("  Passes the floor, but the number has moved materially since the freeze.")
        print("  Worth understanding why before treating the floor as a live gate.")
    else:
        print("  Incumbent is above the floor and close to its recorded value.")
        print("  The floor is usable as-is; the re-freeze can be judged against it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
