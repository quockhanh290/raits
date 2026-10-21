from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd

import stocks_pit_full_quality_universe_gate_nowarmup as qgate


OUT_PREFIX = "STOCKS_PIT_FULL_MARKET_CAP_UNIVERSE_NOWARMUP_2026-09-14"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
SIGNAL_QA_OUT = Path(f"{OUT_PREFIX}_SIGNAL_QA.csv")
MEMBERSHIP_QA_OUT = Path(f"{OUT_PREFIX}_MEMBERSHIP_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)
TOP_NS = [62, 100, 200, 500]


def load_market_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker_query"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps


def top_membership(caps: pd.DataFrame, top_n: int) -> pd.DataFrame:
    x = caps[caps["rank_market_cap"].le(top_n)].copy()
    grouped = (
        x.groupby("date", sort=True)["ticker_query"]
        .apply(lambda s: set(s.astype(str)))
        .rename("ticker_set")
        .reset_index()
    )
    return grouped


def membership_mask(daily: pd.DataFrame, membership: pd.DataFrame) -> pd.Series:
    dates = pd.DataFrame({"date": sorted(daily["date"].drop_duplicates())})
    assigned = pd.merge_asof(dates, membership.sort_values("date"), on="date", direction="backward")
    date_to_set = dict(zip(assigned["date"], assigned["ticker_set"]))
    sets = daily["date"].map(date_to_set)
    tickers = daily["ticker"].astype(str).str.upper()
    mask = [ticker in s if isinstance(s, set) else False for ticker, s in zip(tickers, sets)]
    return pd.Series(mask, index=daily.index)


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
    caps = load_market_caps()

    summaries = []
    years = []
    signal_qa_rows = []
    membership_qa_rows = []
    manifest = {
        "out_prefix": OUT_PREFIX,
        "market_cap_csv": str(MARKET_CAP_CSV).replace("\\", "/"),
        "source": "Polygon ticker details market_cap, fetched at quarterly PIT eligible snapshots.",
        "top_ns": TOP_NS,
        "variants": [],
    }

    for top_n in TOP_NS:
        variant = f"market_cap_top{top_n}_quarterly"
        membership = top_membership(caps, top_n)
        mask = membership_mask(daily, membership)
        mask &= daily["eligible_final"].fillna(True) if "eligible_final" in daily.columns else True
        selected = daily.loc[mask, ["date", "ticker"]].copy()
        broad = qgate.build_broad_trades(daily, mask)
        local = qgate.build_local_trades(daily, mask)
        yday = qgate.build_yday_trades(daily, mask)
        signals = qgate.load_signals(broad, local, yday, daily_px, intraday_px)
        gated_signals, gate_qa, _, _ = qgate.base.pit_gate.apply_pit_gate(signals, gate)
        name = f"B_pit_full_{variant}_nowarmup_cap40"
        summary, eq, _ = qgate.base.poly.simulate(name, cfg, gated_signals, daily_px)
        summary["variant"] = variant
        summaries.append(summary)
        years.extend(yearly_metrics(variant, eq))
        signal_qa = {
            "variant": variant,
            "top_n": top_n,
            "selected_rows": int(mask.sum()),
            "selected_tickers": int(selected["ticker"].nunique()),
            "median_names_per_day": float(selected.groupby("date")["ticker"].nunique().median()) if not selected.empty else np.nan,
            "snapshot_count": int(membership["date"].nunique()),
            "broad_rows": int(len(broad)),
            "local_rows": int(len(local)),
            "yday_rows_all_modes": int(len(yday)),
            "yday_rows_rolling3": int((yday["wfo_mode"].eq("rolling3")).sum()) if "wfo_mode" in yday else 0,
            "gate_total": int(gate_qa.get("total", 0)) if isinstance(gate_qa, dict) else np.nan,
            "gate_pass": int(gate_qa.get("pass", 0)) if isinstance(gate_qa, dict) else np.nan,
        }
        signal_qa_rows.append(signal_qa)
        membership_qa_rows.extend(
            {
                "variant": variant,
                "snapshot_date": row.date.strftime("%Y-%m-%d"),
                "members": len(row.ticker_set),
            }
            for row in membership.itertuples(index=False)
        )
        manifest["variants"].append(signal_qa)
        print("VARIANT", variant, summary, signal_qa, flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(years).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(signal_qa_rows).to_csv(SIGNAL_QA_OUT, index=False)
    pd.DataFrame(membership_qa_rows).to_csv(MEMBERSHIP_QA_OUT, index=False)
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, SIGNAL_QA_OUT, MEMBERSHIP_QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
