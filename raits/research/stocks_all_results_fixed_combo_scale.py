from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_ALL_RESULTS_FIXED_COMBO_SCALE_PREREG_2026-09-24.json")
SELECTION = Path("STOCKS_ALL_RESULTS_SLEEVE_GRID_2026-09-24_SELECTION.json")
PAIR_DAILY = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_DAILY.csv")
PAIR_CONTRIB = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_TICKER_CONTRIB.csv")
CALENDAR_DAILY = Path("STOCKS_PIT_FULL_TURN_OF_MONTH_COSTAWARE_2026-09-14_DAILY.csv")
SPREAD_DAILY = Path("STOCKS_PIT_FULL_MEGACAP_RELATIVE_SPREAD_2026-09-14_DAILY.csv")
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")

PREFIX = "STOCKS_ALL_RESULTS_FIXED_COMBO_SCALE_2026-09-24"
PAIR_VARIANT = "sic_pairs_quarterly_z2_hold10"
CALENDAR_VARIANT = "spy_first5_x25_fin25_cost4"
SPREAD_VARIANT = "long_top62_short_top200_100_100"
START = pd.Timestamp("2018-04-27")
END = pd.Timestamp("2024-12-31")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
START_CAPITAL = 100_000.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def load_source_streams() -> tuple[pd.DataFrame, pd.DataFrame]:
    pair = pd.read_csv(PAIR_DAILY, parse_dates=["date"])
    pair = pair[pair["variant"].eq(PAIR_VARIANT)].sort_values("date").copy()
    pair["prior_equity"] = pair["equity"] - pair["daily_pnl"]
    pair["pair_gross_ret"] = (pair["daily_pnl"] + pair["trade_cost"] + pair["borrow_cost"]) / pair["prior_equity"]
    pair["pair_short_gross"] = pair["gross_exposure"] / 2.0

    calendar = pd.read_csv(CALENDAR_DAILY, parse_dates=["date"])
    calendar = calendar[calendar["variant"].eq(CALENDAR_VARIANT)].sort_values("date").copy()
    calendar["calendar_gross_ret"] = calendar["exposure"] * calendar["base_ret"]

    streams = pair[["date", "pair_gross_ret", "turnover", "gross_exposure", "pair_short_gross"]].rename(
        columns={"turnover": "pair_turnover", "gross_exposure": "pair_gross"}
    )
    streams = streams.merge(
        calendar[["date", "calendar_gross_ret", "turnover", "exposure"]].rename(
            columns={"turnover": "calendar_turnover", "exposure": "calendar_gross"}
        ),
        on="date",
        how="inner",
    )
    return streams, pair


def load_spread() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[daily["date"].between(pd.Timestamp("2018-03-29"), END)].copy()
    daily = daily.dropna(subset=["ticker", "prev_close_1555", "close_1555"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0)].copy()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily["ret"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0

    caps = pd.read_csv(MARKET_CAPS, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker_query"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    memberships = {}
    for n in (62, 200):
        memberships[n] = (
            caps[caps["rank"].le(n)].groupby("date")["ticker_query"].apply(lambda x: set(x)).sort_index()
        )

    dates = pd.DataFrame({"date": sorted(daily["date"].unique())})
    assigned = dates.copy()
    for n in (62, 200):
        table = memberships[n].rename(f"set{n}").reset_index()
        assigned = pd.merge_asof(assigned.sort_values("date"), table, on="date", direction="backward")
    sets = assigned.set_index("date")[["set62", "set200"]].to_dict("index")

    rows: list[dict[str, object]] = []
    contrib_rows: list[dict[str, object]] = []
    previous_end = pd.Series(dtype=float)
    for date, group in daily.groupby("date", sort=True):
        membership = sets.get(date)
        if not membership:
            continue
        returns = group.drop_duplicates("ticker", keep="last").set_index("ticker")["ret"]
        long_names = sorted(set(returns.index).intersection(membership["set62"]))
        short_names = sorted(set(returns.index).intersection(membership["set200"]))
        if not long_names or not short_names:
            continue
        target = pd.Series(dtype=float)
        target = target.add(pd.Series(1.0 / len(long_names), index=long_names), fill_value=0.0)
        target = target.add(pd.Series(-1.0 / len(short_names), index=short_names), fill_value=0.0)
        union = target.index.union(previous_end.index)
        turnover = float((target.reindex(union, fill_value=0.0) - previous_end.reindex(union, fill_value=0.0)).abs().sum())
        ticker_ret = target * returns.reindex(target.index)
        spread_ret = float(ticker_ret.sum())
        gross = float(target.abs().sum())
        short_gross = float(target[target < 0].abs().sum())
        rows.append({"date": date, "spread_gross_ret": spread_ret, "spread_turnover": turnover, "spread_gross": gross, "spread_short_gross": short_gross, "long_names": len(long_names), "short_names": len(short_names)})
        contrib_rows.extend({"date": date, "ticker": ticker, "spread_gross_contrib_ret": float(value)} for ticker, value in ticker_ret.items())
        denominator = 1.0 + spread_ret
        previous_end = target * (1.0 + returns.reindex(target.index)) / denominator if denominator != 0 else target.copy()
    spread = pd.DataFrame(rows)
    contrib = pd.DataFrame(contrib_rows)
    return spread, contrib


def pair_gross_contributions(pair_daily: pd.DataFrame) -> pd.DataFrame:
    contrib = pd.read_csv(PAIR_CONTRIB, parse_dates=["date"])
    contrib = contrib[contrib["variant"].eq(PAIR_VARIANT)].groupby(["date", "ticker"], as_index=False)["pnl"].sum()
    costs = pair_daily.set_index("date")[["prior_equity", "trade_cost", "borrow_cost"]]
    contrib = contrib.merge(costs, on="date", how="left")
    contrib["net_contrib_ret"] = contrib["pnl"] / contrib["prior_equity"]
    abs_sum = contrib.groupby("date")["net_contrib_ret"].transform(lambda x: x.abs().sum())
    reversal = (contrib["trade_cost"] + contrib["borrow_cost"]) / contrib["prior_equity"]
    share = np.where(abs_sum > 0, contrib["net_contrib_ret"].abs() / abs_sum, 0.0)
    contrib["pair_gross_contrib_ret"] = contrib["net_contrib_ret"] + share * reversal
    return contrib[["date", "ticker", "pair_gross_contrib_ret"]]


def metric_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    periods = (("development", START, DEV_END), ("validation_touched", VAL_START, END))
    for scale, scale_frame in daily.groupby("scale", sort=True):
        for stage, begin, finish in periods:
            x = scale_frame[scale_frame["date"].between(begin, finish)].copy()
            start_equity = float(x.iloc[0]["prior_equity"])
            curve = pd.concat([pd.Series([start_equity]), x["equity"].reset_index(drop=True)], ignore_index=True)
            peak = curve.cummax()
            years = max((x["date"].max() - x["date"].min()).days / 365.25, 1e-9)
            yearly = (1.0 + x["net_ret"]).groupby(x["date"].dt.year).prod() - 1.0
            rows.append({
                "scale": scale, "stage": stage, "days": len(x), "pnl": float(x["daily_pnl"].sum()),
                "endingEquity": float(x.iloc[-1]["equity"]), "cagr": float((x.iloc[-1]["equity"] / start_equity) ** (1.0 / years) - 1.0),
                "sharpe": float(x["net_ret"].mean() / x["net_ret"].std() * math.sqrt(252)),
                "ddDollar": float((curve - peak).min()), "ddPct": float((curve / peak - 1.0).min()),
                "positiveYears": int(yearly.gt(0).sum()), "avgGross": float(x["gross_exposure"].mean()),
                "maxGross": float(x["gross_exposure"].max()), "avgShortGross": float(x["short_gross"].mean()),
                "tradeCost": float(x["trade_cost"].sum()), "borrowCost": float(x["borrow_cost"].sum()),
                "financingCost": float(x["financing_cost"].sum()),
            })
    return rows


def concentration_rows(ticker: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (scale, stage), group in ticker.groupby(["scale", "stage"], sort=True):
        by_ticker = group.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        total = float(by_ticker.sum())
        positive = by_ticker[by_ticker > 0]
        source = positive if positive.sum() > 0 else by_ticker.abs()
        weights = source / source.sum() if source.sum() else source
        row = {"scale": scale, "stage": stage, "tickers": len(by_ticker), "netTickerPnl": total, "effectiveTickerCount": float(1.0 / weights.pow(2).sum()) if len(weights) else 0.0, "topTicker": by_ticker.index[0] if len(by_ticker) else ""}
        denom = total if total > 0 else float(by_ticker.abs().sum())
        for n in (1, 3, 5, 10):
            value = float(by_ticker.head(n).sum())
            row[f"top{n}Pnl"] = value
            row[f"top{n}Share"] = value / denom if denom else np.nan
        rows.append(row)
    return rows


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="utf-8"))
    if not prereg.get("frozen_before_performance") or prereg["implementation_freeze"]["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash is not frozen")
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))["selectedWeights"]
    required = {PAIR_VARIANT: "0.50", CALENDAR_VARIANT: "0.25", SPREAD_VARIANT: "0.25"}
    if not all(name in selection and f"{name}={weight}" in selection for name, weight in required.items()):
        raise RuntimeError("Section 6.212 selected weights do not match the frozen combo")

    streams, pair_daily = load_source_streams()
    spread, spread_contrib = load_spread()
    streams = streams.merge(spread, on="date", how="inner")
    streams = streams[streams["date"].between(START, END)].copy()
    source_spread = pd.read_csv(SPREAD_DAILY, parse_dates=["date"])
    source_spread = source_spread[source_spread["variant"].eq(SPREAD_VARIANT)][["date", "base_spread_ret"]]
    qa = streams[["date", "spread_gross_ret", "long_names", "short_names"]].merge(source_spread, on="date", how="left")
    qa["return_error"] = qa["spread_gross_ret"] - qa["base_spread_ret"]

    pair_contrib = pair_gross_contributions(pair_daily)
    gross_ticker = pd.concat([
        pair_contrib.assign(sleeve="pairs", weighted_ret=lambda x: 0.50 * x["pair_gross_contrib_ret"])[["date", "ticker", "sleeve", "weighted_ret"]],
        spread_contrib.assign(sleeve="spread", weighted_ret=lambda x: 0.25 * x["spread_gross_contrib_ret"])[["date", "ticker", "sleeve", "weighted_ret"]],
        streams.assign(ticker="SPY", sleeve="calendar", weighted_ret=0.25 * streams["calendar_gross_ret"])[["date", "ticker", "sleeve", "weighted_ret"]],
    ], ignore_index=True)
    gross_ticker = gross_ticker[gross_ticker["date"].between(START, END)]

    daily_frames = []
    source_frames = []
    ticker_frames = []
    for scale in prereg["scale_candidates"]:
        x = streams.copy()
        x["scale"] = float(scale)
        x["gross_ret"] = float(scale) * (0.50 * x["pair_gross_ret"] + 0.25 * x["calendar_gross_ret"] + 0.25 * x["spread_gross_ret"])
        x["turnover"] = float(scale) * (0.50 * x["pair_turnover"] + 0.25 * x["calendar_turnover"] + 0.25 * x["spread_turnover"])
        x["gross_exposure"] = float(scale) * (0.50 * x["pair_gross"] + 0.25 * x["calendar_gross"] + 0.25 * x["spread_gross"])
        x["short_gross"] = float(scale) * (0.50 * x["pair_short_gross"] + 0.25 * x["spread_short_gross"])
        x["trade_cost_ret"] = x["turnover"] * 4.0 / 10_000.0
        x["borrow_cost_ret"] = x["short_gross"] * 0.01 / 252.0
        x["financing_cost_ret"] = (x["gross_exposure"] - 1.0).clip(lower=0.0) * 0.025 / 252.0
        x["net_ret"] = x["gross_ret"] - x["trade_cost_ret"] - x["borrow_cost_ret"] - x["financing_cost_ret"]
        equity = START_CAPITAL
        rows = []
        for row in x.itertuples(index=False):
            prior = equity
            trade_cost = prior * row.trade_cost_ret
            borrow_cost = prior * row.borrow_cost_ret
            financing_cost = prior * row.financing_cost_ret
            pnl = prior * row.net_ret
            equity += pnl
            rows.append({"scale": scale, "date": row.date, "prior_equity": prior, "gross_ret": row.gross_ret, "net_ret": row.net_ret, "daily_pnl": pnl, "equity": equity, "gross_exposure": row.gross_exposure, "short_gross": row.short_gross, "turnover": row.turnover, "trade_cost": trade_cost, "borrow_cost": borrow_cost, "financing_cost": financing_cost})
            source_frames.extend([
                {"scale": scale, "date": row.date, "component": "pairs_gross", "pnl": prior * scale * 0.50 * row.pair_gross_ret},
                {"scale": scale, "date": row.date, "component": "calendar_gross", "pnl": prior * scale * 0.25 * row.calendar_gross_ret},
                {"scale": scale, "date": row.date, "component": "spread_gross", "pnl": prior * scale * 0.25 * row.spread_gross_ret},
                {"scale": scale, "date": row.date, "component": "trade_cost", "pnl": -trade_cost},
                {"scale": scale, "date": row.date, "component": "borrow_cost", "pnl": -borrow_cost},
                {"scale": scale, "date": row.date, "component": "financing_cost", "pnl": -financing_cost},
            ])
        path = pd.DataFrame(rows)
        daily_frames.append(path)

        tc = gross_ticker.merge(path[["date", "prior_equity", "trade_cost", "borrow_cost", "financing_cost"]], on="date", how="inner")
        tc["gross_pnl"] = tc["prior_equity"] * float(scale) * tc["weighted_ret"]
        abs_sum = tc.groupby("date")["gross_pnl"].transform(lambda z: z.abs().sum())
        total_cost = tc["trade_cost"] + tc["borrow_cost"] + tc["financing_cost"]
        tc["allocated_cost"] = np.where(abs_sum > 0, tc["gross_pnl"].abs() / abs_sum * total_cost, 0.0)
        tc["pnl"] = tc["gross_pnl"] - tc["allocated_cost"]
        tc["scale"] = scale
        tc["stage"] = np.where(tc["date"].le(DEV_END), "development", "validation_touched")
        ticker_frames.append(tc[["scale", "stage", "date", "ticker", "sleeve", "gross_pnl", "allocated_cost", "pnl"]])

    daily = pd.concat(daily_frames, ignore_index=True)
    source = pd.DataFrame(source_frames)
    source["stage"] = np.where(source["date"].le(DEV_END), "development", "validation_touched")
    ticker = pd.concat(ticker_frames, ignore_index=True)
    summary = pd.DataFrame(metric_rows(daily))
    yearly = daily.assign(year=daily["date"].dt.year).groupby(["scale", "year"], as_index=False).agg(pnl=("daily_pnl", "sum"), tradeCost=("trade_cost", "sum"), borrowCost=("borrow_cost", "sum"), financingCost=("financing_cost", "sum"))
    concentration = pd.DataFrame(concentration_rows(ticker))
    cost_summary = source.groupby(["scale", "stage", "component"], as_index=False)["pnl"].sum()

    daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    summary.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    source.to_csv(f"{PREFIX}_SOURCE_ATTRIBUTION_DAILY.csv", index=False)
    cost_summary.to_csv(f"{PREFIX}_SOURCE_ATTRIBUTION.csv", index=False)
    ticker.to_csv(f"{PREFIX}_TICKER_ATTRIBUTION.csv", index=False)
    concentration.to_csv(f"{PREFIX}_CONCENTRATION.csv", index=False)
    qa.to_csv(f"{PREFIX}_SPREAD_QA.csv", index=False)

    inputs = [SELECTION, PAIR_DAILY, PAIR_CONTRIB, CALENDAR_DAILY, SPREAD_DAILY, DAILY_FEATURES, MARKET_CAPS, PREREG]
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "inputs": {str(path).replace("\\", "/"): sha256(path) for path in inputs},
        "fixedWeights": prereg["selected_sleeves"], "scales": prereg["scale_candidates"],
        "sample": [str(START.date()), str(END.date())], "oos2025_2026Consumed": False,
        "ruleSelectionEffect": "None in this audit; the section 6.212 development-selected weights are frozen.",
        "tradeSelectionEffect": "None; inherited sleeve trades and memberships are unchanged. Only shared-book scale and cost accounting differ.",
        "productionPassAllowed": False, "tickerAttributionCostAllocationExact": False,
        "spreadReturnMaxAbsError": float(qa["return_error"].abs().max()),
        "outputs": [f"{PREFIX}_{suffix}" for suffix in ("DAILY.csv", "SUMMARY.csv", "YEARLY.csv", "SOURCE_ATTRIBUTION_DAILY.csv", "SOURCE_ATTRIBUTION.csv", "TICKER_ATTRIBUTION.csv", "CONCENTRATION.csv", "SPREAD_QA.csv", "MANIFEST.json")],
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.to_string(index=False), flush=True)
    print(concentration.to_string(index=False), flush=True)
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
