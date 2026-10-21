from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base
from stocks_pit_full_ticker_fallback_impact_nowarmup import VARIANTS, add_quality_columns


OUT_PREFIX = "STOCKS_PIT_FULL_REGIME_OVERLAY_NOWARMUP_2026-09-13"
YDAY = "yday_ex6_actual"
BROAD = "broad_adv10_g2_dd85"
LOCAL = "local_xs_full_s10"

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
MONTHLY_2022_OUT = Path(f"{OUT_PREFIX}_2022_MONTHLY.csv")
REGIME_DAILY_OUT = Path(f"{OUT_PREFIX}_REGIME_DAILY.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")


YDAY_VARIANTS = {
    "base_drop_fallback": "base",
    "balanced_drop_fallback": "ret60_le_neg20_price_15_100",
}


OVERLAYS = {
    "none": lambda sig: pd.Series(True, index=sig.index),
    "skip_bl_spy20_lt_neg5": lambda sig: ~(
        sig["sleeve"].isin([BROAD, LOCAL]) & sig["spy20"].lt(-0.05)
    ),
    "skip_bl_univ20_lt_neg8": lambda sig: ~(
        sig["sleeve"].isin([BROAD, LOCAL]) & sig["univ20"].lt(-0.08)
    ),
    "skip_broad_univ20_lt_neg8": lambda sig: ~(
        sig["sleeve"].eq(BROAD) & sig["univ20"].lt(-0.08)
    ),
    "skip_local_univ20_lt_neg8": lambda sig: ~(
        sig["sleeve"].eq(LOCAL) & sig["univ20"].lt(-0.08)
    ),
    "skip_bl_breadth20_lt_45": lambda sig: ~(
        sig["sleeve"].isin([BROAD, LOCAL]) & sig["breadth20"].lt(0.45)
    ),
    "skip_bl_any_riskoff": lambda sig: ~(
        sig["sleeve"].isin([BROAD, LOCAL])
        & (sig["spy20"].lt(-0.05) | sig["univ20"].lt(-0.08) | sig["breadth20"].lt(0.45))
    ),
    "skip_broad_any_riskoff": lambda sig: ~(
        sig["sleeve"].eq(BROAD)
        & (sig["spy20"].lt(-0.05) | sig["univ20"].lt(-0.08) | sig["breadth20"].lt(0.45))
    ),
    "skip_local_any_riskoff": lambda sig: ~(
        sig["sleeve"].eq(LOCAL)
        & (sig["spy20"].lt(-0.05) | sig["univ20"].lt(-0.08) | sig["breadth20"].lt(0.45))
    ),
}


def build_regime(daily: pd.DataFrame) -> pd.DataFrame:
    spy = daily[["date", "spy_prev_dayret"]].dropna().drop_duplicates("date").sort_values("date")
    breadth = (
        daily.groupby("date")
        .agg(
            univ_ret=("prev_dayret", "mean"),
            breadth=("prev_dayret", lambda s: float((s > 0).mean())),
            universe_names=("ticker", "nunique"),
        )
        .reset_index()
        .sort_values("date")
    )
    out = spy.merge(breadth, on="date", how="inner").sort_values("date")
    # Inputs are previous-session returns as of the current open, so rolling windows are causal.
    out["spy20"] = (1.0 + out["spy_prev_dayret"].astype(float)).rolling(20, min_periods=10).apply(np.prod, raw=True) - 1.0
    out["univ20"] = (1.0 + out["univ_ret"].astype(float)).rolling(20, min_periods=10).apply(np.prod, raw=True) - 1.0
    out["breadth20"] = out["breadth"].rolling(20, min_periods=10).mean()
    out["riskoff_any"] = out["spy20"].lt(-0.05) | out["univ20"].lt(-0.08) | out["breadth20"].lt(0.45)
    out.to_csv(REGIME_DAILY_OUT, index=False)
    return out


def append_csv(path: Path, rows: dict | list[dict]) -> None:
    batch = rows if isinstance(rows, list) else [rows]
    pd.DataFrame(batch).to_csv(path, mode="a", header=not path.exists(), index=False)


def completed() -> set[tuple[str, str]]:
    if not SUMMARY_OUT.exists():
        return set()
    df = pd.read_csv(SUMMARY_OUT)
    return set(zip(df["yday_variant"].astype(str), df["overlay"].astype(str)))


def yearly_rows(yday_variant: str, overlay: str, portfolio: str, eq: pd.DataFrame) -> list[dict]:
    rows = []
    for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
        curve = group["daily_pnl"].cumsum()
        std = float(group["daily_pnl"].std())
        rows.append(
            {
                "yday_variant": yday_variant,
                "overlay": overlay,
                "portfolio": portfolio,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "dd": float((curve - curve.cummax()).min()),
                "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
                "avgGross": float(group["gross"].mean()),
                "maxGross": float(group["gross"].max()),
            }
        )
    return rows


def monthly_2022_rows(yday_variant: str, overlay: str, eq: pd.DataFrame, regime: pd.DataFrame) -> list[dict]:
    eq22 = eq[eq["date"].dt.year.eq(2022)].copy()
    eq22["month"] = eq22["date"].dt.to_period("M").astype(str)
    market = regime[regime["date"].dt.year.eq(2022)].copy()
    market["month"] = market["date"].dt.to_period("M").astype(str)
    m = (
        eq22.groupby("month")
        .agg(strategy_pnl=("daily_pnl", "sum"), avg_gross=("gross", "mean"))
        .reset_index()
        .merge(
            market.groupby("month")
            .agg(
                spy_proxy_ret=("spy_prev_dayret", lambda s: float((1.0 + s).prod() - 1.0)),
                univ_proxy_ret=("univ_ret", lambda s: float((1.0 + s).prod() - 1.0)),
                avg_breadth=("breadth", "mean"),
                riskoff_days=("riskoff_any", "sum"),
                days=("date", "count"),
            )
            .reset_index(),
            on="month",
            how="left",
        )
    )
    m["yday_variant"] = yday_variant
    m["overlay"] = overlay
    return m.to_dict("records")


def main() -> None:
    base.configure_poly()
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    intraday = pd.read_pickle(base.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    regime = build_regime(daily)

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
    gated_signals = gated_signals.merge(
        regime[["date", "spy20", "univ20", "breadth20", "riskoff_any"]],
        on="date",
        how="left",
    )

    cfg = base.PORTFOLIOS["B_pit_full_no_intraday_nowarmup_cap40"]
    done = completed()
    for yday_variant, variant_key in YDAY_VARIANTS.items():
        # Conservative baseline: exclude all ticker-fallback rows, then apply yday rule.
        base_mask = (~gated_signals["is_ticker_fallback"]) & VARIANTS[variant_key](gated_signals)
        variant_signals = gated_signals[base_mask].copy()
        for overlay, overlay_fn in OVERLAYS.items():
            if (yday_variant, overlay) in done:
                print("SKIP", yday_variant, overlay, flush=True)
                continue
            final_signals = variant_signals[overlay_fn(variant_signals)].copy()
            name = f"B_{yday_variant}_{overlay}"
            summary, eq, trades = base.poly.simulate(name, cfg, final_signals, daily_px)
            summary["yday_variant"] = yday_variant
            summary["overlay"] = overlay
            summary["signals"] = int(len(final_signals))
            summary["broad_signals"] = int(final_signals["sleeve"].eq(BROAD).sum())
            summary["local_signals"] = int(final_signals["sleeve"].eq(LOCAL).sum())
            summary["yday_signals"] = int(final_signals["sleeve"].eq(YDAY).sum())
            append_csv(SUMMARY_OUT, summary)
            append_csv(YEARLY_OUT, yearly_rows(yday_variant, overlay, name, eq))
            append_csv(MONTHLY_2022_OUT, monthly_2022_rows(yday_variant, overlay, eq, regime))
            qa = (
                final_signals.groupby("sleeve")
                .agg(signals=("ticker", "size"), unique_tickers=("ticker", "nunique"))
                .reset_index()
            )
            qa["yday_variant"] = yday_variant
            qa["overlay"] = overlay
            append_csv(SIGNAL_QA_OUT, qa.to_dict("records"))
            done.add((yday_variant, overlay))
            print("OVERLAY", yday_variant, overlay, summary, flush=True)

    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
