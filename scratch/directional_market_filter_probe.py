from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.harness import ARM_LIVE, Cfg, run_deploy
from scratch.regime_candidate_probe import parse_extra
from scratch.window_probe import BASE


def feature_frame(spy_csv: str) -> pd.DataFrame:
    spy = pd.read_csv(spy_csv, parse_dates=["date"]).set_index("date")["close"].sort_index()
    ret = spy.pct_change()
    c = spy.shift(1)
    f = pd.DataFrame(index=spy.index)
    f["ret20"] = c / spy.shift(21) - 1.0
    f["rv20"] = ret.rolling(20).std().shift(1) * (252 ** 0.5)
    f["dd63"] = c / spy.rolling(63).max().shift(1) - 1.0
    f["above_sma50"] = c > spy.rolling(50).mean().shift(1)
    f["above_sma200"] = c > spy.rolling(200).mean().shift(1)
    return f


def allowed_short_days(f: pd.DataFrame, name: str) -> set[pd.Timestamp]:
    if name == "dd63_le_-3":
        m = f["dd63"] <= -0.03
    elif name == "dd63_le_-5":
        m = f["dd63"] <= -0.05
    elif name == "ret20_le_0":
        m = f["ret20"] <= 0
    elif name == "below_sma50":
        m = ~f["above_sma50"]
    elif name == "weak_combo":
        m = (f["dd63"] <= -0.03) | (f["ret20"] <= 0) | (~f["above_sma50"])
    elif name == "not_strong_bull":
        m = (f["dd63"] <= -0.03) | (~f["above_sma50"])
    else:
        raise ValueError(f"unknown short filter {name}")
    return set(pd.Timestamp(d).normalize() for d in f.index[m.fillna(False)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowed", nargs="+", default=["Normal"])
    ap.add_argument("--short-filters", nargs="+", default=["dd63_le_-3", "dd63_le_-5", "below_sma50", "not_strong_bull", "weak_combo"])
    ap.add_argument("--which", nargs="+", default=["baseline", "vault2324", "vault2025", "vault2026"])
    ap.add_argument("--windows", nargs="+")
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--stop-basis", type=float, default=2.0)
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    args = ap.parse_args()

    whiches = list(args.which)
    if args.windows:
        whiches = []
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
            whiches.append(key)

    import raits.strategies.trend_follow as tf

    f = feature_frame(args.spy_csv)
    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    cfg = Cfg(
        fix_fill=True,
        arm_hours=ARM_LIVE,
        ratchet=False,
        roska4_only=False,
        ema=args.ema,
        stop_basis=args.stop_basis,
    )

    for filt in args.short_filters:
        days = allowed_short_days(f, filt)

        def filtered_generate(self, *a, **kw):
            sig = old_generate(self, *a, **kw)
            if not sig or sig.get("direction") != "SHORT":
                return sig
            resume_bar = a[1]
            day = pd.Timestamp(resume_bar.name).tz_localize(None).normalize()
            return sig if day in days else None

        tf.DEFAULT_CONFIG["allowed_regimes"] = list(args.allowed)
        tf.TrendFollowStrategy.generate_signal = filtered_generate
        try:
            vals = []
            for which in whiches:
                r = run_deploy(cfg, which)
                _, maxdd_pct, halts = parse_extra(r["out"])
                vals.append(r["calmar"] or 0)
                print(
                    "short_{:<14} {:<9} net=${:>8,.0f} calmar={:>6.2f} "
                    "maxdd={:>5.1f}% halts={:<4} fix_n={:<4} fix=${:>8,.0f}".format(
                        filt,
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
            print(f"short_{filt:<14} min_calmar={min(vals):.2f}", flush=True)
        finally:
            tf.TrendFollowStrategy.generate_signal = old_generate
            tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
