from __future__ import annotations

from pathlib import Path

import json
import math
import pickle

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_BENCHMARK_HURDLES_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
SPY_QQQ_BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
TOP_NS = [62, 100, 200, 500]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


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


def load_daily_returns() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    daily = daily.dropna(subset=["ticker", "prev_close_1555", "close_1555"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0)].copy()
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    return daily[["date", "ticker", "ret_close_to_close"]].copy()


def load_market_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker_query"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps


def top_membership(caps: pd.DataFrame, top_n: int) -> pd.DataFrame:
    x = caps[caps["rank_market_cap"].le(top_n)].copy()
    return (
        x.groupby("date", sort=True)["ticker_query"]
        .apply(lambda s: set(s.astype(str)))
        .rename("ticker_set")
        .reset_index()
    )


def apply_membership(daily: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership.sort_values("date"), on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    sets = daily["date"].map(date_to_set)
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(daily["ticker"].astype(str), sets)]
    return daily.loc[mask].copy()


def simulate_equal_weight(variant: str, daily: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    equity = START_CAPITAL
    daily_rows = []
    contrib_rows = []
    for date, group in daily.groupby("date", sort=True):
        if group.empty:
            continue
        weight = 1.0 / len(group)
        group = group.copy()
        group["pnl"] = equity * weight * group["ret_close_to_close"]
        daily_pnl = float(group["pnl"].sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": variant,
                "date": date,
                "daily_pnl": daily_pnl,
                "daily_ret": daily_pnl / (equity - daily_pnl),
                "equity": equity,
                "gross": 1.0,
                "names": int(len(group)),
            }
        )
        contrib_rows.append(group[["date", "ticker", "pnl"]].assign(variant=variant))
    daily_out = pd.DataFrame(daily_rows)
    contrib = pd.concat(contrib_rows, ignore_index=True) if contrib_rows else pd.DataFrame()
    dd, dd_pct = max_drawdown(daily_out["equity"])
    summary = {
        "variant": variant,
        "kind": "daily_rebalanced_equal_weight",
        "pnl": float(daily_out["daily_pnl"].sum()),
        "cagr": cagr(daily_out["equity"], daily_out["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily_out["daily_pnl"]),
        "days": int(len(daily_out)),
        "avgNames": float(daily_out["names"].mean()),
        "medianNames": float(daily_out["names"].median()),
        "selectedTickers": int(daily["ticker"].nunique()),
    }
    return summary, daily_out, contrib


def load_etf_daily(symbol: str) -> pd.DataFrame:
    with SPY_QQQ_BARS.open("rb") as f:
        bars = pickle.load(f)
    if symbol not in bars:
        return pd.DataFrame(columns=["date", "ret_close_to_close", "ticker"])
    x = bars[symbol].copy().reset_index()
    time_col = "ts" if "ts" in x.columns else ("timestamp" if "timestamp" in x.columns else x.columns[0])
    x["ts"] = pd.to_datetime(x[time_col])
    x["date"] = x["ts"].dt.normalize()
    close = (
        x[x["ts"].dt.time.astype(str).le("15:55:00")]
        .sort_values("ts")
        .groupby("date", as_index=False)
        .tail(1)[["date", "close"]]
        .sort_values("date")
    )
    close["prev_close"] = close["close"].shift(1)
    close = close[(close["date"] >= START) & (close["date"] <= END)].copy()
    close = close.dropna(subset=["prev_close"])
    close["ret_close_to_close"] = close["close"] / close["prev_close"] - 1.0
    return close[["date", "ret_close_to_close"]].assign(ticker=symbol)


def simulate_buy_hold(variant: str, returns: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    x = returns.sort_values("date").copy()
    x["equity"] = START_CAPITAL * (1.0 + x["ret_close_to_close"]).cumprod()
    x["daily_pnl"] = x["equity"].diff().fillna(x["equity"] - START_CAPITAL)
    x["gross"] = 1.0
    x["names"] = 1
    x["variant"] = variant
    dd, dd_pct = max_drawdown(x["equity"])
    summary = {
        "variant": variant,
        "kind": "buy_hold_etf",
        "pnl": float(x["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(x["equity"], x["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(x["daily_pnl"]),
        "days": int(len(x)),
        "avgNames": 1.0,
        "medianNames": 1.0,
        "selectedTickers": 1,
    }
    contrib = x[["date", "ticker", "daily_pnl"]].rename(columns={"daily_pnl": "pnl"}).assign(variant=variant)
    return summary, x[["variant", "date", "daily_pnl", "equity", "gross", "names"]], contrib


def yearly_rows(variant: str, daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for year, group in daily.assign(year=daily["date"].dt.year).groupby("year", sort=True):
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
                "days": int(len(group)),
            }
        )
    return rows


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(contrib["pnl"].sum())
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def main() -> None:
    daily = load_daily_returns()
    caps = load_market_caps()
    summaries = []
    daily_frames = []
    contrib_frames = []
    yearly = []
    concentration = []
    qa = []

    benchmark_inputs = [("broad_pit_equal_weight", daily)]
    for top_n in TOP_NS:
        membership = top_membership(caps, top_n)
        selected = apply_membership(daily, membership)
        benchmark_inputs.append((f"market_cap_top{top_n}_equal_weight", selected))
        qa.append(
            {
                "variant": f"market_cap_top{top_n}_equal_weight",
                "rows": int(len(selected)),
                "tickers": int(selected["ticker"].nunique()),
                "medianNamesPerDay": float(selected.groupby("date")["ticker"].nunique().median()),
                "snapshotCount": int(membership["date"].nunique()),
            }
        )

    qa.append(
        {
            "variant": "broad_pit_equal_weight",
            "rows": int(len(daily)),
            "tickers": int(daily["ticker"].nunique()),
            "medianNamesPerDay": float(daily.groupby("date")["ticker"].nunique().median()),
            "snapshotCount": 0,
        }
    )

    for variant, data in benchmark_inputs:
        summary, daily_out, contrib = simulate_equal_weight(variant, data)
        summaries.append(summary)
        daily_frames.append(daily_out)
        contrib_frames.append(contrib)
        yearly.extend(yearly_rows(variant, daily_out))
        concentration.append(concentration_row(variant, contrib))
        print("BENCH", variant, summary, flush=True)

    for symbol in ("SPY", "QQQ"):
        variant = f"{symbol.lower()}_buy_hold"
        etf_returns = load_etf_daily(symbol)
        if etf_returns.empty:
            qa.append(
                {
                    "variant": variant,
                    "rows": 0,
                    "tickers": 0,
                    "medianNamesPerDay": 0.0,
                    "snapshotCount": 0,
                    "status": "unavailable_local_bars",
                }
            )
            print("BENCH_SKIP", variant, "unavailable_local_bars", flush=True)
            continue
        summary, daily_out, contrib = simulate_buy_hold(variant, etf_returns)
        summaries.append(summary)
        daily_frames.append(daily_out)
        contrib_frames.append(contrib)
        yearly.extend(yearly_rows(variant, daily_out))
        concentration.append(concentration_row(variant, contrib))
        qa.append({"variant": variant, "rows": int(len(daily_out)), "tickers": 1, "medianNamesPerDay": 1.0, "snapshotCount": 0, "status": "ok"})
        print("BENCH", variant, summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa).to_csv(QA_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_benchmark_hurdles.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/"), str(SPY_QQQ_BARS).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "benchmarks": ["broad PIT equal weight", "quarterly market-cap top-N equal weight", "SPY buy hold", "QQQ buy hold"],
        "old_62_usage": "SPY/QQQ ETF bars come from the Polygon62+ETF pickle only for benchmark prices; no old-62 equity universe is used for selection.",
        "rule_selection": "None. Benchmarks are fixed before measurement.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
