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


OUT = Path("scratch/stress_switch_basket_probe_20260822_report.md")


@dataclass(frozen=True)
class Scenario:
    name: str
    instruments: tuple[str, ...]
    qty: int
    gap_min: int = 3
    rr: float = 1.5


SCENARIOS = [
    Scenario("mnq_only_g3_q7", ("MNQ",), 7),
    Scenario("r4_basket_g3_q1each", ("MES", "MNQ", "MYM", "M2K"), 1),
    Scenario("r4_basket_g3_q2each", ("MES", "MNQ", "MYM", "M2K"), 2),
]


def arg_from(argv: list[str], flag: str, default=None):
    if flag not in argv:
        return default
    return argv[argv.index(flag) + 1]


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:30",)
    return [
        base.Rule(
            name=s.name,
            family="cont_short",
            direction="SHORT",
            instruments=s.instruments,
            setup_time="10:30",
            entry_start="10:35",
            entry_end="12:30",
            exit_time="15:55",
            rr=s.rr,
            breadth_min=4,
            gapdown_min=s.gap_min,
            wide_min=0,
            avg_ret_max=None,
            avg_gap_max=-0.001,
        )
        for s in SCENARIOS
    ]


def load_book(which: str, normal: bool = True, calm: bool = True) -> pd.DataFrame:
    rows = []
    if normal:
        path = NORMAL_FILES[which]
        if path.exists():
            data = json.loads(path.read_text())
            bucket = data.get("corrected") or data.get("booked") or {}
            for inst, trades in bucket.items():
                for idx, t in enumerate(trades):
                    rows.append({
                        "trade_id": f"normal_{inst}_{idx}",
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
    if calm:
        path = CALM_FILES[which]
        if path.exists():
            df = pd.read_csv(path)
            df = df[df["variant"] == CALM_VARIANT].copy()
            for idx, r in df.iterrows():
                rows.append({
                    "trade_id": f"calm_{idx}",
                    "source": "calm",
                    "instrument": r["inst"],
                    "direction": r["direction"],
                    "day": pd.Timestamp(r["day"]).normalize(),
                    "entry_time": pd.Timestamp(r["entry_time"]),
                    "exit_time": pd.Timestamp(r["exit_time"]),
                    "entry": float(r["entry"]),
                    "exit": float(r["exit"]),
                    "pnl": float(r["pnl"]),
                })
    return pd.DataFrame(rows)


def load_prices(which: str, instruments: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    argv = list(base.ARGV[which])
    data_dir = arg_from(argv, "--data-dir")
    start = arg_from(argv, "--start")
    end = arg_from(argv, "--end")
    return {
        inst: base.clip(base.load_parquet(str(Path(data_dir) / data_filename(BASKET[inst]))), start, end)
        for inst in instruments
    }


def price_at_or_after(df: pd.DataFrame, ts: pd.Timestamp) -> float | None:
    loc = df.index.searchsorted(ts)
    if loc >= len(df.index):
        return None
    return float(df.iloc[loc]["open"])


def early_pnl(row: pd.Series, exit_px: float, costs: dict) -> float:
    pv = BASKET[row["instrument"]].point_value
    gross = (exit_px - row["entry"]) if row["direction"] == "LONG" else (row["entry"] - exit_px)
    return gross * pv - costs[row["instrument"]].round_turn_cost()


def switch_book(book: pd.DataFrame, stress: pd.DataFrame, prices: dict[str, pd.DataFrame], costs: dict) -> tuple[pd.DataFrame, dict]:
    if book.empty or stress.empty:
        return book.copy(), {"switched": 0, "delta": 0.0}
    out = book.copy()
    switches = []
    for tid, group in book.groupby("trade_id"):
        inst = group.iloc[0]["instrument"]
        s_hits = stress[
            (stress["instrument"] == inst)
            & (stress["entry_time"] > group.iloc[0]["entry_time"])
            & (stress["entry_time"] < group.iloc[0]["exit_time"])
        ].sort_values("entry_time")
        if s_hits.empty:
            continue
        px = price_at_or_after(prices[inst], s_hits.iloc[0]["entry_time"])
        if px is None:
            continue
        ep = early_pnl(group.iloc[0], px, costs)
        switches.append({
            "trade_id": tid,
            "exit_time": s_hits.iloc[0]["entry_time"],
            "exit": px,
            "pnl": ep,
            "delta": ep - float(group.iloc[0]["pnl"]),
        })
    if not switches:
        return out, {"switched": 0, "delta": 0.0}
    sw = pd.DataFrame(switches)
    for _, r in sw.iterrows():
        mask = out["trade_id"] == r["trade_id"]
        out.loc[mask, "exit_time"] = r["exit_time"]
        out.loc[mask, "exit"] = r["exit"]
        out.loc[mask, "pnl"] = r["pnl"]
    return out, {"switched": int(len(sw)), "delta": float(sw["delta"].sum())}


def scaled_stress(stress: pd.DataFrame, qty: int) -> pd.DataFrame:
    out = stress.copy()
    out["pnl"] = out["pnl"].astype(float) * qty
    return out


def run_window(which: str, rules: list[base.Rule]) -> str:
    stress_by_name, sessions = load_stress(which, rules)
    book = load_book(which)
    base_daily = dense_daily(book, sessions, 1.0)
    base_sum = summarize_daily(base_daily)
    costs = costs_for_basket(slippage_ticks=2.0)
    rows = []
    for s in SCENARIOS:
        raw = stress_by_name[s.name]
        stress = scaled_stress(raw, s.qty)
        prices = load_prices(which, s.instruments)
        switched_book, sw = switch_book(book, raw, prices, costs)
        switched_daily = dense_daily(switched_book, sessions, 1.0)
        stress_daily = dense_daily(stress, sessions, 1.0)
        combined_daily = switched_daily + stress_daily
        ss = summarize_daily(stress_daily)
        bs = summarize_daily(switched_daily)
        cs = summarize_daily(combined_daily)
        bad20 = insurance_rows(base_daily, stress_daily)[2]
        margin = sum(BASKET[i].est_margin for i in s.instruments) * s.qty
        rows.append({
            "scenario": s.name,
            "legs": int(len(raw)),
            "trade_days": int(raw["day"].nunique()) if not raw.empty else 0,
            "qty_each": s.qty,
            "margin_est": fmt_money(margin),
            "switched_existing": sw["switched"],
            "switch_delta": fmt_money(sw["delta"]),
            "stress_net": fmt_money(ss["net"]),
            "base_maxdd": fmt_money(base_sum["maxdd"]),
            "switched_base_maxdd": fmt_money(bs["maxdd"]),
            "combined_net": fmt_money(cs["net"]),
            "combined_maxdd": fmt_money(cs["maxdd"]),
            "maxdd_delta": fmt_money(cs["maxdd"] - base_sum["maxdd"]),
            "bad20_stress": bad20["stress_pnl"],
        })
    return "\n".join([f"## {which}", "", table(rows, [
        "scenario", "legs", "trade_days", "qty_each", "margin_est", "switched_existing",
        "switch_delta", "stress_net", "base_maxdd", "switched_base_maxdd", "combined_net",
        "combined_maxdd", "maxdd_delta", "bad20_stress",
    ]), ""])


def main() -> int:
    rules = make_rules()
    parts = [
        "# Stress Switch Basket Probe - 2026-08-22",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Question: what if Stress trades the whole R4 basket instead of MNQ only?",
        "",
        "Policy: close existing same-symbol Normal/Calm position at Stress entry timestamp, then allow Stress on that symbol.",
        "",
        "Scenarios:",
        "",
        "- `mnq_only_g3_q7`: MNQ only, qty 7.",
        "- `r4_basket_g3_q1each`: MES/MNQ/MYM/M2K, qty 1 each.",
        "- `r4_basket_g3_q2each`: MES/MNQ/MYM/M2K, qty 2 each.",
        "",
    ]
    for which in ("floor", "vault2025", "vault2026"):
        parts.append(run_window(which, rules))
    parts += [
        "## Verdict",
        "",
        "- Basket Stress is only interesting if it improves combined MaxDD and OOS without requiring unrealistic margin or excessive switching.",
        "- Compare against MNQ-only 7x, which is the current switch-policy benchmark.",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
