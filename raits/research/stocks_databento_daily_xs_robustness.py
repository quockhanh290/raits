from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_databento_daily_xs_mtm as mtm


OUT = Path("STOCKS_DATABENTO_DAILY_XS_ROBUSTNESS_2026-09-08.csv")
BOOT_OUT = Path("STOCKS_DATABENTO_DAILY_XS_ROBUSTNESS_BOOTSTRAP_2026-09-08.csv")
MIX_OUT = Path("STOCKS_ALL_SLEEVE_LIBRARY_ROBUSTNESS_2026-09-08.csv")


def metrics_from_equity(eq: pd.DataFrame) -> dict[str, float]:
    if eq.empty:
        return {"pnl": 0.0, "dd": 0.0, "sharpe": np.nan, "negYears": np.nan, "minYear": np.nan}
    equity = eq.set_index("date")["equity"]
    pnl = float(equity.iloc[-1] - mtm.START_CAPITAL)
    dd = mtm.max_drawdown(equity)
    daily = eq["daily_pnl"].astype(float)
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else np.nan
    yearly = eq.assign(year=eq["date"].dt.year).groupby("year")["daily_pnl"].sum()
    return {
        "pnl": pnl,
        "dd": float(dd),
        "sharpe": sharpe,
        "negYears": int((yearly < 0).sum()),
        "minYear": float(yearly.min()) if len(yearly) else np.nan,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }


def approximate_symbol_pnl(panel: pd.DataFrame, trades: pd.DataFrame, cost_bps: float) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    close_lookup = panel.set_index(["date", "symbol"])["close"]
    cost_rate = cost_bps / 10_000.0
    rows = []
    for _, t in trades.iterrows():
        key = (pd.Timestamp(t["planned_exit_date"]), str(t["symbol"]))
        if key not in close_lookup.index:
            continue
        exit_px = float(close_lookup.loc[key])
        shares = float(t["shares"])
        gross = shares * (exit_px - float(t["entry_price"]))
        cost = float(t["entry_cost"]) + shares * exit_px * cost_rate
        rows.append((str(t["symbol"]), gross - cost))
    if not rows:
        return pd.Series(dtype=float)
    return pd.DataFrame(rows, columns=["symbol", "pnl"]).groupby("symbol")["pnl"].sum().sort_values(ascending=False)


def run_cfg(panel: pd.DataFrame, cfg: mtm.Config, cost_bps: float, label: str) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    old_cost = mtm.COST_BPS
    mtm.COST_BPS = cost_bps
    try:
        summary, trades, eq = mtm.simulate(panel, cfg)
    finally:
        mtm.COST_BPS = old_cost
    row: dict[str, object] = {"label": label, "costBps": cost_bps}
    row.update(summary)
    return row, trades, eq


def bootstrap_months(eq: pd.DataFrame, label: str, n: int = 2000, seed: int = 7) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    daily = eq[["date", "daily_pnl"]].copy()
    daily["month"] = daily["date"].dt.to_period("M").astype(str)
    months = [m for _, m in daily.groupby("month", sort=True)]
    pnl_vals = []
    dd_vals = []
    for _ in range(n):
        sample = [months[int(i)] for i in rng.integers(0, len(months), len(months))]
        pnl = pd.concat(sample, ignore_index=True)["daily_pnl"].to_numpy(dtype=float)
        equity = pd.Series(mtm.START_CAPITAL + np.cumsum(pnl))
        pnl_vals.append(float(equity.iloc[-1] - mtm.START_CAPITAL))
        dd_vals.append(float((equity - equity.cummax()).min()))
    pnl_a = np.array(pnl_vals)
    dd_a = np.array(dd_vals)
    return {
        "label": label,
        "bootN": n,
        "pnlP05": float(np.quantile(pnl_a, 0.05)),
        "pnlP50": float(np.quantile(pnl_a, 0.50)),
        "pnlP95": float(np.quantile(pnl_a, 0.95)),
        "ddP05": float(np.quantile(dd_a, 0.05)),
        "ddP50": float(np.quantile(dd_a, 0.50)),
        "ddP95": float(np.quantile(dd_a, 0.95)),
        "probPnlNeg": float((pnl_a < 0).mean()),
        "probDdWorse20k": float((dd_a <= -20_000).mean()),
    }


def mix_metrics(streams: pd.DataFrame, weights: dict[str, float], label: str) -> tuple[dict[str, object], pd.DataFrame]:
    daily_pnl = sum(streams[name].fillna(0.0) * weight for name, weight in weights.items())
    eq = pd.DataFrame({"date": streams["date"], "daily_pnl": daily_pnl})
    eq["equity"] = mtm.START_CAPITAL + eq["daily_pnl"].cumsum()
    row: dict[str, object] = {"label": label, "weights": " ".join(f"{k}:{v:g}" for k, v in weights.items())}
    row.update(metrics_from_equity(eq))
    return row, eq


def main() -> None:
    panel = mtm.load_panel()
    base_cfg = mtm.Config(
        adv=10_000_000.0,
        slots=20,
        hold=20,
        gross_cap=2.0,
        layer_gross=0.10,
        min_ret5=-0.50,
        max_ticker_gross=0.10,
        active_ticker_cap=3,
    )

    rows = []
    boot_rows = []

    base_row, base_trades, base_eq = run_cfg(panel, base_cfg, 4.0, "base_adv10_g2")
    rows.append(base_row)
    boot_rows.append(bootstrap_months(base_eq, "base_adv10_g2"))
    top = approximate_symbol_pnl(panel, base_trades, 4.0)

    for cost in [0.0, 1.0, 4.0, 10.0, 15.0, 25.0]:
        row, _, eq = run_cfg(panel, base_cfg, cost, f"cost_{cost:g}bps")
        rows.append(row)
        if cost in {10.0, 25.0}:
            boot_rows.append(bootstrap_months(eq, f"cost_{cost:g}bps"))

    for k in [1, 3, 5, 10, 20, 50, 100]:
        drop = set(top.head(k).index)
        filtered = panel[~panel["symbol"].isin(drop)].copy()
        row, _, eq = run_cfg(filtered, base_cfg, 4.0, f"drop_top_{k}_symbols")
        row["droppedSymbols"] = ",".join(top.head(k).index)
        rows.append(row)
        if k in {10, 50, 100}:
            boot_rows.append(bootstrap_months(eq, f"drop_top_{k}_symbols"))

    symbols = np.array(sorted(panel["symbol"].dropna().astype(str).unique()))
    for frac in [0.10, 0.25, 0.50]:
        for seed in range(10):
            rng = np.random.default_rng(1000 + seed)
            drop_n = int(round(len(symbols) * frac))
            drop = set(rng.choice(symbols, size=drop_n, replace=False))
            filtered = panel[~panel["symbol"].isin(drop)].copy()
            row, _, _ = run_cfg(filtered, base_cfg, 4.0, f"random_drop_{int(frac*100)}pct_seed{seed}")
            row["dropFrac"] = frac
            row["dropN"] = drop_n
            rows.append(row)

    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.DataFrame(boot_rows).to_csv(BOOT_OUT, index=False)

    streams = pd.read_csv("STOCKS_ALL_SLEEVE_LIBRARY_DAILY_STREAMS_2026-09-08.csv", parse_dates=["date"])
    mix_rows = []
    best_score_weights = {
        "broad_adv10_g2_dd85": 0.60,
        "local_xs_full_s10": 0.50,
        "ml_ex6_0935_s20": 0.33,
        "yday_ex6_actual": 0.46,
        "intraday_full": 0.32,
        "intraday_ex10": 0.42,
    }
    broad_clean_weights = {
        "broad_adv10_g2_dd85": 0.80,
        "local_xs_full_s10": 0.50,
        "yday_ex6_actual": 0.30,
        "intraday_ex10": 0.30,
    }
    for label, weights in [
        ("opt_best_score_pnl35", best_score_weights),
        ("simpler_broad_clean", broad_clean_weights),
    ]:
        row, eq = mix_metrics(streams, weights, label)
        mix_rows.append(row)
        boot_rows.append(bootstrap_months(eq, f"mix_{label}"))
        for name in list(weights):
            w2 = dict(weights)
            w2.pop(name)
            row, _ = mix_metrics(streams, w2, f"{label}_without_{name}")
            mix_rows.append(row)
    pd.DataFrame(mix_rows).to_csv(MIX_OUT, index=False)
    pd.DataFrame(boot_rows).to_csv(BOOT_OUT, index=False)
    print("WROTE", OUT, BOOT_OUT, MIX_OUT)


if __name__ == "__main__":
    main()
