from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base


OUT_PREFIX = "STOCKS_PIT_FULL_YDAY_REDESIGN_VARIANTS_NOWARMUP_2026-09-13"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")
PIT_FILTER = base.pit_gate.PIT_FILTER
YDAY = "yday_ex6_actual"


def keep_yday(sig: pd.DataFrame, cond: pd.Series) -> pd.Series:
    return (~sig["sleeve"].eq(YDAY)) | cond.fillna(False)


FILTER_VARIANTS = {
    "base": lambda sig: pd.Series(True, index=sig.index),
    "drop_yday": lambda sig: ~sig["sleeve"].eq(YDAY),
    "price_ge_10": lambda sig: keep_yday(sig, sig["prior_close"] >= 10),
    "price_ge_15": lambda sig: keep_yday(sig, sig["prior_close"] >= 15),
    "price_15_100": lambda sig: keep_yday(sig, sig["prior_close"].between(15, 100, inclusive="both")),
    "price_25_50": lambda sig: keep_yday(sig, sig["prior_close"].between(25, 50, inclusive="both")),
    "ret60_le_neg20": lambda sig: keep_yday(sig, sig["ret60_pre"] <= -0.20),
    "ret60_le_neg30": lambda sig: keep_yday(sig, sig["ret60_pre"] <= -0.30),
    "ret60_le_neg20_price_ge_10": lambda sig: keep_yday(
        sig, (sig["ret60_pre"] <= -0.20) & (sig["prior_close"] >= 10)
    ),
    "ret60_le_neg20_price_10_100": lambda sig: keep_yday(
        sig, (sig["ret60_pre"] <= -0.20) & sig["prior_close"].between(10, 100, inclusive="both")
    ),
    "ret60_le_neg20_price_15_100": lambda sig: keep_yday(
        sig, (sig["ret60_pre"] <= -0.20) & sig["prior_close"].between(15, 100, inclusive="both")
    ),
    "ret60_le_neg20_price_15_100_adv_lt_250m": lambda sig: keep_yday(
        sig,
        (sig["ret60_pre"] <= -0.20)
        & sig["prior_close"].between(15, 100, inclusive="both")
        & (sig["adv20"] < 250_000_000),
    ),
    "price_ge_10_adv_50_250m": lambda sig: keep_yday(
        sig, (sig["prior_close"] >= 10) & sig["adv20"].between(50_000_000, 250_000_000, inclusive="both")
    ),
    "price_ge_10_ret60_le_20_adv_lt_250m": lambda sig: keep_yday(
        sig, (sig["prior_close"] >= 10) & (sig["ret60_pre"] <= 0.20) & (sig["adv20"] < 250_000_000)
    ),
    "vol20_le_6": lambda sig: keep_yday(sig, sig["vol20_pre"] <= 0.06),
    "price_ge_10_vol20_le_6": lambda sig: keep_yday(
        sig, (sig["prior_close"] >= 10) & (sig["vol20_pre"] <= 0.06)
    ),
}


def add_quality_columns(signals: pd.DataFrame) -> pd.DataFrame:
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    quality = daily[["date", "ticker", "vol20_pre", "ret60_pre"]].copy()
    pit = pd.read_parquet(PIT_FILTER, columns=["date", "ticker", "prior_close", "adv20", "liquidity_metric_source"])
    pit["date"] = pd.to_datetime(pit["date"])
    pit = pit.drop_duplicates(["date", "ticker"])
    return signals.merge(quality, on=["date", "ticker"], how="left").merge(pit, on=["date", "ticker"], how="left")


def make_configs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for portfolio_name, cfg in base.PORTFOLIOS.items():
        if not portfolio_name.startswith("B_"):
            continue
        out[portfolio_name] = cfg
        for yday_weight in (0.10, 0.20):
            reduced = deepcopy(cfg)
            reduced["weights"] = dict(reduced["weights"])
            reduced["weights"][YDAY] = yday_weight
            out[f"{portfolio_name}_ydayw{int(yday_weight * 100):02d}"] = reduced
    return out


def append_csv(path: Path, row: dict | list[dict]) -> None:
    rows = row if isinstance(row, list) else [row]
    pd.DataFrame(rows).to_csv(path, mode="a", header=not path.exists(), index=False)


def completed_pairs() -> set[tuple[str, str]]:
    if not SUMMARY_OUT.exists():
        return set()
    done = pd.read_csv(SUMMARY_OUT)
    if "variant" not in done or "base_portfolio" not in done:
        return set()
    return set(zip(done["variant"].astype(str), done["base_portfolio"].astype(str)))


def yearly_metrics(variant: str, name: str, eq: pd.DataFrame) -> list[dict]:
    rows = []
    for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
        std = float(group["daily_pnl"].std())
        curve = group["daily_pnl"].cumsum()
        rows.append(
            {
                "variant": variant,
                "portfolio": name,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddSubset": float((curve - curve.cummax()).min()),
                "sharpe": float(group["daily_pnl"].mean() / std * np.sqrt(252)) if std > 0 else np.nan,
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

    configs = make_configs()
    done = completed_pairs()

    for variant, mask_fn in FILTER_VARIANTS.items():
        variant_signals = gated_signals[mask_fn(gated_signals)].copy()
        yday_before = gated_signals[gated_signals["sleeve"].eq(YDAY)]
        yday_after = variant_signals[variant_signals["sleeve"].eq(YDAY)]
        if not SIGNAL_QA_OUT.exists() or variant not in set(pd.read_csv(SIGNAL_QA_OUT)["variant"].astype(str)):
            append_csv(
                SIGNAL_QA_OUT,
                {
                    "variant": variant,
                    "yday_before": int(len(yday_before)),
                    "yday_after": int(len(yday_after)),
                    "yday_removed": int(len(yday_before) - len(yday_after)),
                    "median_prior_close": float(yday_after["prior_close"].median()) if len(yday_after) else np.nan,
                    "median_adv20": float(yday_after["adv20"].median()) if len(yday_after) else np.nan,
                    "median_vol20": float(yday_after["vol20_pre"].median()) if len(yday_after) else np.nan,
                    "median_ret60": float(yday_after["ret60_pre"].median()) if len(yday_after) else np.nan,
                },
            )
        for portfolio_name, cfg in configs.items():
            if (variant, portfolio_name) in done:
                print("SKIP", variant, portfolio_name, flush=True)
                continue
            name = portfolio_name.replace("nowarmup", f"{variant}_nowarmup")
            summary, eq, _ = base.poly.simulate(name, cfg, variant_signals, daily_px)
            summary["variant"] = variant
            summary["base_portfolio"] = portfolio_name
            append_csv(SUMMARY_OUT, summary)
            append_csv(YEARLY_OUT, yearly_metrics(variant, name, eq))
            done.add((variant, portfolio_name))
            print("VARIANT", variant, name, summary, flush=True)

    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
