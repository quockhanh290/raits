from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_FINAL_COSTAWARE_FOUR_SLEEVE_GRID_PREREG_2026-09-24.json")
PREFIX = "STOCKS_FINAL_COSTAWARE_FOUR_SLEEVE_GRID_2026-09-24"
START, DEV_END = pd.Timestamp("2018-04-27"), pd.Timestamp("2022-12-30")
VAL_START, END = pd.Timestamp("2023-01-03"), pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0

SOURCES = {
    "pairs": {
        "variant": "sic_pairs_quarterly_z2_hold10",
        "daily": Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_DAILY.csv"),
        "ticker": Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_TICKER_CONTRIB.csv"),
    },
    "crisis": {
        "variant": "overnight20_negative_05x",
        "daily": Path("STOCKS_PIT_FULL_RESIDUAL_CRISIS_SLEEVE_2026-09-17_DAILY.csv"),
        "ticker": Path("STOCKS_PIT_FULL_RESIDUAL_CRISIS_SLEEVE_2026-09-17_TICKER_CONTRIB.csv"),
    },
    "reversal": {
        "variant": "market_resid_rev_10x10_hold5",
        "daily": Path("STOCKS_PIT_FULL_RESIDUAL_REVERSAL_COHORTS_2026-09-17_DAILY.csv"),
        "ticker": Path("STOCKS_PIT_FULL_RESIDUAL_REVERSAL_COHORTS_2026-09-17_TICKER_CONTRIB.csv"),
    },
}
CALENDAR_DAILY = Path("STOCKS_PIT_FULL_TURN_OF_MONTH_COSTAWARE_2026-09-14_DAILY.csv")
CALENDAR_VARIANT = "spy_first5_x25_fin25_cost4"
SOURCE_ORDER = ["pairs", "calendar", "crisis", "reversal"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    stream_frames, ticker_frames = [], []
    for name, spec in SOURCES.items():
        daily = pd.read_csv(spec["daily"], parse_dates=["date"])
        daily = daily[daily["variant"].eq(spec["variant"])].sort_values("date").copy()
        daily["prior_source_equity"] = daily["equity"] - daily["daily_pnl"]
        daily["gross_ret"] = (daily["daily_pnl"] + daily["trade_cost"] + daily["borrow_cost"]) / daily["prior_source_equity"]
        daily["short_gross"] = daily["gross_exposure"] / 2.0
        stream_frames.append(daily[["date", "gross_ret", "turnover", "gross_exposure", "short_gross"]].assign(source=name))

        contrib = pd.read_csv(spec["ticker"], parse_dates=["date"])
        contrib = contrib[contrib["variant"].eq(spec["variant"])].groupby(["date", "ticker"], as_index=False)["pnl"].sum()
        contrib = contrib.merge(daily[["date", "prior_source_equity", "trade_cost", "borrow_cost"]], on="date", how="left")
        contrib["net_ret"] = contrib["pnl"] / contrib["prior_source_equity"]
        absolute = contrib.groupby("date")["net_ret"].transform(lambda x: x.abs().sum())
        reversal = (contrib["trade_cost"] + contrib["borrow_cost"]) / contrib["prior_source_equity"]
        contrib["ticker_gross_ret"] = contrib["net_ret"] + np.where(absolute > 0, contrib["net_ret"].abs() / absolute * reversal, 0.0)
        ticker_frames.append(contrib[["date", "ticker", "ticker_gross_ret"]].assign(source=name))

    calendar = pd.read_csv(CALENDAR_DAILY, parse_dates=["date"])
    calendar = calendar[calendar["variant"].eq(CALENDAR_VARIANT)].sort_values("date").copy()
    calendar["gross_ret"] = calendar["exposure"] * calendar["base_ret"]
    calendar["gross_exposure"] = calendar["exposure"]
    calendar["short_gross"] = 0.0
    stream_frames.append(calendar[["date", "gross_ret", "turnover", "gross_exposure", "short_gross"]].assign(source="calendar"))
    ticker_frames.append(calendar[["date", "gross_ret"]].rename(columns={"gross_ret": "ticker_gross_ret"}).assign(ticker="SPY", source="calendar"))

    streams = pd.concat(stream_frames, ignore_index=True)
    streams = streams[streams["date"].between(START, END)]
    wide = streams.pivot(index="date", columns="source", values=["gross_ret", "turnover", "gross_exposure", "short_gross"])
    calendar_index = pd.DatetimeIndex(sorted(wide.index))
    expected = pd.MultiIndex.from_product([["gross_ret", "turnover", "gross_exposure", "short_gross"], SOURCE_ORDER])
    wide = wide.reindex(index=calendar_index, columns=expected).fillna(0.0)
    tickers = pd.concat(ticker_frames, ignore_index=True)
    tickers = tickers[tickers["date"].between(START, END)].copy()
    return wide, tickers


def replay(wide: pd.DataFrame, weights: dict[str, float], scale: float, begin: pd.Timestamp, finish: pd.Timestamp) -> pd.DataFrame:
    x = wide.loc[begin:finish]
    w = np.array([weights[name] for name in SOURCE_ORDER], dtype=float) * scale
    gross_ret = x["gross_ret"][SOURCE_ORDER].to_numpy() @ w
    turnover = x["turnover"][SOURCE_ORDER].to_numpy() @ w
    gross = x["gross_exposure"][SOURCE_ORDER].to_numpy() @ w
    short = x["short_gross"][SOURCE_ORDER].to_numpy() @ w
    trade_ret = turnover * 4.0 / 10_000.0
    borrow_ret = short * 0.01 / 252.0
    financing_ret = np.maximum(gross - 1.0, 0.0) * 0.025 / 252.0
    net_ret = gross_ret - trade_ret - borrow_ret - financing_ret
    equity = START_CAPITAL * np.cumprod(1.0 + net_ret)
    prior = np.r_[START_CAPITAL, equity[:-1]]
    return pd.DataFrame({"date": x.index, "gross_ret": gross_ret, "net_ret": net_ret, "prior_equity": prior,
        "daily_pnl": prior * net_ret, "equity": equity, "turnover": turnover, "gross_exposure": gross,
        "short_gross": short, "trade_cost": prior * trade_ret, "borrow_cost": prior * borrow_ret,
        "financing_cost": prior * financing_ret})


def stats(path: pd.DataFrame) -> dict[str, float | int]:
    curve = pd.concat([pd.Series([START_CAPITAL]), path["equity"].reset_index(drop=True)], ignore_index=True)
    peak = curve.cummax()
    years = max((path["date"].max() - path["date"].min()).days / 365.25, 1e-9)
    yearly = (1.0 + path["net_ret"]).groupby(path["date"].dt.year).prod() - 1.0
    return {"days": len(path), "pnl": path["daily_pnl"].sum(), "cagr": (path["equity"].iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0,
        "sharpe": path["net_ret"].mean() / path["net_ret"].std() * math.sqrt(252),
        "ddDollar": (curve - peak).min(), "ddPct": (curve / peak - 1.0).min(), "positiveYears": int(yearly.gt(0).sum()),
        "avgGross": path["gross_exposure"].mean(), "maxGross": path["gross_exposure"].max(),
        "tradeCost": path["trade_cost"].sum(), "borrowCost": path["borrow_cost"].sum(), "financingCost": path["financing_cost"].sum()}


def ticker_path(tickers: pd.DataFrame, path: pd.DataFrame, weights: dict[str, float], scale: float) -> pd.DataFrame:
    active = tickers[tickers["source"].map(weights).fillna(0.0).gt(0)].copy()
    active["weighted_ret"] = active["ticker_gross_ret"] * active["source"].map(weights) * scale
    combined = active.groupby(["date", "ticker"], as_index=False)["weighted_ret"].sum()
    combined = combined.merge(path[["date", "prior_equity", "trade_cost", "borrow_cost", "financing_cost"]], on="date", how="inner")
    combined["gross_pnl"] = combined["prior_equity"] * combined["weighted_ret"]
    absolute = combined.groupby("date")["gross_pnl"].transform(lambda x: x.abs().sum())
    total_cost = combined["trade_cost"] + combined["borrow_cost"] + combined["financing_cost"]
    combined["allocated_cost"] = np.where(absolute > 0, combined["gross_pnl"].abs() / absolute * total_cost, 0.0)
    zero_dates = combined.loc[absolute.eq(0), "date"].drop_duplicates()
    for date in zero_dates:
        mask = combined["date"].eq(date)
        spy = mask & combined["ticker"].eq("SPY")
        target = combined.index[spy][0] if spy.any() else combined.index[mask][0]
        combined.loc[target, "allocated_cost"] = float(total_cost.loc[target])
    combined["pnl"] = combined["gross_pnl"] - combined["allocated_cost"]
    return combined


def concentration(ticker: pd.DataFrame) -> dict[str, object]:
    by = ticker.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(by.sum())
    positive = by[by > 0]
    basis = positive if positive.sum() > 0 else by.abs()
    weights = basis / basis.sum() if basis.sum() else basis
    row: dict[str, object] = {"tickers": len(by), "netTickerPnl": total, "effectiveTickerCount": 1.0 / weights.pow(2).sum() if len(weights) else 0.0,
        "topTicker": by.index[0] if len(by) else "", "spyPnl": float(by.get("SPY", 0.0)), "spyNetPnlShare": float(by.get("SPY", 0.0)) / total if total else np.nan}
    denominator = total if total > 0 else float(by.abs().sum())
    for n in (1, 3, 5, 10):
        value = float(by.head(n).sum())
        row[f"top{n}Pnl"], row[f"top{n}Share"] = value, value / denominator if denominator else np.nan
    return row


def weight_string(weights: dict[str, float]) -> str:
    return "|".join(f"{name}={weights[name]:.3f}" for name in SOURCE_ORDER if weights[name] > 0)


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_performance") or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    wide, tickers = load_inputs()
    dev_tickers = tickers[tickers["date"].between(START, DEV_END)]
    grid_rows = []
    selected_payload = None
    for units in itertools.product(range(9), repeat=4):
        if sum(units) != 8 or sum(unit > 0 for unit in units) < 2:
            continue
        weights = {name: units[i] / 8.0 for i, name in enumerate(SOURCE_ORDER)}
        path = replay(wide, weights, 1.0, START, DEV_END)
        result = stats(path)
        preliminary = result["cagr"] >= 0.08 and result["ddPct"] >= -0.12 and result["positiveYears"] >= 4
        conc = concentration(ticker_path(dev_tickers, path, weights, 1.0)) if preliminary else {"spyNetPnlShare": np.nan}
        passed = bool(preliminary and conc["spyNetPnlShare"] <= 0.65)
        grid_rows.append({"weights": weight_string(weights), "units": json.dumps(units), "nonzeroSleeves": sum(unit > 0 for unit in units),
            "developmentPass": passed, **result, "spyNetPnlShare": conc["spyNetPnlShare"],
            "rejectionReason": "" if passed else ("return_dd_year_gate" if not preliminary else "spy_share>65%")})
    grid = pd.DataFrame(grid_rows).sort_values(["developmentPass", "cagr", "sharpe", "ddPct", "weights"], ascending=[False, False, False, False, True])
    passing = grid[grid["developmentPass"].eq(True)]
    if passing.empty:
        selection = {"selectedWeights": None, "status": "KILL_NO_DEVELOPMENT_PASS", "validationOpened": False}
        summary = yearly = source_summary = ticker_selected = concentrations = pd.DataFrame()
        daily_all = pd.DataFrame()
    else:
        units = json.loads(passing.iloc[0]["units"])
        weights = {name: units[i] / 8.0 for i, name in enumerate(SOURCE_ORDER)}
        selected_payload = weights
        daily_frames, summary_rows, yearly_rows, source_rows, ticker_frames, concentration_rows = [], [], [], [], [], []
        for scale in prereg["selected_row_scale_audit"]:
            for stage, begin, finish in (("development", START, DEV_END), ("validation_touched", VAL_START, END), ("full_touched", START, END)):
                path = replay(wide, weights, scale, begin, finish)
                path["scale"], path["stage"] = scale, stage
                daily_frames.append(path)
                result = stats(path)
                summary_rows.append({"scale": scale, "stage": stage, "weights": weight_string(weights), **result})
                for year, group in path.assign(year=path["date"].dt.year).groupby("year"):
                    yearly_rows.append({"scale": scale, "stage": stage, "year": year, "pnl": group["daily_pnl"].sum(), "tradeCost": group["trade_cost"].sum(), "borrowCost": group["borrow_cost"].sum(), "financingCost": group["financing_cost"].sum()})
                period_tickers = tickers[tickers["date"].between(begin, finish)]
                tc = ticker_path(period_tickers, path, weights, scale)
                tc["scale"], tc["stage"] = scale, stage
                ticker_frames.append(tc)
                concentration_rows.append({"scale": scale, "stage": stage, **concentration(tc)})
                prior = path.set_index("date")["prior_equity"]
                for name in SOURCE_ORDER:
                    component = wide.loc[begin:finish, ("gross_ret", name)]
                    pnl = float((prior * scale * weights[name] * component).sum())
                    source_rows.append({"scale": scale, "stage": stage, "component": f"{name}_gross", "pnl": pnl})
                for component in ("trade_cost", "borrow_cost", "financing_cost"):
                    source_rows.append({"scale": scale, "stage": stage, "component": component, "pnl": -float(path[component].sum())})
        daily_all = pd.concat(daily_frames, ignore_index=True)
        summary, yearly = pd.DataFrame(summary_rows), pd.DataFrame(yearly_rows)
        source_summary, ticker_selected = pd.DataFrame(source_rows), pd.concat(ticker_frames, ignore_index=True)
        concentrations = pd.DataFrame(concentration_rows)
        val = summary[(summary["scale"].eq(1.0)) & summary["stage"].eq("validation_touched")].iloc[0]
        val_conc = concentrations[(concentrations["scale"].eq(1.0)) & concentrations["stage"].eq("validation_touched")].iloc[0]
        val_years = yearly[(yearly["scale"].eq(1.0)) & yearly["stage"].eq("validation_touched")]["pnl"]
        validation_pass = bool(val["cagr"] > 0 and val["ddPct"] >= -0.15 and val_years.gt(0).all() and val_conc["spyNetPnlShare"] <= 0.80)
        selection = {"selectedWeights": weight_string(weights), "developmentRank": 1, "developmentPass": True,
            "validationPass": validation_pass, "status": "CONTINUE_DIAGNOSTIC" if validation_pass else "KILL_VALIDATION",
            "productionPassAllowed": False}

    grid.to_csv(f"{PREFIX}_GRID.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    daily_all.to_csv(f"{PREFIX}_SELECTED_DAILY.csv", index=False)
    summary.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    source_summary.to_csv(f"{PREFIX}_SOURCE_ATTRIBUTION.csv", index=False)
    ticker_selected.to_csv(f"{PREFIX}_TICKER_ATTRIBUTION.csv", index=False)
    concentrations.to_csv(f"{PREFIX}_CONCENTRATION.csv", index=False)
    inputs = [spec[key] for spec in SOURCES.values() for key in ("daily", "ticker")] + [CALENDAR_DAILY, PREREG]
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in inputs}, "gridRows": len(grid),
        "developmentPassRows": int(grid["developmentPass"].sum()), "selection": selection,
        "oos2025_2026Consumed": False, "productionPassAllowed": False,
        "ruleSelectionEffect": "One row selected by frozen development gates and ranking; validation does not alter it.",
        "tradeSelectionEffect": "None; all four source trade streams are inherited unchanged.",
        "tickerCostAllocationExact": False}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(grid.head(10).to_string(index=False), flush=True)
    print(json.dumps(selection, indent=2), flush=True)
    print(summary.to_string(index=False), flush=True)
    print(concentrations.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
