from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.harness import ARM_LIVE, ARGV, Cfg, patched_engine
from scratch.regime_candidate_probe import parse_extra


def feature_frame(spy_csv: str) -> pd.DataFrame:
    spy = pd.read_csv(spy_csv, parse_dates=["date"]).set_index("date")["close"].sort_index()
    f = pd.DataFrame(index=spy.index)
    # Shift everything one session: entry happens before today's SPY daily close is known.
    c = spy.shift(1)
    f["above_sma200"] = c > spy.rolling(200).mean().shift(1)
    f["sma50_gt_200"] = spy.rolling(50).mean().shift(1) > spy.rolling(200).mean().shift(1)
    f["ret20"] = c / spy.shift(21) - 1.0
    f["ret60"] = c / spy.shift(61) - 1.0
    ret = spy.pct_change()
    f["rv20"] = ret.rolling(20).std().shift(1) * (252 ** 0.5)
    f["dd63"] = c / spy.rolling(63).max().shift(1) - 1.0
    return f


def mask_for(f: pd.DataFrame, name: str) -> set[pd.Timestamp]:
    if name == "trend200":
        m = f["above_sma200"]
    elif name == "trend_stack":
        m = f["above_sma200"] & f["sma50_gt_200"]
    elif name == "ret20_pos":
        m = f["ret20"] > 0
    elif name == "ret60_pos":
        m = f["ret60"] > 0
    elif name == "rv20_lt20":
        m = f["rv20"] < 0.20
    elif name == "rv20_lt25":
        m = f["rv20"] < 0.25
    elif name == "dd63_gt-5":
        m = f["dd63"] > -0.05
    elif name == "dd63_gt-8":
        m = f["dd63"] > -0.08
    elif name == "trend_ret":
        m = f["above_sma200"] & (f["ret20"] > 0)
    elif name == "trend_lowvol":
        m = f["above_sma200"] & (f["rv20"] < 0.25)
    elif name == "stack_lowvol":
        m = f["above_sma200"] & f["sma50_gt_200"] & (f["rv20"] < 0.25)
    else:
        raise ValueError(f"unknown filter {name}")
    return set(pd.Timestamp(d).normalize() for d in f.index[m.fillna(False)])


class FilteredLabels:
    def __init__(self, labels, allowed_days: set[pd.Timestamp]):
        self.labels = labels
        self.allowed_days = allowed_days

    def get(self, day, default=None):
        d = pd.Timestamp(day).tz_localize(None).normalize()
        if d not in self.allowed_days:
            return "Calm"
        return self.labels.get(day, default)


def run_filtered(cfg: Cfg, which: str, allowed_days: set[pd.Timestamp]) -> dict:
    import futures._validated_core as VC
    import global_index.deploy_sim as DS
    import raits.strategies.trend_follow as tf

    stat = {"n": 0, "tot": 0.0}
    orig, fn = patched_engine(cfg, stat)
    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]

    def filtered_fn(df, labels, cost, **kwargs):
        return fn(df, FilteredLabels(labels, allowed_days), cost, **kwargs)

    VC.backtest_swing_tf = filtered_fn
    buf = io.StringIO()
    try:
        old_argv = sys.argv
        sys.argv = ["deploy_sim"] + list(ARGV[which])
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv
    finally:
        VC.backtest_swing_tf = orig
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed

    out = buf.getvalue()
    net = calmar = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("net $"):
            net = float(s.split("net $")[1].split("|")[0].strip().replace(",", ""))
            calmar = float(s.split("Calmar")[1].split("|")[0].strip())
    maxdd, maxdd_pct, halts = parse_extra(out)
    return {
        "net": net,
        "calmar": calmar,
        "maxdd_pct": maxdd_pct,
        "halts": halts,
        "fix_n": stat["n"],
        "fix_dollars": stat["tot"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--filters", nargs="+", default=["trend200", "trend_stack", "ret20_pos", "rv20_lt25", "dd63_gt-8", "trend_ret", "trend_lowvol", "stack_lowvol"])
    ap.add_argument("--which", nargs="+", default=["baseline", "vault2324", "vault2025", "vault2026"])
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--stop-basis", type=float, default=2.0)
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    args = ap.parse_args()

    f = feature_frame(args.spy_csv)
    cfg = Cfg(fix_fill=True, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              ema=args.ema, stop_basis=args.stop_basis)

    for filt in args.filters:
        days = mask_for(f, filt)
        vals = []
        for which in args.which:
            r = run_filtered(cfg, which, days)
            vals.append(r["calmar"] or 0)
            print(
                "{:<12} {:<9} net=${:>8,.0f} calmar={:>6.2f} maxdd={:>5.1f}% "
                "halts={:<4} fix_n={:<4} fix=${:>8,.0f}".format(
                    filt, which, r["net"] or 0, r["calmar"] or 0,
                    r["maxdd_pct"] or 0, r["halts"] if r["halts"] is not None else -1,
                    r["fix_n"], r["fix_dollars"],
                ),
                flush=True,
            )
        print(f"{filt:<12} min_calmar={min(vals):.2f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
