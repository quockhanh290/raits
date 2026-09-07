from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.harness import ARM_LIVE, Cfg, run_deploy


NET_RE = re.compile(r"net\s+\$([\-\d,]+)\s+\|\s+Calmar\s+([\-\d.]+)")
MAXDD_RE = re.compile(r"MaxDD\s+\$([\d,]+)\s+\(([\d.]+)%\)")
HALTS_RE = re.compile(r"circuit-breaker halts:\s+(\d+)")


def parse_extra(out: str) -> tuple[float | None, float | None, int | None]:
    maxdd = maxdd_pct = halts = None
    for line in out.splitlines():
        m = MAXDD_RE.search(line)
        if m:
            maxdd = float(m.group(1).replace(",", ""))
            maxdd_pct = float(m.group(2))
        h = HALTS_RE.search(line)
        if h:
            halts = int(h.group(1))
    return maxdd, maxdd_pct, halts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["vault2324", "vault2025"])
    ap.add_argument("--ema", nargs="+", type=int, default=[30, 40, 50])
    ap.add_argument("--stop-basis", nargs="+", type=float, default=[1.5, 2.0, 2.5])
    args = ap.parse_args()

    rows = []
    for ema in args.ema:
        for stop_basis in args.stop_basis:
            cfg = Cfg(
                fix_fill=True,
                arm_hours=ARM_LIVE,
                ratchet=False,
                roska4_only=False,
                ema=ema,
                stop_basis=stop_basis,
            )
            for which in args.which:
                r = run_deploy(cfg, which)
                maxdd, maxdd_pct, halts = parse_extra(r["out"])
                rows.append(
                    {
                        "ema": ema,
                        "stop_basis": stop_basis,
                        "which": which,
                        "net": r["net"],
                        "calmar": r["calmar"],
                        "fix_n": r["sua_n"],
                        "fix_dollars": r["sua_tot"],
                        "maxdd": maxdd,
                        "maxdd_pct": maxdd_pct,
                        "halts": halts,
                    }
                )
                print(
                    "ema={:<3} stop={:<3g} {:<9} net=${:>8,.0f} calmar={:>5.2f} "
                    "maxdd={:>5.1f}% halts={:<4} fix_n={:<4} fix=${:>8,.0f}".format(
                        ema,
                        stop_basis,
                        which,
                        r["net"] or 0,
                        r["calmar"] or 0,
                        maxdd_pct or 0,
                        halts if halts is not None else -1,
                        r["sua_n"],
                        r["sua_tot"],
                    ),
                    flush=True,
                )

    print()
    print("summary_by_candidate:")
    for ema in args.ema:
        for stop_basis in args.stop_basis:
            sub = [r for r in rows if r["ema"] == ema and r["stop_basis"] == stop_basis]
            if not sub:
                continue
            min_calmar = min(float(r["calmar"] or 0) for r in sub)
            total_net = sum(float(r["net"] or 0) for r in sub)
            max_dd_pct = max(float(r["maxdd_pct"] or 0) for r in sub)
            total_halts = sum(int(r["halts"] or 0) for r in sub)
            print(
                "ema={:<3} stop={:<3g} min_calmar={:>5.2f} total_net=${:>8,.0f} "
                "worst_maxdd={:>5.1f}% total_halts={}".format(
                    ema, stop_basis, min_calmar, total_net, max_dd_pct, total_halts
                )
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
