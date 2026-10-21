from __future__ import annotations

from pathlib import Path

import json
import math

import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_SIC_BALANCED_MARKET_CAP_BENCHMARK_2026-09-14"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
MEMBERSHIP_QA_OUT = Path(f"{OUT_PREFIX}_MEMBERSHIP_QA.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

VARIANTS = [
    {"variant": "mcap_pool500_target62_siccap4", "candidate_pool": 500, "target_n": 62, "sic_cap": 4},
    {"variant": "mcap_pool500_target62_siccap6", "candidate_pool": 500, "target_n": 62, "sic_cap": 6},
    {"variant": "mcap_pool500_target100_siccap6", "candidate_pool": 500, "target_n": 100, "sic_cap": 6},
    {"variant": "mcap_pool500_target100_siccap8", "candidate_pool": 500, "target_n": 100, "sic_cap": 8},
]


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = equity / peak - 1.0
    return float(dd.min()), float(dd_pct.min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    if std <= 0:
        return float("nan")
    return float(pnl.mean() / std * math.sqrt(252))


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_daily_returns() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[(daily["date"] >= START) & (daily["date"] <= END)].copy()
    daily = daily.dropna(subset=["ticker", "prev_close_1555", "close_1555"])
    daily = daily[(daily["prev_close_1555"] > 0) & (daily["close_1555"] > 0)].copy()
    daily["ret_close_to_close"] = daily["close_1555"] / daily["prev_close_1555"] - 1.0
    return daily[["date", "ticker", "ret_close_to_close"]].copy()


def load_market_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps["sic_bucket"] = caps["sic_description"].fillna("UNKNOWN").astype(str).str.upper()
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps


def build_membership(caps: pd.DataFrame, spec: dict[str, object]) -> pd.DataFrame:
    rows = []
    for date, group in caps.groupby("date", sort=True):
        pool = group[group["rank_market_cap"].le(int(spec["candidate_pool"]))].copy()
        selected = []
        counts: dict[str, int] = {}
        for row in pool.itertuples(index=False):
            bucket = str(row.sic_bucket)
            if counts.get(bucket, 0) >= int(spec["sic_cap"]):
                continue
            selected.append((str(row.ticker), bucket, float(row.market_cap), int(row.rank_market_cap)))
            counts[bucket] = counts.get(bucket, 0) + 1
            if len(selected) >= int(spec["target_n"]):
                break
        rows.append(
            {
                "date": date,
                "ticker_set": {x[0] for x in selected},
                "members": len(selected),
                "sic_buckets": len({x[1] for x in selected}),
                "max_bucket_count": max(counts.values()) if counts else 0,
                "unknown_count": counts.get("UNKNOWN", 0),
            }
        )
    return pd.DataFrame(rows)


def apply_membership(daily: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership.sort_values("date"), on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    sets = daily["date"].map(date_to_set)
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(daily["ticker"].astype(str), sets)]
    return daily.loc[mask].copy()


def simulate_equal_weight(variant: str, selected: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    equity = START_CAPITAL
    daily_rows = []
    contrib_rows = []
    for date, group in selected.groupby("date", sort=True):
        group = group.copy()
        weight = 1.0 / len(group)
        group["pnl"] = equity * weight * group["ret_close_to_close"]
        daily_pnl = float(group["pnl"].sum())
        equity += daily_pnl
        daily_rows.append(
            {
                "variant": variant,
                "date": date,
                "daily_pnl": daily_pnl,
                "equity": equity,
                "gross": 1.0,
                "names": int(len(group)),
            }
        )
        contrib_rows.append(group[["date", "ticker", "pnl"]].assign(variant=variant))
    daily = pd.DataFrame(daily_rows)
    contrib = pd.concat(contrib_rows, ignore_index=True)
    dd, dd_pct = max_drawdown(daily["equity"])
    summary = {
        "variant": variant,
        "kind": "daily_rebalanced_equal_weight",
        "pnl": float(daily["daily_pnl"].sum()),
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "days": int(len(daily)),
        "avgNames": float(daily["names"].mean()),
        "medianNames": float(daily["names"].median()),
        "selectedTickers": int(selected["ticker"].nunique()),
    }
    return summary, daily, contrib


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
                "ddDollarSubset": dd,
                "ddPctSubset": dd_pct,
                "sharpe": sharpe(group["daily_pnl"]),
                "days": int(len(group)),
            }
        )
    return rows


def effective_ticker_count(pnl_by_ticker: pd.Series) -> float:
    positive = pnl_by_ticker[pnl_by_ticker > 0]
    weights_source = positive if positive.sum() > 0 else pnl_by_ticker.abs()
    total = float(weights_source.sum())
    if total <= 0:
        return 0.0
    weights = weights_source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker", sort=False)["pnl"].sum().sort_values(ascending=False)
    total = float(contrib["pnl"].sum())
    denom = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
        "topTickerPnl": float(by_ticker.iloc[0]) if not by_ticker.empty else 0.0,
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum())
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denom if denom else float("nan")
    return row


def main() -> None:
    daily = load_daily_returns()
    caps = load_market_caps()
    summaries = []
    yearly = []
    concentration = []
    membership_qa = []
    daily_frames = []
    contrib_frames = []

    for spec in VARIANTS:
        membership = build_membership(caps, spec)
        selected = apply_membership(daily, membership)
        variant = str(spec["variant"])
        summary, daily_out, contrib = simulate_equal_weight(variant, selected)
        summary.update({k: spec[k] for k in ("candidate_pool", "target_n", "sic_cap")})
        summaries.append(summary)
        yearly.extend(yearly_rows(variant, daily_out))
        concentration.append(concentration_row(variant, contrib))
        daily_frames.append(daily_out)
        contrib_frames.append(contrib)
        membership_qa.append(
            {
                "variant": variant,
                "snapshots": int(len(membership)),
                "medianMembersSnapshot": float(membership["members"].median()),
                "medianSicBucketsSnapshot": float(membership["sic_buckets"].median()),
                "maxBucketCountMax": int(membership["max_bucket_count"].max()),
                "unknownCountMax": int(membership["unknown_count"].max()),
                "dailyRows": int(len(selected)),
                "selectedTickers": int(selected["ticker"].nunique()),
                "medianNamesPerDay": float(selected.groupby("date")["ticker"].nunique().median()),
            }
        )
        print("VARIANT", variant, summary, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(membership_qa).to_csv(MEMBERSHIP_QA_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_sic_balanced_market_cap_benchmark.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "sample_period": [START.strftime("%Y-%m-%d"), END.strftime("%Y-%m-%d")],
        "variants": VARIANTS,
        "method": "Quarterly PIT market-cap candidates; select by descending market cap with maximum names per raw Polygon sic_description bucket; 100% gross daily-rebalanced equal weight.",
        "sic_caveat": "Polygon sic_description is a coarse/granular industry label, not official GICS sector.",
        "old_62_usage": "None.",
        "rule_selection": "None. Variant set fixed in VARIANTS before measuring.",
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(MEMBERSHIP_QA_OUT), str(DAILY_OUT), str(CONTRIB_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, MEMBERSHIP_QA_OUT, DAILY_OUT, CONTRIB_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
