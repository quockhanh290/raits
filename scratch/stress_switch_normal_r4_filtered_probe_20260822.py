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
from scratch.stress_mnq_overlap_insurance_20260821 import dense_daily, fmt_money, insurance_rows, summarize_daily, table


OUT = Path("scratch/stress_switch_normal_r4_filtered_probe_20260822_report.md")
NORMAL_PROMOTION_FILES = {
    "floor": Path("scratch/normal_promotion_trades_floor_20260821.json"),
    "vault2025": Path("scratch/normal_promotion_trades_vault2025_20260821.json"),
    "vault2026": Path("scratch/normal_promotion_trades_vault2026_20260821.json"),
}
R4 = ("MES", "MNQ", "MYM", "M2K")


@dataclass(frozen=True)
class Scenario:
    name: str
    instruments: tuple[str, ...]
    qty: int
    gap_min: int = 3
    rr: float = 1.5


SCENARIOS = [
    Scenario("mnq_only_g3_q7", ("MNQ",), 7),
    Scenario("r4_basket_g3_q1each", R4, 1),
    Scenario("r4_basket_g3_q2each", R4, 2),
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


def load_normal_filtered_r4(which: str) -> pd.DataFrame:
    data = json.loads(NORMAL_PROMOTION_FILES[which].read_text())
    bucket = data["filtered"]
    rows = []
    for inst in R4:
        for idx, t in enumerate(bucket.get(inst, [])):
            rows.append({
                "trade_id": f"normal_filtered_{inst}_{idx}",
                "source": "normal_r4_filtered",
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
        hits = stress[
            (stress["instrument"] == inst)
            & (stress["entry_time"] > group.iloc[0]["entry_time"])
            & (stress["entry_time"] < group.iloc[0]["exit_time"])
        ].sort_values("entry_time")
        if hits.empty:
            continue
        px = price_at_or_after(prices[inst], hits.iloc[0]["entry_time"])
        if px is None:
            continue
        ep = early_pnl(group.iloc[0], px, costs)
        switches.append({
            "trade_id": tid,
            "exit_time": hits.iloc[0]["entry_time"],
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


def load_stress(which: str, rules: list[base.Rule]) -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    dfs, costs, sessions = base.load_window(which)
    frames, ctx = base.build_day_cache(dfs)
    return {r.name: base.build_rule(frames, ctx, costs, r) for r in rules}, sessions


def scaled(df: pd.DataFrame, qty: int) -> pd.DataFrame:
    out = df.copy()
    out["pnl"] = out["pnl"].astype(float) * qty
    return out


def run_window(which: str, rules: list[base.Rule]) -> str:
    stress_by_name, sessions = load_stress(which, rules)
    normal = load_normal_filtered_r4(which)
    base_daily = dense_daily(normal, sessions, 1.0)
    base_sum = summarize_daily(base_daily)
    costs = costs_for_basket(slippage_ticks=2.0)
    rows = []
    for s in SCENARIOS:
        raw_stress = stress_by_name[s.name]
        stress = scaled(raw_stress, s.qty)
        prices = load_prices(which, s.instruments)
        switched_normal, sw = switch_book(normal, raw_stress, prices, costs)
        switched_daily = dense_daily(switched_normal, sessions, 1.0)
        stress_daily = dense_daily(stress, sessions, 1.0)
        combined = switched_daily + stress_daily
        bs = summarize_daily(switched_daily)
        ss = summarize_daily(stress_daily)
        cs = summarize_daily(combined)
        bad20 = insurance_rows(base_daily, stress_daily)[2]
        margin = sum(BASKET[i].est_margin for i in s.instruments) * s.qty
        rows.append({
            "scenario": s.name,
            "legs": int(len(raw_stress)),
            "days": int(raw_stress["day"].nunique()) if not raw_stress.empty else 0,
            "margin_est": fmt_money(margin),
            "switched_normal": sw["switched"],
            "switch_delta": fmt_money(sw["delta"]),
            "base_net": fmt_money(base_sum["net"]),
            "stress_net": fmt_money(ss["net"]),
            "combined_net": fmt_money(cs["net"]),
            "base_maxdd": fmt_money(base_sum["maxdd"]),
            "switched_base_maxdd": fmt_money(bs["maxdd"]),
            "combined_maxdd": fmt_money(cs["maxdd"]),
            "maxdd_delta": fmt_money(cs["maxdd"] - base_sum["maxdd"]),
            "bad20_stress": bad20["stress_pnl"],
        })
    return "\n".join([f"## {which}", "", table(rows, [
        "scenario", "legs", "days", "margin_est", "switched_normal", "switch_delta",
        "base_net", "stress_net", "combined_net", "base_maxdd", "switched_base_maxdd",
        "combined_maxdd", "maxdd_delta", "bad20_stress",
    ]), ""])


def main() -> int:
    rules = make_rules()
    parts = [
        "# Stress Switch On Normal-R4 Filtered Probe - 2026-08-22",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Base Normal: `normal_promotion_trades_*` bucket `filtered`, R4 only (MES/MNQ/MYM/M2K), MNKD excluded.",
        "",
        "Note: this uses the regenerated trade artifact directly. It is not a full production cap/breaker replay.",
        "",
        "Switch policy: close existing same-symbol Normal-R4 position at Stress entry timestamp, then allow Stress on that symbol.",
        "",
    ]
    for which in ("floor", "vault2025", "vault2026"):
        parts.append(run_window(which, rules))
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
