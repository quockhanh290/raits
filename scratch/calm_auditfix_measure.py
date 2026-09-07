from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import load_parquet
from futures.basket import BASKET, data_filename
from global_index.deploy_sim import metrics


WINDOWS = {
    "is": ("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_is.csv", "data/cache/futures/frozen_sim"),
    "2025": ("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2025.csv", "data/cache/futures/frozen_2025_sim"),
    "2026": ("scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym_2026.csv", "data/cache/futures"),
}
VARIANT = "on_neg_fade_mod001_010_x1555"
ACCOUNT = 50_000.0


def price_inside_bar(price: float, bar: pd.Series) -> bool:
    px = float(price)
    lo = float(bar["low"])
    hi = float(bar["high"])
    eps = max(abs(px), abs(lo), abs(hi), 1.0) * 1e-9
    return lo - eps <= px <= hi + eps


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"trades": 0, "net": 0.0, "pf": 0.0, "sharpe": 0.0, "calmar": 0.0, "maxdd": 0.0}
    pnl = tr["pnl"].astype(float)
    gw = float(pnl[pnl > 0].sum())
    gl = float(-pnl[pnl < 0].sum())
    daily = tr.groupby(pd.to_datetime(tr["day"]))["pnl"].sum().sort_index()
    m = metrics(daily)
    return {
        "trades": int(len(tr)),
        "net": float(pnl.sum()),
        "pf": gw / gl if gl else math.inf,
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
    }


def load_window(csv_path: str, data_dir: str) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    tr = pd.read_csv(csv_path)
    tr = tr[tr["variant"] == VARIANT].copy()
    tr["day"] = pd.to_datetime(tr["day"]).dt.normalize()
    tr["entry_time"] = tr["entry_time"].map(pd.Timestamp)
    tr["exit_time"] = tr["exit_time"].map(pd.Timestamp)
    dfs = {}
    for inst in sorted(tr["inst"].unique()):
        df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
        dfs[inst] = df
    return tr, dfs


def bar_at(df: pd.DataFrame, ts: pd.Timestamp) -> pd.Series | None:
    ts = pd.Timestamp(ts)
    try:
        return df.loc[ts]
    except KeyError:
        pass
    idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
    needle = ts.tz_localize(None) if ts.tzinfo is not None else ts
    loc = np.where(idx == needle)[0]
    if len(loc) == 0:
        return None
    return df.iloc[int(loc[0])]


def audit_and_reprice(tr: pd.DataFrame, dfs: dict[str, pd.DataFrame], *, delay_minutes: int = 0, extra_entry_cost_ticks: float = 0.0) -> tuple[pd.DataFrame, dict]:
    rows = []
    audit = {
        "outside_entry_bar": 0,
        "outside_exit_bar": 0,
        "missing_entry_bar": 0,
        "missing_exit_bar": 0,
        "signal_after_entry": 0,
        "same_or_before_exit": 0,
    }
    for _, r in tr.iterrows():
        inst = str(r["inst"])
        df = dfs[inst]
        day = pd.Timestamp(r["day"]).normalize()
        base_entry = pd.Timestamp(r["entry_time"])
        entry_ts = base_entry + pd.Timedelta(minutes=delay_minutes)
        exit_ts = pd.Timestamp(r["exit_time"])
        entry_bar = bar_at(df, entry_ts)
        exit_bar = bar_at(df, exit_ts)
        if entry_bar is None:
            audit["missing_entry_bar"] += 1
            continue
        if exit_bar is None:
            audit["missing_exit_bar"] += 1
            continue
        if exit_ts <= entry_ts:
            audit["same_or_before_exit"] += 1
            continue
        entry_px = float(entry_bar["open"])
        exit_px = float(exit_bar["open"])
        if not price_inside_bar(entry_px, entry_bar):
            audit["outside_entry_bar"] += 1
        if not price_inside_bar(exit_px, exit_bar):
            audit["outside_exit_bar"] += 1
        known = day + pd.Timedelta(hours=9, minutes=30)
        cmp_entry = entry_ts.tz_localize(None) if entry_ts.tzinfo is not None else entry_ts
        if cmp_entry < known:
            audit["signal_after_entry"] += 1
        pv = BASKET[inst].point_value
        cost = (float(r["exit"]) - float(r["entry"])) * pv - float(r["pnl"])
        cost += extra_entry_cost_ticks * BASKET[inst].tick * pv
        out = r.copy()
        out["entry_time"] = entry_ts
        out["entry"] = entry_px
        out["exit"] = exit_px
        out["pnl"] = (exit_px - entry_px) * pv - cost
        rows.append(out)
    return pd.DataFrame(rows), audit


def cap_by_day(tr: pd.DataFrame, max_per_day: int) -> tuple[pd.DataFrame, int]:
    kept = []
    rejected = 0
    for _, g in tr.groupby("day"):
        g = g.sort_values(["overnight_ret", "inst"], ascending=[True, True])
        kept.append(g.head(max_per_day))
        rejected += max(0, len(g) - max_per_day)
    return (pd.concat(kept).sort_values(["day", "inst"]).reset_index(drop=True) if kept else tr.iloc[0:0], rejected)


def print_row(window: str, name: str, tr: pd.DataFrame, rejected: int = 0) -> None:
    s = stats(tr)
    print(
        f"{window:<5} {name:<18} n={s['trades']:>4} rej={rejected:>3} "
        f"net=${s['net']:>8,.0f} pf={s['pf']:>5.2f} sharpe={s['sharpe']:>5.2f} "
        f"calmar={s['calmar']:>5.2f} maxdd=${s['maxdd']:>7,.0f}"
    )


def main() -> int:
    print("Calm audit-fix measurement from saved signals + parquet repricing")
    print(f"variant={VARIANT}")
    all_pooled = []
    for window, (csv_path, data_dir) in WINDOWS.items():
        tr, dfs = load_window(csv_path, data_dir)
        base, audit = audit_and_reprice(tr, dfs)
        d1, audit_d1 = audit_and_reprice(tr, dfs, delay_minutes=1)
        d2, _ = audit_and_reprice(tr, dfs, delay_minutes=2)
        d5, _ = audit_and_reprice(tr, dfs, delay_minutes=5)
        slip1, audit_s1 = audit_and_reprice(tr, dfs, extra_entry_cost_ticks=1.0)
        slip2, _ = audit_and_reprice(tr, dfs, extra_entry_cost_ticks=2.0)
        cap2, rej2 = cap_by_day(base, 2)
        cap1, rej1 = cap_by_day(base, 1)

        print(f"\n=== {window} ===")
        print(f"audit base={audit}")
        print(f"audit +1m={audit_d1}")
        print(f"audit +1 extra entry cost tick={audit_s1}")
        print_row(window, "base_0930", base)
        print_row(window, "entry_0931", d1)
        print_row(window, "entry_0932", d2)
        print_row(window, "entry_0935", d5)
        print_row(window, "entry_cost+1t", slip1)
        print_row(window, "entry_cost+2t", slip2)
        print_row(window, "max2_mostneg", cap2, rej2)
        print_row(window, "max1_mostneg", cap1, rej1)

        base2 = base.copy()
        base2["window"] = window
        all_pooled.append(base2[base2["window"].isin(["2025", "2026"])])

    pooled = pd.concat(all_pooled, ignore_index=True)
    if not pooled.empty:
        print("\n=== pooled OOS 2025+2026 ===")
        print_row("oos", "base_0930", pooled)
        print_row("oos", "max2_mostneg", cap_by_day(pooled, 2)[0], cap_by_day(pooled, 2)[1])
        print_row("oos", "max1_mostneg", cap_by_day(pooled, 1)[0], cap_by_day(pooled, 1)[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
