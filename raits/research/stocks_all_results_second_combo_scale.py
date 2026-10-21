from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_ALL_RESULTS_SECOND_COMBO_SCALE_PREREG_2026-09-24.json")
GRID = Path("STOCKS_ALL_RESULTS_SLEEVE_GRID_2026-09-24_GRID.csv")
PAIR_DAILY = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_DAILY.csv")
PAIR_CONTRIB = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_TICKER_CONTRIB.csv")
CALENDAR_DAILY = Path("STOCKS_PIT_FULL_TURN_OF_MONTH_COSTAWARE_2026-09-14_DAILY.csv")
PREFIX = "STOCKS_ALL_RESULTS_SECOND_COMBO_SCALE_2026-09-24"
PAIR_VARIANT = "sic_pairs_quarterly_z2_hold10"
CALENDAR_VARIANT = "spy_first5_x25_fin25_cost4"
START = pd.Timestamp("2018-04-27")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_streams() -> tuple[pd.DataFrame, pd.DataFrame]:
    pair = pd.read_csv(PAIR_DAILY, parse_dates=["date"])
    pair = pair[pair["variant"].eq(PAIR_VARIANT)].sort_values("date").copy()
    pair["prior_source_equity"] = pair["equity"] - pair["daily_pnl"]
    pair["pair_gross_ret"] = (pair["daily_pnl"] + pair["trade_cost"] + pair["borrow_cost"]) / pair["prior_source_equity"]
    pair["pair_short_gross"] = pair["gross_exposure"] / 2.0

    calendar = pd.read_csv(CALENDAR_DAILY, parse_dates=["date"])
    calendar = calendar[calendar["variant"].eq(CALENDAR_VARIANT)].sort_values("date").copy()
    calendar["calendar_gross_ret"] = calendar["exposure"] * calendar["base_ret"]
    streams = pair[["date", "pair_gross_ret", "turnover", "gross_exposure", "pair_short_gross"]].rename(
        columns={"turnover": "pair_turnover", "gross_exposure": "pair_gross"}
    ).merge(
        calendar[["date", "calendar_gross_ret", "turnover", "exposure"]].rename(
            columns={"turnover": "calendar_turnover", "exposure": "calendar_gross"}
        ), on="date", how="inner"
    )
    return streams[streams["date"].between(START, END)].copy(), pair


def pair_ticker_gross(pair: pd.DataFrame) -> pd.DataFrame:
    contrib = pd.read_csv(PAIR_CONTRIB, parse_dates=["date"])
    contrib = contrib[contrib["variant"].eq(PAIR_VARIANT)].groupby(["date", "ticker"], as_index=False)["pnl"].sum()
    costs = pair.set_index("date")[["prior_source_equity", "trade_cost", "borrow_cost"]]
    contrib = contrib.merge(costs, on="date", how="left")
    contrib["net_ret"] = contrib["pnl"] / contrib["prior_source_equity"]
    absolute = contrib.groupby("date")["net_ret"].transform(lambda x: x.abs().sum())
    reversal = (contrib["trade_cost"] + contrib["borrow_cost"]) / contrib["prior_source_equity"]
    contrib["gross_ret"] = contrib["net_ret"] + np.where(absolute > 0, contrib["net_ret"].abs() / absolute * reversal, 0.0)
    return contrib[["date", "ticker", "gross_ret"]]


def metrics(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    periods = (("development", START, DEV_END), ("validation_touched", VAL_START, END), ("full_touched", START, END))
    for scale, frame in daily.groupby("scale", sort=True):
        for stage, begin, finish in periods:
            x = frame[frame["date"].between(begin, finish)].copy()
            start_equity = float(x.iloc[0]["prior_equity"])
            curve = pd.concat([pd.Series([start_equity]), x["equity"].reset_index(drop=True)], ignore_index=True)
            peak = curve.cummax()
            years = max((x["date"].max() - x["date"].min()).days / 365.25, 1e-9)
            yearly = (1.0 + x["net_ret"]).groupby(x["date"].dt.year).prod() - 1.0
            rows.append({"scale": scale, "stage": stage, "days": len(x), "pnl": x["daily_pnl"].sum(),
                "cagr": (x.iloc[-1]["equity"] / start_equity) ** (1.0 / years) - 1.0,
                "sharpe": x["net_ret"].mean() / x["net_ret"].std() * math.sqrt(252),
                "ddDollar": (curve - peak).min(), "ddPct": (curve / peak - 1.0).min(),
                "positiveYears": int(yearly.gt(0).sum()), "avgGross": x["gross_exposure"].mean(),
                "maxGross": x["gross_exposure"].max(), "tradeCost": x["trade_cost"].sum(),
                "borrowCost": x["borrow_cost"].sum(), "financingCost": x["financing_cost"].sum()})
    return pd.DataFrame(rows)


def concentration(ticker: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (scale, stage), group in ticker.groupby(["scale", "stage"], sort=True):
        by_ticker = group.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        total = float(by_ticker.sum())
        positive = by_ticker[by_ticker > 0]
        basis = positive if positive.sum() > 0 else by_ticker.abs()
        weights = basis / basis.sum() if basis.sum() else basis
        row = {"scale": scale, "stage": stage, "tickers": len(by_ticker), "netTickerPnl": total,
            "effectiveTickerCount": 1.0 / weights.pow(2).sum() if len(weights) else 0.0,
            "topTicker": by_ticker.index[0] if len(by_ticker) else ""}
        denominator = total if total > 0 else float(by_ticker.abs().sum())
        for n in (1, 3, 5, 10):
            value = float(by_ticker.head(n).sum())
            row[f"top{n}Pnl"] = value
            row[f"top{n}Share"] = value / denominator if denominator else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_performance") or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    grid = pd.read_csv(GRID)
    rank2 = grid[grid["developmentPass"].eq(True)].iloc[1]["weights"]
    if not (f"{PAIR_VARIANT}=0.75" in rank2 and f"{CALENDAR_VARIANT}=0.25" in rank2 and rank2.count("|") == 1):
        raise RuntimeError(f"Frozen grid rank 2 changed: {rank2}")

    streams, pair = load_streams()
    pair_ticker = pair_ticker_gross(pair)
    gross_ticker = pd.concat([
        pair_ticker.assign(sleeve="pairs", weighted_ret=lambda x: 0.75 * x["gross_ret"])[["date", "ticker", "sleeve", "weighted_ret"]],
        streams.assign(ticker="SPY", sleeve="calendar", weighted_ret=0.25 * streams["calendar_gross_ret"])[["date", "ticker", "sleeve", "weighted_ret"]]
    ], ignore_index=True)
    gross_ticker = gross_ticker[gross_ticker["date"].between(START, END)]

    daily_frames, source_rows, ticker_frames = [], [], []
    for scale in prereg["scale_candidates"]:
        x = streams.copy()
        x["gross_ret"] = scale * (0.75 * x["pair_gross_ret"] + 0.25 * x["calendar_gross_ret"])
        x["turnover"] = scale * (0.75 * x["pair_turnover"] + 0.25 * x["calendar_turnover"])
        x["gross_exposure"] = scale * (0.75 * x["pair_gross"] + 0.25 * x["calendar_gross"])
        x["short_gross"] = scale * 0.75 * x["pair_short_gross"]
        x["trade_cost_ret"] = x["turnover"] * 4.0 / 10_000.0
        x["borrow_cost_ret"] = x["short_gross"] * 0.01 / 252.0
        x["financing_cost_ret"] = (x["gross_exposure"] - 1.0).clip(lower=0.0) * 0.025 / 252.0
        x["net_ret"] = x["gross_ret"] - x["trade_cost_ret"] - x["borrow_cost_ret"] - x["financing_cost_ret"]
        equity, rows = START_CAPITAL, []
        for row in x.itertuples(index=False):
            prior = equity
            trade, borrow, financing = prior * row.trade_cost_ret, prior * row.borrow_cost_ret, prior * row.financing_cost_ret
            pnl = prior * row.net_ret
            equity += pnl
            rows.append({"scale": scale, "date": row.date, "prior_equity": prior, "gross_ret": row.gross_ret,
                "net_ret": row.net_ret, "daily_pnl": pnl, "equity": equity, "gross_exposure": row.gross_exposure,
                "short_gross": row.short_gross, "turnover": row.turnover, "trade_cost": trade,
                "borrow_cost": borrow, "financing_cost": financing})
            source_rows.extend([
                {"scale": scale, "date": row.date, "component": "pairs_gross", "pnl": prior * scale * 0.75 * row.pair_gross_ret},
                {"scale": scale, "date": row.date, "component": "calendar_gross", "pnl": prior * scale * 0.25 * row.calendar_gross_ret},
                {"scale": scale, "date": row.date, "component": "trade_cost", "pnl": -trade},
                {"scale": scale, "date": row.date, "component": "borrow_cost", "pnl": -borrow},
                {"scale": scale, "date": row.date, "component": "financing_cost", "pnl": -financing}])
        path = pd.DataFrame(rows)
        daily_frames.append(path)
        tc = gross_ticker.merge(path[["date", "prior_equity", "trade_cost", "borrow_cost", "financing_cost"]], on="date", how="inner")
        tc["gross_pnl"] = tc["prior_equity"] * scale * tc["weighted_ret"]
        absolute = tc.groupby("date")["gross_pnl"].transform(lambda z: z.abs().sum())
        total_cost = tc["trade_cost"] + tc["borrow_cost"] + tc["financing_cost"]
        tc["allocated_cost"] = np.where(absolute > 0, tc["gross_pnl"].abs() / absolute * total_cost, 0.0)
        zero_dates = tc.loc[absolute.eq(0), "date"].drop_duplicates()
        if not zero_dates.empty:
            zero_mask = tc["date"].isin(zero_dates) & tc["ticker"].eq("SPY")
            tc.loc[zero_mask, "allocated_cost"] = total_cost[zero_mask]
        tc["pnl"] = tc["gross_pnl"] - tc["allocated_cost"]
        tc["scale"] = scale
        tc["stage"] = np.where(tc["date"].le(DEV_END), "development", "validation_touched")
        ticker_frames.append(tc[["scale", "stage", "date", "ticker", "sleeve", "gross_pnl", "allocated_cost", "pnl"]])

    daily = pd.concat(daily_frames, ignore_index=True)
    source = pd.DataFrame(source_rows)
    source["stage"] = np.where(source["date"].le(DEV_END), "development", "validation_touched")
    ticker = pd.concat(ticker_frames, ignore_index=True)
    summary = metrics(daily)
    yearly = daily.assign(year=daily["date"].dt.year).groupby(["scale", "year"], as_index=False).agg(
        pnl=("daily_pnl", "sum"), tradeCost=("trade_cost", "sum"), borrowCost=("borrow_cost", "sum"), financingCost=("financing_cost", "sum"))
    source_summary = source.groupby(["scale", "stage", "component"], as_index=False)["pnl"].sum()
    concentrations = concentration(ticker)
    daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    summary.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    source.to_csv(f"{PREFIX}_SOURCE_ATTRIBUTION_DAILY.csv", index=False)
    source_summary.to_csv(f"{PREFIX}_SOURCE_ATTRIBUTION.csv", index=False)
    ticker.to_csv(f"{PREFIX}_TICKER_ATTRIBUTION.csv", index=False)
    concentrations.to_csv(f"{PREFIX}_CONCENTRATION.csv", index=False)

    inputs = [GRID, PAIR_DAILY, PAIR_CONTRIB, CALENDAR_DAILY, PREREG]
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "inputs": {str(p).replace("\\", "/"): sha256(p) for p in inputs}, "frozenGridRank": 2,
        "frozenWeights": prereg["selected_sleeves"], "scales": prereg["scale_candidates"],
        "oos2025_2026Consumed": False, "productionPassAllowed": False,
        "ruleSelectionEffect": "Rank 2 was selected mechanically from the already-frozen development grid; no validation ranking.",
        "tradeSelectionEffect": "None; inherited pair and calendar trades are unchanged.",
        "tickerAttributionCostAllocationExact": False,
        "outputs": [f"{PREFIX}_{x}" for x in ("DAILY.csv", "SUMMARY.csv", "YEARLY.csv", "SOURCE_ATTRIBUTION_DAILY.csv", "SOURCE_ATTRIBUTION.csv", "TICKER_ATTRIBUTION.csv", "CONCENTRATION.csv", "MANIFEST.json")]}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.to_string(index=False), flush=True)
    print(source_summary.to_string(index=False), flush=True)
    print(concentrations.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
