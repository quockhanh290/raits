from __future__ import annotations

from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd


START_CAPITAL = 50_000.0
STREAMS = Path("STOCKS_ALL_SLEEVE_LIBRARY_DAILY_STREAMS_2026-09-08.csv")
OUT = Path("STOCKS_FIXED_CORE_PORTFOLIO_2026-09-09.csv")
BOOT_OUT = Path("STOCKS_FIXED_CORE_PORTFOLIO_BOOTSTRAP_2026-09-09.csv")


SATELLITE_SETS = {
    "none": [],
    "clean3": ["local_xs_full_s10", "yday_ex6_actual", "intraday_ex10"],
    "clean4": ["local_xs_full_s10", "ml_ex6_0935_s20", "yday_ex6_actual", "intraday_ex10"],
    "xs_yday": ["local_xs_full_s10", "yday_ex6_actual"],
    "xs_intraday": ["local_xs_full_s10", "intraday_ex10"],
    "yday_intraday": ["yday_ex6_actual", "intraday_ex10"],
}


def pnl_for(daily: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    pnl = pd.Series(0.0, index=daily.index)
    for name, weight in weights.items():
        pnl = pnl + daily[name].fillna(0.0) * weight
    return pnl


def max_drawdown(pnl: pd.Series) -> float:
    equity = START_CAPITAL + pnl.cumsum()
    return float((equity - equity.cummax()).min())


def summarize(daily: pd.DataFrame, pnl: pd.Series) -> dict[str, float]:
    equity = START_CAPITAL + pnl.cumsum()
    yearly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(year=lambda x: x["date"].dt.year).groupby("year")["pnl"].sum()
    monthly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(month=lambda x: x["date"].dt.to_period("M")).groupby("month")["pnl"].sum()
    return {
        "pnl": float(pnl.sum()),
        "ending": float(equity.iloc[-1]),
        "dd": max_drawdown(pnl),
        "sharpe": float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else np.nan,
        "negYears": int((yearly < 0).sum()),
        "minYear": float(yearly.min()) if len(yearly) else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
        "negMonths": int((monthly < 0).sum()),
        "minMonth": float(monthly.min()) if len(monthly) else np.nan,
        "medianMonth": float(monthly.median()) if len(monthly) else np.nan,
    }


def bootstrap_months(daily: pd.DataFrame, pnl: pd.Series, label: str, n: int = 2000, seed: int = 11) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    tmp = pd.DataFrame({"date": daily["date"], "pnl": pnl}).copy()
    tmp["month"] = tmp["date"].dt.to_period("M").astype(str)
    months = [m for _, m in tmp.groupby("month", sort=True)]
    pnl_vals = []
    dd_vals = []
    for _ in range(n):
        sample = [months[int(i)] for i in rng.integers(0, len(months), len(months))]
        p = pd.concat(sample, ignore_index=True)["pnl"].to_numpy(dtype=float)
        eq = pd.Series(START_CAPITAL + np.cumsum(p))
        pnl_vals.append(float(eq.iloc[-1] - START_CAPITAL))
        dd_vals.append(float((eq - eq.cummax()).min()))
    p = np.array(pnl_vals)
    d = np.array(dd_vals)
    return {
        "label": label,
        "pnlP05": float(np.quantile(p, 0.05)),
        "pnlP50": float(np.quantile(p, 0.50)),
        "pnlP95": float(np.quantile(p, 0.95)),
        "ddP05": float(np.quantile(d, 0.05)),
        "ddP50": float(np.quantile(d, 0.50)),
        "ddP95": float(np.quantile(d, 0.95)),
        "probPnlNeg": float((p < 0).mean()),
        "probDdWorse15k": float((d <= -15_000).mean()),
        "probDdWorse20k": float((d <= -20_000).mean()),
    }


def make_weights(core: str, core_w: float, sat_set: str, sat_w: float) -> dict[str, float]:
    weights = {core: core_w}
    for name in SATELLITE_SETS[sat_set]:
        weights[name] = sat_w
    return weights


def main() -> None:
    daily = pd.read_csv(STREAMS, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    boot_rows: list[dict[str, object]] = []
    windows = {
        "full_202303_2024": daily["date"].ge(pd.Timestamp("2023-03-28")),
        "wfo6_same_202309_2024": daily["date"].ge(pd.Timestamp("2023-09-01")),
        "wfo12_same_202403_2024": daily["date"].ge(pd.Timestamp("2024-03-01")),
        "train2023_test2024": daily["date"].dt.year.eq(2024),
    }

    configs: list[tuple[str, dict[str, float]]] = []
    for core_w, sat_set, sat_w in product([0.40, 0.60, 0.80, 1.00], SATELLITE_SETS, [0.20, 0.30, 0.40]):
        if sat_set == "none" and sat_w != 0.20:
            continue
        weights = make_weights("broad_adv10_g2_dd85", core_w, sat_set, sat_w)
        if sum(weights.values()) > 2.0:
            continue
        label = f"core{core_w:g}_{sat_set}_sat{sat_w:g}"
        configs.append((label, weights))

    # Explicit baselines from prior sections.
    configs.append(("equal_clean_prior", {
        "broad_adv10_g2_dd85": 0.35,
        "local_xs_full_s10": 0.35,
        "ml_ex6_0935_s20": 0.35,
        "yday_ex6_actual": 0.35,
        "intraday_ex10": 0.35,
    }))
    configs.append(("simple_core60_clean3_30", {
        "broad_adv10_g2_dd85": 0.60,
        "local_xs_full_s10": 0.30,
        "yday_ex6_actual": 0.30,
        "intraday_ex10": 0.30,
    }))
    configs.append(("simple_core80_clean3_25", {
        "broad_adv10_g2_dd85": 0.80,
        "local_xs_full_s10": 0.25,
        "yday_ex6_actual": 0.25,
        "intraday_ex10": 0.25,
    }))

    for label, weights in configs:
        full_pnl = pnl_for(daily, weights)
        full_stats = summarize(daily, full_pnl)
        for window_label, mask in windows.items():
            d = daily[mask].reset_index(drop=True)
            pnl = pnl_for(d, weights)
            row: dict[str, object] = {
                "label": label,
                "window": window_label,
                "weights": ";".join(f"{k}:{v:g}" for k, v in weights.items()),
                "activeSleeves": len(weights),
                "totalWeight": float(sum(weights.values())),
                "coreWeight": float(weights["broad_adv10_g2_dd85"]),
                "satSet": label.split("_", 2)[1] if label.startswith("core") else "",
            }
            row.update(summarize(d, pnl))
            row["fullPnl"] = full_stats["pnl"]
            row["fullDd"] = full_stats["dd"]
            row["score"] = row["pnl"] / max(abs(float(row["dd"])), 1.0)
            rows.append(row)
        if label in {
            "equal_clean_prior",
            "simple_core60_clean3_30",
            "simple_core80_clean3_25",
            "core0.6_clean3_sat0.3",
            "core0.8_clean3_sat0.3",
            "core0.6_clean4_sat0.3",
            "core0.6_clean3_sat0.4",
            "core0.4_clean4_sat0.4",
            "core0.4_clean3_sat0.4",
        }:
            boot_rows.append(bootstrap_months(daily, full_pnl, label))

    out = pd.DataFrame(rows).sort_values(["window", "score"], ascending=[True, False])
    out.to_csv(OUT, index=False)
    pd.DataFrame(boot_rows).to_csv(BOOT_OUT, index=False)
    print("WROTE", OUT, BOOT_OUT)


if __name__ == "__main__":
    main()
