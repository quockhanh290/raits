"""Stage 5ZZZ-I — a promotion artifact with the Swing sleeve removed and nothing else.

Built from the 2026-08-21 baseline by emptying the four R4 instruments' trade lists and leaving
MNKD exactly as it is, so the "no-Swing" route runs through the same replay, the same caps and
the same NKD/Stress/Calm inputs as every other arm. Anything else would be comparing two
different books rather than one book with and without a sleeve.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

R4 = ("MES", "MNQ", "M2K", "MYM")


def main() -> int:
    for which in ("floor", "vault2025", "vault2026"):
        src = Path(f"scratch/normal_promotion_trades_{which}_20260821.json")
        d = json.loads(src.read_text(encoding="utf-8"))
        nkd = d["nkd_instrument"]
        before = {k: len(v) for k, v in d["filtered"].items()}
        for bucket in ("raw", "filtered", "filtered_prevbar"):
            for inst in R4:
                if inst in d.get(bucket, {}):
                    d[bucket][inst] = []
        assert d["filtered"].get(nkd), f"{which}: NKD was emptied too; that is not this variant"
        assert all(not d["filtered"].get(i) for i in R4), which
        dest = Path(f"scratch/normal_promotion_trades_{which}_noswing_20260829.json")
        dest.write_text(json.dumps(d, indent=1), encoding="utf-8")
        after = {k: len(v) for k, v in d["filtered"].items()}
        print(f"  {which:10s} -> {dest.name}")
        print(f"      before {before}")
        print(f"      after  {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
