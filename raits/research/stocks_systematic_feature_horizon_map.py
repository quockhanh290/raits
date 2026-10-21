from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_pit_medium_horizon_replay as medium


PREREG = Path("STOCKS_SYSTEMATIC_FEATURE_HORIZON_PREREG_2026-10-03.json")
TAPE = Path("raits/data/cache/polygon_stock_trades_1000_flow_2018_2022/causal_tape_features_pre1000.parquet")
TAPE_PLAN = Path("STOCKS_PIT_1000_FLOW_FETCH_PLAN_2026-10-02.csv")
TAPE_EXACT = Path("STOCKS_PIT_1000_FLOW_EXACT_CLOCK_ROWS_2026-10-02.csv")
CONTEXT = Path("raits/data/cache/external_equity_context/polygon_2018_2024")
EVENTS = Path("raits/data/cache/external_events/polygon_2018_2024")
PREFIX = "STOCKS_SYSTEMATIC_FEATURE_HORIZON_2026-10-03"
DISC_END = pd.Timestamp("2020-12-31")
REP_START, REP_END = pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
CONF_START, CONF_END = pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-30")
TAPE_FEATURES = [
    "unique_exchanges", "exchange_dollar_hhi", "trf_dollar_share", "lit_flow_imbalance",
    "large_lit_flow_imbalance", "large_trade_dollar_share_fixed100k", "block_dollar_share_size1000",
    "sub100_share_dollar_share", "odd_lot_condition_dollar_share", "odd_lot_flow_imbalance",
    "sweep_dollar_share", "cross_dollar_share", "official_open_dollar_share",
    "official_open_discount_to_signal_vwap", "median_sip_latency_us", "p90_sip_latency_us",
    "median_interarrival_us", "burst_share_top_second",
]
SHORT_FEATURES = ["log_short_interest_change", "days_to_cover", "days_to_cover_change"]
NEWS_FEATURES = ["article_count", "publisher_count", "single_ticker_article_share"]
EDGAR_FEATURES = ["event_8k", "event_10q", "event_10k", "event_form4", "event_13dg", "event_offering"]
HORIZONS = ["intraday", "overnight", "d1", "d5", "d20"]
MIN_EDGE = {"intraday": 0.0010, "overnight": 0.0010, "d1": 0.0015, "d5": 0.0040, "d20": 0.0080}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normal_pvalue(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0)) if np.isfinite(t_value) else 1.0


def bh_qvalues(pvalues: pd.Series) -> pd.Series:
    order = np.argsort(pvalues.to_numpy())
    ranked = pvalues.to_numpy()[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    result = np.empty(len(ranked)); result[order] = np.minimum(adjusted, 1.0)
    return pd.Series(result, index=pvalues.index)


def next_session(dates: pd.Series, sessions: pd.DatetimeIndex, offset: int = 1) -> pd.Series:
    values = pd.to_datetime(dates).values.astype("datetime64[ns]")
    indices = sessions.searchsorted(values, side="right") + offset - 1
    output = np.full(len(indices), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = indices < len(sessions)
    output[valid] = sessions.values[indices[valid]]
    return pd.Series(output, index=dates.index)


def session_offset(dates: pd.Series, sessions: pd.DatetimeIndex, offset: int) -> pd.Series:
    indices = sessions.get_indexer(pd.to_datetime(dates)) + offset
    output = np.full(len(indices), np.datetime64("NaT"), dtype="datetime64[ns]")
    valid = (indices >= 0) & (indices < len(sessions))
    output[valid] = sessions.values[indices[valid]]
    return pd.Series(output, index=dates.index)


def attach_daily_outcomes(frame: pd.DataFrame, prices: pd.DataFrame, sessions: pd.DatetimeIndex,
                          entry_column: str = "entry_date") -> pd.DataFrame:
    x = frame.copy()
    entry = prices.rename(columns={"date": entry_column, "open_0935": "entry_open_0935",
                                   "close_1555": "entry_close_1555"})
    x = x.merge(entry[[entry_column, "ticker", "entry_open_0935", "entry_close_1555"]],
                on=[entry_column, "ticker"], how="left", validate="many_to_one")
    x["ret_d1"] = x["entry_close_1555"] / x["entry_open_0935"] - 1.0
    for horizon, offset in (("d5", 4), ("d20", 19)):
        target = f"target_{horizon}"
        x[target] = session_offset(x[entry_column], sessions, offset)
        exits = prices.rename(columns={"date": target, "close_1555": f"exit_{horizon}"})
        x = x.merge(exits[[target, "ticker", f"exit_{horizon}"]], on=[target, "ticker"],
                    how="left", validate="many_to_one")
        x[f"ret_{horizon}"] = x[f"exit_{horizon}"] / x["entry_open_0935"] - 1.0
    return x


def load_news(end: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    files = sorted((EVENTS / "news").glob("*.parquet"))
    rows = pd.concat([pd.read_parquet(path, columns=["published_utc", "publisher_name", "tickers_json"])
                      for path in files], ignore_index=True)
    rows["published_utc"] = pd.to_datetime(rows["published_utc"], utc=True, errors="coerce")
    rows = rows[rows["published_utc"].dt.tz_localize(None).le(end + pd.Timedelta(days=1))].copy()
    rows["published_et"] = rows["published_utc"].dt.tz_convert("America/New_York")
    rows["published_date"] = rows["published_et"].dt.tz_localize(None).dt.normalize()
    same_day = rows["published_et"].dt.strftime("%H:%M:%S").lt("09:25:00") & rows["published_date"].isin(sessions)
    rows["entry_date"] = next_session(rows["published_date"], sessions)
    rows.loc[same_day, "entry_date"] = rows.loc[same_day, "published_date"]
    rows["tickers"] = rows["tickers_json"].map(json.loads)
    rows["ticker_count"] = rows["tickers"].map(len)
    rows = rows.explode("tickers").rename(columns={"tickers": "ticker"})
    rows["ticker"] = rows["ticker"].astype(str).str.upper()
    rows["single"] = rows["ticker_count"].eq(1).astype(float)
    return rows.groupby(["entry_date", "ticker"], as_index=False).agg(
        article_count=("published_utc", "size"), publisher_count=("publisher_name", "nunique"),
        single_ticker_article_share=("single", "mean"))


def load_short_interest(end: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    files = sorted((CONTEXT / "short_interest").glob("*.parquet"))
    rows = pd.concat([pd.read_parquet(path) for path in files if path.stem[-7:] <= end.strftime("%Y-%m")],
                     ignore_index=True)
    rows["settlement_date"] = pd.to_datetime(rows["settlement_date"])
    rows = rows[rows["settlement_date"].le(end)].drop_duplicates(["ticker", "settlement_date"], keep="last")
    rows["ticker"] = rows["ticker"].astype(str).str.upper()
    rows = rows.sort_values(["ticker", "settlement_date"])
    prior = rows.groupby("ticker")["short_interest"].shift()
    rows["log_short_interest_change"] = np.log(rows["short_interest"].clip(lower=1) / prior.clip(lower=1))
    rows["days_to_cover_change"] = rows["days_to_cover"] - rows.groupby("ticker")["days_to_cover"].shift()
    rows["entry_date"] = next_session(rows["settlement_date"], sessions, offset=10)
    return rows[["entry_date", "ticker", *SHORT_FEATURES]].dropna(subset=["entry_date"])


def load_edgar(end: pd.Timestamp, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    files = sorted((CONTEXT / "edgar_index").glob("*.parquet"))
    rows = pd.concat([pd.read_parquet(path) for path in files if path.stem[-7:] <= end.strftime("%Y-%m")],
                     ignore_index=True).drop_duplicates()
    rows["filing_date"] = pd.to_datetime(rows["filing_date"])
    rows = rows[rows["filing_date"].le(end) & rows["ticker"].notna()].copy()
    rows["ticker"] = rows["ticker"].astype(str).str.upper()
    rows["entry_date"] = next_session(rows["filing_date"], sessions)
    form = rows["form_type"].fillna("").str.upper()
    rows["event_8k"] = form.eq("8-K")
    rows["event_10q"] = form.eq("10-Q")
    rows["event_10k"] = form.eq("10-K")
    rows["event_form4"] = form.eq("4")
    rows["event_13dg"] = form.str.startswith("SC 13D") | form.str.startswith("SC 13G")
    rows["event_offering"] = form.str.startswith("S-1") | form.str.startswith("S-3") | form.str.startswith("424B")
    return rows.groupby(["entry_date", "ticker"], as_index=False)[EDGAR_FEATURES].max()


def load_tape(end: pd.Timestamp, prices: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    tape = pd.read_parquet(TAPE); tape["date"] = pd.to_datetime(tape["date"])
    plan = pd.read_csv(TAPE_PLAN, parse_dates=["date"])
    exact = pd.read_csv(TAPE_EXACT, parse_dates=["date"])
    wide = exact.pivot(index=["date", "ticker"], columns="clock", values=["open", "close"])
    wide.columns = [f"{field}_{clock.replace(':', '')}" for field, clock in wide.columns]
    x = plan.merge(tape, on=["date", "ticker"], validate="one_to_one")
    x = x.merge(wide.reset_index()[["date", "ticker", "open_1005", "close_1555"]],
                on=["date", "ticker"], how="left", validate="one_to_one")
    x = x[x["date"].le(end) & x["open_1005"].gt(0)].copy()
    x["entry_date"] = x["date"]
    x["ret_intraday"] = x["close_1555"] / x["open_1005"] - 1.0
    x["next_date"] = session_offset(x["date"], sessions, 1)
    next_open = prices.rename(columns={"date": "next_date", "open_0935": "next_open_0935"})
    x = x.merge(next_open[["next_date", "ticker", "next_open_0935"]], on=["next_date", "ticker"], how="left")
    x["ret_overnight"] = x["next_open_0935"] / x["open_1005"] - 1.0
    for horizon, offset in (("d5", 4), ("d20", 19)):
        target = f"target_{horizon}"; x[target] = session_offset(x["date"], sessions, offset)
        exits = prices.rename(columns={"date": target, "close_1555": f"exit_{horizon}"})
        x = x.merge(exits[[target, "ticker", f"exit_{horizon}"]], on=[target, "ticker"], how="left")
        x[f"ret_{horizon}"] = x[f"exit_{horizon}"] / x["open_1005"] - 1.0
    return x


def daily_spread(frame: pd.DataFrame, feature: str, outcome: str, binary: bool) -> tuple[pd.Series, int, int]:
    usable = frame[["entry_date", "ticker", feature, outcome]].replace([np.inf, -np.inf], np.nan).dropna()
    spreads = []
    top_obs = bottom_obs = 0
    for _, group in usable.groupby("entry_date"):
        if binary:
            top, bottom = group[group[feature].astype(bool)], group[~group[feature].astype(bool)]
        else:
            ranks = group[feature].rank(pct=True, method="average")
            top, bottom = group[ranks.ge(0.8)], group[ranks.le(0.2)]
        if len(top) and len(bottom):
            spreads.append((group.iloc[0]["entry_date"], top[outcome].mean() - bottom[outcome].mean()))
            top_obs += len(top); bottom_obs += len(bottom)
    series = pd.Series(dict(spreads), dtype=float).sort_index()
    return series, top_obs, bottom_obs


def summarize(series: pd.Series, top_obs: int, bottom_obs: int) -> dict[str, float]:
    std = series.std()
    t_value = float(series.mean() / std * math.sqrt(len(series))) if len(series) > 1 and std > 0 else np.nan
    return {"spread": float(series.mean()) if len(series) else np.nan, "t": t_value,
            "p": normal_pvalue(t_value), "dates": len(series), "topObs": top_obs, "bottomObs": bottom_obs}


def build_tests(datasets: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    specs = []
    for context in ("tape_yday", "tape_gap"):
        for feature in TAPE_FEATURES:
            for horizon in ("intraday", "overnight", "d5", "d20"):
                specs.append((context, feature, horizon, False))
    for feature in SHORT_FEATURES:
        for horizon in ("d1", "d5", "d20"): specs.append(("short_interest", feature, horizon, False))
    for feature in NEWS_FEATURES:
        for horizon in ("d1", "d5", "d20"): specs.append(("news", feature, horizon, False))
    for feature in EDGAR_FEATURES:
        for horizon in ("d1", "d5", "d20"): specs.append(("edgar", feature, horizon, True))
    for context, feature, horizon, binary in specs:
        frame = datasets[context]
        frame = frame[frame["entry_date"].between(start, end)]
        series, top_obs, bottom_obs = daily_spread(frame, feature, f"ret_{horizon}", binary)
        rows.append({"context": context, "feature": feature, "horizon": horizon, "binary": binary,
                     **summarize(series, top_obs, bottom_obs)})
    return pd.DataFrame(rows)


def prepare(end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    panel, prices, session_list = medium.load_data()
    sessions = pd.DatetimeIndex(session_list)
    allowed = panel[["date", "ticker"]].drop_duplicates().rename(columns={"date": "entry_date"})
    tape = load_tape(end, prices, sessions)
    datasets = {
        "tape_yday": tape[tape["yday_precandidate"].astype(bool)].copy(),
        "tape_gap": tape[tape["gapup_precandidate"].astype(bool)].copy(),
    }
    for name, loader in (("short_interest", load_short_interest), ("news", load_news), ("edgar", load_edgar)):
        base = loader(end, sessions)
        base = base.merge(allowed, on=["entry_date", "ticker"], how="inner")
        datasets[name] = attach_daily_outcomes(base, prices, sessions)
    inputs = {str(path).replace("\\", "/"): sha256(path) for path in (TAPE, TAPE_PLAN, TAPE_EXACT)}
    return datasets, inputs


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if prereg["script_hash"] != sha256(Path(__file__)) or not prereg["frozen_before_performance"]:
        raise RuntimeError("Preregistration mismatch")
    datasets, inputs = prepare(REP_END)
    discovery = build_tests(datasets, medium.START, DISC_END)
    discovery["q"] = bh_qvalues(discovery["p"])
    replication = build_tests(datasets, REP_START, REP_END).drop(columns=["p"])
    replication = replication.rename(columns={column: f"rep_{column}" for column in
        ["spread", "t", "dates", "topObs", "bottomObs"]})
    results = discovery.merge(replication, on=["context", "feature", "horizon", "binary"], validate="one_to_one")
    direction = np.sign(results["spread"])
    results["discoveryPass"] = (results["q"].le(0.10) & results["spread"].abs().ge(results["horizon"].map(MIN_EDGE))
        & results["dates"].ge(60) & results["topObs"].ge(400) & results["bottomObs"].ge(400))
    results["replicationPass"] = (results["discoveryPass"] & (direction * results["rep_spread"]).gt(0)
        & (direction * results["rep_t"]).ge(1.0) & results["rep_spread"].abs().ge(results["spread"].abs() * 0.25)
        & results["rep_dates"].ge(20) & results["rep_topObs"].ge(100) & results["rep_bottomObs"].ge(100))
    qualified = results[results["replicationPass"]][["context", "feature", "horizon", "binary", "spread"]].copy()
    confirmation = pd.DataFrame()
    if not qualified.empty:
        conf_data, _ = prepare(CONF_END)
        all_conf = build_tests(conf_data, CONF_START, CONF_END)
        confirmation = qualified.merge(all_conf, on=["context", "feature", "horizon", "binary"], suffixes=("_discovery", ""))
        confirmation["confirmationPass"] = (
            (np.sign(confirmation["spread_discovery"]) * confirmation["spread"] > 0)
            & (np.sign(confirmation["spread_discovery"]) * confirmation["t"] >= 0.5)
        )
    results.to_csv(f"{PREFIX}_DISCOVERY_REPLICATION.csv", index=False)
    confirmation.to_csv(f"{PREFIX}_CONFIRMATION.csv", index=False)
    selection = {"tests": len(results), "discoveryPasses": int(results["discoveryPass"].sum()),
                 "replicationPasses": int(results["replicationPass"].sum()),
                 "confirmationOpened": not qualified.empty,
                 "confirmationPasses": int(confirmation.get("confirmationPass", pd.Series(dtype=bool)).sum()),
                 "productionPassAllowed": False}
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    manifest = {"script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
                "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG), "inputs": inputs,
                "selection": selection, "oldManual62Used": False, "post2022Consumed": False}
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(json.dumps(selection, indent=2))
    print(results.sort_values(["replicationPass", "q", "p"], ascending=[False, True, True]).head(30).to_string(index=False))
    if not confirmation.empty: print(confirmation.to_string(index=False))


if __name__ == "__main__":
    main()
