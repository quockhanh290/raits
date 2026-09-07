from __future__ import annotations

import argparse
import io
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.directional_market_filter_probe import allowed_short_days, feature_frame
from scratch.harness import ARM_LIVE, Cfg, patched_engine
from scratch.stress_candidate_deploy_probe import stress_candidate_engine_class


METRIC_RE = re.compile(
    r"net\s+\$([\-\d,]+)\s+\|\s+Calmar\s+([\-\d.]+)\s+\|\s+PF\s+([\-\din\.]+)\s+\|\s+Sharpe\s+([\-\d.]+)"
)
MAXDD_RE = re.compile(r"MaxDD\s+\$([\d,]+)\s+\(([\d.]+)%\)")


def parse_metrics(out: str) -> dict:
    m = {}
    for line in out.splitlines():
        mm = METRIC_RE.search(line)
        if mm:
            m.update(
                net=float(mm.group(1).replace(",", "")),
                calmar=float(mm.group(2)),
                pf=float("inf") if mm.group(3) == "inf" else float(mm.group(3)),
                sharpe=float(mm.group(4)),
            )
        dd = MAXDD_RE.search(line)
        if dd:
            m.update(maxdd=float(dd.group(1).replace(",", "")), maxdd_pct=float(dd.group(2)))
    return m


def run_case(which: str, args, case: dict) -> dict:
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import futures.swing_tf as ST
    import global_index.deploy_sim as DS
    import global_index.net_exposure_multi as NEM
    import raits.strategies.trend_follow as tf

    stat = {"n": 0, "tot": 0.0}
    cfg = Cfg(
        fix_fill=True,
        arm_hours=ARM_LIVE,
        ratchet=False,
        roska4_only=False,
        ema=int(case.get("ema", 50)),
        stop_basis=float(case.get("stop_basis", 2.0)),
    )
    orig_bt, bt_fn = patched_engine(cfg, stat)
    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    old_defaults = dict(tf.DEFAULT_CONFIG)
    old_stress_cls = SM.StressMidEngine
    old_clusters = dict(NEM.DEFAULT_CLUSTERS)
    old_swing_cls = ST.SwingTFEngine

    short_days = allowed_short_days(feature_frame(args.spy_csv), case.get("short_filter", "below_sma50"))

    def filtered_generate(self, *a, **kw):
        sig = old_generate(self, *a, **kw)
        if not sig or sig.get("direction") != "SHORT":
            return sig
        resume_bar = a[1]
        day = pd.Timestamp(resume_bar.name).tz_localize(None).normalize()
        return sig if day in short_days else None

    class PatchedSwingTFEngine:
        def __init__(self):
            self._inner = old_swing_cls(
                ema_period=30,
                chandelier_atr_mult=2.5,
                max_hold_days=int(case.get("max_hold_days", 5)),
            )

        def backtest_basket(self, *a, **kw):
            return self._inner.backtest_basket(*a, **kw)

    VC.backtest_swing_tf = bt_fn
    tf.DEFAULT_CONFIG.update(case.get("tf_config", {}))
    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
    tf.TrendFollowStrategy.generate_signal = filtered_generate
    ST.SwingTFEngine = PatchedSwingTFEngine
    SM.StressMidEngine = stress_candidate_engine_class(args.variant, set(args.instruments))
    if args.stress_cap is not None:
        NEM.DEFAULT_CLUSTERS["roska4_stress"] = NEM.ClusterBudget(
            "roska4_stress", max_gross_pct=args.stress_cap, max_net_pct=None
        )

    argv = list(H.ARGV[which])
    if "--include-stress" not in argv:
        argv.append("--include-stress")
    if case.get("nkd_ema") is not None:
        argv.extend(["--nkd-ema", str(case["nkd_ema"])])
    if case.get("nkd_mult") is not None:
        argv.extend(["--nkd-mult", str(case["nkd_mult"])])

    buf = io.StringIO()
    try:
        old_argv = sys.argv
        sys.argv = ["deploy_sim"] + argv
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        except Exception as exc:
            print(f"ERROR running {which} case={case}: {type(exc).__name__}: {exc}", file=sys.stderr)
            raise
        finally:
            sys.argv = old_argv
    finally:
        VC.backtest_swing_tf = orig_bt
        tf.DEFAULT_CONFIG.clear()
        tf.DEFAULT_CONFIG.update(old_defaults)
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
        tf.TrendFollowStrategy.generate_signal = old_generate
        SM.StressMidEngine = old_stress_cls
        NEM.DEFAULT_CLUSTERS.clear()
        NEM.DEFAULT_CLUSTERS.update(old_clusters)
        ST.SwingTFEngine = old_swing_cls

    m = parse_metrics(buf.getvalue())
    m.update(fix_n=stat["n"], fix_dollars=stat["tot"])
    return m


def cases() -> list[tuple[str, dict]]:
    base = {
        "ema": 50,
        "stop_basis": 2.0,
        "max_hold_days": 5,
        "short_filter": "below_sma50",
        "tf_config": {},
    }
    out = [("current", base)]
    for k, v in [
        ("ema_prox_003", {"tf_config": {"ema_proximity_pct": 0.003}}),
        ("ema_prox_007", {"tf_config": {"ema_proximity_pct": 0.007}}),
        ("vol_surge_11", {"tf_config": {"resume_volume_surge_mult": 1.1}}),
        ("vol_surge_15", {"tf_config": {"resume_volume_surge_mult": 1.5}}),
        ("near_hl_pct_02", {"tf_config": {"near_hod_lod_pct": 0.02}}),
        ("near_hl_pct_04", {"tf_config": {"near_hod_lod_pct": 0.04}}),
        ("max_hold_3", {"max_hold_days": 3}),
        ("max_hold_7", {"max_hold_days": 7}),
        ("short_weak_combo", {"short_filter": "weak_combo"}),
        ("short_not_strong_bull", {"short_filter": "not_strong_bull"}),
        ("nkd_ema_20", {"nkd_ema": 20}),
        ("nkd_mult_3", {"nkd_mult": 3.0}),
    ]:
        c = dict(base)
        c.update(v)
        if "tf_config" in v:
            c["tf_config"] = v["tf_config"]
        out.append((k, c))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["baseline"])
    ap.add_argument("--variant", choices=["breadth3", "wide_range3"], default="breadth3")
    ap.add_argument("--instruments", nargs="+", default=["MNQ", "MES"])
    ap.add_argument("--stress-cap", type=float, default=0.075)
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--cases", nargs="+", default=None)
    args = ap.parse_args()

    for which in args.which:
        rows = []
        selected = cases()
        if args.cases:
            wanted = set(args.cases)
            selected = [(n, c) for n, c in selected if n in wanted]
        for name, case in selected:
            m = run_case(which, args, case)
            rows.append((name, m))
            print(
                "{:<18} {:<9} net=${:>8,.0f} pf={:>4.2f} sharpe={:>5.2f} calmar={:>5.2f} maxdd={:>5.1f}% fix_n={}".format(
                    name,
                    which,
                    m.get("net", 0.0),
                    m.get("pf", 0.0),
                    m.get("sharpe", 0.0),
                    m.get("calmar", 0.0),
                    m.get("maxdd_pct", 0.0),
                    m.get("fix_n", 0),
                ),
                flush=True,
            )
        best = sorted(rows, key=lambda x: (x[1].get("calmar", -999), x[1].get("net", -999)), reverse=True)[:5]
        print(f"\nTop {which}:")
        for name, m in best:
            print(
                "  {:<18} net=${:>8,.0f} pf={:>4.2f} sharpe={:>5.2f} calmar={:>5.2f} maxdd={:>5.1f}%".format(
                    name,
                    m.get("net", 0.0),
                    m.get("pf", 0.0),
                    m.get("sharpe", 0.0),
                    m.get("calmar", 0.0),
                    m.get("maxdd_pct", 0.0),
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
