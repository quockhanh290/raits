from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base


OUT_PREFIX = "STOCKS_PIT_FULL_TICKER_FALLBACK_IMPACT_NOWARMUP_2026-09-13"
PIT_FILTER = base.pit_gate.PIT_FILTER
YDAY = "yday_ex6_actual"


SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
TRADE_ATTR_OUT = Path(f"{OUT_PREFIX}_TRADE_ATTRIBUTION.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")


def keep_yday(sig: pd.DataFrame, cond: pd.Series) -> pd.Series:
    return (~sig["sleeve"].eq(YDAY)) | cond.fillna(False)


VARIANTS = {
    "base": lambda sig: pd.Series(True, index=sig.index),
    "price_15_100": lambda sig: keep_yday(sig, sig["prior_close"].between(15, 100, inclusive="both")),
    "ret60_le_neg20": lambda sig: keep_yday(sig, sig["ret60_pre"] <= -0.20),
    "ret60_le_neg20_price_15_100": lambda sig: keep_yday(
        sig, (sig["ret60_pre"] <= -0.20) & sig["prior_close"].between(15, 100, inclusive="both")
    ),
}


FALLBACK_POLICIES = {
    "all_rows": lambda sig: pd.Series(True, index=sig.index),
    "drop_yday_fallback": lambda sig: ~(sig["sleeve"].eq(YDAY) & sig["is_ticker_fallback"]),
    "drop_any_fallback": lambda sig: ~sig["is_ticker_fallback"],
}


def add_quality_columns(signals: pd.DataFrame) -> pd.DataFrame:
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    quality = daily[["date", "ticker", "vol20_pre", "ret60_pre"]].copy()
    pit = pd.read_parquet(
        PIT_FILTER,
        columns=["date", "ticker", "prior_close", "adv20"],
    )
    pit["date"] = pd.to_datetime(pit["date"])
    pit = pit.drop_duplicates(["date", "ticker"])
    return signals.merge(quality, on=["date", "ticker"], how="left").merge(pit, on=["date", "ticker"], how="left")


def append_csv(path: Path, rows: dict | list[dict]) -> None:
    batch = rows if isinstance(rows, list) else [rows]
    pd.DataFrame(batch).to_csv(path, mode="a", header=not path.exists(), index=False)


def completed() -> set[tuple[str, str]]:
    if not SUMMARY_OUT.exists():
        return set()
    df = pd.read_csv(SUMMARY_OUT)
    if "variant" not in df or "fallback_policy" not in df:
        return set()
    return set(zip(df["variant"].astype(str), df["fallback_policy"].astype(str)))


def yearly_metrics(variant: str, fallback_policy: str, portfolio: str, eq: pd.DataFrame) -> list[dict]:
    rows = []
    for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
        std = float(group["daily_pnl"].std())
        curve = group["daily_pnl"].cumsum()
        rows.append(
            {
                "variant": variant,
                "fallback_policy": fallback_policy,
                "portfolio": portfolio,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddSubset": float((curve - curve.cummax()).min()),
                "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
            }
        )
    return rows


def signal_qa(variant: str, variant_signals: pd.DataFrame) -> list[dict]:
    rows = []
    for sleeve, group in variant_signals.groupby("sleeve", sort=True):
        fallback = group["is_ticker_fallback"]
        rows.append(
            {
                "variant": variant,
                "sleeve": sleeve,
                "signals": int(len(group)),
                "ticker_fallback_signals": int(fallback.sum()),
                "fallback_pct": float(fallback.mean()) if len(group) else 0.0,
                "unique_tickers": int(group["ticker"].nunique()),
                "fallback_unique_tickers": int(group.loc[fallback, "ticker"].nunique()),
            }
        )
    return rows


def trade_attribution(
    variant: str,
    fallback_policy: str,
    trades: pd.DataFrame,
    signals: pd.DataFrame,
) -> list[dict]:
    flags = signals[
        [
            "date",
            "ticker",
            "sleeve",
            "pit_gate_mode",
            "liquidity_metric_source",
            "is_ticker_fallback",
        ]
    ].drop_duplicates(["date", "ticker", "sleeve"])
    out = trades.merge(flags, on=["date", "ticker", "sleeve"], how="left")
    rows = []
    for keys, group in out.groupby(["sleeve", "is_ticker_fallback"], dropna=False, sort=True):
        sleeve, is_fallback = keys
        rows.append(
            {
                "variant": variant,
                "fallback_policy": fallback_policy,
                "sleeve": sleeve,
                "is_ticker_fallback": bool(is_fallback) if pd.notna(is_fallback) else np.nan,
                "trades": int(len(group)),
                "pnl": float(group["pnl"].sum()),
                "avg_pnl": float(group["pnl"].mean()),
                "win_rate": float((group["pnl"] > 0).mean()),
                "unique_tickers": int(group["ticker"].nunique()),
            }
        )
    return rows


def main() -> None:
    base.configure_poly()
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    intraday = pd.read_pickle(base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])

    if not base.BROAD_TRADES.exists():
        base.poly.build_broad_trades(daily)
    if not base.LOCAL_TRADES.exists():
        base.poly.build_local_trades(daily)
    if not base.YDAY_TRADES.exists():
        base.build_yday_trades_from_daily(daily)

    daily_px = base.poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    intraday_px = intraday[["date", "ticker", "open930", "entry935", "exit1555"]].copy()
    signals = base.load_signals_no_intraday(daily_px, intraday_px)
    gate = base.pit_gate.load_pit_gate()
    gated_signals, _, _, _ = base.pit_gate.apply_pit_gate(signals, gate)
    gated_signals = add_quality_columns(gated_signals)
    gated_signals["is_ticker_fallback"] = gated_signals["liquidity_metric_source"].fillna("").eq("ticker_fallback")

    cfg = base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]
    done = completed()

    for variant, variant_mask_fn in VARIANTS.items():
        variant_signals = gated_signals[variant_mask_fn(gated_signals)].copy()
        if not SIGNAL_QA_OUT.exists() or variant not in set(pd.read_csv(SIGNAL_QA_OUT)["variant"].astype(str)):
            append_csv(SIGNAL_QA_OUT, signal_qa(variant, variant_signals))
        for fallback_policy, policy_mask_fn in FALLBACK_POLICIES.items():
            if (variant, fallback_policy) in done:
                print("SKIP", variant, fallback_policy, flush=True)
                continue
            final_signals = variant_signals[policy_mask_fn(variant_signals)].copy()
            name = f"B_pit_full_no_intraday_{variant}_{fallback_policy}_nowarmup_cap40"
            summary, eq, trades = base.poly.simulate(name, cfg, final_signals, daily_px)
            summary["variant"] = variant
            summary["fallback_policy"] = fallback_policy
            summary["signals"] = int(len(final_signals))
            summary["ticker_fallback_signals"] = int(final_signals["is_ticker_fallback"].sum())
            append_csv(SUMMARY_OUT, summary)
            append_csv(YEARLY_OUT, yearly_metrics(variant, fallback_policy, name, eq))
            append_csv(TRADE_ATTR_OUT, trade_attribution(variant, fallback_policy, trades, final_signals))
            done.add((variant, fallback_policy))
            print("VARIANT", variant, fallback_policy, summary, flush=True)

    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
