from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd

import stocks_pit_full_quality_universe_gate_nowarmup as qgate


OUT_PREFIX = "STOCKS_PIT_FULL_HISTORICAL_INDEX_UNIVERSE_NOWARMUP_2026-09-14"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

SOURCES = {
    "sp500_thuningxu": {
        "path": "raits/data/cache/external_universes/sp500_components_history_thuningxu.csv",
        "url": "https://github.com/thuningxu/sp500nq100",
        "raw_url": "https://raw.githubusercontent.com/thuningxu/sp500nq100/main/sp500_components_history.csv",
    },
    "nasdaq100_thuningxu": {
        "path": "raits/data/cache/external_universes/nasdaq100_components_history_thuningxu.csv",
        "url": "https://github.com/thuningxu/sp500nq100",
        "raw_url": "https://raw.githubusercontent.com/thuningxu/sp500nq100/main/nasdaq100_components_history.csv",
    },
}


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace("-", ".")


def load_membership(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    df["ticker_set"] = df["tickers"].fillna("").map(lambda s: {normalize_symbol(x) for x in str(s).split(",") if x})
    return df[["date", "ticker_set"]].sort_values("date").reset_index(drop=True)


def membership_mask(daily: pd.DataFrame, membership: pd.DataFrame) -> pd.Series:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership, on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    tickers = daily["ticker"].astype(str).map(normalize_symbol)
    sets = daily["date"].map(date_to_set)
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(tickers, sets)]
    return pd.Series(mask, index=daily.index)


def infer_notional(pnl: pd.Series, ret: pd.Series) -> pd.Series:
    out = (pnl.astype(float) / ret.astype(float).replace(0.0, np.nan)).abs()
    med = float(out.replace([np.inf, -np.inf], np.nan).dropna().median()) if out.notna().any() else 0.0
    return out.replace([np.inf, -np.inf], np.nan).fillna(med)


def yearly_metrics(variant: str, eq: pd.DataFrame) -> list[dict]:
    rows = []
    for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
        curve = group["daily_pnl"].cumsum()
        std = float(group["daily_pnl"].std())
        rows.append(
            {
                "variant": variant,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddSubset": float((curve - curve.cummax()).min()),
                "sharpe": float(group["daily_pnl"].mean() / std * math.sqrt(252)) if std > 0 else np.nan,
            }
        )
    return rows


def main() -> None:
    qgate.base.configure_poly()
    daily = pd.read_pickle(qgate.base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = qgate.add_quality(daily)
    intraday = pd.read_pickle(qgate.base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    daily_px = qgate.base.poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    gate = qgate.base.pit_gate.load_pit_gate()
    cfg = qgate.base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]

    summaries = []
    years = []
    qa_rows = []
    manifest = {
        "out_prefix": OUT_PREFIX,
        "source_note": "Public reconstructed point-in-time index membership. Treat as research input, not official S&P/Nasdaq licensed data.",
        "sources": SOURCES,
        "variants": [],
    }

    for variant, source in SOURCES.items():
        membership = load_membership(Path(str(source["path"])))
        mask = membership_mask(daily, membership)
        # Keep PIT tradability/liquidity gate too. Index membership alone is not sufficient if the
        # local PIT bar/liquidity artifact cannot trade the ticker-day.
        mask &= daily["eligible_final"].fillna(True) if "eligible_final" in daily.columns else True
        broad = qgate.build_broad_trades(daily, mask)
        local = qgate.build_local_trades(daily, mask)
        yday = qgate.build_yday_trades(daily, mask)
        signals = qgate.load_signals(broad, local, yday, daily_px, intraday_px)
        gated_signals, gate_qa, _, _ = qgate.base.pit_gate.apply_pit_gate(signals, gate)
        name = f"B_pit_full_historical_index_{variant}_nowarmup_cap40"
        summary, eq, _ = qgate.base.poly.simulate(name, cfg, gated_signals, daily_px)
        summary["variant"] = variant
        summaries.append(summary)
        years.extend(yearly_metrics(variant, eq))

        dates = daily.loc[mask, ["date", "ticker"]]
        qa = {
            "variant": variant,
            "membership_rows": int(len(membership)),
            "membership_start": str(membership["date"].min().date()),
            "membership_end": str(membership["date"].max().date()),
            "quality_rows": int(mask.sum()),
            "quality_tickers": int(dates["ticker"].nunique()),
            "median_names_per_day": float(dates.groupby("date")["ticker"].nunique().median()) if not dates.empty else np.nan,
            "broad_rows": int(len(broad)),
            "local_rows": int(len(local)),
            "yday_rows_all_modes": int(len(yday)),
            "yday_rows_rolling3": int((yday["wfo_mode"].eq("rolling3")).sum()) if "wfo_mode" in yday else 0,
        }
        qa_rows.append(qa)
        manifest["variants"].append({**qa, "source_path": str(source["path"]).replace("\\", "/"), "source_url": source["url"]})
        print("VARIANT", variant, summary, qa, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(years).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(SIGNAL_QA_OUT, index=False)
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SIGNAL_QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
