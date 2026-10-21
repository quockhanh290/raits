from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import stocks_pit_open_trade_flow as source


PREREG = Path("STOCKS_PIT_ADAPTIVE_OPENING_POLICY_PREREG_2026-10-04.json")
PREFIX = "STOCKS_PIT_ADAPTIVE_OPENING_POLICY_2026-10-04"
POLICY = "monthly_hgb_calibrated_abstain_eod"
DEVELOPMENT_START = pd.Timestamp("2019-06-03")
DEVELOPMENT_END = pd.Timestamp("2021-12-31")
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2022-12-30")
TRAIN_SESSIONS = 378
CALIBRATION_SESSIONS = 63
MIN_CORE_SESSIONS = 189
MIN_CALIBRATION_DAYS = 20
MIN_SIGNAL_TRADES = 100
MIN_SIGNAL_DOLLARS = 1_000_000.0
BASE_COST_BPS_PER_SIDE = 4.0
STRESS_COST_BPS_PER_SIDE = 8.0
HALF_SCALE_EDGE = 0.0012
FULL_SCALE_EDGE = 0.0020
MODEL_PARAMS = {
    "loss": "squared_error",
    "learning_rate": 0.05,
    "max_iter": 100,
    "max_leaf_nodes": 7,
    "min_samples_leaf": 100,
    "l2_regularization": 10.0,
    "random_state": 314159,
}
RAW_FEATURES = [
    "gap", "prev_dayret", "spy_prev_dayret", "vol20_pre", "beta60_lag",
    "first5_ret", "rvol930", "market_residual_first5", "opening_residual",
    "range_pct", "close_location", "flow_imbalance", "early_flow_imbalance",
    "late_flow_imbalance", "large_flow_imbalance", "large_trade_dollar_share",
    "trf_flow_imbalance", "lit_flow_imbalance", "trf_dollar_share",
    "opening_print_dollar_share", "late_vs_early_trade_rate", "vwap_displacement",
    "log_signal_trades", "log_signal_dollar", "log_market_cap", "log_adv20",
]
FEATURES = [f"xs_{name}" for name in RAW_FEATURES]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def prepare_panel() -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    panel, sessions = source.load_panel()
    x = panel.copy()
    x["vwap_displacement"] = x["last_signal_price"] / x["signal_vwap"] - 1.0
    x["log_signal_trades"] = np.log1p(x["signal_trades"].clip(lower=0.0))
    x["log_signal_dollar"] = np.log1p(x["signal_dollar"].clip(lower=0.0))
    x["log_market_cap"] = np.log1p(x["market_cap"].clip(lower=0.0))
    x["log_adv20"] = np.log1p(x["adv20"].clip(lower=0.0))
    x["target_return"] = x["open_1555"] / x["open_0940"] - 1.0
    x["candidate_known"] = (
        x["signal_entry_complete"]
        & x["open_0940"].notna()
        & x["open_0940"].gt(0.0)
        & x["signal_trades"].ge(MIN_SIGNAL_TRADES)
        & x["signal_dollar"].ge(MIN_SIGNAL_DOLLARS)
    )
    for column in RAW_FEATURES:
        values = pd.to_numeric(x[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        x[f"xs_{column}"] = values.groupby(x["date"]).rank(pct=True, method="average") * 2.0 - 1.0
    x[FEATURES] = x[FEATURES].fillna(0.0)
    return x.sort_values(["date", "ticker"]).reset_index(drop=True), sessions


def make_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(**MODEL_PARAMS)


def fit_model(frame: pd.DataFrame) -> HistGradientBoostingRegressor:
    clean = frame[frame["candidate_known"] & frame["target_return"].notna()].copy()
    lower, upper = clean["target_return"].quantile([0.01, 0.99])
    target = clean["target_return"].clip(lower, upper)
    weights = 1.0 / clean.groupby("date")["ticker"].transform("size")
    model = make_model()
    model.fit(clean[FEATURES].to_numpy(dtype=float), target.to_numpy(dtype=float), sample_weight=weights)
    return model


def select_side(group: pd.DataFrame, descending: bool) -> pd.DataFrame:
    selected: list[int] = []
    sic_counts: defaultdict[str, int] = defaultdict(int)
    ordered = group.sort_values(["score", "adv20", "ticker"], ascending=[not descending, False, True])
    for row in ordered.itertuples():
        sic = str(row.sic_description)
        if sic_counts[sic] >= 1:
            continue
        selected.append(row.Index)
        sic_counts[sic] += 1
        if len(selected) == 3:
            break
    return group.loc[selected].copy() if selected else group.iloc[0:0].copy()


def selected_day(group: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    longs = select_side(group, True)
    short_pool = group.drop(index=longs.index, errors="ignore")
    shorts = select_side(short_pool, False)
    if len(longs) != 3 or len(shorts) != 3:
        return group.iloc[0:0].copy(), np.nan, np.nan
    selected = pd.concat([longs, shorts], ignore_index=True)
    selected["side"] = [1] * 3 + [-1] * 3
    predicted = 0.5 * (float(longs["score"].mean()) - float(shorts["score"].mean()))
    realized = 0.5 * (float(longs["target_return"].mean()) - float(shorts["target_return"].mean()))
    return selected, predicted, realized


def calibration_diagnostics(core: pd.DataFrame, calibration: pd.DataFrame) -> dict[str, object]:
    model = fit_model(core)
    scored = calibration[calibration["candidate_known"]].copy()
    scored["score"] = model.predict(scored[FEATURES].to_numpy(dtype=float))
    rows: list[dict[str, float]] = []
    for date, group in scored.groupby("date", sort=True):
        _, predicted, realized = selected_day(group)
        if np.isfinite(predicted) and np.isfinite(realized) and predicted > 0:
            rows.append({"date": date, "predicted": predicted, "realized": realized})
    daily = pd.DataFrame(rows)
    if len(daily) < MIN_CALIBRATION_DAYS:
        return {"days": len(daily), "slope": 0.0, "netMean": np.nan, "healthy": False,
                "reason": "calibration_breadth"}
    denominator = float(np.square(daily["predicted"]).sum())
    slope = float((daily["predicted"] * daily["realized"]).sum() / denominator) if denominator > 0 else 0.0
    slope = float(np.clip(slope, 0.0, 1.0))
    net = daily["realized"] - 2.0 * BASE_COST_BPS_PER_SIDE / 10_000.0
    midpoint = len(daily) // 2
    first_half = float(net.iloc[:midpoint].mean())
    second_half = float(net.iloc[midpoint:].mean())
    healthy = bool(slope > 0 and net.mean() > 0 and first_half > 0 and second_half > 0)
    reason = "active" if healthy else "calibration_health"
    return {"days": len(daily), "slope": slope, "netMean": float(net.mean()),
            "firstHalfNetMean": first_half, "secondHalfNetMean": second_half,
            "healthy": healthy, "reason": reason}


def month_starts(sessions: list[pd.Timestamp], start: pd.Timestamp, end: pd.Timestamp) -> list[pd.Timestamp]:
    dates = pd.Series([date for date in sessions if start <= date <= end])
    return dates.groupby(dates.dt.to_period("M"), sort=True).min().tolist()


def score_scope(panel: pd.DataFrame, sessions: list[pd.Timestamp], start: pd.Timestamp,
                end: pd.Timestamp, scope: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    session_index = pd.DatetimeIndex(sessions)
    trades: list[pd.DataFrame] = []
    vintage_rows: list[dict[str, object]] = []
    for month_start in month_starts(sessions, start, end):
        month_period = month_start.to_period("M")
        month_dates = session_index[(session_index >= month_start) & (session_index <= end)
                                    & (session_index.to_period("M") == month_period)]
        prior_sessions = session_index[session_index < month_start][-TRAIN_SESSIONS:]
        if len(prior_sessions) < MIN_CORE_SESSIONS + CALIBRATION_SESSIONS:
            vintage_rows.append({"scope": scope, "month": str(month_period), "status": "insufficient_history",
                                 "trainSessions": len(prior_sessions), "activeDays": 0})
            continue
        core_dates = prior_sessions[:-CALIBRATION_SESSIONS]
        calibration_dates = prior_sessions[-CALIBRATION_SESSIONS:]
        core = panel[panel["date"].isin(core_dates)]
        calibration = panel[panel["date"].isin(calibration_dates)]
        diagnostic = calibration_diagnostics(core, calibration)
        row: dict[str, object] = {
            "scope": scope, "month": str(month_period), "trainStart": prior_sessions.min(),
            "trainEnd": prior_sessions.max(), "coreSessions": len(core_dates),
            "calibrationSessions": len(calibration_dates), "calibrationDays": diagnostic["days"],
            "calibrationSlope": diagnostic["slope"], "calibrationNetMean": diagnostic["netMean"],
            "firstHalfNetMean": diagnostic.get("firstHalfNetMean", np.nan),
            "secondHalfNetMean": diagnostic.get("secondHalfNetMean", np.nan),
            "status": diagnostic["reason"], "activeDays": 0,
        }
        if not diagnostic["healthy"]:
            vintage_rows.append(row)
            continue
        final_train = panel[panel["date"].isin(prior_sessions)]
        model = fit_model(final_train)
        month = panel[panel["date"].isin(month_dates) & panel["candidate_known"]].copy()
        month["score"] = model.predict(month[FEATURES].to_numpy(dtype=float))
        active_days = 0
        for date, group in month.groupby("date", sort=True):
            selected, predicted, _ = selected_day(group)
            calibrated_edge = float(diagnostic["slope"] * predicted) if np.isfinite(predicted) else np.nan
            if selected.empty or not np.isfinite(calibrated_edge) or calibrated_edge < HALF_SCALE_EDGE:
                continue
            scale = 1.0 if calibrated_edge >= FULL_SCALE_EDGE else 0.5
            selected["target_weight"] = selected["side"] * scale / 6.0
            selected["entry_price"] = selected["open_0940"]
            exit_columns = ["open_1555", "open_1600"]
            available = selected[exit_columns].notna()
            if not available.any(axis=1).all():
                raise RuntimeError(f"No same-session causal exit for {date.date()}")
            selected["exit_price"] = selected[exit_columns].bfill(axis=1).iloc[:, 0]
            selected["exit_clock"] = available.idxmax(axis=1).str.removeprefix("open_").str.replace(
                r"^(\d{2})(\d{2})$", r"\1:\2", regex=True
            )
            selected["exit_delay_minutes"] = np.where(selected["exit_clock"].eq("15:55"), 0.0, 5.0)
            selected["hold_minutes"] = np.where(selected["exit_clock"].eq("15:55"), 375.0, 380.0)
            selected["raw_return"] = selected["exit_price"] / selected["entry_price"] - 1.0
            selected["signed_return"] = selected["target_weight"] * selected["raw_return"]
            selected["variant"] = POLICY
            selected["scope"] = scope
            selected["model_month"] = str(month_period)
            selected["calibration_slope"] = diagnostic["slope"]
            selected["predicted_book_edge"] = predicted
            selected["calibrated_book_edge"] = calibrated_edge
            selected["scale"] = scale
            trades.append(selected)
            active_days += 1
        row["activeDays"] = active_days
        vintage_rows.append(row)
    trade_frame = pd.concat(trades, ignore_index=True) if trades else panel.iloc[0:0].copy()
    return trade_frame, pd.DataFrame(vintage_rows)


def replay_scope(trades: pd.DataFrame, sessions: list[pd.Timestamp], start: pd.Timestamp,
                 end: pd.Timestamp, scope: str) -> dict[str, object]:
    scoped_sessions = [date for date in sessions if start <= date <= end]
    daily_frames: list[pd.DataFrame] = []
    contrib_frames: list[pd.DataFrame] = []
    base_daily = pd.DataFrame()
    base_contrib = pd.DataFrame()
    stress_pnl = np.nan
    for cost in (BASE_COST_BPS_PER_SIDE, STRESS_COST_BPS_PER_SIDE):
        daily, contrib = source.simulate(POLICY, trades, scoped_sessions, cost, scope)
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        if cost == BASE_COST_BPS_PER_SIDE:
            base_daily, base_contrib = daily, contrib
        else:
            stress_pnl = source.metrics(daily)["pnl"]
    result = source.metrics(base_daily)
    gross_edge = (
        trades.groupby("date").apply(lambda g: float(g["signed_return"].sum()), include_groups=False).mean() * 10_000.0
        if not trades.empty else np.nan
    )
    summary = {"policy": POLICY, "scope": scope, "grossEdgeBpsPerActiveDay": gross_edge,
               "stressPnl": stress_pnl, **result, **source.concentration(base_contrib)}
    return {"summary": summary, "daily": pd.concat(daily_frames, ignore_index=True),
            "contrib": pd.concat(contrib_frames, ignore_index=True)}


def yearly_table(daily: pd.DataFrame) -> pd.DataFrame:
    return daily.assign(year=daily["date"].dt.year).groupby(
        ["variant", "scope", "cost_bps", "year"], as_index=False
    ).agg(pnl=("daily_pnl", "sum"), grossPnl=("gross_pnl", "sum"),
          tradingCost=("trading_cost", "sum"), borrowCost=("borrow_cost", "sum"),
          activeDays=("trade_legs", lambda x: int(x.gt(0).sum())), tradeLegs=("trade_legs", "sum"))


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("Preregistration/script hash mismatch")
    panel, sessions = prepare_panel()
    dev_trades, dev_vintages = score_scope(panel, sessions, DEVELOPMENT_START, DEVELOPMENT_END, "development")
    dev = replay_scope(dev_trades, sessions, DEVELOPMENT_START, DEVELOPMENT_END, "development")
    dev_summary = dev["summary"]
    development_pass = bool(
        dev_summary["activeDays"] >= 100
        and dev_summary["tradeLegs"] >= 600
        and dev_summary["cagr"] >= 0.05
        and dev_summary["sharpe"] >= 1.0
        and dev_summary["ddPct"] >= -0.10
        and dev_summary["positiveYears"] >= 2
        and dev_summary["grossEdgeBpsPerActiveDay"] >= 12.0
        and dev_summary["stressPnl"] > 0
        and dev_summary["effectiveTickerCount"] >= 30
        and dev_summary["top10PositiveShare"] <= 0.50
    )
    dev_summary["developmentPass"] = development_pass
    summaries = [dev_summary]
    all_trades = [dev_trades]
    all_daily = [dev["daily"]]
    all_contrib = [dev["contrib"]]
    all_vintages = [dev_vintages]
    if development_pass:
        val_trades, val_vintages = score_scope(panel, sessions, VALIDATION_START, VALIDATION_END, "validation")
        val = replay_scope(val_trades, sessions, VALIDATION_START, VALIDATION_END, "validation")
        val_summary = val["summary"]
        validation_pass = bool(
            val_summary["activeDays"] >= 20 and val_summary["pnl"] > 0
            and val_summary["sharpe"] >= 0.5 and val_summary["ddPct"] >= -0.10
            and val_summary["stressPnl"] > 0 and val_summary["effectiveTickerCount"] >= 15
            and val_summary["top10PositiveShare"] <= 0.60
        )
        val_summary["validationPass"] = validation_pass
        summaries.append(val_summary)
        all_trades.append(val_trades); all_daily.append(val["daily"])
        all_contrib.append(val["contrib"]); all_vintages.append(val_vintages)
        selection = {"status": "CONTINUE_AUDIT" if validation_pass else "KILL_VALIDATION_FAIL",
                     "developmentPass": True, "validationOpened": True,
                     "validationPass": validation_pass, "productionPassAllowed": False}
    else:
        selection = {"status": "KILL_NO_DEVELOPMENT_PASS", "developmentPass": False,
                     "validationOpened": False, "productionPassAllowed": False}
    trades = pd.concat(all_trades, ignore_index=True)
    daily = pd.concat(all_daily, ignore_index=True)
    contrib = pd.concat(all_contrib, ignore_index=True)
    vintages = pd.concat(all_vintages, ignore_index=True)
    summary = pd.DataFrame(summaries)
    yearly = yearly_table(daily)
    qa_rows = []
    for (scope_name, cost), group in daily.groupby(["scope", "cost_bps"]):
        matching = contrib[(contrib["scope"].eq(scope_name)) & (contrib["cost_bps"].eq(cost))]
        ending = float(group.sort_values("date").iloc[-1]["equity"] - source.INITIAL_EQUITY)
        qa_rows.append({"scope": scope_name, "cost_bps": cost, "dailyPnl": group["daily_pnl"].sum(),
                        "endingDelta": ending, "contribPnl": matching["net_pnl"].sum(),
                        "dailyMinusEnding": group["daily_pnl"].sum() - ending,
                        "dailyMinusContrib": group["daily_pnl"].sum() - matching["net_pnl"].sum()})
    qa = pd.DataFrame(qa_rows)
    summary.to_csv(f"{PREFIX}_SUMMARY.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    trades.to_csv(f"{PREFIX}_TRADES.csv", index=False)
    daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    vintages.to_csv(f"{PREFIX}_MODEL_VINTAGES.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False)
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "featureCache": str(source.FEATURES).replace("\\", "/"), "featureCacheHash": sha256(source.FEATURES),
        "exactClock": str(source.EXACT_CLOCK), "exactClockHash": sha256(source.EXACT_CLOCK),
        "selection": selection, "development": [str(DEVELOPMENT_START.date()), str(DEVELOPMENT_END.date())],
        "validation": [str(VALIDATION_START.date()), str(VALIDATION_END.date())] if selection["validationOpened"] else None,
        "oldManual62Used": False, "post2022Consumed": False, "productionPassAllowed": False,
        "ruleSelectionEffect": "One frozen adaptive learning policy; no model/threshold/horizon winner is selected after returns.",
        "tradeSelectionEffect": "Every model vintage rebuilds ranks, SIC-limited sides, exact-entry admission, abstention, scale, costs, exits, and compounding.",
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(summary.to_string(index=False), flush=True)
    print(yearly.to_string(index=False), flush=True)
    print(vintages.groupby(["scope", "status"], dropna=False).agg(months=("month", "count"), activeDays=("activeDays", "sum")).reset_index().to_string(index=False), flush=True)
    print(json.dumps(selection, indent=2), flush=True)
    print(qa.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
