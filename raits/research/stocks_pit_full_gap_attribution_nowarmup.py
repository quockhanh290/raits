from __future__ import annotations

from pathlib import Path

import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_GAP_ATTRIBUTION_NOWARMUP_2026-09-13"
POLY_TRADES = Path("STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024_TRADES.csv")
PIT_TRADES = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_TRADES.csv")
QUALITY_JOINED = Path("STOCKS_PIT_FULL_QUALITY_AUDIT_NOWARMUP_2026-09-13_JOINED_TRADES.csv")
VARIANT_YEARLY = Path("STOCKS_PIT_FULL_YDAY_QUALITY_VARIANTS_NOWARMUP_2026-09-13_YEARLY.csv")


def agg(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    return (
        df.groupby(keys, dropna=False, observed=True)
        .agg(
            trades=("pnl", "size"),
            pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            win_rate=("pnl", lambda s: float((s > 0).mean())),
            gross_in=("entry_notional", "sum"),
        )
        .reset_index()
    )


def main() -> None:
    poly = pd.read_csv(POLY_TRADES, parse_dates=["date", "exit_date"])
    pit = pd.read_csv(PIT_TRADES, parse_dates=["date", "exit_date"])

    poly_b = poly[poly["portfolio"].str.startswith("B_polygon62_no_intraday")].copy()
    pit_b = pit[pit["portfolio"].str.startswith("B_pit_full_no_intraday")].copy()
    poly_b["source"] = "polygon62_warmup"
    pit_b["source"] = "broad_pit_nowarmup"
    poly_b["year"] = poly_b["date"].dt.year
    pit_b["year"] = pit_b["date"].dt.year

    poly_tickers = set(poly_b["ticker"].unique())
    pit_b["is_poly62_ticker"] = pit_b["ticker"].isin(poly_tickers)

    sleeve = pd.concat(
        [
            agg(poly_b, ["source", "sleeve"]),
            agg(pit_b, ["source", "sleeve"]),
            agg(pit_b, ["source", "sleeve", "is_poly62_ticker"]),
        ],
        ignore_index=True,
    )
    sleeve.to_csv(f"{OUT_PREFIX}_SLEEVE_COMPARE.csv", index=False)

    yearly = pd.concat(
        [
            agg(poly_b, ["source", "year", "sleeve"]),
            agg(pit_b, ["source", "year", "sleeve"]),
        ],
        ignore_index=True,
    )
    yearly.to_csv(f"{OUT_PREFIX}_YEARLY_SLEEVE_COMPARE.csv", index=False)

    start_split = poly_b[poly_b["year"].eq(2018)].copy()
    start_split["entry_period"] = start_split["date"].lt(pd.Timestamp("2018-03-29")).map(
        {True: "2018_pre_0329", False: "2018_0329_on_or_later"}
    )
    agg(start_split, ["entry_period", "sleeve"]).to_csv(f"{OUT_PREFIX}_POLY62_2018_START_SPLIT.csv", index=False)

    from_0329 = agg(poly_b[poly_b["date"].ge("2018-03-29")], ["source", "sleeve"])
    from_0329["source"] = "polygon62_warmup_from_2018_03_29"
    from_0329.to_csv(f"{OUT_PREFIX}_POLY62_FROM_20180329.csv", index=False)

    q = pd.read_csv(QUALITY_JOINED, parse_dates=["date"], low_memory=False)
    yday = q[(q["portfolio"].str.startswith("B_")) & (q["sleeve"].eq("yday_ex6_actual"))].copy()
    yday["year"] = yday["date"].dt.year
    yday["price_bucket"] = pd.cut(
        yday["prior_close"],
        [-1, 5, 10, 15, 25, 50, 100, 1e12],
        labels=["<5", "5-10", "10-15", "15-25", "25-50", "50-100", ">100"],
    )
    yday["vol_bucket"] = pd.cut(
        yday["vol20_pre"],
        [-1, 0.04, 0.06, 0.08, 0.12, 1e12],
        labels=["<=4%", "4-6%", "6-8%", "8-12%", ">12%"],
    )
    agg(yday, ["year", "price_bucket"]).to_csv(f"{OUT_PREFIX}_YDAY_PRICE_BUCKETS.csv", index=False)
    agg(yday, ["year", "vol_bucket"]).to_csv(f"{OUT_PREFIX}_YDAY_VOL_BUCKETS.csv", index=False)

    variants = pd.read_csv(VARIANT_YEARLY)
    variants = variants[variants["portfolio"].str.startswith("B_")].copy()
    variants.pivot_table(index="year", columns="variant", values="pnl", aggfunc="sum").reset_index().to_csv(
        f"{OUT_PREFIX}_YDAY_VARIANT_YEARLY_PNL.csv", index=False
    )

    print("WROTE", OUT_PREFIX)


if __name__ == "__main__":
    main()
