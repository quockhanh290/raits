from __future__ import annotations

from itertools import combinations, product
from pathlib import Path

import numpy as np
import pandas as pd


START_CAPITAL = 50_000.0
STREAMS = Path("STOCKS_ALL_SLEEVE_LIBRARY_DAILY_STREAMS_2026-09-08.csv")
OUT = Path("STOCKS_ALL_SLEEVE_WFO_ALLOCATOR_2026-09-08.csv")
FOLDS_OUT = Path("STOCKS_ALL_SLEEVE_WFO_ALLOCATOR_FOLDS_2026-09-08.csv")


SLEEVES_ALL = [
    "broad_adv10_g2_dd85",
    "local_xs_filtered_s30",
    "local_xs_full_s10",
    "ml_ex6_0935_s20",
    "ml_full_0935_s20",
    "rebound_ex6_g08",
    "yday_ex6_actual",
    "intraday_full",
    "intraday_ex6",
    "intraday_ex10",
]

SLEEVES_CLEAN = [
    "broad_adv10_g2_dd85",
    "local_xs_full_s10",
    "ml_ex6_0935_s20",
    "yday_ex6_actual",
    "intraday_ex10",
]


def max_drawdown_from_pnl(pnl: pd.Series) -> float:
    equity = START_CAPITAL + pnl.cumsum()
    return float((equity - equity.cummax()).min())


def stats(daily: pd.DataFrame, pnl: pd.Series) -> dict[str, float]:
    if pnl.empty:
        return {"pnl": 0.0, "dd": 0.0, "sharpe": np.nan}
    total = float(pnl.sum())
    dd = max_drawdown_from_pnl(pnl)
    sharpe = float(pnl.mean() / pnl.std() * np.sqrt(252)) if pnl.std() > 0 else np.nan
    yearly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(year=lambda x: x["date"].dt.year).groupby("year")["pnl"].sum()
    return {
        "pnl": total,
        "dd": dd,
        "sharpe": sharpe,
        "negYears": int((yearly < 0).sum()),
        "minYear": float(yearly.min()) if len(yearly) else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }


def make_candidates(cols: list[str], max_active: int, max_weight: float, max_total: float) -> list[dict[str, float]]:
    grid = [0.3, 0.6]
    cands: list[dict[str, float]] = []
    for k in range(1, max_active + 1):
        for subset in combinations(cols, k):
            for weights in product(grid, repeat=k):
                if max(weights) > max_weight:
                    continue
                if sum(weights) > max_total:
                    continue
                cands.append(dict(zip(subset, weights)))
    return cands


def pnl_for(daily: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    out = pd.Series(0.0, index=daily.index)
    for name, weight in weights.items():
        out = out + daily[name].fillna(0.0) * weight
    return out


def max_drawdown_np(pnl: np.ndarray) -> float:
    equity = START_CAPITAL + np.cumsum(pnl)
    return float(np.min(equity - np.maximum.accumulate(equity)))


def score_train_np(x: np.ndarray, month_codes: np.ndarray, weights: dict[str, float], cols: list[str]) -> float:
    w = np.array([weights.get(c, 0.0) for c in cols], dtype=float)
    pnl = x @ w
    total = float(pnl.sum())
    if total <= 0:
        return -1e9
    dd = max_drawdown_np(pnl)
    monthly = np.bincount(month_codes, weights=pnl)
    neg_months = int(np.sum(monthly < 0))
    # Prefer high return/DD, but penalize month fragility and too many knobs.
    return (total / max(abs(dd), 1.0)) - 0.10 * neg_months - 0.05 * len(weights)


def choose_best(train: pd.DataFrame, candidates: list[dict[str, float]], cols: list[str]) -> dict[str, float]:
    x = train[cols].fillna(0.0).to_numpy(dtype=float)
    month_codes = pd.factorize(train["date"].dt.to_period("M"))[0]
    best_score = -1e18
    best_weights: dict[str, float] = {}
    for weights in candidates:
        score = score_train_np(x, month_codes, weights, cols)
        if score > best_score:
            best_score = score
            best_weights = weights
    return best_weights


def run_wfo(daily: pd.DataFrame, cols: list[str], label: str, train_months: int, max_active: int) -> tuple[dict[str, object], pd.DataFrame]:
    candidates = make_candidates(cols, max_active=max_active, max_weight=0.6, max_total=2.0)
    months = sorted(daily["date"].dt.to_period("M").unique())
    fold_rows = []
    pnl_parts = []
    for i in range(train_months, len(months)):
        train_ms = months[i - train_months : i]
        test_m = months[i]
        train = daily[daily["date"].dt.to_period("M").isin(train_ms)].copy()
        test = daily[daily["date"].dt.to_period("M").eq(test_m)].copy()
        weights = choose_best(train, candidates, cols)
        test_pnl = pnl_for(test, weights)
        train_pnl = pnl_for(train, weights)
        fold_row: dict[str, object] = {
            "label": label,
            "trainMonths": train_months,
            "maxActive": max_active,
            "testMonth": str(test_m),
            "weights": ";".join(f"{k}:{v:g}" for k, v in weights.items()),
            "activeSleeves": len(weights),
            "totalWeight": float(sum(weights.values())),
            "trainPnl": float(train_pnl.sum()),
            "trainDd": max_drawdown_from_pnl(train_pnl),
            "testPnl": float(test_pnl.sum()),
            "testDd": max_drawdown_from_pnl(test_pnl),
        }
        fold_rows.append(fold_row)
        pnl_parts.append(pd.DataFrame({"date": test["date"], "pnl": test_pnl}))
    oos = pd.concat(pnl_parts, ignore_index=True) if pnl_parts else pd.DataFrame(columns=["date", "pnl"])
    summary: dict[str, object] = {
        "label": label,
        "trainMonths": train_months,
        "maxActive": max_active,
        "folds": len(fold_rows),
        "start": str(oos["date"].min().date()) if not oos.empty else "",
        "end": str(oos["date"].max().date()) if not oos.empty else "",
    }
    summary.update(stats(oos.rename(columns={"pnl": "daily_pnl"}), oos["pnl"] if not oos.empty else pd.Series(dtype=float)))
    if fold_rows:
        fr = pd.DataFrame(fold_rows)
        summary["negTestMonths"] = int((fr["testPnl"] < 0).sum())
        summary["minTestMonth"] = float(fr["testPnl"].min())
        summary["medianTestMonth"] = float(fr["testPnl"].median())
        summary["avgActiveSleeves"] = float(fr["activeSleeves"].mean())
        summary["avgTotalWeight"] = float(fr["totalWeight"].mean())
    return summary, pd.DataFrame(fold_rows)


def fixed_mix(daily: pd.DataFrame, weights: dict[str, float], label: str) -> dict[str, object]:
    pnl = pnl_for(daily, weights)
    row: dict[str, object] = {
        "label": label,
        "trainMonths": 0,
        "maxActive": len(weights),
        "folds": 0,
        "start": str(daily["date"].min().date()),
        "end": str(daily["date"].max().date()),
        "weights": ";".join(f"{k}:{v:g}" for k, v in weights.items()),
    }
    row.update(stats(daily, pnl))
    monthly = pd.DataFrame({"date": daily["date"], "pnl": pnl}).assign(month=lambda x: x["date"].dt.to_period("M")).groupby("month")["pnl"].sum()
    row["negTestMonths"] = int((monthly < 0).sum())
    row["minTestMonth"] = float(monthly.min())
    row["medianTestMonth"] = float(monthly.median())
    row["avgActiveSleeves"] = len(weights)
    row["avgTotalWeight"] = float(sum(weights.values()))
    return row


def main() -> None:
    daily = pd.read_csv(STREAMS, parse_dates=["date"]).sort_values("date").reset_index(drop=True)
    rows: list[dict[str, object]] = []
    folds: list[pd.DataFrame] = []

    reference_weights = {
        "broad_adv10_g2_dd85": 0.60,
        "local_xs_full_s10": 0.50,
        "ml_ex6_0935_s20": 0.33,
        "yday_ex6_actual": 0.46,
        "intraday_full": 0.32,
        "intraday_ex10": 0.42,
    }
    simpler_weights = {
        "broad_adv10_g2_dd85": 0.80,
        "local_xs_full_s10": 0.50,
        "yday_ex6_actual": 0.30,
        "intraday_ex10": 0.30,
    }
    equal_clean = {name: 0.35 for name in SLEEVES_CLEAN}
    equal_all = {name: 0.20 for name in SLEEVES_ALL}

    for weights, label in [
        (reference_weights, "fixed_reference_lookback_biased"),
        (simpler_weights, "fixed_simpler_lookback_biased"),
        (equal_clean, "fixed_equal_clean"),
        (equal_all, "fixed_equal_all"),
    ]:
        rows.append(fixed_mix(daily, weights, label))

    for cols, universe_label in [(SLEEVES_CLEAN, "clean"), (SLEEVES_ALL, "all")]:
        for train_months in [6, 12]:
            for max_active in [3, 4]:
                summary, fold = run_wfo(
                    daily,
                    cols,
                    label=f"wfo_{universe_label}_train{train_months}_max{max_active}",
                    train_months=train_months,
                    max_active=max_active,
                )
                rows.append(summary)
                folds.append(fold)

    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.concat(folds, ignore_index=True).to_csv(FOLDS_OUT, index=False)
    print("WROTE", OUT, FOLDS_OUT)


if __name__ == "__main__":
    main()
