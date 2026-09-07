from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index.deploy_sim import metrics
from scratch.stress_mnq_overlap_insurance_20260821 import dense_daily, fmt_money, table
from scratch.stress_switch_normal_r4_filtered_probe_20260822 import (
    OUT as _PREV_OUT,
    SCENARIOS,
    load_normal_filtered_r4,
    load_prices,
    load_stress,
    make_rules,
    scaled,
    switch_book,
)
from futures.basket import BASKET
from futures.swing_tf import costs_for_basket


OUT = Path("scratch/stress_switch_normal_r4_filtered_metrics_20260822_report.md")
ACCOUNT = 50_000.0


def perf_from_daily(daily: pd.Series) -> dict:
    m = metrics(daily)
    gp = float(daily[daily > 0].sum())
    gl = float(-daily[daily < 0].sum())
    eq = daily.cumsum()
    maxdd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    return {
        "net": float(daily.sum()),
        "ret_pct": float(daily.sum()) / ACCOUNT,
        "pf": gp / gl if gl else float("inf"),
        "sharpe": float(m.get("sharpe", 0.0)),
        "calmar": float(m.get("calmar", 0.0)),
        "maxdd": maxdd,
    }


def winrate_from_trades(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return float((df["pnl"].astype(float) > 0).mean())


def fmt_pct(x: float) -> str:
    return f"{x:.1%}"


def fmt_num(x: float) -> str:
    return "inf" if x == float("inf") else f"{x:.2f}"


def row_for(name: str, trade_count: int, winrate: float, daily: pd.Series) -> dict:
    p = perf_from_daily(daily)
    return {
        "book": name,
        "trades": trade_count,
        "net": fmt_money(p["net"]),
        "return_pct": fmt_pct(p["ret_pct"]),
        "pf": fmt_num(p["pf"]),
        "sharpe": fmt_num(p["sharpe"]),
        "calmar": fmt_num(p["calmar"]),
        "maxdd": fmt_money(p["maxdd"]),
        "winrate": fmt_pct(winrate),
    }


def run_window(which: str, rules) -> str:
    stress_by_name, sessions = load_stress(which, rules)
    normal = load_normal_filtered_r4(which)
    base_daily = dense_daily(normal, sessions, 1.0)
    costs = costs_for_basket(slippage_ticks=2.0)
    rows = [row_for("Normal-R4 filtered only", int(len(normal)), winrate_from_trades(normal), base_daily)]
    for s in SCENARIOS:
        raw_stress = stress_by_name[s.name]
        stress = scaled(raw_stress, s.qty)
        prices = load_prices(which, s.instruments)
        switched_normal, sw = switch_book(normal, raw_stress, prices, costs)
        switched_daily = dense_daily(switched_normal, sessions, 1.0)
        stress_daily = dense_daily(stress, sessions, 1.0)
        combined = switched_daily + stress_daily
        rows.append(row_for(
            f"Stress {s.name}",
            int(len(raw_stress)),
            winrate_from_trades(raw_stress),
            stress_daily,
        ))
        rows.append(row_for(
            f"Combined + {s.name}",
            int(len(switched_normal)) + int(len(raw_stress)),
            winrate_from_trades(pd.concat([switched_normal, stress], ignore_index=True)),
            combined,
        ))
    return "\n".join([
        f"## {which}",
        "",
        table(rows, ["book", "trades", "net", "return_pct", "pf", "sharpe", "calmar", "maxdd", "winrate"]),
        "",
    ])


def main() -> int:
    rules = make_rules()
    parts = [
        "# Stress Switch On Normal-R4 Filtered Metrics - 2026-08-22",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Base: Normal-R4 filtered trade artifact (`filtered`, MES/MNQ/MYM/M2K only, MNKD excluded).",
        "Return % uses $50,000 account and raw window net, not annualized return.",
        "PF/Sharpe/Calmar are computed from daily PnL series.",
        "Winrate is trade-level for Stress and combined switched trade books.",
        "",
    ]
    for which in ("floor", "vault2025", "vault2026"):
        parts.append(run_window(which, rules))
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
