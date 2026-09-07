from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from futures.basket import BASKET, data_filename
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from scratch.stress_mnq_overlap_insurance_20260821 import (
    CALM_FILES,
    CALM_VARIANT,
    NORMAL_FILES,
    dense_daily,
    fmt_money,
    insurance_rows,
    load_stress,
    summarize_daily,
    table,
)


OUT = Path("scratch/stress_switch_policy_probe_20260822_report.md")


@dataclass(frozen=True)
class Candidate:
    name: str
    scale: int
    gap_min: int


CANDIDATES = [
    Candidate("mnq_strict_10:30_b4_g2_rr15_x1555", 5, 2),
    Candidate("mnq_strict_10:30_b4_g3_rr15_x1555", 7, 3),
]


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:30",)
    return [
        base.Rule(
            name=c.name,
            family="cont_short",
            direction="SHORT",
            instruments=("MNQ",),
            setup_time="10:30",
            entry_start="10:35",
            entry_end="12:30",
            exit_time="15:55",
            rr=1.5,
            breadth_min=4,
            gapdown_min=c.gap_min,
            wide_min=0,
            avg_ret_max=None,
            avg_gap_max=-0.001,
        )
        for c in CANDIDATES
    ]


def load_normal_full(which: str) -> pd.DataFrame:
    path = NORMAL_FILES[which]
    if not path.exists():
        return pd.DataFrame()
    data = json.loads(path.read_text())
    bucket = data.get("corrected") or data.get("booked") or {}
    rows = []
    for inst, trades in bucket.items():
        for idx, t in enumerate(trades):
            rows.append({
                "trade_id": f"{inst}_{idx}",
                "source": "normal",
                "instrument": inst,
                "direction": t.get("direction", ""),
                "day": pd.Timestamp(t["day"]).normalize(),
                "entry_time": pd.Timestamp(t["entry_time"]),
                "exit_time": pd.Timestamp(t["exit_time"]),
                "entry": float(t["entry"]),
                "exit": float(t["exit"]),
                "pnl": float(t["pnl"]),
            })
    return pd.DataFrame(rows)


def load_calm_full(which: str) -> pd.DataFrame:
    path = CALM_FILES[which]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = df[df["variant"] == CALM_VARIANT].copy()
    if df.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "trade_id": [f"calm_{i}" for i in range(len(df))],
        "source": "calm",
        "instrument": df["inst"],
        "direction": df["direction"],
        "day": pd.to_datetime(df["day"]).dt.normalize(),
        "entry_time": df["entry_time"].map(pd.Timestamp),
        "exit_time": df["exit_time"].map(pd.Timestamp),
        "entry": df["entry"].astype(float),
        "exit": df["exit"].astype(float),
        "pnl": df["pnl"].astype(float),
    })


def load_mnq_prices(which: str) -> pd.DataFrame:
    argv = list(base.ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    df = base.clip(base.load_parquet(str(Path(data_dir) / data_filename(BASKET["MNQ"]))), start, end)
    return df


def price_at_or_before(df: pd.DataFrame, ts: pd.Timestamp) -> float | None:
    if ts in df.index:
        return float(df.loc[ts]["open"])
    loc = df.index.searchsorted(ts)
    if loc >= len(df.index):
        return None
    return float(df.iloc[loc]["open"])


def early_pnl(row: pd.Series, exit_px: float, costs: dict) -> float:
    pv = BASKET[row["instrument"]].point_value
    gross = (exit_px - row["entry"]) if row["direction"] == "LONG" else (row["entry"] - exit_px)
    return gross * pv - costs[row["instrument"]].round_turn_cost()


def switch_book_for_stress(
    book: pd.DataFrame,
    stress: pd.DataFrame,
    prices: pd.DataFrame,
    costs: dict,
) -> tuple[pd.DataFrame, dict]:
    if book.empty or stress.empty:
        return book.copy(), {"switched": 0, "delta": 0.0, "orig_pnl": 0.0, "early_pnl": 0.0}
    out = book.copy()
    mnq = out[out["instrument"] == "MNQ"].copy()
    switch_rows = []
    for tid, group in mnq.groupby("trade_id"):
        hits = stress[
            (stress["entry_time"] > group.iloc[0]["entry_time"])
            & (stress["entry_time"] < group.iloc[0]["exit_time"])
        ].sort_values("entry_time")
        if hits.empty:
            continue
        s = hits.iloc[0]
        px = price_at_or_before(prices, s["entry_time"])
        if px is None:
            continue
        n = group.iloc[0]
        ep = early_pnl(n, px, costs)
        switch_rows.append({
            "trade_id": tid,
            "new_exit_time": s["entry_time"],
            "new_exit": px,
            "orig_pnl": float(n["pnl"]),
            "early_pnl": ep,
            "delta": ep - float(n["pnl"]),
        })
    if not switch_rows:
        return out, {"switched": 0, "delta": 0.0, "orig_pnl": 0.0, "early_pnl": 0.0}
    sw = pd.DataFrame(switch_rows)
    for _, r in sw.iterrows():
        mask = out["trade_id"] == r["trade_id"]
        out.loc[mask, "pnl"] = r["early_pnl"]
        out.loc[mask, "exit"] = r["new_exit"]
        out.loc[mask, "exit_time"] = r["new_exit_time"]
    return out, {
        "switched": int(len(sw)),
        "delta": float(sw["delta"].sum()),
        "orig_pnl": float(sw["orig_pnl"].sum()),
        "early_pnl": float(sw["early_pnl"].sum()),
    }


def run_window(which: str, rules: list[base.Rule]) -> str:
    stress_by_name, sessions = load_stress(which, rules)
    normal = load_normal_full(which)
    calm = load_calm_full(which)
    prices = load_mnq_prices(which)
    costs = costs_for_basket(slippage_ticks=2.0)
    base_book = pd.concat([x for x in (normal, calm) if not x.empty], ignore_index=True) if (not normal.empty or not calm.empty) else pd.DataFrame()
    base_daily = dense_daily(base_book, sessions, 1.0)
    base_sum = summarize_daily(base_daily)
    rows = []
    insurance = []
    for cand in CANDIDATES:
        stress = stress_by_name[cand.name].copy()
        switched_normal, sw_normal = switch_book_for_stress(normal, stress, prices, costs)
        switched_calm, sw_calm = switch_book_for_stress(calm, stress, prices, costs)
        switched_base = pd.concat([x for x in (switched_normal, calm) if not x.empty], ignore_index=True) if (not switched_normal.empty or not calm.empty) else pd.DataFrame()
        switched_all_base = pd.concat([x for x in (switched_normal, switched_calm) if not x.empty], ignore_index=True) if (not switched_normal.empty or not switched_calm.empty) else pd.DataFrame()
        switched_base_daily = dense_daily(switched_base, sessions, 1.0)
        switched_all_base_daily = dense_daily(switched_all_base, sessions, 1.0)
        stress_daily = dense_daily(stress, sessions, cand.scale)
        combined_daily = switched_all_base_daily + stress_daily
        switched_base_sum = summarize_daily(switched_base_daily)
        switched_all_base_sum = summarize_daily(switched_all_base_daily)
        stress_sum = summarize_daily(stress_daily)
        combined_sum = summarize_daily(combined_daily)
        bad20 = insurance_rows(base_daily, stress_daily)[2]
        rows.append({
            "candidate": cand.name.replace("mnq_strict_10:30_", ""),
            "scale": f"{cand.scale}x",
            "stress_trades": int(len(stress)),
            "switched_normal": sw_normal["switched"],
            "normal_pnl_delta": fmt_money(sw_normal["delta"]),
            "switched_calm": sw_calm["switched"],
            "calm_pnl_delta": fmt_money(sw_calm["delta"]),
            "switched_base_net": fmt_money(switched_all_base_sum["net"]),
            "stress_net": fmt_money(stress_sum["net"]),
            "combined_net": fmt_money(combined_sum["net"]),
            "base_maxdd": fmt_money(base_sum["maxdd"]),
            "switched_base_maxdd": fmt_money(switched_all_base_sum["maxdd"]),
            "combined_maxdd": fmt_money(combined_sum["maxdd"]),
            "combined_maxdd_delta": fmt_money(combined_sum["maxdd"] - base_sum["maxdd"]),
            "bad20_stress": bad20["stress_pnl"],
        })
    return "\n".join([
        f"## {which}",
        "",
        table(rows, [
            "candidate", "scale", "stress_trades", "switched_normal", "normal_pnl_delta",
            "switched_calm", "calm_pnl_delta",
            "switched_base_net", "stress_net", "combined_net", "base_maxdd",
            "switched_base_maxdd", "combined_maxdd", "combined_maxdd_delta", "bad20_stress",
        ]),
        "",
    ])


def main() -> int:
    rules = make_rules()
    parts = [
        "# Stress Switch Policy Probe - 2026-08-22",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Policy: if Stress wants to SHORT MNQ while Normal or Calm MNQ is open, close that existing MNQ trade at the Stress entry timestamp, then allow Stress.",
        "",
        "This approximates a live-safe sleeve handoff. It does not model order-book liquidity or partial fills.",
        "",
    ]
    for which in ("floor", "vault2025", "vault2026"):
        parts.append(run_window(which, rules))
    parts += [
        "## Verdict",
        "",
        "- If switch policy keeps 2025 positive and preserves combined MaxDD improvement, it may be a viable alternative to blocking Stress.",
        "- If the cost of early-closing Normal consumes the Stress edge, the final rejection remains.",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
