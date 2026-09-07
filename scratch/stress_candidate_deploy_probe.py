from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from futures.basket import BASKET
from scratch.directional_market_filter_probe import allowed_short_days, feature_frame
from scratch.harness import ARM_LIVE, Cfg, patched_engine
from scratch.regime_candidate_probe import parse_extra
from scratch.stress_path_excavation import confirmed_short, day_context


def stress_candidate_engine_class(variant: str, instruments: set[str]):
    class StressCandidateEngine:
        def backtest(self, df, labels, cost):
            raise NotImplementedError("use backtest_basket")

        def backtest_basket(self, dfs: dict, labels, costs: dict):
            contexts = {}
            frames = {}
            for inst, df in dfs.items():
                for day_ts, day in df.groupby(df.index.normalize()):
                    key = pd.Timestamp(day_ts).tz_localize(None).normalize()
                    if labels.get(key) != "Stress":
                        continue
                    ctx = day_context(day)
                    if ctx:
                        contexts[(key, inst)] = ctx
                        frames[(key, inst)] = day

            out = {name: [] for name in dfs}
            for (day, inst), ctx in contexts.items():
                if inst not in instruments:
                    continue
                peer = [contexts.get((day, i)) for i in BASKET]
                peer = [p for p in peer if p is not None]
                below_count = sum(1 for p in peer if p["sig_close"] < p["vwap"] and p["sig_close"] < p["open"])
                range_big_count = sum(1 for p in peer if p["range_pct"] >= 0.0075)
                if variant == "breadth3":
                    ok = below_count >= 3
                elif variant == "wide_range3":
                    ok = below_count >= 3 and range_big_count >= 3
                else:
                    raise ValueError(f"unknown stress variant {variant}")
                if not ok:
                    continue
                day1 = frames[(day, inst)]
                tr = confirmed_short(day1, ctx, rr=2.0)
                if not tr:
                    continue
                pv = BASKET[inst].point_value
                pnl = (tr["entry"] - tr["exit"]) * pv - costs[inst].round_turn_cost()
                out[inst].append(dict(
                    day=day.date(),
                    exit_day=day.date(),
                    regime="Stress",
                    direction="SHORT",
                    entry=round(tr["entry"], 2),
                    exit=round(tr["exit"], 2),
                    points=round(tr["entry"] - tr["exit"], 2),
                    pnl=round(pnl, 2),
                    reason=f"STRESS_{variant}",
                    entry_time=tr["entry_time"],
                    exit_time=tr["exit_time"],
                    exit_reason=tr["reason"],
                ))
            return out

    return StressCandidateEngine


def run_with_patches(which: str, include_stress: bool, args) -> dict:
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import global_index.deploy_sim as DS
    import global_index.net_exposure_multi as NEM
    import raits.strategies.trend_follow as tf

    stat = {"n": 0, "tot": 0.0}
    cfg = Cfg(
        fix_fill=True,
        arm_hours=ARM_LIVE,
        ratchet=False,
        roska4_only=False,
        ema=50,
        stop_basis=2.0,
    )
    orig_bt, bt_fn = patched_engine(cfg, stat)
    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    old_stress_cls = SM.StressMidEngine
    old_clusters = dict(NEM.DEFAULT_CLUSTERS)

    short_days = allowed_short_days(feature_frame(args.spy_csv), "below_sma50")

    def filtered_generate(self, *a, **kw):
        sig = old_generate(self, *a, **kw)
        if not sig or sig.get("direction") != "SHORT":
            return sig
        resume_bar = a[1]
        day = pd.Timestamp(resume_bar.name).tz_localize(None).normalize()
        return sig if day in short_days else None

    VC.backtest_swing_tf = bt_fn
    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
    tf.TrendFollowStrategy.generate_signal = filtered_generate
    SM.StressMidEngine = stress_candidate_engine_class(args.variant, set(args.instruments))
    if args.stress_cap is not None:
        NEM.DEFAULT_CLUSTERS["roska4_stress"] = NEM.ClusterBudget(
            "roska4_stress", max_gross_pct=args.stress_cap, max_net_pct=None
        )

    argv = list(H.ARGV[which])
    if include_stress and "--include-stress" not in argv:
        argv.append("--include-stress")
    if not include_stress:
        argv = [x for x in argv if x != "--include-stress"]

    buf = io.StringIO()
    try:
        old_argv = sys.argv
        sys.argv = ["deploy_sim"] + argv
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv
    finally:
        VC.backtest_swing_tf = orig_bt
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
        tf.TrendFollowStrategy.generate_signal = old_generate
        SM.StressMidEngine = old_stress_cls
        NEM.DEFAULT_CLUSTERS.clear()
        NEM.DEFAULT_CLUSTERS.update(old_clusters)

    out = buf.getvalue()
    net = calmar = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("net $"):
            net = float(s.split("net $")[1].split("|")[0].strip().replace(",", ""))
            calmar = float(s.split("Calmar")[1].split("|")[0].strip())
    _, maxdd_pct, halts = parse_extra(out)
    return {
        "net": net,
        "calmar": calmar,
        "maxdd_pct": maxdd_pct,
        "halts": halts,
        "fix_n": stat["n"],
        "fix_dollars": stat["tot"],
        "out": out,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["baseline", "floor", "vault2324", "vault2025", "vault2026"])
    ap.add_argument("--variant", choices=["wide_range3", "breadth3"], default="wide_range3")
    ap.add_argument("--instruments", nargs="+", default=["MNQ", "MES"])
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--details", action="store_true")
    ap.add_argument("--stress-cap", type=float, default=None, help="override roska4_stress gross cap, e.g. 0.05")
    args = ap.parse_args()

    for which in args.which:
        base = run_with_patches(which, include_stress=False, args=args)
        stress = run_with_patches(which, include_stress=True, args=args)
        print(
            "{:<9} no_stress net=${:>8,.0f} calmar={:>5.2f} maxdd={:>5.1f}% halts={:<4} | "
            "+stress({},{}) net=${:>8,.0f} calmar={:>5.2f} maxdd={:>5.1f}% halts={:<4} delta=${:>7,.0f}".format(
                which,
                base["net"] or 0,
                base["calmar"] or 0,
                base["maxdd_pct"] or 0,
                base["halts"] if base["halts"] is not None else -1,
                args.variant,
                "+".join(args.instruments),
                stress["net"] or 0,
                stress["calmar"] or 0,
                stress["maxdd_pct"] or 0,
                stress["halts"] if stress["halts"] is not None else -1,
                (stress["net"] or 0) - (base["net"] or 0),
            ),
            flush=True,
        )
        if args.details:
            print("\n--- no_stress deploy output ---")
            print(base["out"])
            print("\n--- with_stress deploy output ---")
            print(stress["out"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
