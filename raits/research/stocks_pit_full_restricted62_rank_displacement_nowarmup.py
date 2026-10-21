from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_no_intraday_replay_nowarmup as base
import stocks_databento_daily_xs_mtm_dd_overlay as broad_overlay


OUT_PREFIX = "STOCKS_PIT_FULL_RESTRICTED62_RANK_DISPLACEMENT_NOWARMUP_2026-09-13"

RESTRICTED_BROAD = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_BROAD_TRADES.csv")
RESTRICTED_LOCAL = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_LOCAL_TRADES.csv")
RESTRICTED_YDAY = Path("STOCKS_PIT_FULL_RESTRICTED62_NOWARMUP_2026-09-13_YDAY_TRADES.csv")

FULL_BROAD = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_BROAD_TRADES.csv")
FULL_LOCAL = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_LOCAL_TRADES.csv")
FULL_YDAY = Path("STOCKS_PIT_FULL_NO_INTRADAY_NOWARMUP_2018_2024_YDAY_TRADES.csv")

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
DETAIL_OUT = Path(f"{OUT_PREFIX}_DETAIL.csv")
REPLACEMENT_OUT = Path(f"{OUT_PREFIX}_REPLACEMENTS.csv")


def broad_candidates(daily: pd.DataFrame) -> pd.DataFrame:
    cfg = broad_overlay.config()
    panel = daily.rename(
        columns={
            "ticker": "symbol",
            "open_0930": "open",
            "close_1555": "close",
            "volume_0930": "volume",
        }
    )[["symbol", "date", "open", "close", "volume"]].copy()
    panel["dollar"] = panel["close"] * panel["volume"]
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = panel.groupby("symbol", sort=False)
    panel["adv20"] = g["dollar"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    prev_close = g["close"].shift(1)
    panel["ret5"] = prev_close / g["close"].shift(6) - 1.0
    panel[f"exit_date{cfg.hold}"] = g["date"].shift(-(cfg.hold - 1))
    data = panel.dropna(subset=["ret5", "adv20", f"exit_date{cfg.hold}"]).copy()
    data = data[(data["adv20"] >= cfg.adv) & (data["ret5"] >= cfg.min_ret5)]
    data = data[(data["date"] >= base.START) & (data["date"] <= base.END)]
    data = data.sort_values(["date", "ret5", "symbol"]).copy()
    data["candidate_rank"] = data.groupby("date").cumcount() + 1
    data["candidate_count"] = data.groupby("date")["symbol"].transform("size")
    return data[["date", "symbol", "ret5", "adv20", "candidate_rank", "candidate_count"]].rename(columns={"symbol": "ticker"})


def local_candidates(daily: pd.DataFrame) -> pd.DataFrame:
    data = daily[daily["ticker"].ne("SPY")].sort_values(["ticker", "date"]).copy()
    g = data.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    data["ret5_pre_clean"] = prev_close / g["close_1555"].shift(6) - 1.0
    data["exit_close"] = g["close_1555"].shift(-19)
    data["ret"] = data["exit_close"] / data["open_0930"] - 1.0
    data = data.dropna(subset=["ret5_pre_clean", "ret", "open_0930", "exit_close"]).copy()
    data = data[(data["date"] >= base.START) & (data["date"] <= base.END)]
    data = data.sort_values(["date", "ret5_pre_clean", "ticker"]).copy()
    data["candidate_rank"] = data.groupby("date").cumcount() + 1
    data["candidate_count"] = data.groupby("date")["ticker"].transform("size")
    return data[["date", "ticker", "ret5_pre_clean", "candidate_rank", "candidate_count"]]


def load_selected(path: Path, sleeve: str, date_col: str = "date") -> pd.DataFrame:
    out = pd.read_csv(path, parse_dates=[date_col])
    if date_col != "date":
        out = out.rename(columns={date_col: "date"})
    if "symbol" in out.columns:
        out = out.rename(columns={"symbol": "ticker"})
    if "pnl" not in out.columns:
        out["pnl"] = np.nan
    out["sleeve"] = sleeve
    return out


def summarize_displacement(detail: pd.DataFrame) -> pd.DataFrame:
    bins = [0, 10, 20, 50, 100, 200, 500, 1000, np.inf]
    labels = ["1-10", "11-20", "21-50", "51-100", "101-200", "201-500", "501-1000", ">1000"]
    x = detail.copy()
    x["rank_bucket"] = pd.cut(x["candidate_rank"], bins=bins, labels=labels, include_lowest=True)
    x["year"] = x["date"].dt.year
    rows = []
    for keys, group in x.groupby(["period", "sleeve", "rank_bucket"], observed=True):
        rows.append(
            {
                "period": keys[0],
                "sleeve": keys[1],
                "rank_bucket": str(keys[2]),
                "restricted62_trades": int(len(group)),
                "restricted62_pnl": float(group["restricted_pnl"].sum()) if group["restricted_pnl"].notna().any() else np.nan,
                "selected_in_full": int(group["selected_in_full"].sum()),
                "selected_in_full_rate": float(group["selected_in_full"].mean()) if len(group) else np.nan,
                "median_full_rank": float(group["candidate_rank"].median()),
                "p90_full_rank": float(group["candidate_rank"].quantile(0.90)),
            }
        )
    return pd.DataFrame(rows)


def displacement_detail(restricted: pd.DataFrame, full_selected: pd.DataFrame, candidates: pd.DataFrame, sleeve: str, score_col: str) -> pd.DataFrame:
    if score_col not in restricted.columns:
        restricted = restricted.copy()
        restricted[score_col] = np.nan
    r = restricted[["date", "ticker", score_col, "pnl"]].copy()
    r = r.rename(columns={score_col: "restricted_score", "pnl": "restricted_pnl"})
    f = full_selected[["date", "ticker"]].drop_duplicates().assign(selected_in_full=True)
    c = candidates.rename(columns={score_col: "full_score"}) if score_col in candidates.columns else candidates.copy()
    out = r.merge(c, on=["date", "ticker"], how="left").merge(f, on=["date", "ticker"], how="left")
    out["selected_in_full"] = out["selected_in_full"].fillna(False).astype(bool)
    out["sleeve"] = sleeve
    all_period = out.assign(period="2018_2024")
    recent = out[out["date"].dt.year.isin([2023, 2024])].assign(period="2023_2024")
    return pd.concat([all_period, recent], ignore_index=True)


def replacement_summary(full_selected: pd.DataFrame, restricted: pd.DataFrame, sleeve: str) -> pd.DataFrame:
    f = full_selected.copy()
    rkeys = restricted[["date", "ticker"]].drop_duplicates().assign(in_restricted62_pick=True)
    f = f.merge(rkeys, on=["date", "ticker"], how="left")
    f["in_restricted62_pick"] = f["in_restricted62_pick"].fillna(False).astype(bool)
    f["year"] = f["date"].dt.year
    rows = []
    for period, group in [("2018_2024", f), ("2023_2024", f[f["year"].isin([2023, 2024])])]:
        for label, part in [("full_selected_overlap_with_restricted62", group[group["in_restricted62_pick"]]), ("full_selected_replacements", group[~group["in_restricted62_pick"]])]:
            rows.append(
                {
                    "period": period,
                    "sleeve": sleeve,
                    "bucket": label,
                    "trades": int(len(part)),
                    "pnl": float(part["pnl"].sum()) if "pnl" in part.columns and part["pnl"].notna().any() else np.nan,
                    "avg_pnl": float(part["pnl"].mean()) if "pnl" in part.columns and len(part) else np.nan,
                    "win_rate": float((part["pnl"] > 0).mean()) if "pnl" in part.columns and len(part) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    daily = pd.read_pickle(base.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])

    broad_c = broad_candidates(daily)
    local_c = local_candidates(daily)

    restricted_broad = load_selected(RESTRICTED_BROAD, "broad_adv10_g2_dd85", "entry_date")
    restricted_local = load_selected(RESTRICTED_LOCAL, "local_xs_full_s10")
    restricted_yday = load_selected(RESTRICTED_YDAY, "yday_ex6_actual")
    if "wfo_mode" in restricted_yday.columns:
        restricted_yday = restricted_yday[restricted_yday["wfo_mode"].eq("rolling3")].copy()

    full_broad = load_selected(FULL_BROAD, "broad_adv10_g2_dd85", "entry_date")
    full_local = load_selected(FULL_LOCAL, "local_xs_full_s10")
    full_yday = load_selected(FULL_YDAY, "yday_ex6_actual")
    if "wfo_mode" in full_yday.columns:
        full_yday = full_yday[full_yday["wfo_mode"].eq("rolling3")].copy()

    broad_detail = displacement_detail(restricted_broad, full_broad, broad_c, "broad_adv10_g2_dd85", "ret5")
    local_detail = displacement_detail(restricted_local, full_local, local_c, "local_xs_full_s10", "ret5_pre_clean")

    y = restricted_yday[["date", "ticker", "pnl"]].copy().rename(columns={"pnl": "restricted_pnl"})
    y_full = full_yday[["date", "ticker"]].drop_duplicates().assign(selected_in_full=True)
    y_detail = y.merge(y_full, on=["date", "ticker"], how="left")
    y_detail["selected_in_full"] = y_detail["selected_in_full"].fillna(False).astype(bool)
    y_detail["candidate_rank"] = np.nan
    y_detail["candidate_count"] = np.nan
    y_detail["sleeve"] = "yday_ex6_actual"
    y_detail = pd.concat(
        [
            y_detail.assign(period="2018_2024"),
            y_detail[y_detail["date"].dt.year.isin([2023, 2024])].assign(period="2023_2024"),
        ],
        ignore_index=True,
    )

    detail = pd.concat([broad_detail, local_detail, y_detail], ignore_index=True, sort=False)
    detail.to_csv(DETAIL_OUT, index=False)

    rank_summary = summarize_displacement(detail[detail["sleeve"].ne("yday_ex6_actual")])
    y_summary = (
        y_detail.groupby(["period", "sleeve"], as_index=False)
        .agg(
            restricted62_trades=("ticker", "size"),
            restricted62_pnl=("restricted_pnl", "sum"),
            selected_in_full=("selected_in_full", "sum"),
            selected_in_full_rate=("selected_in_full", "mean"),
        )
    )
    y_summary["rank_bucket"] = "wfo_overlap_only"
    summary = pd.concat([rank_summary, y_summary], ignore_index=True, sort=False)
    summary.to_csv(SUMMARY_OUT, index=False)

    replacements = pd.concat(
        [
            replacement_summary(full_broad, restricted_broad, "broad_adv10_g2_dd85"),
            replacement_summary(full_local, restricted_local, "local_xs_full_s10"),
            replacement_summary(full_yday, restricted_yday, "yday_ex6_actual"),
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
