from __future__ import annotations

import argparse
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.harness import ARM_LIVE, Cfg, run_deploy
from scratch.regime_candidate_probe import parse_extra


BASE = [
    "--data-dir",
    "data/cache/futures/frozen_sim",
    "--nkd-parquet",
    "global_index/data/NKD_frozen_2024.parquet",
    "--regime-csv",
    "spy_daily_live.csv",
    "--n-contracts",
    "1",
    "--slippage-ticks",
    "2",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--stop-basis", type=float, default=2.0)
    ap.add_argument(
        "--windows",
        nargs="+",
        default=["2018:2020", "2021:2021", "2022:2022", "2023:2023", "2024:2024"],
    )
    args = ap.parse_args()

    cfg = Cfg(
        fix_fill=True,
        arm_hours=ARM_LIVE,
        ratchet=False,
        roska4_only=False,
        ema=args.ema,
        stop_basis=args.stop_basis,
    )

    for w in args.windows:
        start_year, end_year = w.split(":", 1)
        key = f"custom_{start_year}_{end_year}"
        H.ARGV[key] = BASE + [
            "--start",
            f"{start_year}-01-01",
            "--end",
            f"{end_year}-12-31",
            "--hmm-fit-end",
            "2022-12-31",
        ]
        r = run_deploy(cfg, key)
        maxdd, maxdd_pct, halts = parse_extra(r["out"])
        print(
            "{}-{} net=${:>8,.0f} calmar={:>6.2f} maxdd={:>5.1f}% "
            "halts={:<4} fix_n={:<4} fix=${:>8,.0f}".format(
                start_year,
                end_year,
                r["net"] or 0,
                r["calmar"] or 0,
                maxdd_pct or 0,
                halts if halts is not None else -1,
                r["sua_n"],
                r["sua_tot"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
