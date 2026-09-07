"""scratch/stocks_stage0_stability_20260826.py — parameter and regime-label stability.
READ-ONLY.

This is NOT a search. Nothing here selects a parameter, and the pre-committed statement is
made before the run: **`ema_period` stays at 50 whatever this prints**, because 50 is the
value the Track 1 futures artifacts were produced under and Stage STOCKS-0 was told to
reproduce the candidate logic, not to tune it. The sweep exists to answer a different
question — *is the result a knife-edge?* — and a sweep that changes the shipped value would
be curve fitting wearing a stability label.

Two axes, and each earns its cost
---------------------------------
`ema_period` in {20, 30, 50}: the Blueprint's own WFO grid for this strategy. It also probes
something specific to the equity port. The engine computes its EMA on the SESSION's own 5-minute
bars, from the session's first bar. A futures session carries roughly 276 five-minute bars, so at
14:00 an EMA(50) has about 250 behind it. An RTH equity session carries 78, so at 14:00 the same
EMA(50) has about 54 — barely more than its own period, and still seed-dominated. If the answer
swings hard across 20/30/50, that warm-up is load-bearing and the port is fragile for a reason
that has nothing to do with edge.

`labels` x `lag`: the causal HMM (fit ends 2018-12-31) against the production freeze (fit ends
2024-12-31), each at lag 1 and lag 0. The two label sets agree on 80.3% of sessions, so this is
not a formality. Lag 0 is what `track1_params` declares for `roska4_swing`; it is measured here
and it is not the headline, because at 14:00 on D the label for D does not exist yet.

Subset
------
The first 20 symbols alphabetically. Alphabetical rather than "most liquid" or "best" on
purpose: any ranking is a choice made after seeing something, and this one is made before.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
OUT = HERE / "_stocks_stage0_stability.json"

RUNS = [
    # tag                       args
    ("ema20", ["--ema", "20", "--labels", "causal", "--lag", "1"]),
    ("ema30", ["--ema", "30", "--labels", "causal", "--lag", "1"]),
    ("ema50", ["--ema", "50", "--labels", "causal", "--lag", "1"]),
    ("prod_lag1", ["--ema", "50", "--labels", "production", "--lag", "1"]),
    ("prod_lag0", ["--ema", "50", "--labels", "production", "--lag", "0"]),
    ("causal_lag0", ["--ema", "50", "--labels", "causal", "--lag", "0"]),
]
N_SYMBOLS = 20


def main() -> int:
    rep: dict = {"subset": "first {} symbols alphabetically".format(N_SYMBOLS),
                 "pre_committed": "ema_period stays 50; this sweep does not select it",
                 "runs": {}}
    for tag, extra in RUNS:
        t0 = time.time()
        cmd = [sys.executable, str(HERE / "stocks_stage0_run_20260826.py"),
               "--configs", "B", "--max-symbols", str(N_SYMBOLS), "--tag", "stab_" + tag,
               *extra]
        print("running", tag, "...", flush=True)
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if p.returncode != 0:
            print("  FAILED\n", p.stdout[-2000:], p.stderr[-2000:])
            rep["runs"][tag] = {"error": p.stderr[-500:]}
            continue
        res = json.loads((HERE / "_stocks_stage0_results_stab_{}.json".format(tag))
                         .read_text(encoding="utf-8"))
        m = res["results"]["B"]["overall"]
        sc = res["results"]["B"]["self_check"]
        rep["runs"][tag] = dict(metrics=m, self_check_all_pass=all(
            v is True for k, v in sc.items() if isinstance(v, bool)),
            seconds=round(time.time() - t0, 1))
        print("  {:12s} trades={:4}  net=${:>10,.0f}  PF={:>5}  win={:>5}%  maxDD=${:>9,.0f}"
              "  ({:.0f}s)".format(tag, m.get("trades", 0), m.get("net", 0),
                                   str(m.get("profit_factor")), str(m.get("win_rate")),
                                   m.get("max_dd", 0), time.time() - t0), flush=True)

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print("\n=== stability summary (subset of {} symbols) ===".format(N_SYMBOLS))
    print("  {:12s} {:>7s} {:>12s} {:>7s} {:>7s} {:>11s}".format(
        "run", "trades", "net", "PF", "win%", "maxDD"))
    for tag, r in rep["runs"].items():
        if "metrics" not in r:
            continue
        m = r["metrics"]
        print("  {:12s} {:>7} {:>12,.0f} {:>7} {:>7} {:>11,.0f}".format(
            tag, m.get("trades", 0), m.get("net", 0), str(m.get("profit_factor")),
            str(m.get("win_rate")), m.get("max_dd", 0)))
    print("\nwrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
