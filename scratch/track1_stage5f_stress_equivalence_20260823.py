"""Equivalence harness: promoted Stress module vs the canonical scratch chain.

Read-only. Loads the same windows the measured book was built from, runs both, and compares
trade for trade. Prints a verdict; writes nothing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import pandas as pd
import scratch.stress_switch_full_replay_20260822 as full
import scratch.stress_open_search_20260821 as base
from futures.basket import BASKET
from global_index import track1_stress_mnq as SM

KEYS = ["day", "instrument", "direction", "entry_time", "exit_time",
        "entry", "stop", "target", "exit", "exit_reason", "qty", "pnl_sized", "risk_sized"]
SC = full.Scenario("mnq_only_g3_q7", ("MNQ",), 7)


def norm(df):
    if df.empty:
        return df
    out = df[KEYS].copy()
    out["day"] = pd.to_datetime(out["day"]).dt.tz_localize(None).dt.normalize()
    for c in ("entry_time", "exit_time"):
        out[c] = out[c].astype(str)
    for c in ("entry", "stop", "target", "exit", "pnl_sized", "risk_sized"):
        out[c] = out[c].astype(float).round(6)
    return out.sort_values(["day", "instrument", "entry_time"]).reset_index(drop=True)


def main():
    ok = True
    for which in ("vault2026", "vault2025", "floor"):
        anchor, _ = full.load_stress(which, SC)
        old = base.SETUPS
        base.SETUPS = ("10:30",)
        try:
            dfs, costs, _ = base.load_window(which)
        finally:
            base.SETUPS = old
        pv = {n: c.point_value for n, c in BASKET.items()}
        mine = SM.build_trades(dfs, costs, pv)

        a, b = norm(anchor), norm(mine)
        same = len(a) == len(b) and (a.equals(b) if len(a) else True)
        pa = float(anchor["pnl_sized"].sum()) if len(anchor) else 0.0
        pb = float(mine["pnl_sized"].sum()) if len(mine) else 0.0
        print(f"{which:10s} anchor={len(a):3d} promoted={len(b):3d} "
              f"pnl {pa:10.2f} vs {pb:10.2f}  delta={pb-pa:+.6f}  identical={same}")
        if not same:
            ok = False
            if len(a) != len(b):
                print(f"   row counts differ; anchor days={sorted(set(a['day'].astype(str)))[:6]}")
                print(f"                     promoted days={sorted(set(b['day'].astype(str)))[:6]}")
            else:
                for i in range(len(a)):
                    if not a.iloc[i].equals(b.iloc[i]):
                        print("   first divergence at row", i)
                        print("     anchor  :", a.iloc[i].to_dict())
                        print("     promoted:", b.iloc[i].to_dict())
                        break
    print("\nEQUIVALENT" if ok else "\nNOT EQUIVALENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
