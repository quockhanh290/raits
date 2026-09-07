"""Stage 5ZZZ-L — the `vol_feature` arm, free.

Every promotion artifact already carries THREE trade tables: `raw`, `filtered` (the context
filter on `rvol_slot20`) and `filtered_prevbar` (the same filter on `rvol_prevbar`, the stricter
variant that does not use the entry bar's own volume at all). The replay reads `filtered`.

So the second vol_feature is a bucket swap, not a regeneration: take the D-1 artifact and put its
`filtered_prevbar` list where `filtered` goes. NKD is left exactly as it is - it is never filtered.
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
        src = Path(f"scratch/normal_promotion_trades_{which}_d1_20260829.json")
        if not src.exists():
            print(f"  {which}: no D-1 artifact, skipped")
            continue
        d = json.loads(src.read_text(encoding="utf-8"))
        nkd = d["nkd_instrument"]
        before = {i: len(d["filtered"].get(i, [])) for i in R4}
        after = {}
        for inst in R4:
            pb = d.get("filtered_prevbar", {}).get(inst)
            if pb is None:
                print(f"  {which}/{inst}: no prevbar bucket; left as is")
                continue
            d["filtered"][inst] = pb
            after[inst] = len(pb)
        assert d["filtered"].get(nkd), f"{which}: NKD must be untouched"
        dest = Path(f"scratch/normal_promotion_trades_{which}_d1pb_20260829.json")
        dest.write_text(json.dumps(d, indent=1), encoding="utf-8")
        print(f"  {which:10s} -> {dest.name}")
        print(f"      slot20  {before}")
        print(f"      prevbar {after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
