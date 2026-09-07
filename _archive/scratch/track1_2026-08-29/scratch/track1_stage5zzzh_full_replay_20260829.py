"""Stage 5ZZZ-H — the full Track 1 candidate replay, baseline vs causal-D-1 swing.

Runs the AUTHORITATIVE replay (`combined_repaired_replay_20260822.replay_repaired`) unchanged.
The only difference between the two variants is which Normal/R4 promotion artifact it reads:
the 2026-08-21 baseline, or the D-1 regeneration from this stage. Everything else - caps,
account, costs, fill law, HMM fit end per window, Stress, Calm, NKD - is whatever that script
already does.

Run one variant per process. The loaders memoise per window, and swapping artifact paths inside
a live process would hand the second variant the first one's cached frames.

    python scratch/track1_stage5zzzh_full_replay_20260829.py --variant base
    python scratch/track1_stage5zzzh_full_replay_20260829.py --variant d1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

WINDOWS = ("floor", "vault2025", "vault2026")
POLICIES = ("repaired_mechanics_family_cap_5_44", "risk_clean_no_calm_nkd_family_cap_5_44")


def main() -> int:
    ap = argparse.ArgumentParser()
    # Stage 5ZZZ-I. Any arm, named by the artifact suffix it reads. "base" is the untouched
    # 2026-08-21 promotion artifact; every other arm is a regenerated one.
    ap.add_argument("--variant", required=True,
                    help="base | d1 | d1r | noswing  (anything but base reads "
                         "normal_promotion_trades_<window>_<variant>_20260829.json)")
    a = ap.parse_args()

    import scratch.stress_switch_full_replay_20260822 as full

    windows = list(WINDOWS)
    if a.variant != "base":
        present = []
        for w in WINDOWS:
            p = Path(f"scratch/normal_promotion_trades_{w}_{a.variant}_20260829.json")
            if p.exists():
                full.NORMAL_PROMOTION_FILES[w] = p
                present.append(w)
            else:
                # Stage 5ZZZ-J. A partial arm is allowed and SAID SO. The intraday proxy has no
                # 2025/2026 artifact because SPY intraday data ends 2024-12-30, and silently
                # falling back to the baseline artifact for those windows would report the
                # baseline's numbers under the proxy's name.
                print(f"  no '{a.variant}' artifact for {w} - that window is SKIPPED, "
                      f"not substituted")
        if not present:
            print(f"no artifacts at all for variant '{a.variant}'")
            return 2
        windows = present
        print(f"reading '{a.variant}' Normal/R4 artifacts for: {', '.join(present)}")
    else:
        print("reading the 2026-08-21 baseline Normal/R4 artifacts")

    import scratch.combined_repaired_replay_20260822 as rep
    from global_index.deploy_sim import metrics

    wanted = [p for p in rep.POLICIES if p.name in POLICIES]
    assert len(wanted) == 2, [p.name for p in rep.POLICIES]

    out: dict = {}
    for which in windows:
        out[which] = {}
        for pol in wanted:
            daily, st = rep.replay_repaired(which, pol)
            m = metrics(daily)
            by_cluster = st.get("pnl_by_cluster", {})
            out[which][pol.name] = {
                "net": round(float(m["pnl"]), 2),
                "pf": round(float(m["pf"]), 4),
                "sharpe": round(float(m["sharpe"]), 4),
                "calmar": round(float(m["calmar"]), 4),
                "maxdd": round(abs(float(m["maxdd"])), 2),
                "taken": dict(st["taken"]),
                "rejected": dict(st["rejected"]),
                "family_rejected": st["family_rejected"],
                "halted": st["halted"],
                "double_booked": st["double_booked"],
                "suppressed_normal_same_symbol": st["suppressed_normal_same_symbol"],
                "suppressed_normal_pnl": round(float(st["suppressed_normal_pnl"]), 2),
                "stress_closed_r4": st["stress_closed_r4"],
                "calm_closed_current_nkd": st["calm_closed_current_nkd"],
                "pnl_by_cluster": {k: round(float(v), 2) for k, v in by_cluster.items()},
            }
            r = out[which][pol.name]
            print(f"  {which:10s} {pol.name:38s} net={r['net']:>11,.0f} pf={r['pf']:.2f} "
                  f"sharpe={r['sharpe']:.2f} calmar={r['calmar']:.2f} "
                  f"maxdd={r['maxdd']:>9,.0f} "
                  f"R4 {r['taken']['roska4_swing']}/{r['rejected']['roska4_swing']}")

    dest = Path(f"scratch/track1_stage5zzzh_full_replay_{a.variant}_20260829.json")
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
