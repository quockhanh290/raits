from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_quality_universe_gate_nowarmup as qgate
import stocks_pit_full_restricted62_rank_displacement_nowarmup as rank_audit


OUT_PREFIX = "STOCKS_PIT_FULL_PROFILE62_SELECTION_AUDIT_NOWARMUP_2026-09-14"
SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
DETAIL_OUT = Path(f"{OUT_PREFIX}_DETAIL.csv")
REPLACEMENT_OUT = Path(f"{OUT_PREFIX}_REPLACEMENTS.csv")

RESTRICTED_BROAD = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_BROAD_TRADES.csv")
RESTRICTED_LOCAL = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_LOCAL_TRADES.csv")
RESTRICTED_YDAY = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_YDAY_TRADES.csv")

PROFILE_TRADES = Path("STOCKS_PIT_FULL_QUALITY_UNIVERSE_GATE_NOWARMUP_2026-09-13_SUMMARY.csv")


def selected_from_engine(variant: str) -> pd.DataFrame:
    # The quality gate script does not persist per-variant engine trades, so rebuild only selected
    # candidate files and use candidate-level overlap/rank. P&L replacement attribution is local/yday
    # candidate-level where available.
    raise NotImplementedError


def profile_masked_candidates(variant: str = "profile62_score_top100") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series]:
    daily = pd.read_pickle(qgate.base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = qgate.add_quality(daily)
    params = qgate.profile_params(daily)
    mask = qgate.quality_mask(daily, qgate.VARIANTS[variant], params)
    broad = qgate.build_broad_trades(daily, mask)
    local = qgate.build_local_trades(daily, mask)
    yday = qgate.build_yday_trades(daily, mask)
    return broad, local, yday, mask


def load_restricted(path: Path, sleeve: str, date_col: str = "date") -> pd.DataFrame:
    out = pd.read_csv(path, parse_dates=[date_col])
    if date_col != "date":
        out = out.rename(columns={date_col: "date"})
    if "symbol" in out.columns:
        out = out.rename(columns={"symbol": "ticker"})
    if "pnl" not in out.columns:
        out["pnl"] = np.nan
    out["sleeve"] = sleeve
    return out


def broad_profile_rank(daily: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    c = rank_audit.broad_candidates(daily)
    allowed = daily.loc[mask, ["date", "ticker"]].drop_duplicates().assign(profile_allowed=True)
    c = c.merge(allowed, on=["date", "ticker"], how="left")
    c = c[c["profile_allowed"].fillna(False)].copy()
    c = c.sort_values(["date", "ret5", "ticker"])
    c["profile_rank"] = c.groupby("date").cumcount() + 1
    c["profile_count"] = c.groupby("date")["ticker"].transform("size")
    return c


def local_profile_rank(daily: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    c = rank_audit.local_candidates(daily)
    allowed = daily.loc[mask, ["date", "ticker"]].drop_duplicates().assign(profile_allowed=True)
    c = c.merge(allowed, on=["date", "ticker"], how="left")
    c = c[c["profile_allowed"].fillna(False)].copy()
    c = c.sort_values(["date", "ret5_pre_clean", "ticker"])
    c["profile_rank"] = c.groupby("date").cumcount() + 1
    c["profile_count"] = c.groupby("date")["ticker"].transform("size")
    return c


def summarize_rank(detail: pd.DataFrame) -> pd.DataFrame:
    bins = [0, 10, 20, 50, 100, 200, 500, np.inf]
    labels = ["1-10", "11-20", "21-50", "51-100", "101-200", "201-500", ">500"]
    x = detail.copy()
    x["rank_bucket"] = pd.cut(x["profile_rank"], bins=bins, labels=labels, include_lowest=True)
    rows = []
    for keys, group in x.groupby(["period", "sleeve", "rank_bucket"], observed=True):
        rows.append(
            {
                "period": keys[0],
                "sleeve": keys[1],
                "rank_bucket": str(keys[2]),
                "restricted62_rows": int(len(group)),
                "restricted62_pnl": float(group["restricted_pnl"].sum()) if group["restricted_pnl"].notna().any() else np.nan,
                "profile_allowed_rows": int(group["profile_rank"].notna().sum()),
                "selected_by_profile_candidate": int(group["selected_by_profile"].sum()),
                "selected_by_profile_rate": float(group["selected_by_profile"].mean()) if len(group) else np.nan,
                "median_profile_rank": float(group["profile_rank"].median()) if group["profile_rank"].notna().any() else np.nan,
                "p90_profile_rank": float(group["profile_rank"].quantile(0.90)) if group["profile_rank"].notna().any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def detail_for(restricted: pd.DataFrame, selected: pd.DataFrame, ranks: pd.DataFrame, sleeve: str, score_col: str) -> pd.DataFrame:
    r = restricted[["date", "ticker", "pnl"]].copy().rename(columns={"pnl": "restricted_pnl"})
    if "symbol" in selected.columns:
        selected = selected.rename(columns={"symbol": "ticker", "entry_date": "date"})
    s = selected[["date", "ticker"]].drop_duplicates().assign(selected_by_profile=True)
    c = ranks[["date", "ticker", "profile_rank", "profile_count"]].copy()
    out = r.merge(c, on=["date", "ticker"], how="left").merge(s, on=["date", "ticker"], how="left")
    out["selected_by_profile"] = out["selected_by_profile"].fillna(False).astype(bool)
    out["sleeve"] = sleeve
    out["period"] = "2018_2024"
    recent = out[out["date"].dt.year.isin([2023, 2024])].assign(period="2023_2024")
    return pd.concat([out, recent], ignore_index=True)


def yday_detail(restricted: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    r = restricted[restricted.get("wfo_mode", "rolling3").eq("rolling3") if "wfo_mode" in restricted else slice(None)].copy()
    s = selected[selected.get("wfo_mode", "rolling3").eq("rolling3") if "wfo_mode" in selected else slice(None)].copy()
    out = r[["date", "ticker", "pnl"]].rename(columns={"pnl": "restricted_pnl"}).merge(
        s[["date", "ticker"]].drop_duplicates().assign(selected_by_profile=True),
        on=["date", "ticker"],
        how="left",
    )
    out["selected_by_profile"] = out["selected_by_profile"].fillna(False).astype(bool)
    out["profile_rank"] = np.nan
    out["profile_count"] = np.nan
    out["sleeve"] = "yday_ex6_actual"
    out["period"] = "2018_2024"
    recent = out[out["date"].dt.year.isin([2023, 2024])].assign(period="2023_2024")
    return pd.concat([out, recent], ignore_index=True)


def replacement_summary(profile_selected: pd.DataFrame, restricted: pd.DataFrame, sleeve: str) -> pd.DataFrame:
    s = profile_selected.copy()
    if "symbol" in s.columns:
        s = s.rename(columns={"symbol": "ticker", "entry_date": "date"})
    if "pnl" not in s.columns:
        s["pnl"] = np.nan
    if "wfo_mode" in s.columns:
        s = s[s["wfo_mode"].eq("rolling3")].copy()
    if "wfo_mode" in restricted.columns:
        restricted = restricted[restricted["wfo_mode"].eq("rolling3")].copy()
    rkeys = restricted[["date", "ticker"]].drop_duplicates().assign(in_restricted_pick=True)
    s = s.merge(rkeys, on=["date", "ticker"], how="left")
    s["in_restricted_pick"] = s["in_restricted_pick"].fillna(False).astype(bool)
    s["year"] = s["date"].dt.year
    rows = []
    for period, group in [("2018_2024", s), ("2023_2024", s[s["year"].isin([2023, 2024])])]:
        for bucket, part in [
            ("profile_overlap_with_restricted62", group[group["in_restricted_pick"]]),
            ("profile_replacements", group[~group["in_restricted_pick"]]),
        ]:
            rows.append(
                {
                    "period": period,
                    "sleeve": sleeve,
                    "bucket": bucket,
                    "rows": int(len(part)),
                    "pnl": float(part["pnl"].sum()) if part["pnl"].notna().any() else np.nan,
                    "avg_pnl": float(part["pnl"].mean()) if part["pnl"].notna().any() else np.nan,
                    "win_rate": float((part["pnl"] > 0).mean()) if part["pnl"].notna().any() else np.nan,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    daily = pd.read_pickle(qgate.base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily = qgate.add_quality(daily)
    params = qgate.profile_params(daily)
    mask = qgate.quality_mask(daily, qgate.VARIANTS["profile62_score_top100"], params)

    broad, local, yday = qgate.build_broad_trades(daily, mask), qgate.build_local_trades(daily, mask), qgate.build_yday_trades(daily, mask)
    b_rank = broad_profile_rank(daily, mask)
    l_rank = local_profile_rank(daily, mask)

    rb = load_restricted(RESTRICTED_BROAD, "broad_adv10_g2_dd85", "entry_date")
    rl = load_restricted(RESTRICTED_LOCAL, "local_xs_full_s10")
    ry = load_restricted(RESTRICTED_YDAY, "yday_ex6_actual")

    detail = pd.concat(
        [
            detail_for(rb, broad, b_rank, "broad_adv10_g2_dd85", "ret5"),
            detail_for(rl, local, l_rank, "local_xs_full_s10", "ret5_pre_clean"),
            yday_detail(ry, yday),
        ],
        ignore_index=True,
        sort=False,
    )
    detail.to_csv(DETAIL_OUT, index=False)

    summary = summarize_rank(detail[detail["sleeve"].ne("yday_ex6_actual")])
    ysum = (
        detail[detail["sleeve"].eq("yday_ex6_actual")]
        .groupby(["period", "sleeve"], as_index=False)
        .agg(
            restricted62_rows=("ticker", "size"),
            restricted62_pnl=("restricted_pnl", "sum"),
            selected_by_profile_candidate=("selected_by_profile", "sum"),
            selected_by_profile_rate=("selected_by_profile", "mean"),
        )
    )
    ysum["rank_bucket"] = "wfo_overlap_only"
    summary = pd.concat([summary, ysum], ignore_index=True, sort=False)
    summary.to_csv(SUMMARY_OUT, index=False)

    replacements = pd.concat(
        [
            replacement_summary(broad, rb, "broad_adv10_g2_dd85"),
            replacement_summary(local, rl, "local_xs_full_s10"),
            replacement_summary(yday, ry, "yday_ex6_actual"),
        ],
        ignore_index=True,
    )
    replacements.to_csv(REPLACEMENT_OUT, index=False)

    print("SUMMARY")
    print(summary.to_string(index=False))
    print("REPLACEMENTS")
    print(replacements.to_string(index=False))
    print("WROTE", SUMMARY_OUT, DETAIL_OUT, REPLACEMENT_OUT, flush=True)


if __name__ == "__main__":
    main()
