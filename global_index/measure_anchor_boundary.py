"""global_index/measure_anchor_boundary.py — where does the store start matching the feed exactly?

WHY THIS EXISTS
---------------
The overlap check may only demand an exact match from bars written under the anchor now in
force. Older bars carry an earlier adjustment and differ by a couple of basis points for a
structural reason: the store is difference-adjusted to a 2024 contract and IBKR's continuous
series is ratio-adjusted to the current one, so one additive offset lines the two up at a
single price level and nowhere else.

Going forward `update_ibkr_daily` stamps `exact_from` into the anchor file when it re-anchors.
For the anchor already in force there is no such stamp — the file holds only the current
offset and has no history — so the boundary has to be MEASURED from the data instead of read.

Measured 2026-09-23: bars written after the last anchor matched on 1376 of 1376 minutes with a
standard deviation of 0.000, while bars from before it differed by a median of -2.3 bp. The
boundary between those two populations is what this finds.

HOW
---
One long fetch per instrument — not a day-by-day scan. A scan of 28 short requests on
2026-09-23 had IBKR return an empty list for nine trading days, with no error raised: the
silent-empty failure this codebase already documents. One request per instrument, spaced, does
not provoke it.

The boundary reported is the first minute after the LAST disagreement, so everything at or
after it is exact by construction.

READ-ONLY unless --write is given.

    python -m global_index.measure_anchor_boundary            # measure and print
    python -m global_index.measure_anchor_boundary --write    # also stamp exact_from
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index import run_live_day_track1 as entry          # noqa: E402
from global_index import track1_live_source as S               # noqa: E402
from global_index.ibkr_broker import IBKRBroker                # noqa: E402
from global_index.update_ibkr_daily import SPLICE_OFFSETS_PATH  # noqa: E402

INSTS = ["MES", "MNQ", "MYM", "M2K", "MNKD"]
#: Long enough to contain the boundary with room either side, short enough for one request.
LOOKBACK = "1 W"
#: IBKR paces historical requests; the silent answer to too many is an empty list.
GAP_SECONDS = 8


def measure(broker, inst: str, through) -> dict:
    fr = S.frozen_frame(inst, entry.default_data_paths()[inst])
    raw = broker.fetch_bars(inst, through, lookback=LOOKBACK)
    if raw is None or raw.empty:
        return {"inst": inst, "error": "provider returned no bars"}
    aligned = S.on_frozen_clock(inst, raw, fr)
    aligned, _ = S.project_to_frozen_columns(inst, aligned, fr)
    shared = pd.DatetimeIndex(aligned.index).intersection(pd.DatetimeIndex(fr.index))
    if len(shared) == 0:
        return {"inst": inst, "error": "no shared minutes in the window"}
    a = pd.to_numeric(aligned.loc[shared, "open"], errors="coerce")
    b = pd.to_numeric(fr.loc[shared, "open"], errors="coerce")
    bad = (a - b).abs() > 1e-6
    if not bad.any():
        return {"inst": inst, "shared": int(len(shared)), "mismatches": 0,
                "exact_from": str(shared[0]),
                "note": "exact across the whole window; the boundary is older than it"}
    last_bad = shared[bad][-1]
    after = shared[shared > last_bad]
    return {"inst": inst, "shared": int(len(shared)), "mismatches": int(bad.sum()),
            "last_mismatch": str(last_bad),
            "exact_from": str(after[0]) if len(after) else None,
            "exact_bars_after": int(len(after))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=98)
    ap.add_argument("--through", default=None, help="naive-ET instant; default now")
    ap.add_argument("--write", action="store_true",
                    help="stamp exact_from into the anchor file (otherwise read-only)")
    a = ap.parse_args()

    through = pd.Timestamp(a.through) if a.through else \
        pd.Timestamp.now(tz="America/New_York").tz_localize(None)
    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    out = []
    for i, inst in enumerate(INSTS):
        if i:
            time.sleep(GAP_SECONDS)
        out.append(measure(broker, inst, through))
        print(json.dumps(out[-1], ensure_ascii=False))
    try:
        broker.disconnect()
    except Exception:                                                 # noqa: BLE001
        pass

    if not a.write:
        print("\nREAD-ONLY: nothing written. Re-run with --write to stamp exact_from.")
        return 0

    bad = [r for r in out if r.get("error") or not r.get("exact_from")]
    if bad:
        print(f"\nREFUSING to write: {len(bad)} instrument(s) have no measured boundary "
              f"({[r['inst'] for r in bad]}). A partial stamp would narrow the check on some "
              f"instruments and not others, which is worse than not narrowing at all.")
        return 2

    p = Path(SPLICE_OFFSETS_PATH)
    data = json.loads(p.read_text(encoding="utf-8"))
    for r in out:
        entry_ = data.get(r["inst"])
        if not isinstance(entry_, dict):
            print(f"REFUSING: {r['inst']} has no anchor entry to stamp"); return 2
        entry_["exact_from"] = r["exact_from"]
        entry_["exact_from_source"] = "measure_anchor_boundary"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nstamped exact_from for {len(out)} instrument(s) -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
