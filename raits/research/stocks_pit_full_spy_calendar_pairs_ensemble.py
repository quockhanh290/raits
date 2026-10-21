from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_SPY_CALENDAR_PAIRS_ENSEMBLE_2026-09-17"
CORE_DAILY = Path("STOCKS_PIT_FULL_BETA_PLUS_CALENDAR_OVERLAY_2026-09-14_DAILY.csv")
PAIR_DAILY = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_DAILY.csv")
PAIR_CONTRIB = Path("STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17_TICKER_CONTRIB.csv")
CORE_VARIANT = "spyvt16c150_plus_spy_first5_x05_fin25_cost4"
PAIR_VARIANT = "sic_pairs_quarterly_z2_hold10"
START_CAPITAL = 100_000.0
FINANCING_ANNUAL_RATE = 0.025

# Frozen family: preserve the audited core and pair trades, changing only the
# pre-registered pair sleeve scale in a shared-equity book.
PAIR_SCALES = (0.0, 0.5, 1.0)

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
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


def load_sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    core = pd.read_csv(CORE_DAILY, parse_dates=["date"])
    core = core[core["variant"].eq(CORE_VARIANT)].sort_values("date").copy()
    pair = pd.read_csv(PAIR_DAILY, parse_dates=["date"])
    pair = pair[pair["variant"].eq(PAIR_VARIANT)].sort_values("date").copy()
    pair["start_equity"] = pair["equity"] - pair["daily_pnl"]
    pair["pair_net_ret"] = pair["daily_pnl"] / pair["start_equity"]
    x = core.merge(
        pair[["date", "pair_net_ret", "gross_exposure"]].rename(columns={"gross_exposure": "pair_gross"}),
        on="date",
        how="left",
    )
    x[["pair_net_ret", "pair_gross"]] = x[["pair_net_ret", "pair_gross"]].fillna(0.0)

    contrib = pd.read_csv(PAIR_CONTRIB, parse_dates=["date"])
    contrib = contrib[contrib["variant"].eq(PAIR_VARIANT)].merge(pair[["date", "start_equity"]], on="date", how="inner")
    contrib["pair_contrib_ret"] = contrib["pnl"] / contrib["start_equity"]
    return x, contrib[["date", "ticker", "pair_contrib_ret"]]


def variant_name(scale: float) -> str:
    return f"spy_vt16_first5_05_plus_pairs_{scale:g}x"


def simulate(source: pd.DataFrame, pair_contrib: pd.DataFrame, scale: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    contrib_by_date = {date: group.set_index("ticker")["pair_contrib_ret"] for date, group in pair_contrib.groupby("date", sort=True)}
    equity = START_CAPITAL
    daily_rows = []
    contrib_rows = []
    for row in source.itertuples(index=False):
        core_net_ret = float(row.daily_ret)
        pair_net_ret = float(row.pair_net_ret) * scale
        combined_gross = float(row.gross_exposure) + float(row.pair_gross) * scale
        core_financed = max(float(row.gross_exposure) - 1.0, 0.0)
        combined_financed = max(combined_gross - 1.0, 0.0)
        incremental_financing_ret = (combined_financed - core_financed) * FINANCING_ANNUAL_RATE / 252.0
        core_pnl = equity * core_net_ret
        pair_pnl = equity * pair_net_ret
        financing_pnl = -equity * incremental_financing_ret
        daily_pnl = core_pnl + pair_pnl + financing_pnl

        contrib_rows.append({"variant": variant_name(scale), "date": row.date, "ticker": "SPY", "sleeve": "core", "pnl": core_pnl})
        pair_rates = contrib_by_date.get(row.date, pd.Series(dtype=float))
        contrib_rows.extend(
            {"variant": variant_name(scale), "date": row.date, "ticker": ticker, "sleeve": "pairs", "pnl": equity * float(rate) * scale}
            for ticker, rate in pair_rates.items()
            if float(rate) != 0.0 and scale > 0
        )
        if financing_pnl != 0:
            contrib_rows.append({"variant": variant_name(scale), "date": row.date, "ticker": "_FINANCING", "sleeve": "financing", "pnl": financing_pnl})

        equity += daily_pnl
        daily_rows.append(
            {
                "variant": variant_name(scale),
                "date": row.date,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "core_pnl": core_pnl,
                "pair_pnl": pair_pnl,
                "incremental_financing_pnl": financing_pnl,
                "core_gross": float(row.gross_exposure),
                "pair_gross": float(row.pair_gross) * scale,
                "combined_gross": combined_gross,
            }
        )
    daily = pd.DataFrame(daily_rows)
    daily["year"] = daily["date"].dt.year
    return daily, pd.DataFrame(contrib_rows)


def effective_ticker_count(by_ticker: pd.Series) -> float:
    positive = by_ticker[by_ticker > 0]
    source = positive if positive.sum() > 0 else by_ticker.abs()
    total = float(source.sum())
    if total <= 0:
        return 0.0
    weights = source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_rows(variant: str, contrib: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for scope, selected in (
        ("total_ex_financing", contrib[~contrib["ticker"].eq("_FINANCING")]),
        ("pairs_only", contrib[contrib["sleeve"].eq("pairs")]),
    ):
        by_ticker = selected.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
        portfolio_total = float(contrib["pnl"].sum()) if scope == "total_ex_financing" else float(selected["pnl"].sum())
        denominator = portfolio_total if portfolio_total > 0 else float(by_ticker.abs().sum())
        row: dict[str, object] = {
            "variant": variant,
            "scope": scope,
            "tickers": int(len(by_ticker)),
            "effectiveTickerCount": effective_ticker_count(by_ticker),
            "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        }
        for n in (1, 3, 5, 10):
            top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
            row[f"top{n}Pnl"] = top
            row[f"top{n}Share"] = top / denominator if denominator else float("nan")
        rows.append(row)
    return rows


def summary_row(daily: pd.DataFrame, scale: float) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    return {
        "variant": variant_name(scale),
        "pairScale": scale,
        "pnl": float(daily["equity"].iloc[-1] - START_CAPITAL),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "corePnlAttribution": float(daily["core_pnl"].sum()),
        "pairPnlAttribution": float(daily["pair_pnl"].sum()),
        "incrementalFinancing": float(-daily["incremental_financing_pnl"].sum()),
        "avgCombinedGross": float(daily["combined_gross"].mean()),
        "maxCombinedGross": float(daily["combined_gross"].max()),
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (variant, year), group in daily.groupby(["variant", "year"], sort=True):
        curve = START_CAPITAL + group["daily_pnl"].cumsum()
        dd, dd_pct = max_drawdown(curve)
        rows.append({"variant": variant, "year": int(year), "pnl": float(group["daily_pnl"].sum()), "ddDollarSubset": dd, "ddPctSubset": dd_pct, "sharpe": sharpe(group["daily_pnl"])})
    return rows


def main() -> None:
    source, pair_contrib = load_sources()
    summaries = []
    yearly = []
    concentration = []
    sleeve_rows = []
    daily_frames = []
    contrib_frames = []
    qa_rows = []
    for scale in PAIR_SCALES:
        daily, contrib = simulate(source, pair_contrib, scale)
        summaries.append(summary_row(daily, scale))
        yearly.extend(yearly_rows(daily))
        concentration.extend(concentration_rows(variant_name(scale), contrib))
        for sleeve, pnl in contrib.groupby("sleeve")["pnl"].sum().items():
            sleeve_rows.append({"variant": variant_name(scale), "sleeve": sleeve, "pnl": float(pnl)})
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        qa_rows.append({"variant": variant_name(scale), "dailyPnl": float(daily["daily_pnl"].sum()), "contribPnl": float(contrib["pnl"].sum()), "difference": float(daily["daily_pnl"].sum() - contrib["pnl"].sum())})
        print("CAL_PAIRS", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(sleeve_rows).to_csv(SLEEVE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_spy_calendar_pairs_ensemble.py",
        "inputs": [str(CORE_DAILY), str(PAIR_DAILY), str(PAIR_CONTRIB)],
        "method": "Shared-equity ensemble of frozen SPY vt16 plus SPY first-five-days 0.5x core and frozen quarterly same-SIC pairs; pair scales 0/0.5/1.0.",
        "financing": f"Core retains its original costs; add {FINANCING_ANNUAL_RATE:.1%} annual financing only for incremental combined gross above the financing already charged to the core.",
        "sample_label": "Research/touched 2018-2024 only. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "rule_selection_effect": "None. Both source strategies and pair scale family were frozen before ensemble measurement; no rule re-selection.",
        "trade_selection_effect": "Source trades remain frozen. Shared-equity compounding and incremental financing are recomputed; no PnL subtraction or ticker removal.",
        "attribution_note": "Ticker ledger applies pair constituent return contributions and core SPY return to shared equity each day. Incremental financing is retained as a separate pseudo-ticker.",
        "pair_scales": list(PAIR_SCALES),
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, SLEEVE_OUT, DAILY_OUT, CONTRIB_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
