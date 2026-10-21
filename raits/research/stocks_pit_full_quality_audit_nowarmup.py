from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


TRADES = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_TRADES.csv")
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
PIT_FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20180102_20241231_resumable/"
    "liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
OUT_PREFIX = "STOCKS_PIT_FULL_QUALITY_AUDIT_NOWARMUP_2026-09-13"


def bucket(series: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(series.astype(float), bins=edges, labels=labels, include_lowest=True)


def summarize(group: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    rows = (
        group.groupby(keys, dropna=False)
        .agg(
            trades=("pnl", "size"),
            tickers=("ticker", "nunique"),
            days=("date", "nunique"),
            pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            win_rate=("pnl", lambda s: float((s > 0).mean())),
            avg_entry_notional=("entry_notional", "mean"),
            avg_prior_close=("prior_close", "mean"),
            avg_adv20=("adv20", "mean"),
            avg_vol20=("vol20_pre", "mean"),
            avg_ret60=("ret60_pre", "mean"),
            avg_prev_dayret=("prev_dayret", "mean"),
        )
        .reset_index()
        .sort_values(keys)
    )
    return rows


def diagnostic_filters(trades: pd.DataFrame) -> pd.DataFrame:
    filters: list[tuple[str, pd.Series]] = [
        ("all", pd.Series(True, index=trades.index)),
        ("prior_close_ge_10", trades["prior_close"] >= 10),
        ("prior_close_ge_15", trades["prior_close"] >= 15),
        ("adv20_ge_25m", trades["adv20"] >= 25_000_000),
        ("adv20_ge_50m", trades["adv20"] >= 50_000_000),
        ("ret60_gt_neg30pct", trades["ret60_pre"] > -0.30),
        ("ret60_gt_neg20pct", trades["ret60_pre"] > -0.20),
        ("vol20_le_6pct", trades["vol20_pre"] <= 0.06),
        ("vol20_le_4pct", trades["vol20_pre"] <= 0.04),
        (
            "price10_adv25m_ret60gt-30_vol20le6",
            (trades["prior_close"] >= 10)
            & (trades["adv20"] >= 25_000_000)
            & (trades["ret60_pre"] > -0.30)
            & (trades["vol20_pre"] <= 0.06),
        ),
        (
            "price15_adv50m_ret60gt-20_vol20le4",
            (trades["prior_close"] >= 15)
            & (trades["adv20"] >= 50_000_000)
            & (trades["ret60_pre"] > -0.20)
            & (trades["vol20_pre"] <= 0.04),
        ),
    ]
    rows = []
    for sleeve, sleeve_df in trades.groupby("sleeve", sort=True):
        base_pnl = float(sleeve_df["pnl"].sum())
        base_trades = int(len(sleeve_df))
        for name, mask in filters:
            kept = sleeve_df[mask.reindex(sleeve_df.index).fillna(False)]
            rows.append(
                {
                    "sleeve": sleeve,
                    "filter": name,
                    "trades": int(len(kept)),
                    "trades_removed": base_trades - int(len(kept)),
                    "pnl": float(kept["pnl"].sum()),
                    "pnl_delta_vs_all": float(kept["pnl"].sum()) - base_pnl,
                    "avg_pnl": float(kept["pnl"].mean()) if len(kept) else np.nan,
                    "win_rate": float((kept["pnl"] > 0).mean()) if len(kept) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    trades = pd.read_csv(TRADES, parse_dates=["date", "planned_exit_date", "exit_date"])
    trades = trades[trades["portfolio"].eq("B_pit_full_no_intraday_nowarmup_cap40")].copy()

    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily_cols = [
        "date",
        "ticker",
        "prev_dayret",
        "gap",
        "ret20_pre",
        "ret60_pre",
        "vol20_pre",
        "spy_prev_dayret",
        "volume_0930",
    ]
    trades = trades.merge(daily[daily_cols], on=["date", "ticker"], how="left")

    pit = pd.read_parquet(
        PIT_FILTER,
        columns=[
            "date",
            "ticker",
            "prior_close",
            "adv20",
            "adv20_obs",
            "liquidity_metric_source",
            "reason_excluded",
            "eligible_final",
        ],
    )
    pit["date"] = pd.to_datetime(pit["date"])
    pit = pit.drop_duplicates(["date", "ticker"])
    trades = trades.merge(pit, on=["date", "ticker"], how="left")

    trades["price_bucket"] = bucket(
        trades["prior_close"],
        [0, 5, 10, 15, 25, 50, 100, np.inf],
        ["<=5", "5-10", "10-15", "15-25", "25-50", "50-100", ">100"],
    )
    trades["adv_bucket"] = bucket(
        trades["adv20"],
        [0, 10_000_000, 25_000_000, 50_000_000, 100_000_000, 250_000_000, np.inf],
        ["<=10m", "10-25m", "25-50m", "50-100m", "100-250m", ">250m"],
    )
    trades["ret60_bucket"] = bucket(
        trades["ret60_pre"],
        [-np.inf, -0.50, -0.30, -0.20, -0.10, 0.0, 0.20, np.inf],
        ["<=-50%", "-50:-30%", "-30:-20%", "-20:-10%", "-10:0%", "0:20%", ">20%"],
    )
    trades["vol20_bucket"] = bucket(
        trades["vol20_pre"],
        [-np.inf, 0.02, 0.04, 0.06, 0.08, 0.12, np.inf],
        ["<=2%", "2-4%", "4-6%", "6-8%", "8-12%", ">12%"],
    )
    trades["prev_day_bucket"] = bucket(
        trades["prev_dayret"],
        [-np.inf, -0.20, -0.10, -0.06, -0.04, -0.02, 0.0, np.inf],
        ["<=-20%", "-20:-10%", "-10:-6%", "-6:-4%", "-4:-2%", "-2:0%", ">0%"],
    )

    trades.to_csv(f"{OUT_PREFIX}_JOINED_TRADES.csv", index=False)
    summaries = []
    for col in [
        "price_bucket",
        "adv_bucket",
        "ret60_bucket",
        "vol20_bucket",
        "prev_day_bucket",
        "liquidity_metric_source",
    ]:
        out = summarize(trades, ["sleeve", col])
        out.insert(1, "bucket_type", col)
        out = out.rename(columns={col: "bucket"})
        summaries.append(out)
    bucket_summary = pd.concat(summaries, ignore_index=True)
    bucket_summary.to_csv(f"{OUT_PREFIX}_BUCKETS.csv", index=False)

    by_ticker = (
        trades.groupby(["sleeve", "ticker"], as_index=False)
        .agg(
            trades=("pnl", "size"),
            days=("date", "nunique"),
            pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            avg_prior_close=("prior_close", "mean"),
            avg_adv20=("adv20", "mean"),
            avg_vol20=("vol20_pre", "mean"),
            avg_ret60=("ret60_pre", "mean"),
        )
        .sort_values(["sleeve", "pnl"])
    )
    by_ticker.to_csv(f"{OUT_PREFIX}_BY_TICKER.csv", index=False)

    diagnostic = diagnostic_filters(trades)
    diagnostic.to_csv(f"{OUT_PREFIX}_DIAGNOSTIC_FILTERS.csv", index=False)

    overview = (
        trades.groupby("sleeve", as_index=False)
        .agg(
            trades=("pnl", "size"),
            tickers=("ticker", "nunique"),
            pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            win_rate=("pnl", lambda s: float((s > 0).mean())),
            avg_prior_close=("prior_close", "mean"),
            avg_adv20=("adv20", "mean"),
            avg_vol20=("vol20_pre", "mean"),
            avg_ret60=("ret60_pre", "mean"),
        )
        .sort_values("sleeve")
    )
    overview.to_csv(f"{OUT_PREFIX}_OVERVIEW.csv", index=False)

    print("OVERVIEW")
    print(overview.to_string(index=False))
    print("DIAGNOSTIC_FILTERS")
    print(diagnostic.to_string(index=False))
    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
