"""
global_index/fix_offset_step.py — remove the splice-offset step left by the repair

On 2026-08-04 repair_parquet_utc rebuilt the tail of every parquet by refetching
from IBKR, and wrote those bars at IBKR's own price level: its log recorded join
gaps of 0.003-0.043% and applied no offset. The splice-offsets sidecar was left
holding the pre-repair values, so from the next daily append onward
update_ibkr_daily resumed adding them to every new bar.

The result is a step inside each price series at the first append after the
repair — MES +11.50, MNQ +183.00, MYM -57.00, M2K +7.20, MNKD +1065.00, each
exactly the stale sidecar value.

Confirmed against real trades, not just against another IBKR series: the M2K stop
filled at 3020.10 on 2026-08-07 11:20:20 UTC while the parquet's bar for that
minute reads O=3026.90 H=3027.30 L=3026.90 C=3027.00. The fill sits outside the
recorded high-low. The parquet is describing prices that never traded.

Measured effect so far is small — MNQ's daily ATR is off by 6.93 (1.0%) and its
chandelier band by 17.32 points, MES is unaffected, and no instrument's desired
position changes. Live order prices were never wrong either, because _splice_live
measures the parquet-to-live difference and to_candidate removes it again. But the
step stays in the history permanently, and every future backtest or replay across
2026-08-05 would read a jump that did not happen.

    python -m global_index.fix_offset_step                # report only
    python -m global_index.fix_offset_step --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

_CWD = Path.cwd()
if not ((_CWD / "global_index").is_dir() and (_CWD / "futures").is_dir()):
    sys.stderr.write("CWD guard FAIL: run from d:\\raits\n")
    sys.exit(1)
if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

import pandas as pd

from futures.basket import BASKET, data_filename
from global_index.update_ibkr_daily import _fetch_contfuture, _load_parquet, _split_entry

OFFSETS = Path("global_index/data/_ibkr_splice_offsets.json")
PRICE_COLS = ("open", "high", "low", "close")
MIN_OVERLAP = 500          # below this the measurement is not worth trusting
DETECT_MIN = 1.0           # a difference this small is not a step

TARGETS = [
    ("MES",  "CME",  "data/cache/futures/" + data_filename(BASKET["MES"])),
    ("MNQ",  "CME",  "data/cache/futures/" + data_filename(BASKET["MNQ"])),
    ("MYM",  "CBOT", "data/cache/futures/" + data_filename(BASKET["MYM"])),
    ("M2K",  "CME",  "data/cache/futures/" + data_filename(BASKET["M2K"])),
    ("MNKD", "CME",  "global_index/data/NKD_continuous_1m_8y.parquet"),
]


def _ibkr_symbol(inst: str) -> str:
    return "NKD" if inst == "MNKD" else inst


def main() -> int:
    ap = argparse.ArgumentParser(description="remove the post-repair offset step")
    ap.add_argument("--apply", action="store_true",
                    help="write the corrected parquets and zero the sidecar")
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--client-id", type=int, default=88)
    a = ap.parse_args()

    import ib_insync as ibi
    ib = ibi.IB()
    ib.connect("127.0.0.1", a.port, clientId=a.client_id, timeout=60)
    ib.sleep(3)

    sidecar = json.loads(OFFSETS.read_text()) if OFFSETS.exists() else {}
    plans = []
    print("=" * 78)
    print(f"{'APPLY' if a.apply else 'DRY-RUN'} — measuring each parquet against IBKR")
    print("=" * 78)

    try:
        for inst, exch, path in TARGETS:
            stored, contract = _split_entry(sidecar.get(inst))
            live, _ = _fetch_contfuture(ib, _ibkr_symbol(inst), exch, duration="10 D")
            ib.sleep(1.2)
            df = _load_parquet(Path(path))
            ov = df.index.intersection(live.index)
            if len(ov) < MIN_OVERLAP:
                print(f"{inst:<6} overlap {len(ov)} bars — too few, skipping")
                continue

            d = (df.loc[ov, "close"] - live.loc[ov, "close"]).sort_index()
            stepped = d[d.abs() > DETECT_MIN]
            if stepped.empty:
                print(f"{inst:<6} already aligned (median {d.median():+.4f}) — nothing to do")
                continue

            # The step starts at the first bar that disagrees, and the size is the
            # median over every bar after it — one bad print cannot move it.
            t0 = stepped.index[0]
            step = float(d.loc[t0:].median())
            before = d.loc[:t0].iloc[:-1]
            print(f"{inst:<6} step {step:+.4f} from {t0}  "
                  f"(sidecar {stored:+.4f}, aligned before: median "
                  f"{before.median() if len(before) else float('nan'):+.4f}, n={len(before)})")
            plans.append((inst, path, t0, step))

        if not plans:
            print("\nnothing to correct")
            return 0

        if not a.apply:
            print("\ndry-run — nothing written. Re-run with --apply")
            return 0

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = Path(f"data/cache/futures/_backup_{stamp}_pre_offset_fix")
        backup.mkdir(parents=True, exist_ok=True)
        print(f"\nbackup → {backup}")

        for inst, path, t0, step in plans:
            src = Path(path)
            shutil.copy2(src, backup / src.name)
            df = _load_parquet(src)
            mask = df.index >= t0
            for c in PRICE_COLS:
                if c in df.columns:
                    df.loc[mask, c] = df.loc[mask, c] - step
            tmp = src.with_suffix(".fixed.parquet")
            df.to_parquet(tmp)
            shutil.move(str(tmp), str(src))
            print(f"  {inst:<6} {int(mask.sum()):>7,} bars shifted by {-step:+.4f}  → {src.name}")

        # The repair aligned the parquets to IBKR's own level, so the correct offset
        # is now zero. Leaving the old values would put the step straight back at the
        # next append — which is exactly how this happened.
        for inst, _p, _t, _s in plans:
            _, contract = _split_entry(sidecar.get(inst))
            sidecar[inst] = {"offset": 0.0, "contract": contract}
        OFFSETS.write_text(json.dumps(sidecar, indent=2))
        print(f"\nsidecar offsets zeroed → {OFFSETS}")
        print("re-run with no --apply to verify each series now reads median ~0.0000")
        return 0
    finally:
        ib.disconnect()


if __name__ == "__main__":
    sys.exit(main())
