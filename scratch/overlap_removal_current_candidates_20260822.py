from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd


NORMAL_FILES = {
    "IS_2018_2024": Path("scratch/normal_sleeve_trades_floor_20260821.json"),
    "OOS_2025": Path("scratch/normal_sleeve_trades_vault2025_20260821.json"),
    "SANITY_2026": Path("scratch/normal_sleeve_trades_vault2026_20260821.json"),
}


def normal_book(window: str) -> pd.DataFrame:
    data = json.loads(NORMAL_FILES[window].read_text())
    bucket = data.get("corrected") or data.get("booked") or {}
    rows = []
    for inst, trades in bucket.items():
        for t in trades:
            rows.append(
                {
                    "source": "normal_book",
                    "inst": inst,
                    "direction": t.get("direction", ""),
                    "day": pd.Timestamp(t["day"]).tz_localize(None).normalize(),
                    "entry_time": pd.Timestamp(t["entry_time"]),
                    "exit_time": pd.Timestamp(t["exit_time"]),
                    "pnl": float(t["pnl"]),
                }
            )
    return pd.DataFrame(rows)


def normalize_times(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["day"] = pd.to_datetime(out["day"]).dt.tz_localize(None).dt.normalize()
    out["entry_time"] = out["entry_time"].map(pd.Timestamp)
    out["exit_time"] = out["exit_time"].map(pd.Timestamp)
    return out


def load_candidate(name: str, window: str) -> pd.DataFrame:
    if name == "calm_pcloc_not_deep":
        df = pd.read_csv("scratch/calm_pcloc_not_deep_gap_trade_list.csv")
        df = df[df["window"] == window].copy()
        df["candidate"] = name
        return normalize_times(df[["candidate", "window", "day", "inst", "direction", "entry_time", "exit_time", "pnl"]])
    if name == "calm_marketwide_mes_setup":
        df = pd.read_csv("scratch/calm_causal_marketwide_setup_artifact_is.csv" if window == "IS_2018_2024" else
                         "scratch/calm_causal_marketwide_setup_artifact_2025.csv" if window == "OOS_2025" else
                         "scratch/calm_causal_marketwide_setup_artifact_2026_sanity.csv")
        df = df[df["variant"] == "market_mes_pcloc_mkt_notdeep_trade_mesmnq"].copy()
        df["candidate"] = name
        df["window"] = window
        return normalize_times(df[["candidate", "window", "day", "inst", "direction", "entry_time", "exit_time", "pnl"]])
    if name == "calm_nkd_swing_d1calm":
        df = pd.read_csv("scratch/calm_nkd_swing_calm_only_trades.csv")
        df = df[(df["window"] == window) & (df["variant"] == "nkd_swing_d1calm_as_normal_ema5_mult2.5")].copy()
        df["candidate"] = name
        return normalize_times(df[["candidate", "window", "day", "inst", "direction", "entry_time", "exit_time", "pnl"]])
    raise ValueError(name)


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "net": 0.0, "pf": 0.0, "avg": 0.0, "maxdd": 0.0, "win_rate": 0.0}
    pnl = df["pnl"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    daily = df.groupby("day")["pnl"].sum().sort_index()
    eq = daily.cumsum()
    return {
        "n": int(len(df)),
        "net": float(pnl.sum()),
        "pf": float(wins.sum() / -losses.sum()) if len(losses) else math.inf,
        "avg": float(pnl.mean()),
        "maxdd": float((eq.cummax() - eq).max()) if len(eq) else 0.0,
        "win_rate": float((pnl > 0).mean()),
    }


def mark_overlap(candidate: pd.DataFrame, base: pd.DataFrame) -> pd.Series:
    if candidate.empty or base.empty:
        return pd.Series(False, index=candidate.index)
    flags = []
    for _, c in candidate.iterrows():
        b = base[base["inst"] == c["inst"]]
        hit = b[(b["entry_time"] < c["exit_time"]) & (b["exit_time"] > c["entry_time"])]
        flags.append(not hit.empty)
    return pd.Series(flags, index=candidate.index)


def overlap_pnl(candidate: pd.DataFrame, base: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    flags = []
    opposite = []
    for _, c in candidate.iterrows():
        b = base[base["inst"] == c["inst"]]
        hit = b[(b["entry_time"] < c["exit_time"]) & (b["exit_time"] > c["entry_time"])]
        flags.append(not hit.empty)
        opposite.append(bool((hit["direction"] != c["direction"]).any()) if not hit.empty else False)
    return pd.Series(flags, index=candidate.index), pd.Series(opposite, index=candidate.index)


def fmt(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def money(x: float) -> str:
    return f"${x:,.0f}"


def main() -> int:
    candidates = ["calm_pcloc_not_deep", "calm_marketwide_mes_setup", "calm_nkd_swing_d1calm"]
    rows = []
    for window in ["IS_2018_2024", "OOS_2025", "SANITY_2026"]:
        base = normal_book(window)
        for cand_name in candidates:
            cand = load_candidate(cand_name, window)
            ov, opp = overlap_pnl(cand, base)
            keep = cand[~ov].copy()
            dropped = cand[ov].copy()
            s0 = stats(cand)
            s1 = stats(keep)
            sd = stats(dropped)
            rows.append(
                {
                    "window": window,
                    "candidate": cand_name,
                    "base_n": s0["n"],
                    "base_net": s0["net"],
                    "base_pf": s0["pf"],
                    "base_dd": s0["maxdd"],
                    "overlap_n": int(ov.sum()),
                    "opposite_n": int(opp.sum()),
                    "overlap_net": sd["net"],
                    "after_n": s1["n"],
                    "after_net": s1["net"],
                    "after_pf": s1["pf"],
                    "after_dd": s1["maxdd"],
                    "delta_net": s1["net"] - s0["net"],
                    "delta_dd": s1["maxdd"] - s0["maxdd"],
                }
            )

    out = pd.DataFrame(rows)
    out.to_csv("scratch/overlap_removal_current_candidates_20260822.csv", index=False)
    print("| window | candidate | base | overlap | after_drop_overlap | delta |")
    print("| --- | --- | --- | --- | --- | --- |")
    for _, r in out.iterrows():
        print(
            f"| {r['window']} | {r['candidate']} | "
            f"{int(r['base_n'])} / {money(r['base_net'])} / PF {fmt(r['base_pf'])} / DD {money(r['base_dd'])} | "
            f"{int(r['overlap_n'])} legs, {int(r['opposite_n'])} opposite, net {money(r['overlap_net'])} | "
            f"{int(r['after_n'])} / {money(r['after_net'])} / PF {fmt(r['after_pf'])} / DD {money(r['after_dd'])} | "
            f"net {money(r['delta_net'])}, DD {money(r['delta_dd'])} |"
        )
    print("wrote scratch/overlap_removal_current_candidates_20260822.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
