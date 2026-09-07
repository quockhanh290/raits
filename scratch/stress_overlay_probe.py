from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.harness import ARM_LIVE, Cfg, patched_engine
from scratch.market_filter_probe import FilteredLabels
from scratch.regime_candidate_probe import parse_extra


def run_overlay(cfg: Cfg, which: str, allowed: list[str]) -> dict:
    import futures._validated_core as VC
    import global_index.deploy_sim as DS
    import raits.strategies.trend_follow as tf

    stat = {"n": 0, "tot": 0.0}
    orig, fn = patched_engine(cfg, stat)
    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    tf.DEFAULT_CONFIG["allowed_regimes"] = list(allowed)
    VC.backtest_swing_tf = fn

    argv = list(H.ARGV[which])
    if "--include-stress" not in argv:
        argv.append("--include-stress")

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
        VC.backtest_swing_tf = orig
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed

    out = buf.getvalue()
    net = calmar = None
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("net $"):
            net = float(s.split("net $")[1].split("|")[0].strip().replace(",", ""))
            calmar = float(s.split("Calmar")[1].split("|")[0].strip())
    _, maxdd_pct, halts = parse_extra(out)
    return dict(net=net, calmar=calmar, maxdd_pct=maxdd_pct, halts=halts,
                fix_n=stat["n"], fix_dollars=stat["tot"], out=out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["baseline", "floor", "vault2324", "vault2025", "vault2026"])
    ap.add_argument("--allowed", nargs="+", default=["Normal"])
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--stop-basis", type=float, default=2.0)
    args = ap.parse_args()

    cfg = Cfg(fix_fill=True, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              ema=args.ema, stop_basis=args.stop_basis)
    for which in args.which:
        r = run_overlay(cfg, which, args.allowed)
        print(
            "stress_overlay {:<9} swing_allowed={} net=${:>8,.0f} calmar={:>6.2f} "
            "maxdd={:>5.1f}% halts={:<4} fix_n={:<4} fix=${:>8,.0f}".format(
                which, ",".join(args.allowed), r["net"] or 0, r["calmar"] or 0,
                r["maxdd_pct"] or 0, r["halts"] if r["halts"] is not None else -1,
                r["fix_n"], r["fix_dollars"],
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
