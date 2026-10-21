from __future__ import annotations

from pathlib import Path

import calendar
import json

import pandas as pd


START = pd.Timestamp("2025-01-02")
END = pd.Timestamp("2026-09-16")
PIT_FILTER = Path(
    "raits/data/cache/stocks_survivorship/polygon_universe_bulk/"
    "daily_20250102_20260916_clean_oos/"
    "liquidity_filter_daily_20250102_20260916_clean_oos_px5_adv10m_unadjusted/"
    "filtered_daily_universe.parquet"
)
CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2025_2026_clean_oos.csv")
OUT_DIR = Path("raits/data/cache/polygon_5min_pit_full_2025_2026_clean_oos")
OUT_PLAN = Path("STOCKS_PIT_FULL_OOS_5MIN_FETCH_CHUNKS_2026-09-17.csv")
OUT_SYMBOLS = Path("STOCKS_PIT_FULL_OOS_5MIN_FETCH_SYMBOLS_2026-09-17.csv")
OUT_MANIFEST = Path("STOCKS_PIT_FULL_OOS_5MIN_FETCH_MANIFEST_2026-09-17.json")


def month_end(date: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(date.year, date.month, calendar.monthrange(date.year, date.month)[1])


def main() -> None:
    daily = pd.read_parquet(PIT_FILTER, columns=["date", "ticker", "eligible_final"])
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    daily = daily[daily["eligible_final"].fillna(False) & daily["date"].between(START, END)].copy()
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})

    caps = pd.read_csv(CAPS, low_memory=False)
    caps["snapshot_date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps["rank"] = caps.groupby("snapshot_date")["market_cap"].rank(method="first", ascending=False)
    top = caps[caps["rank"].le(500)][["snapshot_date", "ticker"]].copy()

    assigned = pd.merge_asof(
        dates.sort_values("date"),
        top[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date"),
        left_on="date", right_on="snapshot_date", direction="backward",
    )
    membership = assigned.merge(top, on="snapshot_date", how="inner")
    membership["ym"] = membership["date"].dt.strftime("%Y-%m")
    active = membership.groupby(["ticker", "ym"], as_index=False).agg(
        first_member_date=("date", "min"), last_member_date=("date", "max"), eligible_days_in_chunk=("date", "nunique")
    )
    rows = []
    for row in active.itertuples(index=False):
        start = pd.Timestamp(f"{row.ym}-01")
        end = month_end(start)
        rows.append({
            "security_id": f"OOS_TICKER_{row.ticker}", "symbol": row.ticker, "api_ticker": row.ticker,
            "start": max(start, START).date(), "end": min(end, END).date(),
            "eligible_days_in_chunk": int(row.eligible_days_in_chunk),
            "path": str(OUT_DIR / row.ticker / f"{row.ticker}_5m_{row.ym}.parquet").replace("\\", "/"),
        })
    for start in pd.date_range(START.replace(day=1), END.replace(day=1), freq="MS"):
        rows.append({
            "security_id": "BENCHMARK_SPY", "symbol": "SPY", "api_ticker": "SPY",
            "start": max(start, START).date(), "end": min(month_end(start), END).date(),
            "eligible_days_in_chunk": 0,
            "path": str(OUT_DIR / "SPY" / f"SPY_5m_{start.strftime('%Y-%m')}.parquet").replace("\\", "/"),
        })
    plan = pd.DataFrame(rows).drop_duplicates(["symbol", "start", "end"]).sort_values(["symbol", "start"])
    symbols = plan.groupby("symbol", as_index=False).agg(
        chunks=("start", "size"), first_date=("start", "min"), last_date=("end", "max"), membership_days=("eligible_days_in_chunk", "sum")
    )
    plan.to_csv(OUT_PLAN, index=False)
    symbols.to_csv(OUT_SYMBOLS, index=False)
    manifest = {
        "purpose": "Clean OOS PIT top500 plus SPY 5-minute fetch plan",
        "frozen_spec": "STOCKS_PIT_FULL_LEAD_OOS_FROZEN_SPEC_2026-09-17.json",
        "pit_filter": str(PIT_FILTER).replace("\\", "/"), "market_caps": str(CAPS).replace("\\", "/"),
        "output_dir": str(OUT_DIR).replace("\\", "/"), "start": str(START.date()), "end": str(END.date()),
        "symbols": int(plan["symbol"].nunique()), "chunks": int(len(plan)), "opened_2025_2026_oos": True,
        "outputs": [str(OUT_PLAN), str(OUT_SYMBOLS)],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
