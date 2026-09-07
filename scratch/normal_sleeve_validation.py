from __future__ import annotations

import argparse
import io
import math
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.directional_market_filter_probe import allowed_short_days, feature_frame
from scratch.harness import ARM_LIVE, Cfg, patched_engine


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

    class NoStressEngine:
        def backtest_basket(self, dfs, labels, costs):
            return {name: [] for name in dfs}

    SM.StressMidEngine = NoStressEngine
    if case.get("swing_cap") is not None:
        NEM.DEFAULT_CLUSTERS["roska4_swing"] = NEM.ClusterBudget(
            "roska4_swing",
            max_gross_pct=float(case["swing_cap"]),
            max_net_pct=case.get("swing_net_cap"),
        )

    argv = list(H.ARGV[which])
    argv = [x for x in argv if x != "--include-stress"]
    if not case.get("include_nkd", True) and "--no-nkd" not in argv:
        argv.append("--no-nkd")
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
    m.update(fix_n=stat["n"], fix_dollars=stat["tot"], out=buf.getvalue())
    return m


def cases() -> list[tuple[str, dict]]:
    base = {
        "ema": 50,
        "stop_basis": 2.0,
        "max_hold_days": 5,
        "short_filter": "below_sma50",
        "include_nkd": True,
        "tf_config": {},
    }
    out = [("current", base)]
    for name, patch in [
        ("r4_no_nkd", {"include_nkd": False}),
        ("ema40", {"ema": 40}),
        ("ema60", {"ema": 60}),
        ("stop15", {"stop_basis": 1.5}),
        ("stop25", {"stop_basis": 2.5}),
        ("hold3", {"max_hold_days": 3}),
        ("hold4", {"max_hold_days": 4}),
        ("hold7", {"max_hold_days": 7}),
        ("short_weak_combo", {"short_filter": "weak_combo"}),
        ("short_not_strong_bull", {"short_filter": "not_strong_bull"}),
        ("nkd_ema20", {"nkd_ema": 20}),
        ("nkd_mult30", {"nkd_mult": 3.0}),
        ("cap025", {"swing_cap": 0.025, "swing_net_cap": 0.025}),
        ("cap050", {"swing_cap": 0.05, "swing_net_cap": 0.044}),
        ("cap075", {"swing_cap": 0.075, "swing_net_cap": 0.075}),
    ]:
        c = dict(base)
        c.update(patch)
        if "tf_config" in patch:
            c["tf_config"] = patch["tf_config"]
        out.append((name, c))
    return out


def bootstrap(values: np.ndarray, n_iter: int, rng: np.random.Generator) -> dict:
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return {"p_pos": 0.0, "p5": 0.0, "p50": 0.0, "p95": 0.0}
    draws = rng.choice(values, size=(n_iter, len(values)), replace=True).sum(axis=1)
    return {
        "p_pos": float((draws > 0).mean()),
        "p5": float(np.percentile(draws, 5)),
        "p50": float(np.percentile(draws, 50)),
        "p95": float(np.percentile(draws, 95)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--windows", nargs="+", default=None)
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--cases", nargs="+", default=None)
    args = ap.parse_args()

    if args.windows:
        base = [
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
        args.which = []
        for w in args.windows:
            start_year, end_year = w.split(":", 1)
            key = f"custom_{start_year}_{end_year}"
            H.ARGV[key] = base + [
                "--start",
                f"{start_year}-01-01",
                "--end",
                f"{end_year}-12-31",
                "--hmm-fit-end",
                "2022-12-31",
            ]
            args.which.append(key)

    selected = cases()
    if args.cases:
        wanted = set(args.cases)
        selected = [(n, c) for n, c in selected if n in wanted]

    print("Normal sleeve validation:")
    print("  base: Normal-only TF, EMA50, 2x daily ATR stop, corrected/live fill, SHORT only below SPY SMA50 D-1")
    print("  Stress disabled. NKD included unless case says r4_no_nkd.")

    all_rows = {}
    for which in args.which:
        rows = []
        for name, case in selected:
            m = run_case(which, args, case)
            rows.append((name, m))
            all_rows[(which, name)] = m
            print(
                "{:<20} {:<9} net=${:>8,.0f} pf={:>4.2f} sharpe={:>5.2f} calmar={:>5.2f} maxdd={:>5.1f}% fix_n={} fix=${:,.0f}".format(
                    name,
                    which,
                    m.get("net", 0.0),
                    m.get("pf", 0.0),
                    m.get("sharpe", 0.0),
                    m.get("calmar", 0.0),
                    m.get("maxdd_pct", 0.0),
                    m.get("fix_n", 0),
                    m.get("fix_dollars", 0.0),
                ),
                flush=True,
            )
        best = sorted(rows, key=lambda x: (x[1].get("calmar", -999), x[1].get("net", -999)), reverse=True)[:5]
        print(f"\nTop {which}:")
        for name, m in best:
            print(
                "  {:<20} net=${:>8,.0f} pf={:>4.2f} sharpe={:>5.2f} calmar={:>5.2f} maxdd={:>5.1f}%".format(
                    name,
                    m.get("net", 0.0),
                    m.get("pf", 0.0),
                    m.get("sharpe", 0.0),
                    m.get("calmar", 0.0),
                    m.get("maxdd_pct", 0.0),
                )
            )
        print()

    if all((w, "current") in all_rows for w in args.which):
        print("=== current summary ===")
        for which in args.which:
            m = all_rows[(which, "current")]
            print(f"{which:<9} net=${m.get('net',0):>8,.0f} pf={m.get('pf',0):.2f} sharpe={m.get('sharpe',0):.2f} calmar={m.get('calmar',0):.2f} maxdd={m.get('maxdd_pct',0):.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
