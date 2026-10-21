from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_full_lead_candidate_eventtime_audit as base
import stocks_pit_full_lead_crisis_eventtime_audit as engine
import stocks_pit_full_lead_missing_price_replay as missing
import stocks_pit_full_oos_feature_cache_builder as features
import stocks_pit_full_residual_reversal_cohorts as residual
import stocks_pit_full_rolling_sic_pairs as pairs


OUT_PREFIX = "STOCKS_PIT_FULL_LEAD_CLEAN_OOS_2026-09-17"
OOS_START = pd.Timestamp("2025-01-02")
OOS_END = pd.Timestamp("2026-09-16")
WARMUP_START = pd.Timestamp("2024-06-01")

OLD_DAILY = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
OLD_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
OOS_DAILY = features.OUT_DAILY
OOS_0935 = features.OUT_0935
OLD_CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
OOS_CAPS = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2025_2026_clean_oos.csv")
PIT_FILTER = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20250102_20260916_clean_oos/liquidity_filter_daily_20250102_20260916_clean_oos_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
FROZEN_SPEC = Path("STOCKS_PIT_FULL_LEAD_OOS_FROZEN_SPEC_2026-09-17.json")

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
SLEEVE_OUT = Path(f"{OUT_PREFIX}_SLEEVE_ATTRIBUTION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
EVENT_OUT = Path(f"{OUT_PREFIX}_EVENT_LEDGER.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
PAIR_FORMATIONS_OUT = Path(f"{OUT_PREFIX}_PAIR_FORMATIONS.csv")
PAIR_EVENTS_OUT = Path(f"{OUT_PREFIX}_PAIR_EVENTS.csv")
CRISIS_SIGNALS_OUT = Path(f"{OUT_PREFIX}_CRISIS_SIGNALS.csv")
PRICE_COVERAGE_OUT = Path(f"{OUT_PREFIX}_PRICE_COVERAGE.csv")
MARGIN_OUT = Path(f"{OUT_PREFIX}_MARGIN.csv")
BENCHMARK_OUT = Path(f"{OUT_PREFIX}_BENCHMARK.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")

SCENARIOS = [
    {"scenario": "oos_base4", "cost_bps": 4.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "oos_cost8", "cost_bps": 8.0, "financing": 0.025, "borrow": 0.01, "missing_bps": 0.0},
    {"scenario": "oos_severe12", "cost_bps": 12.0, "financing": 0.05, "borrow": 0.03, "missing_bps": 50.0},
]


def load_feature_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_cols = ["date", "ticker", "close_1555", "prev_close_1555", "prev_dayret", "vol20_pre"]
    intra_cols = ["date", "ticker", "entry935", "exit1555"]
    old_daily = pd.read_pickle(OLD_DAILY)[daily_cols]
    old_intra = pd.read_pickle(OLD_0935)[intra_cols]
    old_daily["date"] = pd.to_datetime(old_daily["date"]).dt.normalize()
    old_intra["date"] = pd.to_datetime(old_intra["date"]).dt.normalize()
    old_daily = old_daily[old_daily["date"] >= WARMUP_START]
    old_intra = old_intra[old_intra["date"] >= WARMUP_START]
    oos_daily = pd.read_pickle(OOS_DAILY)[daily_cols]
    oos_intra = pd.read_pickle(OOS_0935)[intra_cols]
    for frame in (oos_daily, oos_intra):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    daily = pd.concat([old_daily, oos_daily], ignore_index=True).drop_duplicates(["date", "ticker"], keep="last")
    intra = pd.concat([old_intra, oos_intra], ignore_index=True).drop_duplicates(["date", "ticker"], keep="last")
    for frame in (daily, intra):
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
    return daily, intra


def load_caps() -> pd.DataFrame:
    frames = [pd.read_csv(path, low_memory=False) for path in (OLD_CAPS, OOS_CAPS)]
    caps = pd.concat(frames, ignore_index=True)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps["sic_bucket"] = caps["sic_description"].fillna("UNKNOWN").astype(str).str.upper()
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps[caps["rank_market_cap"].le(500)][["date", "ticker", "sic_bucket"]].rename(columns={"date": "snapshot_date"})


def make_pair_raw(daily: pd.DataFrame, intra: pd.DataFrame) -> pd.DataFrame:
    x = daily[["date", "ticker", "close_1555", "prev_close_1555"]].merge(
        intra[["date", "ticker", "entry935"]], on=["date", "ticker"], how="inner"
    )
    x = x.dropna()
    x = x[(x["close_1555"] > 0) & (x["prev_close_1555"] > 0) & (x["entry935"] > 0)].copy()
    x["daily_ret"] = x["close_1555"] / x["prev_close_1555"] - 1.0
    x["log_close"] = np.log(x["close_1555"])
    return x.sort_values(["date", "ticker"]).reset_index(drop=True)


def fresh_oos_pair_events(signals: pd.DataFrame, dates: list[pd.Timestamp]) -> pd.DataFrame:
    decision_by_date = {date: group for date, group in signals.groupby("execution_date", sort=True)}
    active: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    empty = signals.iloc[0:0]
    for day_index, date in enumerate(dates):
        decisions = decision_by_date.get(date, empty)
        decision_map = {row.pair_id: row for row in decisions.itertuples(index=False)}
        for pair_id, state in list(active.items()):
            signal = decision_map.get(pair_id)
            held_days = day_index - int(state["entry_index"])
            direction = int(state["direction"])
            reason = None
            if signal is None:
                reason = "formation_drop"
            elif abs(float(signal.zscore)) <= pairs.EXIT_Z or direction * float(signal.zscore) >= 0:
                reason = "mean_revert"
            elif held_days >= 10:
                reason = "timeout"
            if reason:
                rows.append({"variant": "sic_pairs_quarterly_z2_hold10", "date": date, "pair_id": pair_id, "event": "exit", "reason": reason, "zscore": float(signal.zscore) if signal else np.nan})
                del active[pair_id]
        slots = pairs.MAX_ACTIVE_PAIRS - len(active)
        if slots > 0 and not decisions.empty:
            candidates = decisions[~decisions["pair_id"].isin(active)].copy()
            candidates = candidates[candidates["zscore"].abs() >= pairs.ENTRY_Z]
            candidates["abs_z"] = candidates["zscore"].abs()
            candidates = candidates.sort_values(["abs_z", "pair_id"], ascending=[False, True]).head(slots)
            for signal in candidates.itertuples(index=False):
                active[signal.pair_id] = {
                    "direction": -1 if signal.zscore > 0 else 1,
                    "entry_index": day_index,
                }
                rows.append({"variant": "sic_pairs_quarterly_z2_hold10", "date": date, "pair_id": signal.pair_id, "event": "entry", "reason": "z_entry", "zscore": float(signal.zscore)})
    return pd.DataFrame(rows)


def build_pair_source(daily: pd.DataFrame, intra: pd.DataFrame, caps: pd.DataFrame, dates: list[pd.Timestamp]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = make_pair_raw(daily, intra)
    formations = pairs.form_pairs(raw, caps, "quarterly")
    signals = pairs.build_signals(raw, formations, "quarterly")
    signals = signals[(signals["execution_date"] >= OOS_START) & (signals["execution_date"] <= OOS_END)]
    events = fresh_oos_pair_events(signals, dates)
    return formations, events


def build_crisis_source(daily: pd.DataFrame, intra: pd.DataFrame, caps: pd.DataFrame) -> pd.DataFrame:
    raw = daily[["date", "ticker", "prev_dayret", "vol20_pre"]].merge(
        intra[["date", "ticker", "entry935"]], on=["date", "ticker"], how="inner"
    ).dropna()
    raw = raw[(raw["entry935"] > 0) & (raw["vol20_pre"] > 0)].sort_values(["date", "ticker"])
    panel = residual.add_residuals(residual.apply_pool(raw, caps))
    spec = {"variant": "market_resid_rev_10x10_hold3", "signal": "market", "hold_days": 3}
    signals = residual.select_signals(panel, spec)
    return signals[(signals["entry_date"] >= OOS_START) & (signals["entry_date"] <= OOS_END)].copy()


def spy_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bars = features.load_spy_with_warmup().copy()
    bars["date"] = bars.index.normalize()
    p935 = bars[bars.index.time == dt.time(9, 35)][["date", "open"]].drop_duplicates("date", keep="last").rename(columns={"open": "spy935"})
    p1555 = bars[bars.index.time == dt.time(15, 55)][["date", "close"]].drop_duplicates("date", keep="last").rename(columns={"close": "spy1555"})
    spy = p935.merge(p1555, on="date", how="inner").sort_values("date")
    spy["prev_spy1555"] = spy["spy1555"].shift(1)
    spy["base_ret"] = spy["spy1555"] / spy["prev_spy1555"] - 1.0
    realized = spy["base_ret"].rolling(20, min_periods=20).std().shift(1) * math.sqrt(252)
    spy["beta_exposure"] = (0.16 / realized.replace(0.0, np.nan)).clip(0.0, 1.5).fillna(1.0)
    spy["month"] = spy["date"].dt.to_period("M")
    spy["td_from_start"] = spy.groupby("month").cumcount() + 1
    spy["overlay_exposure"] = np.where(spy["td_from_start"] <= 5, 0.5, 0.0)
    spy["spy_exposure"] = spy["beta_exposure"] + spy["overlay_exposure"]
    core = spy[(spy["date"] >= OOS_START) & (spy["date"] <= OOS_END)][["date", "spy_exposure"]].copy()
    price = spy[spy["date"].isin(core["date"])][["date", "spy935", "spy1555", "prev_spy1555"]].dropna()
    overnight = spy.copy()
    overnight["overnight_ret"] = overnight["spy935"] / overnight["prev_spy1555"] - 1.0
    overnight["lagged_overnight20"] = ((1.0 + overnight["overnight_ret"]).rolling(20, min_periods=20).apply(lambda v: v.prod(), raw=True) - 1.0).shift(1)
    gate = overnight.set_index("date")["lagged_overnight20"].lt(0.0)
    return core, price, gate


def crisis_schedule(signals: pd.DataFrame, dates: list[pd.Timestamp], gate: pd.Series) -> dict[pd.Timestamp, pd.Series]:
    signals = signals[signals["entry_date"].map(gate).fillna(False)].copy()
    by_entry = {date: group for date, group in signals.groupby("entry_date", sort=True)}
    cohorts: list[tuple[int, pd.Series]] = []
    schedule: dict[pd.Timestamp, pd.Series] = {}
    for day_index, date in enumerate(dates):
        cohorts = [(start, weights) for start, weights in cohorts if day_index - start < 3]
        new_weights = residual.cohort_weights(by_entry.get(date, signals.iloc[0:0]), 3, gross_scale=0.5)
        if not new_weights.empty:
            cohorts.append((day_index, new_weights))
        schedule[date] = residual.aggregate_cohorts(cohorts)
    return schedule


def price_maps(tickers: set[str], dates: set[pd.Timestamp]) -> tuple[dict, dict, dict, dict, pd.DataFrame]:
    wanted_months = {date.strftime("%Y-%m") for date in dates}
    rows: list[dict[str, object]] = []
    for ticker in sorted(tickers):
        symbol_dir = features.OOS_5M_DIR / ticker
        for path in sorted(symbol_dir.glob("*.parquet")):
            if path.stem.rsplit("_", maxsplit=1)[-1] not in wanted_months:
                continue
            bars = pd.read_parquet(path, columns=["open", "close"]).sort_index()
            bars.index = pd.to_datetime(bars.index)
            bars = bars[bars.index.normalize().isin(dates)]
            for date, day in bars.groupby(bars.index.normalize()):
                for event, when, field in (("0935", dt.time(9, 35), "open"), ("1555", dt.time(15, 55), "close")):
                    exact = day[day.index.time == when]
                    if not exact.empty and np.isfinite(float(exact.iloc[-1][field])):
                        rows.append({"date": date, "ticker": ticker, "event": event, "source": "raw_exact", "price": float(exact.iloc[-1][field]), "ageMinutes": 0.0})
                        continue
                    timestamp = date + pd.Timedelta(hours=when.hour, minutes=when.minute)
                    prior = day[day.index < timestamp]
                    if prior.empty:
                        rows.append({"date": date, "ticker": ticker, "event": event, "source": "unresolved", "price": np.nan, "ageMinutes": np.nan})
                        continue
                    age = (timestamp - prior.index[-1]).total_seconds() / 60.0
                    price = float(prior.iloc[-1]["close"])
                    source = "raw_asof" if age <= 5 and np.isfinite(price) else "unresolved"
                    rows.append({"date": date, "ticker": ticker, "event": event, "source": source, "price": price if source == "raw_asof" else np.nan, "ageMinutes": age})
    coverage = pd.DataFrame(rows)
    exact935: dict[pd.Timestamp, pd.Series] = {}
    exact1555: dict[pd.Timestamp, pd.Series] = {}
    mark935: dict[pd.Timestamp, pd.Series] = {}
    mark1555: dict[pd.Timestamp, pd.Series] = {}
    for row in coverage.itertuples(index=False):
        if not np.isfinite(row.price):
            continue
        exact_map = exact935 if row.event == "0935" else exact1555
        mark_map = mark935 if row.event == "0935" else mark1555
        if row.source == "raw_exact":
            missing.put(exact_map, row.date, row.ticker, float(row.price))
            missing.put(mark_map, row.date, row.ticker, float(row.price))
        elif row.source == "raw_asof":
            missing.put(mark_map, row.date, row.ticker, float(row.price))
    return exact935, exact1555, mark935, mark1555, coverage


def blocked_risk_increases(tickers: set[str], dates: list[pd.Timestamp]) -> set[tuple[pd.Timestamp, str]]:
    eligible = pd.read_parquet(
        PIT_FILTER,
        columns=["date", "ticker"],
        filters=[("ticker", "in", sorted(tickers)), ("date", ">=", OOS_START.date()), ("date", "<=", OOS_END.date()), ("eligible_final", "==", True)],
    )
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    allowed = set(zip(eligible["date"], eligible["ticker"]))
    return {(date, ticker) for date in dates for ticker in tickers if (date, ticker) not in allowed}


def benchmark_row(spy: pd.DataFrame) -> dict[str, object]:
    returns = spy.sort_values("date")["spy1555"].pct_change().fillna(spy.iloc[0]["spy1555"] / spy.iloc[0]["prev_spy1555"] - 1.0)
    equity = base.START_CAPITAL * (1.0 + returns).cumprod()
    dd, dd_pct = base.max_drawdown(equity)
    return {"benchmark": "SPY_1555_buy_hold", "pnl": float(equity.iloc[-1] - base.START_CAPITAL), "cagr": base.cagr(equity, spy["date"]), "ddDollar": dd, "ddPct": dd_pct, "sharpe": base.sharpe(base.START_CAPITAL * returns)}


def margin_proxy(events: pd.DataFrame, core: pd.DataFrame, scenario: str) -> dict[str, object]:
    x = events[events["scenario"].eq(scenario)].copy()
    x["date"] = x["timestamp"].dt.normalize()
    x = x[x["event"].isin(["mark_rebalance_0935", "mark_rebalance_1555"])].merge(core, on="date", how="left")
    x["spyGrossProxy"] = np.minimum(x["gross_exposure"], x["spy_exposure"])
    x["satelliteGrossProxy"] = (x["gross_exposure"] - x["spyGrossProxy"]).clip(lower=0.0)
    x["pmHouseConservativeRequirement"] = 0.15 * x["spyGrossProxy"] + 0.30 * x["satelliteGrossProxy"]
    x["bufferedRequirement"] = 1.25 * x["pmHouseConservativeRequirement"]
    return {"scenario": scenario, "buffer": 1.25, "maxRequirementNav": float(x["pmHouseConservativeRequirement"].max()), "maxBufferedRequirementNav": float(x["bufferedRequirement"].max()), "breachEventMarks": int(x["bufferedRequirement"].gt(1.0).sum()), "status": "PASS" if not x["bufferedRequirement"].gt(1.0).any() else "FAIL", "method": "Conservative proxy: SPY at 15%; all satellite gross at 30% short rate."}


def main() -> None:
    spec = json.loads(FROZEN_SPEC.read_text(encoding="utf-8"))
    if not spec.get("frozen_before_oos_read"):
        raise RuntimeError("Frozen OOS specification is not valid")
    daily_features, intra_features = load_feature_panel()
    caps = load_caps()
    core, spy, gate = spy_frames()
    dates = sorted(set(core["date"]).intersection(spy["date"]))
    core = core[core["date"].isin(dates)].copy()
    spy = spy[spy["date"].isin(dates)].copy()

    formations, pair_event_frame = build_pair_source(daily_features, intra_features, caps, dates)
    crisis_signals = build_crisis_source(daily_features, intra_features, caps)
    schedule = crisis_schedule(crisis_signals, dates, gate)
    pair_events = {date: group for date, group in pair_event_frame.groupby("date", sort=True)} if not pair_event_frame.empty else {}

    pair_tickers = set()
    if not pair_event_frame.empty:
        for pair_id in pair_event_frame["pair_id"]:
            pair_tickers.update(str(pair_id).split("|", maxsplit=1))
    trade_tickers = pair_tickers | set(crisis_signals["ticker"].astype(str).str.upper())
    exact935, exact1555, mark935, mark1555, coverage = price_maps(trade_tickers, set(dates))
    blocked = blocked_risk_increases(trade_tickers, dates)

    summaries: list[dict[str, object]] = []
    yearly: list[dict[str, object]] = []
    concentration: list[dict[str, object]] = []
    sleeves: list[dict[str, object]] = []
    daily_frames = []
    event_frames = []
    contrib_frames = []
    qa_rows = []
    for scenario in SCENARIOS:
        daily, events, contrib = engine.simulate(
            scenario, core, spy, pair_events, exact935, exact1555, schedule,
            name_cap=0.03, hard_gross_cap=3.0,
            missing_name_limit=2, missing_notional_limit=0.02,
            mark935=mark935, mark1555=mark1555, require_current_execution=True,
            blocked_risk_increases=blocked,
        )
        summary = base.summary_row(scenario, daily, events)
        summary.update({
            "failSafeBreaches": int(events["fail_safe_breach"].sum()),
            "disabledSessions": int(events.loc[events["policy_disabled"].eq(True), "timestamp"].dt.normalize().nunique()),
            "nameCapEventMarks": int(events["target_cap_scale"].lt(1.0).sum()),
            "advBlockedOrders": int(events["adv_blocked_count"].fillna(0).sum()),
        })
        summaries.append(summary)
        yearly.extend(base.yearly_rows(daily))
        concentration.extend(missing.concentration_rows(str(scenario["scenario"]), contrib))
        for sleeve, pnl in contrib.groupby("sleeve")["pnl"].sum().items():
            sleeves.append({"scenario": scenario["scenario"], "sleeve": sleeve, "pnl": float(pnl)})
        event_pnl = float(events["event_pnl"].sum())
        contrib_pnl = float(contrib["pnl"].sum())
        ending_pnl = float(events["equity"].iloc[-1] - base.START_CAPITAL)
        qa_rows.append({"scenario": scenario["scenario"], "eventPnl": event_pnl, "contribPnl": contrib_pnl, "endingPnl": ending_pnl, "eventMinusContrib": event_pnl - contrib_pnl, "eventMinusEnding": event_pnl - ending_pnl})
        daily_frames.append(daily)
        event_frames.append(events)
        contrib_frames.append(contrib)
        print("CLEAN_OOS", summary, flush=True)

    summaries_df = pd.DataFrame(summaries)
    events_all = pd.concat(event_frames, ignore_index=True)
    margin = pd.DataFrame([margin_proxy(events_all, core, scenario["scenario"]) for scenario in SCENARIOS])
    base_row = summaries_df.set_index("scenario").loc["oos_base4"]
    cost8_row = summaries_df.set_index("scenario").loc["oos_cost8"]
    base_margin = margin.set_index("scenario").loc["oos_base4"]
    verdict_checks = {
        "base_cagr": bool(base_row["cagr"] >= 0.15),
        "cost8_cagr": bool(cost8_row["cagr"] >= 0.12),
        "base_dd_pct": bool(base_row["ddPct"] >= -0.25),
        "missing_fail_safe": bool(base_row["disabledSessions"] <= 1),
        "portfolio_margin": bool(base_margin["status"] == "PASS"),
    }
    verdict = "CONTINUE" if all(verdict_checks.values()) else "KILL"

    summaries_df.to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.DataFrame(sleeves).to_csv(SLEEVE_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    events_all.to_csv(EVENT_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    formations.to_csv(PAIR_FORMATIONS_OUT, index=False)
    pair_event_frame.to_csv(PAIR_EVENTS_OUT, index=False)
    crisis_signals.to_csv(CRISIS_SIGNALS_OUT, index=False)
    coverage.to_csv(PRICE_COVERAGE_OUT, index=False)
    margin.to_csv(MARGIN_OUT, index=False)
    pd.DataFrame([benchmark_row(spy)]).to_csv(BENCHMARK_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(QA_OUT, index=False)
    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_lead_clean_oos_replay.py",
        "frozen_spec": str(FROZEN_SPEC),
        "sample": {"start": str(OOS_START.date()), "end": str(OOS_END.date()), "warmup_start": str(WARMUP_START.date())},
        "inputs": [str(OLD_DAILY), str(OLD_0935), str(OOS_DAILY), str(OOS_0935), str(OLD_CAPS), str(OOS_CAPS), str(PIT_FILTER), str(features.OOS_5M_DIR)],
        "scenarios": SCENARIOS,
        "data_contract": "2024 is lagged feature/pair-formation warm-up only. OOS account starts at $100,000 on 2025-01-02 and no pre-OOS holdings are carried. Quarterly top500 and same-date liquidity membership use only latest available PIT snapshots/filters.",
        "leakage_controls": "Signals use completed-session data and execute next session at exact 09:35. SPY vol and overnight gate are shifted one completed session. As-of <=5 minute prices are marks only. Missing exact execution freezes shares and blocks trades.",
        "selection_effect": "No rule re-selection and no candidate-family search occurs in OOS. Trade selection changes only through frozen PIT membership, signals, ADV gate, caps, and missing-price policy.",
        "verdict_checks": verdict_checks,
        "verdict": verdict,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(SLEEVE_OUT), str(DAILY_OUT), str(EVENT_OUT), str(CONTRIB_OUT), str(PAIR_FORMATIONS_OUT), str(PAIR_EVENTS_OUT), str(CRISIS_SIGNALS_OUT), str(PRICE_COVERAGE_OUT), str(MARGIN_OUT), str(BENCHMARK_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("VERDICT", verdict, verdict_checks, flush=True)


if __name__ == "__main__":
    main()
