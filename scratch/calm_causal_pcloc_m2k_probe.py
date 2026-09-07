from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.calm_causal_pcloc_shape_gap import add_shape_features, bootstrap, stats


BASE = "lag1calm_pcloc_bottom_down_long_e1000_x1555"
AUDIT_COLS = ["outside_exit_bar", "outside_entry_bar", "signal_after_entry"]


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["variant"] == BASE].copy()
    if df.empty:
        raise ValueError(f"no {BASE} rows in {path}")
    if int(df[AUDIT_COLS].sum().sum()) != 0:
        raise ValueError(f"audit counters failed in {path}")
    df["day"] = pd.to_datetime(df["day"]).dt.normalize()
    return df


def summarize(name: str, df: pd.DataFrame) -> dict:
    base = df[df["inst"].eq("M2K")].copy()
    ndg = base[base["gap_from_prev_rth_close"] >= -0.010].copy()
    out = []
    for filt, g in [("m2k_base", base), ("m2k_not_deep_gap", ndg)]:
        st = stats(g)
        by_year = g.groupby("year")["pnl"].sum()
        b = bootstrap(g, 5000, np.random.default_rng(20260821))
        out.append(
            {
                "window": name,
                "filter": filt,
                **st,
                "pos_years": int((by_year > 0).sum()),
                "years": int(len(by_year)),
                "audit": int(g[AUDIT_COLS].sum().sum()) if not g.empty else 0,
                **b,
            }
        )
    return out


def main() -> int:
    is_df = add_shape_features(load("scratch/calm_causal_lag1_excavation_m2k_is.csv"), "data/cache/futures/frozen_sim")
    o25 = add_shape_features(load("scratch/calm_causal_lag1_excavation_m2k_2025.csv"), "data/cache/futures/frozen_2025_sim")
    rows = summarize("IS_2018_2024", is_df) + summarize("OOS_2025", o25)
    out = pd.DataFrame(rows)
    out.to_csv("scratch/calm_causal_pcloc_m2k_probe_summary.csv", index=False)
    is_df.to_csv("scratch/calm_causal_pcloc_m2k_probe_is.csv", index=False)
    o25.to_csv("scratch/calm_causal_pcloc_m2k_probe_2025.csv", index=False)
    print(out.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
