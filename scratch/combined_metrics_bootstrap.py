from __future__ import annotations

import argparse
import io
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
from scratch.stress_candidate_deploy_probe import stress_candidate_engine_class


METRIC_RE = re.compile(
    r"net\s+\$([\-\d,]+)\s+\|\s+Calmar\s+([\-\d.]+)\s+\|\s+PF\s+([\-\din\.]+)\s+\|\s+Sharpe\s+([\-\d.]+)"
)
MAXDD_RE = re.compile(r"MaxDD\s+\$([\d,]+)\s+\(([\d.]+)%\)")


def metrics(daily: pd.Series) -> dict:
    daily = daily.sort_index()
    if daily.empty:
        return {"net": 0.0, "pf": 0.0, "calmar": 0.0, "sharpe": 0.0, "maxdd": 0.0}
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    wins = float(daily[daily > 0].sum())
    losses = float(-daily[daily < 0].sum())
    return {
        "net": float(daily.sum()),
        "pf": wins / losses if losses > 1e-9 else float("inf"),
        "calmar": (float(daily.sum()) / span) / dd if dd > 1e-9 else float("inf"),
        "sharpe": float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 1e-9 else 0.0,
        "maxdd": dd,
    }


def parse_metrics(out: str) -> dict:
    parsed = {}
    for line in out.splitlines():
        m = METRIC_RE.search(line)
        if m:
            parsed.update(
                net=float(m.group(1).replace(",", "")),
                calmar=float(m.group(2)),
                pf=float("inf") if m.group(3) == "inf" else float(m.group(3)),
                sharpe=float(m.group(4)),
            )
        d = MAXDD_RE.search(line)
        if d:
            parsed.update(maxdd=float(d.group(1).replace(",", "")), maxdd_pct=float(d.group(2)))
    return parsed


def run_capture(which: str, include_stress: bool, args) -> tuple[dict, pd.Series, str]:
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import global_index.deploy_sim as DS
    import global_index.net_exposure_multi as NEM
    import raits.strategies.trend_follow as tf

    cfg = Cfg(
        fix_fill=True,
        arm_hours=ARM_LIVE,
        ratchet=False,
        roska4_only=False,
        ema=50,
        stop_basis=2.0,
    )
    stat = {"n": 0, "tot": 0.0}
    orig_bt, bt_fn = patched_engine(cfg, stat)

    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    old_stress_cls = SM.StressMidEngine
    old_clusters = dict(NEM.DEFAULT_CLUSTERS)
    old_replay = DS.replay
    captures: list[pd.Series] = []

    short_days = allowed_short_days(feature_frame(args.spy_csv), "below_sma50")

    def filtered_generate(self, *a, **kw):
        sig = old_generate(self, *a, **kw)
        if not sig or sig.get("direction") != "SHORT":
            return sig
        resume_bar = a[1]
        day = pd.Timestamp(resume_bar.name).tz_localize(None).normalize()
        return sig if day in short_days else None

    def capture_replay(*a, **kw):
        daily, st = old_replay(*a, **kw)
        captures.append(daily.copy())
        return daily, st

    VC.backtest_swing_tf = bt_fn
    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
    tf.TrendFollowStrategy.generate_signal = filtered_generate
    SM.StressMidEngine = stress_candidate_engine_class(args.variant, set(args.instruments))
    DS.replay = capture_replay
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
        DS.replay = old_replay

    daily = captures[-1] if captures else pd.Series(dtype=float)
    return parse_metrics(buf.getvalue()), daily, buf.getvalue()


def block_bootstrap(daily: pd.Series, n_iter: int, block: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    x = daily.sort_index().astype(float)
    if x.empty:
        return {}
    vals = x.to_numpy()
    n = len(vals)
    idx = x.index
    stats = []
    for _ in range(n_iter):
        pieces = []
        while sum(len(p) for p in pieces) < n:
            start = int(rng.integers(0, max(n - block + 1, 1)))
            pieces.append(vals[start : min(start + block, n)])
        sample = np.concatenate(pieces)[:n]
        s = pd.Series(sample, index=idx)
        stats.append(metrics(s))
    df = pd.DataFrame(stats)
    return {
        "p_net_gt0": float((df["net"] > 0).mean()),
        "p_sharpe_gt0": float((df["sharpe"] > 0).mean()),
        "net_p05": float(df["net"].quantile(0.05)),
        "net_p50": float(df["net"].quantile(0.50)),
        "net_p95": float(df["net"].quantile(0.95)),
        "sharpe_p05": float(df["sharpe"].quantile(0.05)),
        "sharpe_p50": float(df["sharpe"].quantile(0.50)),
        "calmar_p05": float(df["calmar"].quantile(0.05)),
        "pf_p05": float(df["pf"].replace(np.inf, np.nan).quantile(0.05)),
    }


def fmt_money(x: float) -> str:
    return "${:,.0f}".format(x)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["baseline", "floor", "vault2324", "vault2025", "vault2026"])
    ap.add_argument("--variant", choices=["breadth3", "wide_range3"], default="breadth3")
    ap.add_argument("--instruments", nargs="+", default=["MNQ", "MES"])
    ap.add_argument("--stress-cap", type=float, default=0.075)
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--block", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--yearly", action="store_true")
    args = ap.parse_args()

    for which in args.which:
        for include_stress in [False, True]:
            m, daily, _ = run_capture(which, include_stress, args)
            b = block_bootstrap(daily, args.bootstrap, args.block, args.seed)
            tag = "with_stress" if include_stress else "no_stress "
            print(
                "{:<9} {} net={} pf={:.2f} sharpe={:.2f} calmar={:.2f} maxdd={:.1f}% | "
                "boot p(net>0)={:.3f} p(sh>0)={:.3f} net5/50/95={}/{}/{} sh5={:.2f} cal5={:.2f} pf5={:.2f}".format(
                    which,
                    tag,
                    fmt_money(m.get("net", 0.0)),
                    m.get("pf", 0.0),
                    m.get("sharpe", 0.0),
                    m.get("calmar", 0.0),
                    m.get("maxdd_pct", 0.0),
                    b.get("p_net_gt0", 0.0),
                    b.get("p_sharpe_gt0", 0.0),
                    fmt_money(b.get("net_p05", 0.0)),
                    fmt_money(b.get("net_p50", 0.0)),
                    fmt_money(b.get("net_p95", 0.0)),
                    b.get("sharpe_p05", 0.0),
                    b.get("calmar_p05", 0.0),
                    b.get("pf_p05", 0.0),
                ),
                flush=True,
            )
            if args.yearly:
                for year, g in daily.groupby(daily.index.year):
                    ym = metrics(g)
                    print(
                        "  year={} net={} pf={:.2f} sharpe={:.2f} calmar={:.2f} maxdd=${:,.0f}".format(
                            year,
                            fmt_money(ym["net"]),
                            ym["pf"],
                            ym["sharpe"],
                            ym["calmar"],
                            ym["maxdd"],
                        ),
                        flush=True,
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
