"""Stage 5ZZZ-M — what parameters does the Swing artifact engine actually run with?

A structured trace, not prints. Every call into the replacement engine records the parameters it
was ASKED for and the parameters it USED, so the two can be compared instead of assumed.

Suspected root cause, from `scratch/harness.py:315`:

    if cfg.ema is not None and ema_period == 30:
        ema_period = cfg.ema

The regeneration builds `Cfg(..., ema=50, stop_basis=2.0)`. If that line is what it looks like,
then a request for ema=30 is silently rewritten to 50, a request for 50 is already 50, and the
two produce identical artifacts - while 10 and 20 pass through untouched. That is exactly the
pattern Stage 5ZZZ-L measured.

Run:  python scratch/track1_stage5zzzm_param_trace_20260829.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd

CASES = [("A_default", 30, 2.5, 5),
         ("B_wfo_winner", 50, 2.0, 5),
         ("C_ema10", 10, 2.0, 5),
         ("D_ema20", 20, 2.0, 5)]


def trace_engine():
    """Wrap the harness's replacement engine and record asked-vs-used per call."""
    import scratch.harness as H

    calls: list[dict] = []
    orig_patched_engine = H.patched_engine

    def traced(cfg, stat):
        orig_bt, fn = orig_patched_engine(cfg, stat)

        def wrapper(df, labels, cost, *, ema_period=20, chandelier_atr_mult=3.0,
                    max_hold_days=5, **kw):
            # Recompute the harness's own substitution rule so the trace shows what it will do.
            effective_ema = ema_period
            if cfg.ema is not None and ema_period == 30:
                effective_ema = cfg.ema
            calls.append({
                "asked_ema": ema_period, "used_ema": effective_ema,
                "asked_mult": chandelier_atr_mult, "max_hold": max_hold_days,
                "cfg_ema": cfg.ema, "cfg_stop_basis": cfg.stop_basis,
                "cfg_ratchet": cfg.ratchet,
                "substituted": effective_ema != ema_period,
                "rows": len(df),
            })
            return fn(df, labels, cost, ema_period=ema_period,
                      chandelier_atr_mult=chandelier_atr_mult,
                      max_hold_days=max_hold_days, **kw)

        return orig_bt, wrapper

    H.patched_engine = traced
    return calls, orig_patched_engine


def main() -> int:
    import scratch.harness as H

    calls, orig = trace_engine()
    results = {}
    try:
        for name, ema, mult, hold in CASES:
            calls.clear()
            import subprocess
            # a separate process per case keeps module-level caches from crossing cases
            p = subprocess.run(
                [sys.executable, "scratch/track1_stage5zzzh_swing_d1_regen_20260829.py",
                 "--which", "vault2026", "--ema", str(ema), "--mult", str(mult),
                 "--suffix", f"m_{name}"],
                capture_output=True, text=True, timeout=1800)
            art = Path(f"scratch/normal_promotion_trades_vault2026_m_{name}_20260829.json")
            import hashlib
            digest = (hashlib.sha256(art.read_bytes()).hexdigest()[:16]
                      if art.exists() else "MISSING")
            engine_line = [l for l in p.stdout.splitlines()
                           if "engine actually received" in l]
            counts = {}
            if art.exists():
                d = json.loads(art.read_text(encoding="utf-8"))
                counts = {i: len(v) for i, v in d.get("filtered", {}).items()}
            results[name] = {"requested": {"ema": ema, "mult": mult, "hold": hold},
                             "artifact_sha16": digest,
                             "engine_line": engine_line[-1].strip() if engine_line else None,
                             "filtered_counts": counts}
            print(f"  {name:14s} asked ema={ema:>2} mult={mult}  -> sha {digest}  "
                  f"{counts}", flush=True)
    finally:
        H.patched_engine = orig

    print("\n=== the harness substitution rule, evaluated directly ===")
    import scratch.harness as H2
    cfg = H2.Cfg(fix_fill=False, arm_hours=H2.ARM_LIVE, ratchet=False,
                 roska4_only=False, ema=50, stop_basis=2.0)
    rule = {}
    for _n, ema, _m, _h in CASES:
        used = cfg.ema if (cfg.ema is not None and ema == 30) else ema
        rule[ema] = used
        print(f"  asked ema={ema:>2}  ->  used ema={used:>2}"
              f"{'   <-- SUBSTITUTED' if used != ema else ''}")
    results["_substitution_rule"] = {str(k): v for k, v in rule.items()}
    results["_cfg"] = {"ema": cfg.ema, "stop_basis": cfg.stop_basis, "ratchet": cfg.ratchet}

    Path("scratch/track1_stage5zzzm_param_trace_20260829.json").write_text(
        json.dumps(results, indent=1), encoding="utf-8")
    print("\nwrote scratch/track1_stage5zzzm_param_trace_20260829.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
