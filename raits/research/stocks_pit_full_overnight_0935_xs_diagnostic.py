from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_OVERNIGHT_0935_XS_DIAGNOSTIC_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")

START_CAPITAL = 100_000.0
TOTAL_GROSS = 0.80
LONG_ONLY_GROSS = 0.40
COST_BPS_PER_SIDE = 4.0
MAX_NAMES_PER_SIDE = 50
START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DECILE_OUT = Path(f"{OUT_PREFIX}_DECILES.csv")
TRADES_OUT = Path(f"{OUT_PREFIX}_TRADES.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {
        "variant": "gap_reversal_ls_q10_q90",
        "signal": "gap",
        "mode": "reversal",
        "book": "long_short",
        "description": "Long most-negative overnight gap decile, short most-positive gap decile.",
    },
    {
        "variant": "gap_continuation_ls_q10_q90",
        "signal": "gap",
        "mode": "continuation",
        "book": "long_short",
        "description": "Long most-positive overnight gap decile, short most-negative gap decile.",
    },
    {
        "variant": "first5_reversal_ls_q10_q90",
        "signal": "first5_ret",
        "mode": "reversal",
        "book": "long_short",
        "description": "Long weakest first-5min decile, short strongest first-5min decile.",
    },
    {
        "variant": "first5_continuation_ls_q10_q90",
        "signal": "first5_ret",
        "mode": "continuation",
        "book": "long_short",
        "description": "Long strongest first-5min decile, short weakest first-5min decile.",
    },
    {
        "variant": "gap_reversal_long_q10",
        "signal": "gap",
        "mode": "reversal",
        "book": "long_only",
        "description": "Long most-negative overnight gap decile only.",
    },
    {
        "variant": "first5_reversal_long_q10",
        "signal": "first5_ret",
        "mode": "reversal",
        "book": "long_only",
        "description": "Long weakest first-5min decile only.",
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
    return float(1.0 / (weights.pow(2).sum()))


def concentration_rows(variant: str, trades: pd.DataFrame) -> dict[str, float | int | str]:
    by_ticker = trades.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(trades["pnl"].sum())
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
    x = daily[
        [
            "date",
            "ticker",
            "gap",
            "ret_0935_to_1555",
            "ret_open_to_1555",
            "ret60_pre",
            "vol20_pre",
        ]
    ].merge(
        intraday[["date", "ticker", "first5_ret", "ret935_eod", "entry935", "exit1555", "rvol930"]],
        on=["date", "ticker"],
        how="inner",
    )
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=["gap", "first5_ret", "ret935_eod", "entry935", "exit1555"])
    x = x[x["entry935"] > 0].copy()
    x["date"] = pd.to_datetime(x["date"]).dt.normalize()
    x["year"] = x["date"].dt.year
    return x


def attach_deciles(panel: pd.DataFrame) -> pd.DataFrame:
    x = panel.copy()
    for col in ("gap", "first5_ret"):
        rank = x.groupby("date")[col].rank(method="first", pct=True)
        x[f"{col}_decile"] = np.minimum(np.ceil(rank * 10).astype(int), 10)
    return x


def select_trades(panel: pd.DataFrame, spec: dict[str, str]) -> pd.DataFrame:
    signal = spec["signal"]
    decile_col = f"{signal}_decile"
    if spec["book"] == "long_only":
        selected = panel[panel[decile_col].eq(1)].copy()
        selected["side"] = 1
    else:
        low = panel[panel[decile_col].eq(1)].copy()
        high = panel[panel[decile_col].eq(10)].copy()
        if spec["mode"] == "reversal":
            low["side"] = 1
            high["side"] = -1
        else:
            low["side"] = -1
            high["side"] = 1
        selected = pd.concat([low, high], ignore_index=True)

    selected["abs_signal"] = selected[signal].abs()
    selected = selected.sort_values(["date", "side", "abs_signal"], ascending=[True, True, False])
    selected["side_rank"] = selected.groupby(["date", "side"]).cumcount() + 1
    selected = selected[selected["side_rank"].le(MAX_NAMES_PER_SIDE)].copy()
    selected["variant"] = spec["variant"]
    selected["gross_ret"] = selected["side"] * selected["ret935_eod"] - (2.0 * COST_BPS_PER_SIDE / 10_000.0)
    return selected


def simulate_variant(trades: pd.DataFrame, spec: dict[str, str]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    equity = START_CAPITAL
    daily_rows = []
    trade_rows = []
    gross = LONG_ONLY_GROSS if spec["book"] == "long_only" else TOTAL_GROSS

    for date, group in trades.groupby("date", sort=True):
        if spec["book"] == "long_only":
            group = group.copy()
            group["weight"] = gross / len(group) if len(group) else 0.0
        else:
            group = group.copy()
            counts = group.groupby("side")["ticker"].transform("count")
            group["weight"] = (gross / 2.0) / counts
        group["notional"] = equity * group["weight"]
        group["pnl"] = group["notional"] * group["gross_ret"]
        daily_pnl = float(group["pnl"].sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "gross": gross,
                "trades": int(len(group)),
                "longs": int((group["side"] > 0).sum()),
                "shorts": int((group["side"] < 0).sum()),
            }
        )
        trade_rows.append(group)

    daily = pd.DataFrame(daily_rows)
    out_trades = pd.concat(trade_rows, ignore_index=True) if trade_rows else pd.DataFrame()
    dd, dd_pct = max_drawdown(daily["equity"]) if not daily.empty else (0.0, 0.0)
    pnl = float(daily["daily_pnl"].sum()) if not daily.empty else 0.0
    summary = {
        "variant": spec["variant"],
        "signal": spec["signal"],
        "mode": spec["mode"],
        "book": spec["book"],
        "pnl": pnl,
        "cagr": cagr(daily["equity"], daily["date"]) if not daily.empty else float("nan"),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]) if not daily.empty else float("nan"),
        "days": int(len(daily)),
        "trades": int(len(out_trades)),
        "selectedTickers": int(out_trades["ticker"].nunique()) if not out_trades.empty else 0,
        "avgTradesPerDay": float(daily["trades"].mean()) if not daily.empty else 0.0,
        "avgGross": float(daily["gross"].mean()) if not daily.empty else 0.0,
        "maxGross": float(daily["gross"].max()) if not daily.empty else 0.0,
        "description": spec["description"],
    }
    return summary, daily, out_trades


def yearly_rows(variant: str, daily: pd.DataFrame) -> list[dict]:
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
                "trades": int(group["trades"].sum()),
            }
        )
    return rows


def decile_rows(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for signal in ("gap", "first5_ret"):
        decile_col = f"{signal}_decile"
        for decile, group in panel.groupby(decile_col, sort=True):
            rows.append(
                {
                    "signal": signal,
                    "decile": int(decile),
                    "rows": int(len(group)),
                    "meanSignal": float(group[signal].mean()),
                    "meanRet935Eod": float(group["ret935_eod"].mean()),
                    "medianRet935Eod": float(group["ret935_eod"].median()),
                    "winRateLong": float((group["ret935_eod"] > 0).mean()),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    panel = attach_deciles(prepare_panel())
    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    trade_frames = []

    for spec in VARIANTS:
        selected = select_trades(panel, spec)
        summary, daily, trades = simulate_variant(selected, spec)
        summaries.append(summary)
        yearly.extend(yearly_rows(spec["variant"], daily))
        concentration.append(concentration_rows(spec["variant"], trades))
        daily_frames.append(daily)
        trade_frames.append(trades)
        print("VARIANT", spec["variant"], summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    decile_rows(panel).to_csv(DECILE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(trade_frames, ignore_index=True).to_csv(TRADES_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_overnight_0935_xs_diagnostic.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(INTRADAY_0935).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "universe": "Broad PIT eligible universe represented in the PIT_FULL NOWARMUP feature caches.",
        "entry": "09:35 feature-cache entry price; first5_ret is known by entry time.",
        "exit": "15:55 same-day feature-cache exit price.",
        "cost_bps_per_side": COST_BPS_PER_SIDE,
        "total_gross_long_short": TOTAL_GROSS,
        "gross_long_only": LONG_ONLY_GROSS,
        "max_names_per_side": MAX_NAMES_PER_SIDE,
        "rule_selection": "None. All variants are fixed/pre-registered in VARIANTS before measuring.",
        "old_62_usage": "None. No old-62 ticker list/profile filter is loaded.",
        "outputs": [
            str(SUMMARY_OUT),
            str(YEARLY_OUT),
            str(CONCENTRATION_OUT),
            str(DECILE_OUT),
            str(TRADES_OUT),
            str(DAILY_OUT),
        ],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DECILE_OUT, TRADES_OUT, DAILY_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
