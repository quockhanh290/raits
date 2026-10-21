from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_0935_EVENT_SHOCK_COHORTS_2026-09-17"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
POOL_TOP_N = 500
HOLD_DAYS = 5
COHORT_GROSS = 0.20
TRADE_COST_BPS = 4.0
SHORT_BORROW_ANNUAL_RATE = 0.01

# Fixed before measuring. Thresholds describe large, liquid open shocks rather
# than earnings labels, which are not available PIT-safe in the local inputs.
VARIANTS = [
    {"variant": "confirmed_gap_ls_hold5", "event": "confirmed", "mode": "long_short"},
    {"variant": "rejected_gap_ls_hold5", "event": "rejected", "mode": "long_short"},
    {"variant": "confirmed_gap_long_hold5", "event": "confirmed", "mode": "long"},
    {"variant": "rejected_gap_long_hold5", "event": "rejected", "mode": "long"},
]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
SIGNALS_OUT = Path(f"{OUT_PREFIX}_SIGNALS.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1.0).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    return float(pnl.mean() / std * math.sqrt(252)) if std > 0 else float("nan")


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_raw() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    intra = pd.read_pickle(INTRADAY_0935)
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    x = daily[["date", "ticker", "gap", "ret20_pre", "vol20_pre"]].merge(
        intra[["date", "ticker", "entry935", "first5_ret", "rvol930"]],
        on=["date", "ticker"],
        how="inner",
    )
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=["date", "ticker", "gap", "ret20_pre", "vol20_pre", "entry935", "first5_ret", "rvol930"])
    x = x[(x["entry935"] > 0) & (x["vol20_pre"] > 0) & (x["rvol930"] >= 0)].copy()
    x["open_to_0935"] = (1.0 + x["gap"]) * (1.0 + x["first5_ret"]) - 1.0
    return x.sort_values(["date", "ticker"]).reset_index(drop=True)


def load_membership() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps[caps["rank_market_cap"].le(POOL_TOP_N)][["date", "ticker"]].rename(columns={"date": "snapshot_date"})


def apply_pool(raw: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(raw["date"].drop_duplicates())})
    snapshots = membership[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    assigned = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    x = raw.merge(assigned, on="date", how="inner")
    x = x.merge(membership, on=["snapshot_date", "ticker"], how="inner")
    return x.drop(columns="snapshot_date").copy()


def event_candidates(pool: pd.DataFrame, event: str) -> pd.DataFrame:
    base = pool[(pool["gap"].abs() >= 0.02) & (pool["rvol930"] >= 1.5)].copy()
    if event == "confirmed":
        out = base[(base["first5_ret"].abs() >= 0.0025) & (base["gap"] * base["first5_ret"] > 0)].copy()
        out["side"] = np.sign(out["open_to_0935"]).astype(int)
        out["event_score"] = out["open_to_0935"].abs() * np.sqrt(out["rvol930"].clip(upper=25))
    elif event == "rejected":
        out = base[(base["first5_ret"].abs() >= 0.005) & (base["gap"] * base["first5_ret"] < 0)].copy()
        out["side"] = np.sign(out["first5_ret"]).astype(int)
        out["event_score"] = out["first5_ret"].abs() * np.sqrt(out["rvol930"].clip(upper=25))
    else:
        raise ValueError(event)
    return out[out["side"].ne(0)].copy()


def cohort_for_date(candidates: pd.DataFrame, spec: dict[str, object]) -> tuple[pd.Series, pd.DataFrame]:
    if candidates.empty:
        return pd.Series(dtype=float), candidates
    selected_frames = []
    weights: dict[str, float] = {}
    if spec["mode"] == "long_short":
        for side in (1, -1):
            chosen = candidates[candidates["side"].eq(side)].nlargest(5, "event_score").copy()
            if not chosen.empty:
                side_gross = COHORT_GROSS / 2.0
                for ticker in chosen["ticker"]:
                    weights[ticker] = weights.get(ticker, 0.0) + side * side_gross / len(chosen)
                selected_frames.append(chosen)
    else:
        chosen = candidates[candidates["side"].eq(1)].nlargest(10, "event_score").copy()
        if not chosen.empty:
            for ticker in chosen["ticker"]:
                weights[ticker] = COHORT_GROSS / len(chosen)
            selected_frames.append(chosen)
    selected = pd.concat(selected_frames, ignore_index=True) if selected_frames else candidates.iloc[0:0].copy()
    return pd.Series(weights, dtype=float), selected


def aggregate_cohorts(cohorts: list[tuple[int, pd.Series]]) -> pd.Series:
    if not cohorts:
        return pd.Series(dtype=float)
    out = pd.concat([weights.rename(i) for i, (_, weights) in enumerate(cohorts)], axis=1).fillna(0.0).sum(axis=1)
    return out[out.ne(0)].copy()


def simulate(
    spec: dict[str, object], raw: pd.DataFrame, pool: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = sorted(raw["date"].drop_duplicates())
    prices_by_date = {date: group.set_index("ticker")["entry935"] for date, group in raw.groupby("date", sort=True)}
    event = event_candidates(pool, str(spec["event"]))
    event_by_date = {date: group for date, group in event.groupby("date", sort=True)}
    equity = START_CAPITAL
    previous_prices = pd.Series(dtype=float)
    weights = pd.Series(dtype=float)
    cohorts: list[tuple[int, pd.Series]] = []
    rows = []
    contrib_rows = []
    signal_rows = []

    for day_index, date in enumerate(dates):
        prices = prices_by_date[date]
        common = weights.index.intersection(prices.index).intersection(previous_prices.index)
        returns = prices.reindex(common) / previous_prices.reindex(common) - 1.0
        pnl_by_ticker = equity * weights.reindex(common) * returns if len(common) else pd.Series(dtype=float)
        short_gross_before = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_cost = equity * short_gross_before * SHORT_BORROW_ANNUAL_RATE / 252.0
        if borrow_cost > 0 and short_gross_before > 0:
            allocation = weights[weights < 0].abs() / short_gross_before * borrow_cost
            for ticker, cost in allocation.items():
                pnl_by_ticker.loc[ticker] = pnl_by_ticker.get(ticker, 0.0) - cost
        daily_pnl = float(pnl_by_ticker.sum()) if not pnl_by_ticker.empty else 0.0
        equity += daily_pnl

        cohorts = [(start, cohort) for start, cohort in cohorts if day_index - start < HOLD_DAYS]
        candidates = event_by_date.get(date, pool.iloc[0:0])
        new_cohort, selected = cohort_for_date(candidates, spec)
        if not new_cohort.empty:
            cohorts.append((day_index, new_cohort))
            selected = selected.copy()
            selected["variant"] = spec["variant"]
            selected["cohort_date"] = date
            selected["cohort_weight"] = selected["ticker"].map(new_cohort)
            signal_rows.append(selected)

        new_weights = aggregate_cohorts(cohorts)
        tickers = weights.index.union(new_weights.index)
        old_aligned = weights.reindex(tickers).fillna(0.0)
        new_aligned = new_weights.reindex(tickers).fillna(0.0)
        turnover = float((new_aligned - old_aligned).abs().sum())
        trade_cost = equity * turnover * TRADE_COST_BPS / 10_000.0
        equity -= trade_cost
        if turnover > 0:
            allocation = (new_aligned - old_aligned).abs() / turnover * trade_cost
            contrib_rows.extend(
                {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": -float(cost)}
                for ticker, cost in allocation.items()
            )
        contrib_rows.extend(
            {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": float(pnl)}
            for ticker, pnl in pnl_by_ticker.items()
            if float(pnl) != 0.0
        )
        weights = new_weights
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl - trade_cost,
                "equity": equity,
                "trade_cost": trade_cost,
                "borrow_cost": borrow_cost,
                "turnover": turnover,
                "gross_exposure": float(weights.abs().sum()) if not weights.empty else 0.0,
                "net_exposure": float(weights.sum()) if not weights.empty else 0.0,
                "positions": int(weights.ne(0).sum()),
                "active_cohorts": len(cohorts),
                "new_signals": int(len(selected)),
                "missing_positions": int(len(weights.index.difference(prices.index))),
            }
        )
        previous_prices = prices

    daily = pd.DataFrame(rows)
    daily["year"] = daily["date"].dt.year
    contrib = pd.DataFrame(contrib_rows)
    signals = pd.concat(signal_rows, ignore_index=True) if signal_rows else pd.DataFrame()
    return daily, contrib, signals


def effective_ticker_count(by_ticker: pd.Series) -> float:
    positive = by_ticker[by_ticker > 0]
    source = positive if positive.sum() > 0 else by_ticker.abs()
    total = float(source.sum())
    if total <= 0:
        return 0.0
    weights = source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(by_ticker.sum())
    denominator = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum())
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denominator if denominator else float("nan")
    return row


def summary_row(spec: dict[str, object], daily: pd.DataFrame, contrib: pd.DataFrame, signals: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "event": spec["event"],
        "mode": spec["mode"],
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "borrowCost": float(daily["borrow_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "signals": int(len(signals)),
        "selectedTickers": int(signals["ticker"].nunique()) if not signals.empty else 0,
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (variant, year), group in daily.groupby(["variant", "year"], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append(
            {
                "variant": variant,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "tradeCost": float(group["trade_cost"].sum()),
                "borrowCost": float(group["borrow_cost"].sum()),
            }
        )
    return rows


def main() -> None:
    raw = load_raw()
    pool = apply_pool(raw, load_membership())
    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    contrib_frames = []
    signal_frames = []
    qa_rows = []
    for spec in VARIANTS:
        daily, contrib, signals = simulate(spec, raw, pool)
        summaries.append(summary_row(spec, daily, contrib, signals))
        yearly.extend(yearly_rows(daily))
        concentration.append(concentration_row(str(spec["variant"]), contrib))
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        signal_frames.append(signals)
        qa_rows.append(
            {
                "variant": spec["variant"],
                "days": int(len(daily)),
                "activeDays": int(daily["new_signals"].gt(0).sum()),
                "avgNewSignals": float(daily["new_signals"].mean()),
                "maxMissingPositions": int(daily["missing_positions"].max()),
            }
        )
        print("EVENT_SHOCK", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.concat(signal_frames, ignore_index=True).to_csv(SIGNALS_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(QA_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_0935_event_shock_cohorts.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(INTRADAY_0935).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Fixed PIT top500 09:35 confirmed/rejected gap events; daily 20% gross cohorts held five trading sessions, with aggregate gross capped structurally near 1x.",
        "event_rules": {
            "base": "abs(gap)>=2% and rvol930>=1.5",
            "confirmed": "abs(first5)>=0.25%, same sign as gap; trade open-to-09:35 direction",
            "rejected": "abs(first5)>=0.50%, opposite sign to gap; trade first-five-minute direction",
        },
        "costs": f"{TRADE_COST_BPS} bps aggregate target-weight turnover and {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross.",
        "sample_label": "Research/touched 2018-2024 only. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "Signals use only values known by 09:35 and lagged daily features; PIT market-cap membership uses backward snapshots; holdings are marked from the broad PIT price panel; no old manual 62 list.",
        "rule_selection_effect": "None. Event thresholds, ranking, five-day hold, cohort size and four variants were fixed before measuring.",
        "trade_selection_effect": "Daily candidates and overlapping cohorts are rebuilt from PIT inputs; no ticker-PnL subtraction or post-period ticker selection.",
        "variants": VARIANTS,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(SIGNALS_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, SIGNALS_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
