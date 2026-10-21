from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_GAP_EVENT_SAFE_DIAGNOSTIC_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
COST_BPS_PER_SIDE = 4.0
LONG_ONLY_GROSS = 0.40
SHORT_ONLY_GROSS = 0.40
LONG_SHORT_GROSS = 0.80
MAX_NAMES_PER_SIDE = 10

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
EVENT_QA_OUT = Path(f"{OUT_PREFIX}_EVENT_QA.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {
        "variant": "gapdown_3pct_rvol930_2_long",
        "book": "long_only",
        "side": 1,
        "gap_min": None,
        "gap_max": -0.03,
        "rvol930_min": 2.0,
        "tail_pct": None,
        "description": "Long gapdown <= -3% with 09:30 rvol >= 2.",
    },
    {
        "variant": "gapdown_5pct_rvol930_2_long",
        "book": "long_only",
        "side": 1,
        "gap_min": None,
        "gap_max": -0.05,
        "rvol930_min": 2.0,
        "tail_pct": None,
        "description": "Long gapdown <= -5% with 09:30 rvol >= 2.",
    },
    {
        "variant": "gapup_3pct_rvol930_2_short",
        "book": "short_only",
        "side": -1,
        "gap_min": 0.03,
        "gap_max": None,
        "rvol930_min": 2.0,
        "tail_pct": None,
        "description": "Short gapup >= +3% with 09:30 rvol >= 2.",
    },
    {
        "variant": "gapup_5pct_rvol930_2_short",
        "book": "short_only",
        "side": -1,
        "gap_min": 0.05,
        "gap_max": None,
        "rvol930_min": 2.0,
        "tail_pct": None,
        "description": "Short gapup >= +5% with 09:30 rvol >= 2.",
    },
    {
        "variant": "gap_tail2pct_rvol930_2_reversal_ls",
        "book": "long_short",
        "side": 0,
        "gap_min": None,
        "gap_max": None,
        "rvol930_min": 2.0,
        "tail_pct": 0.02,
        "description": "Long bottom 2% gap tail, short top 2% gap tail, both with 09:30 rvol >= 2.",
    },
    {
        "variant": "gap_tail1pct_rvol930_2_reversal_ls",
        "book": "long_short",
        "side": 0,
        "gap_min": None,
        "gap_max": None,
        "rvol930_min": 2.0,
        "tail_pct": 0.01,
        "description": "Long bottom 1% gap tail, short top 1% gap tail, both with 09:30 rvol >= 2.",
    },
]


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = equity / peak - 1.0
    return float(dd.min()), float(dd_pct.min())


def sharpe(daily_pnl: pd.Series) -> float:
    std = float(daily_pnl.std())
    if std <= 0:
        return float("nan")
    return float(daily_pnl.mean() / std * math.sqrt(252))


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    if equity.empty:
        return float("nan")
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, trades: pd.DataFrame) -> dict[str, float | int | str]:
    by_ticker = trades.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(trades["pnl"].sum()) if not trades.empty else 0.0
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, float | int | str] = {
        "variant": variant,
        "tickers": int(by_ticker.shape[0]),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def prepare_panel() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    intraday = pd.read_pickle(INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"]).dt.normalize()
    x = daily[["date", "ticker", "gap", "ret_0935_to_1555", "ret60_pre", "vol20_pre"]].merge(
        intraday[["date", "ticker", "first5_ret", "ret935_eod", "entry935", "exit1555", "rvol930"]],
        on=["date", "ticker"],
        how="inner",
    )
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=["gap", "rvol930", "ret935_eod", "entry935", "exit1555"])
    x = x[x["entry935"] > 0].copy()
    x["gap_rank_pct"] = x.groupby("date")["gap"].rank(method="first", pct=True)
    x["year"] = x["date"].dt.year
    return x


def select_variant(panel: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    x = panel[panel["rvol930"].ge(float(spec["rvol930_min"]))].copy()
    tail_pct = spec["tail_pct"]
    if tail_pct is not None:
        low = x[x["gap_rank_pct"].le(float(tail_pct))].copy()
        high = x[x["gap_rank_pct"].ge(1.0 - float(tail_pct))].copy()
        low["side"] = 1
        high["side"] = -1
        selected = pd.concat([low, high], ignore_index=True)
    else:
        selected = x
        gap_min = spec["gap_min"]
        gap_max = spec["gap_max"]
        if gap_min is not None:
            selected = selected[selected["gap"].ge(float(gap_min))]
        if gap_max is not None:
            selected = selected[selected["gap"].le(float(gap_max))]
        selected = selected.copy()
        selected["side"] = int(spec["side"])

    selected["event_score"] = selected["gap"].abs() * selected["rvol930"].clip(lower=0)
    selected = selected.sort_values(["date", "side", "event_score"], ascending=[True, True, False])
    selected["side_rank"] = selected.groupby(["date", "side"]).cumcount() + 1
    selected = selected[selected["side_rank"].le(MAX_NAMES_PER_SIDE)].copy()
    selected["variant"] = str(spec["variant"])
    selected["gross_ret"] = selected["side"] * selected["ret935_eod"]
    selected["net_ret"] = selected["gross_ret"] - (2.0 * COST_BPS_PER_SIDE / 10_000.0)
    return selected


def simulate(selected: pd.DataFrame, spec: dict[str, object]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    equity = START_CAPITAL
    gross = LONG_SHORT_GROSS if spec["book"] == "long_short" else (LONG_ONLY_GROSS if spec["book"] == "long_only" else SHORT_ONLY_GROSS)
    daily_rows = []
    trade_rows = []

    for date, group in selected.groupby("date", sort=True):
        group = group.copy()
        if spec["book"] == "long_short":
            counts = group.groupby("side")["ticker"].transform("count")
            group["weight"] = (gross / 2.0) / counts
        else:
            group["weight"] = gross / len(group)
        group["notional"] = equity * group["weight"]
        group["gross_pnl"] = group["notional"] * group["gross_ret"]
        group["pnl"] = group["notional"] * group["net_ret"]
        daily_pnl = float(group["pnl"].sum())
        daily_gross_pnl = float(group["gross_pnl"].sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl,
                "daily_gross_pnl": daily_gross_pnl,
                "equity": equity,
                "gross": gross,
                "trades": int(len(group)),
                "longs": int((group["side"] > 0).sum()),
                "shorts": int((group["side"] < 0).sum()),
            }
        )
        trade_rows.append(group)

    daily = pd.DataFrame(daily_rows)
    trades = pd.concat(trade_rows, ignore_index=True) if trade_rows else pd.DataFrame()
    dd, dd_pct = max_drawdown(daily["equity"]) if not daily.empty else (0.0, 0.0)
    summary = {
        "variant": spec["variant"],
        "book": spec["book"],
        "pnl": float(daily["daily_pnl"].sum()) if not daily.empty else 0.0,
        "grossPnlBeforeCosts": float(daily["daily_gross_pnl"].sum()) if not daily.empty else 0.0,
        "costDrag": float(daily["daily_pnl"].sum() - daily["daily_gross_pnl"].sum()) if not daily.empty else 0.0,
        "cagr": cagr(daily["equity"], daily["date"]) if not daily.empty else float("nan"),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]) if not daily.empty else float("nan"),
        "days": int(len(daily)),
        "trades": int(len(trades)),
        "selectedTickers": int(trades["ticker"].nunique()) if not trades.empty else 0,
        "avgTradesPerDay": float(daily["trades"].mean()) if not daily.empty else 0.0,
        "avgGross": float(daily["gross"].mean()) if not daily.empty else 0.0,
        "maxGross": float(daily["gross"].max()) if not daily.empty else 0.0,
        "description": spec["description"],
    }
    return summary, daily, trades


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
                "grossPnlBeforeCosts": float(group["daily_gross_pnl"].sum()),
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "days": int(len(group)),
                "trades": int(group["trades"].sum()),
            }
        )
    return rows


def event_qa_row(spec: dict[str, object], selected: pd.DataFrame) -> dict[str, object]:
    return {
        "variant": spec["variant"],
        "candidateRows": int(len(selected)),
        "eventDays": int(selected["date"].nunique()) if not selected.empty else 0,
        "tickers": int(selected["ticker"].nunique()) if not selected.empty else 0,
        "medianTradesPerEventDay": float(selected.groupby("date")["ticker"].count().median()) if not selected.empty else 0.0,
        "meanGap": float(selected["gap"].mean()) if not selected.empty else float("nan"),
        "meanRvol930": float(selected["rvol930"].mean()) if not selected.empty else float("nan"),
        "meanGrossRet": float(selected["gross_ret"].mean()) if not selected.empty else float("nan"),
        "meanNetRet": float(selected["net_ret"].mean()) if not selected.empty else float("nan"),
    }


def main() -> None:
    panel = prepare_panel()
    summaries = []
    years = []
    concentrations = []
    event_qa = []
    daily_frames = []
    trade_frames = []

    for spec in VARIANTS:
        selected = select_variant(panel, spec)
        summary, daily, trades = simulate(selected, spec)
        summaries.append(summary)
        years.extend(yearly_rows(str(spec["variant"]), daily))
        concentrations.append(concentration_row(str(spec["variant"]), trades))
        event_qa.append(event_qa_row(spec, selected))
        daily_frames.append(daily)
        trade_frames.append(trades)
        print("VARIANT", spec["variant"], summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(years).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentrations).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(event_qa).to_csv(EVENT_QA_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(trade_frames, ignore_index=True).to_csv(TRADES_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_gap_event_safe_diagnostic.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(INTRADAY_0935).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "universe": "Broad PIT eligible universe represented in PIT_FULL NOWARMUP feature caches.",
        "entry": "09:35 entry price.",
        "exit": "15:55 same-day exit price.",
        "signals_known_at_entry": ["overnight gap", "09:30 five-minute relative volume"],
        "external_event_labels": "Excluded; no earnings labels used.",
        "rule_selection": "None. All variants are fixed/pre-registered in VARIANTS before measuring.",
        "old_62_usage": "None. No old-62 ticker list/profile filter is loaded.",
        "cost_bps_per_side": COST_BPS_PER_SIDE,
        "max_names_per_side": MAX_NAMES_PER_SIDE,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(EVENT_QA_OUT), str(TRADES_OUT), str(DAILY_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, EVENT_QA_OUT, DAILY_OUT, TRADES_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
