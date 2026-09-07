from __future__ import annotations

import argparse
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.harness import ARM_LIVE, Cfg, run_deploy
from scratch.regime_candidate_probe import parse_extra


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allowed", nargs="+", required=True)
    ap.add_argument("--direction", choices=["LONG", "SHORT"], required=True)
    ap.add_argument("--which", nargs="+", default=["baseline", "floor", "vault2324", "vault2025", "vault2026"])
    ap.add_argument("--ema", type=int, default=50)
    ap.add_argument("--stop-basis", type=float, default=2.0)
    args = ap.parse_args()

    import raits.strategies.trend_follow as tf

    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal

    def filtered_generate(self, *a, **kw):
        sig = old_generate(self, *a, **kw)
        if sig and sig.get("direction") != args.direction:
            return None
        return sig

    tf.DEFAULT_CONFIG["allowed_regimes"] = list(args.allowed)
    tf.TrendFollowStrategy.generate_signal = filtered_generate
    try:
        cfg = Cfg(
            fix_fill=True,
            arm_hours=ARM_LIVE,
            ratchet=False,
            roska4_only=False,
            ema=args.ema,
            stop_basis=args.stop_basis,
        )
        for which in args.which:
            r = run_deploy(cfg, which)
            _, maxdd_pct, halts = parse_extra(r["out"])
            print(
                "allowed={} dir={} {:<9} net=${:>8,.0f} calmar={:>6.2f} "
                "maxdd={:>5.1f}% halts={:<4} fix_n={:<4} fix=${:>8,.0f}".format(
                    ",".join(args.allowed),
                    args.direction,
                    which,
                    r["net"] or 0,
                    r["calmar"] or 0,
                    maxdd_pct or 0,
                    halts if halts is not None else -1,
                    r["sua_n"],
                    r["sua_tot"],
                )
            )
    finally:
        tf.TrendFollowStrategy.generate_signal = old_generate
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
