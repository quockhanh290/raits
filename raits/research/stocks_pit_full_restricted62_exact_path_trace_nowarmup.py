from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_quality_universe_gate_nowarmup as qgate
import stocks_pit_full_restricted62_rank_displacement_nowarmup as rank_audit


OUT_PREFIX = "STOCKS_PIT_FULL_RESTRICTED62_EXACT_PATH_TRACE_NOWARMUP_2026-09-14"
TRACE_OUT = Path(f"{OUT_PREFIX}_DETAIL.csv")
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
TOP_MISSING_OUT = Path(f"{OUT_PREFIX}_TOP_MISSING_2023_2024.csv")

RESTRICTED_TRADES = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_TRADES.csv")
RESTRICTED_BROAD = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_BROAD_TRADES.csv")
RESTRICTED_LOCAL = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_LOCAL_TRADES.csv")
RESTRICTED_YDAY = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_YDAY_TRADES.csv")

FULL_BROAD = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_BROAD_TRADES.csv")
FULL_LOCAL = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_LOCAL_TRADES.csv")
FULL_YDAY = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_YDAY_TRADES.csv")


def load(path: Path, date_col: str = "date") -> pd.DataFrame:
    out = pd.read_csv(path, parse_dates=[date_col])
    if date_col != "date":
        out = out.rename(columns={date_col: "date"})
    if "symbol" in out.columns:
        out = out.rename(columns={"symbol": "ticker"})
    return out


def poly62_tickers() -> set[str]:
    trades = pd.read_csv("STOCKS_POLYGON62_PIT_REPLAY_2016WARMUP_2018_2024_TRADES.csv", usecols=["portfolio", "ticker"])
    return set(trades[trades["portfolio"].eq("B_polygon62_no_intraday_cap40_PIT")]["ticker"].astype(str).unique())


def add_rank_prefix(frame: pd.DataFrame, prefix: str, score_col: str | None = None) -> pd.DataFrame:
    cols = ["date", "ticker", "candidate_rank", "candidate_count"]
    if score_col and score_col in frame.columns:
        cols.append(score_col)
    out = frame[cols].copy()
    rename = {
        "candidate_rank": f"{prefix}_rank",
        "candidate_count": f"{prefix}_candidate_count",
    }
    if score_col and score_col in frame.columns:
        rename[score_col] = f"{prefix}_{score_col}"
    return out.rename(columns=rename)


def profile_ranks(daily: pd.DataFrame, mask: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame]:
    allowed = daily.loc[mask, ["date", "ticker"]].drop_duplicates().assign(profile_allowed=True)

    b = rank_audit.broad_candidates(daily).merge(allowed, on=["date", "ticker"], how="left")
    b = b[b["profile_allowed"].fillna(False)].sort_values(["date", "ret5", "ticker"]).copy()
    b["candidate_rank"] = b.groupby("date").cumcount() + 1
    b["candidate_count"] = b.groupby("date")["ticker"].transform("size")

    l = rank_audit.local_candidates(daily).merge(allowed, on=["date", "ticker"], how="left")
    l = l[l["profile_allowed"].fillna(False)].sort_values(["date", "ret5_pre_clean", "ticker"]).copy()
    l["candidate_rank"] = l.groupby("date").cumcount() + 1
    l["candidate_count"] = l.groupby("date")["ticker"].transform("size")
    return b, l


def yday_selected_frame(path: Path, prefix: str) -> pd.DataFrame:
    y = load(path)
    if "wfo_mode" in y.columns:
        y = y[y["wfo_mode"].eq("rolling3")].copy()
    keep = ["date", "ticker"]
    extra = [c for c in ["rule", "entry_time", "score", "gross_ret", "pnl"] if c in y.columns]
    y = y[keep + extra].drop_duplicates(["date", "ticker"])
    return y.rename(columns={c: f"{prefix}_{c}" for c in extra}).assign(**{f"{prefix}_selected": True})


def main() -> None:
    daily = pd.read_pickle(qgate.base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = qgate.add_quality(daily)
    daily62 = daily[daily["ticker"].astype(str).isin(poly62_tickers())].copy()
    params = qgate.profile_params(daily)
    profile_mask = qgate.quality_mask(daily, qgate.VARIANTS["profile62_score_top100"], params)

    restricted_engine = pd.read_csv(RESTRICTED_TRADES, parse_dates=["date"])
    restricted_engine = restricted_engine[restricted_engine["portfolio"].eq("B_pit_restricted62_nowarmup_cap40")].copy()

    # Candidate ranks in each universe.
    rb_rank = rank_audit.broad_candidates(daily62)
    rl_rank = rank_audit.local_candidates(daily62)
    fb_rank = rank_audit.broad_candidates(daily)
    fl_rank = rank_audit.local_candidates(daily)
    pb_rank, pl_rank = profile_ranks(daily, profile_mask)

    broad = restricted_engine[restricted_engine["sleeve"].eq("broad_adv10_g2_dd85")].copy()
    broad["selection_rule"] = "broad: ADV20>=10m, ret5>=-50%, rank by lowest prior ret5, slots=20, hold=20; engine then applies active ticker/capacity constraints"
    broad = broad.merge(add_rank_prefix(rb_rank, "restricted", "ret5"), on=["date", "ticker"], how="left")
    broad = broad.merge(add_rank_prefix(fb_rank, "full", "ret5"), on=["date", "ticker"], how="left")
    broad = broad.merge(add_rank_prefix(pb_rank, "profile", "ret5"), on=["date", "ticker"], how="left")

    full_broad_sel = load(FULL_BROAD, "entry_date")[["date", "ticker"]].drop_duplicates().assign(full_selected=True)
    prof_broad_sel = qgate.build_broad_trades(daily, profile_mask)[["entry_date", "symbol"]].rename(columns={"entry_date": "date", "symbol": "ticker"}).drop_duplicates().assign(profile_selected=True)
    broad = broad.merge(full_broad_sel, on=["date", "ticker"], how="left").merge(prof_broad_sel, on=["date", "ticker"], how="left")

    local = restricted_engine[restricted_engine["sleeve"].eq("local_xs_full_s10")].copy()
    local["selection_rule"] = "local: rank by lowest prior ret5_pre_clean, top10 per day, hold=20"
    local = local.merge(add_rank_prefix(rl_rank, "restricted", "ret5_pre_clean"), on=["date", "ticker"], how="left")
    local = local.merge(add_rank_prefix(fl_rank, "full", "ret5_pre_clean"), on=["date", "ticker"], how="left")
    local = local.merge(add_rank_prefix(pl_rank, "profile", "ret5_pre_clean"), on=["date", "ticker"], how="left")

    full_local_sel = load(FULL_LOCAL)[["date", "ticker"]].drop_duplicates().assign(full_selected=True)
    prof_local_sel = qgate.build_local_trades(daily, profile_mask)[["date", "ticker"]].drop_duplicates().assign(profile_selected=True)
    local = local.merge(full_local_sel, on=["date", "ticker"], how="left").merge(prof_local_sel, on=["date", "ticker"], how="left")

    yday = restricted_engine[restricted_engine["sleeve"].eq("yday_ex6_actual")].copy()
    restricted_yday_raw = yday_selected_frame(RESTRICTED_YDAY, "restricted")
    full_yday_raw = yday_selected_frame(FULL_YDAY, "full")
    prof_yday_raw = qgate.build_yday_trades(daily, profile_mask)
    prof_yday_raw.to_csv(Path(f"{OUT_PREFIX}_PROFILE_YDAY_CANDIDATES.csv"), index=False)
    prof_yday_raw = yday_selected_frame(Path(f"{OUT_PREFIX}_PROFILE_YDAY_CANDIDATES.csv"), "profile")
    yday["selection_rule"] = "yday rolling3 WFO: chosen rule by train score, then most severe signal, max1/day"
    yday = yday.merge(restricted_yday_raw, on=["date", "ticker"], how="left")
    yday = yday.merge(full_yday_raw, on=["date", "ticker"], how="left")
    yday = yday.merge(prof_yday_raw, on=["date", "ticker"], how="left")

    trace = pd.concat([broad, local, yday], ignore_index=True, sort=False)
    for col in ["full_selected", "profile_selected"]:
        if col in trace.columns:
            trace[col] = trace[col].fillna(False).astype(bool)
    trace["year"] = trace["date"].dt.year
    trace.to_csv(TRACE_OUT, index=False)

    rows = []
    for period, group in [("2018_2024", trace), ("2023_2024", trace[trace["year"].isin([2023, 2024])])]:
        for sleeve, sg in group.groupby("sleeve"):
            rows.append(
                {
                    "period": period,
                    "sleeve": sleeve,
                    "restricted_trades": int(len(sg)),
                    "restricted_pnl": float(sg["pnl"].sum()),
                    "full_selected_overlap": int(sg.get("full_selected", pd.Series(False, index=sg.index)).sum()),
                    "profile_selected_overlap": int(sg.get("profile_selected", pd.Series(False, index=sg.index)).sum()),
                    "median_restricted_rank": float(sg["restricted_rank"].median()) if "restricted_rank" in sg and sg["restricted_rank"].notna().any() else np.nan,
                    "median_full_rank": float(sg["full_rank"].median()) if "full_rank" in sg and sg["full_rank"].notna().any() else np.nan,
                    "median_profile_rank": float(sg["profile_rank"].median()) if "profile_rank" in sg and sg["profile_rank"].notna().any() else np.nan,
                }
            )
    summary = pd.DataFrame(rows)
    summary.to_csv(SUMMARY_OUT, index=False)

    top_missing = (
        trace[
            trace["year"].isin([2023, 2024])
            & (~trace.get("profile_selected", pd.Series(False, index=trace.index)).astype(bool))
        ]
        .sort_values("pnl", ascending=False)
        .head(80)
    )
    top_missing.to_csv(TOP_MISSING_OUT, index=False)

    print("SUMMARY")
    print(summary.to_string(index=False))
    print("TOP_MISSING")
    cols = [c for c in ["date", "ticker", "sleeve", "pnl", "selection_rule", "restricted_rule", "full_rule", "profile_rule", "restricted_rank", "full_rank", "profile_rank", "full_selected", "profile_selected"] if c in top_missing.columns]
    print(top_missing[cols].head(30).to_string(index=False))
    print("WROTE", TRACE_OUT, SUMMARY_OUT, TOP_MISSING_OUT, flush=True)


if __name__ == "__main__":
    main()
