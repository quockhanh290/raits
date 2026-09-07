"""
Production-equivalent Normal policy anchor after engine gap-fill fix.

Scratch-only harness: runs deploy_sim through the real engine path after the
gap-through fix, with Stress disabled and Normal-only filtering from
normal_sleeve_validation. It monkeypatches only cluster budgets in-memory to
measure the strict 2.5% Ro-4 cap candidate; no files outside scratch/docs are
written by this script.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.normal_sleeve_validation import run_case


def free_caches():
    import gc
    import scratch.harness as H
    import futures._validated_core as VC

    H._CACHE.clear()
    VC._SWING_CACHE.clear()
    gc.collect()


def parse_halts(out: str) -> int:
    for ln in out.splitlines():
        if "circuit-breaker halts" in ln:
            try:
                return int(ln.split(":")[-1].strip())
            except Exception:
                return -1
    return -1


def run(which: str, args, case: dict) -> dict:
    m = run_case(which, args, case)
    m["halts"] = parse_halts(m.get("out", ""))
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--out", default="scratch/normal_sleeve_enginefix_policy_anchor_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_sleeve_enginefix_policy_anchor_20260821.json")
    a = ap.parse_args()

    base = {
        "ema": 50,
        "stop_basis": 2.0,
        "max_hold_days": 5,
        "short_filter": "below_sma50",
        "include_nkd": True,
        "tf_config": {},
    }
    cases = [
        ("current_cap_enginefix", dict(base)),
        ("strict025_enginefix", dict(base, swing_cap=0.025, swing_net_cap=0.025)),
        ("strict030_enginefix", dict(base, swing_cap=0.030, swing_net_cap=0.030)),
    ]

    report = []
    results = {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    emit("=" * 112)
    emit("NORMAL SLEEVE - ENGINE-FIX POLICY ANCHOR (scratch only)")
    emit("=" * 112)
    emit("Real engine path after gap-through fix. Stress disabled. NKD original is now corrected in-engine.")
    emit("")

    for which in a.which:
        emit("#" * 112)
        emit("WINDOW: " + which)
        emit("#" * 112)
        rows = []
        for name, case in cases:
            m = run(which, a, case)
            rows.append((name, m))
            free_caches()
            emit("  completed " + name)
        results[which] = {name: {k: v for k, v in m.items() if k != "out"} for name, m in rows}
        emit("  {:<24} {:>10} {:>5} {:>7} {:>7} {:>9} {:>8} {:>7} {:>7}".format(
            "case", "net$", "PF", "Sharpe", "Calmar", "MaxDD$", "MaxDD%", "fix_n", "halts"))
        for name, m in rows:
            emit("  {:<24} {:>10,.0f} {:>5.2f} {:>7.2f} {:>7.2f} {:>9,.0f} {:>8.1f} {:>7} {:>7}".format(
                name, m.get("net", 0.0), m.get("pf", 0.0), m.get("sharpe", 0.0),
                m.get("calmar", 0.0), m.get("maxdd", 0.0), m.get("maxdd_pct", 0.0),
                m.get("fix_n", 0), m.get("halts", -1)))
        emit("")

    Path(a.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {a.out} and {a.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
