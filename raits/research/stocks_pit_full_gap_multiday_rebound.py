from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_GAP_MULTIDAY_REBOUND_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
TRADE_COST_BPS = 4.0
TOP_N_UNIVERSE = 500

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"variant": "top500_gapdown20_hold3_gross100", "side": "long_gapdown", "select_n": 20, "hold": 3, "gross": 1.0},
    {"variant": "top500_gapdown20_hold5_gross100", "side": "long_gapdown", "select_n": 20, "hold": 5, "gross": 1.0},
    {"variant": "top500_gapdown20_hold10_gross100", "side": "long_gapdown", "select_n": 20, "hold": 10, "gross": 1.0},
    {"variant": "top500_gapdown50_hold5_gross100", "side": "long_gapdown", "select_n": 50, "hold": 5, "gross": 1.0},
    {"variant": "top500_gapup20_hold3_gross100", "side": "long_gapup", "select_n": 20, "hold": 3, "gross": 1.0},
    {"variant": "top500_gapup20_hold5_gross100", "side": "long_gapup", "select_n": 20, "hold": 5, "gross": 1.0},
]


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = equity / peak - 1.0
    return float(dd.min()), float(dd_pct.min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    if std <= 0:
        return float("nan")
    return float(pnl.mean() / std * math.sqrt(252))


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_daily() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    daily = daily.dropna(subset=["ticker", "gap", "prev_close_1555", "close_1555"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0)].copy()
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    return daily[["date", "ticker", "gap", "ret_close_to_close"]].copy()


def load_market_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker_query"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    selected = caps[caps["rank_market_cap"].le(TOP_N_UNIVERSE)].copy()
    return (
        selected.groupby("date", sort=True)["ticker_query"]
        .apply(lambda s: set(s.astype(str)))
        .rename("ticker_set")
        .reset_index()
    )


def apply_membership(daily: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership.sort_values("date"), on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    sets = daily["date"].map(date_to_set)
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(daily["ticker"], sets)]
    return daily.loc[mask].copy()


def build_signals(daily: pd.DataFrame, spec: dict[str, object]) -> dict[pd.Timestamp, list[str]]:
    selected: dict[pd.Timestamp, list[str]] = {}
    ascending = spec["side"] == "long_gapdown"
    for date, group in daily.groupby("date", sort=True):
        ranked = group.sort_values(["gap", "ticker"], ascending=[ascending, True])
        selected[date] = ranked.head(int(spec["select_n"]))["ticker"].tolist()
    return selected


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(contrib["pnl"].sum())
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
        "totalPnl": total,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def simulate(spec: dict[str, object], daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    signals = build_signals(daily, spec)
    returns_by_date = {date: group.set_index("ticker")["ret_close_to_close"] for date, group in daily.groupby("date", sort=True)}
    equity = START_CAPITAL
    active_lots: list[dict[str, object]] = []
    rows = []
    contrib_rows = []
    cost_rate = TRADE_COST_BPS / 10_000.0
    bucket_gross = float(spec["gross"]) / int(spec["hold"])

    for date in sorted(returns_by_date):
        day_rets = returns_by_date[date]
        pnl_by_ticker: dict[str, float] = {}
        gross_exposure = 0.0
        next_lots = []
        for lot in active_lots:
            tickers = lot["tickers"]
            if not tickers:
                continue
            weight = float(lot["bucket_gross"]) / len(tickers)
            gross_exposure += float(lot["bucket_gross"])
            for ticker in tickers:
                ret = float(day_rets.get(ticker, 0.0))
                pnl_by_ticker[ticker] = pnl_by_ticker.get(ticker, 0.0) + equity * weight * ret
            remaining = int(lot["remaining"]) - 1
            if remaining > 0:
                next_lots.append({"tickers": tickers, "remaining": remaining, "bucket_gross": lot["bucket_gross"]})

        entered = signals.get(date, [])
        entry_turnover = bucket_gross if entered else 0.0
        exit_turnover = sum(float(lot["bucket_gross"]) for lot in active_lots if int(lot["remaining"]) <= 1)
        cost = equity * cost_rate * (entry_turnover + exit_turnover)
        if entered:
            next_lots.append({"tickers": entered, "remaining": int(spec["hold"]), "bucket_gross": bucket_gross})
            cost_per_ticker = cost / len(entered) if entered else 0.0
            for ticker in entered:
                pnl_by_ticker[ticker] = pnl_by_ticker.get(ticker, 0.0) - cost_per_ticker

        gross_pnl = float(sum(pnl_by_ticker.values()) + cost)
        daily_pnl = float(sum(pnl_by_ticker.values()))
        equity += daily_pnl
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl,
                "gross_pnl_before_cost": gross_pnl,
                "trade_cost": cost,
                "equity": equity,
                "gross_exposure": gross_exposure,
                "entry_names": len(entered),
                "active_lots": len(active_lots),
                "active_names": sum(len(lot["tickers"]) for lot in active_lots),
            }
        )
        contrib_rows.extend(
            {
                "variant": spec["variant"],
                "date": date,
                "ticker": ticker,
                "pnl": pnl,
            }
            for ticker, pnl in pnl_by_ticker.items()
        )
        active_lots = next_lots

    out = pd.DataFrame(rows)
    out["year"] = out["date"].dt.year
    contrib = pd.DataFrame(contrib_rows)
    return out, contrib


def summary_row(spec: dict[str, object], daily: pd.DataFrame, contrib: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": spec["variant"],
        "side": spec["side"],
        "selectN": int(spec["select_n"]),
        "hold": int(spec["hold"]),
        "gross": float(spec["gross"]),
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": float(daily["trade_cost"].sum()),
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "avgActiveNames": float(daily["active_names"].mean()),
        "selectedTickers": int(contrib["ticker"].nunique()) if not contrib.empty else 0,
        "days": int(len(daily)),
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
                "tradeCost": float(group["trade_cost"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "days": int(len(group)),
            }
        )
    return rows


def main() -> None:
    raw = load_daily()
    daily = apply_membership(raw, load_market_caps())
    frames = []
    contrib_frames = []
    summaries = []
    yearly = []
    concentration = []
    for spec in VARIANTS:
        variant_daily, contrib = simulate(spec, daily)
        frames.append(variant_daily)
        contrib_frames.append(contrib)
        summary = summary_row(spec, variant_daily, contrib)
        summaries.append(summary)
        yearly.extend(yearly_rows(variant_daily))
        concentration.append(concentration_row(str(spec["variant"]), contrib))
        print("GAP_MULTI", summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    qa = pd.DataFrame(
        [
            {
                "rows": int(len(daily)),
                "tickers": int(daily["ticker"].nunique()),
                "days": int(daily["date"].nunique()),
                "medianNamesPerDay": float(daily.groupby("date")["ticker"].nunique().median()),
                "topNUniverse": TOP_N_UNIVERSE,
            }
        ]
    )
    qa.to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_gap_multiday_rebound.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Pre-registered top500 PIT gap-down/gap-up signal observed at the open, entered at close_1555, and held in overlapping 3/5/10-day buckets.",
        "costs": f"{TRADE_COST_BPS} bps per entry/exit bucket notional. No financing because gross is 1x long-only.",
        "sample_label": "Research/touched 2018-2024 only; no 2025-2026 OOS opened.",
        "leakage_controls": "Signal uses same-day open gap, but entry is same-day close_1555; returns begin next close-to-close day. Top500 membership uses PIT market-cap snapshots via backward merge. No old manual 62 list.",
        "rule_selection_effect": "None inside diagnostic. Side, select counts, holds, and gross fixed before running.",
        "variants": VARIANTS,
        "outputs": [
            str(SUMMARY_OUT),
            str(YEARLY_OUT),
            str(CONCENTRATION_OUT),
            str(DAILY_OUT),
            str(CONTRIB_OUT),
            str(QA_OUT),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
