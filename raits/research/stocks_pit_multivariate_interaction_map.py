from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

import stocks_pit_medium_horizon_replay as medium
import stocks_systematic_feature_horizon_map as source_map


PREREG = Path("STOCKS_PIT_MULTIVARIATE_INTERACTION_PREREG_2026-10-03.json")
PREFIX = "STOCKS_PIT_MULTIVARIATE_INTERACTION_2026-10-03"
DEV_YEARS = (2019, 2020)
REP_YEAR = 2021
CONF_YEAR = 2022
ROUND_TRIP_SPREAD_COST = 0.0016
MIN_NET_EDGE = {"d5": 0.0040, "d20": 0.0080}

TAPE_RAW_FEATURES = [
    *source_map.TAPE_FEATURES,
    "prev_dayret", "gap", "vol20_pre", "log_market_cap", "log_adv20",
    "signal_return_0930_1000", "log_signal_trades", "log_signal_dollar",
]
BROAD_CONTINUOUS = [
    "gap", "ret20_pre", "ret60_pre", "vol20_pre", "resid20", "resid60",
    "log_market_cap", "log_adv20", "article_count", "publisher_count",
    "single_ticker_article_share", *source_map.SHORT_FEATURES,
]
BROAD_BINARY = ["news_event", "short_available", *source_map.EDGAR_FEATURES]

CANDIDATES = [
    {"candidate": "tape_gap_ridge_d20", "context": "tape_gap", "model": "ridge", "horizon": "d20"},
    {"candidate": "tape_gap_hgb_d20", "context": "tape_gap", "model": "hgb", "horizon": "d20"},
    {"candidate": "tape_yday_ridge_d20", "context": "tape_yday", "model": "ridge", "horizon": "d20"},
    {"candidate": "tape_yday_hgb_d20", "context": "tape_yday", "model": "hgb", "horizon": "d20"},
    {"candidate": "broad_event_ridge_d5", "context": "broad_event", "model": "ridge", "horizon": "d5"},
    {"candidate": "broad_event_hgb_d5", "context": "broad_event", "model": "hgb", "horizon": "d5"},
    {"candidate": "broad_event_ridge_d20", "context": "broad_event", "model": "ridge", "horizon": "d20"},
    {"candidate": "broad_event_hgb_d20", "context": "broad_event", "model": "hgb", "horizon": "d20"},
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def normal_pvalue(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0)) if np.isfinite(t_value) else 1.0


def bh_qvalues(pvalues: pd.Series) -> np.ndarray:
    values = pvalues.to_numpy(dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted = np.minimum.accumulate((ranked * len(ranked) / np.arange(1, len(ranked) + 1))[::-1])[::-1]
    result = np.empty(len(values)); result[order] = np.minimum(adjusted, 1.0)
    return result


def rank_continuous(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    x = frame.copy()
    for column in columns:
        values = pd.to_numeric(x[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        x[f"xs_{column}"] = values.groupby(x["entry_date"]).rank(pct=True, method="average") * 2.0 - 1.0
    return x


def asof_by_ticker(panel: pd.DataFrame, updates: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = panel.copy()
    for column in columns:
        output[column] = np.nan
    for ticker, indices in output.groupby("ticker", sort=False).groups.items():
        right = updates[updates["ticker"].eq(ticker)].sort_values("entry_date")
        if right.empty:
            continue
        left = output.loc[indices, ["entry_date"]].sort_values("entry_date")
        merged = pd.merge_asof(left, right[["entry_date", *columns]], on="entry_date", direction="backward")
        output.loc[merged.index if merged.index.equals(left.index) else left.index, columns] = merged[columns].to_numpy()
    return output


def add_outcome(frame: pd.DataFrame, prices: pd.DataFrame, sessions: pd.DatetimeIndex,
                horizon: str, entry_price: str) -> pd.DataFrame:
    offset = 4 if horizon == "d5" else 19
    x = frame.copy()
    x["target_date"] = source_map.session_offset(x["entry_date"], sessions, offset)
    exits = prices.rename(columns={"date": "target_date", "close_1555": "exact_exit"})
    x = x.merge(exits[["target_date", "ticker", "exact_exit"]], on=["target_date", "ticker"], how="left")
    x["exit_fallback"] = False
    missing = x["exact_exit"].isna() & x["target_date"].notna()
    if missing.any():
        lookup: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for ticker, group in prices.dropna(subset=["close_1555"]).groupby("ticker", sort=False):
            ordered = group.sort_values("date")
            lookup[str(ticker)] = (ordered["date"].to_numpy(dtype="datetime64[ns]"), ordered["close_1555"].to_numpy())
        for idx, row in x.loc[missing, ["ticker", "entry_date", "target_date"]].iterrows():
            pair = lookup.get(str(row["ticker"]))
            if pair is None:
                continue
            dates, values = pair
            pos = int(np.searchsorted(dates, np.datetime64(row["target_date"]), side="right") - 1)
            if pos >= 0 and dates[pos] > np.datetime64(row["entry_date"]):
                x.at[idx, "exact_exit"] = float(values[pos])
                x.at[idx, "exit_fallback"] = True
    x[f"ret_{horizon}"] = x["exact_exit"] / x[entry_price] - 1.0
    no_exit = x["target_date"].notna() & x[f"ret_{horizon}"].isna()
    x.loc[no_exit, f"ret_{horizon}"] = -1.0
    x["exit_writeoff"] = no_exit
    return x.drop(columns="exact_exit")


def build_broad(panel: pd.DataFrame, prices: pd.DataFrame, sessions: pd.DatetimeIndex,
                end: pd.Timestamp) -> tuple[pd.DataFrame, list[str]]:
    x = panel[panel["date"].le(end)].rename(columns={"date": "entry_date"}).copy()
    x["log_market_cap"] = np.log1p(x["market_cap"].clip(lower=0))
    x["log_adv20"] = np.log1p(x["adv20"].clip(lower=0))

    news = source_map.load_news(end, sessions)
    edgar = source_map.load_edgar(end, sessions)
    short = source_map.load_short_interest(end, sessions)
    x = x.merge(news, on=["entry_date", "ticker"], how="left", validate="one_to_one")
    x = x.merge(edgar, on=["entry_date", "ticker"], how="left", validate="one_to_one")
    x["news_event"] = x["article_count"].notna().astype(float)
    for column in source_map.NEWS_FEATURES:
        x[column] = x[column].fillna(0.0)
    for column in source_map.EDGAR_FEATURES:
        x[column] = x[column].fillna(False).astype(float)
    x = asof_by_ticker(x, short, source_map.SHORT_FEATURES)
    x["short_available"] = x["days_to_cover"].notna().astype(float)
    x = rank_continuous(x, BROAD_CONTINUOUS)
    features = [f"xs_{column}" for column in BROAD_CONTINUOUS] + BROAD_BINARY
    x[features] = x[features].fillna(0.0)
    for horizon in ("d5", "d20"):
        x = add_outcome(x, prices, sessions, horizon, "open_0935")
        x = x.rename(columns={
            "target_date": f"target_date_{horizon}",
            "exit_fallback": f"exit_fallback_{horizon}",
            "exit_writeoff": f"exit_writeoff_{horizon}",
        })
    return x, features


def build_tape(prices: pd.DataFrame, sessions: pd.DatetimeIndex,
               end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], list[str]]:
    x = source_map.load_tape(end, prices, sessions)
    x["log_market_cap"] = np.log1p(x["market_cap"].clip(lower=0))
    x["log_adv20"] = np.log1p(x["adv20"].clip(lower=0))
    x["signal_return_0930_1000"] = x["signal_price_1000"] / x["open_0930"] - 1.0
    x["log_signal_trades"] = np.log1p(x["signal_trades"].clip(lower=0))
    x["log_signal_dollar"] = np.log1p(x["signal_dollar"].clip(lower=0))
    x = x.drop(columns=[column for column in ("target_d20", "exit_d20", "ret_d20") if column in x.columns])
    x = add_outcome(x, prices, sessions, "d20", "open_1005")
    x = rank_continuous(x, TAPE_RAW_FEATURES)
    features = [f"xs_{column}" for column in TAPE_RAW_FEATURES]
    x[features] = x[features].fillna(0.0)
    return {
        "tape_gap": x[x["gapup_precandidate"].astype(bool)].copy(),
        "tape_yday": x[x["yday_precandidate"].astype(bool)].copy(),
    }, features


def build_datasets(end: pd.Timestamp) -> tuple[dict[str, pd.DataFrame], dict[str, list[str]]]:
    panel, prices, session_list = medium.load_data()
    sessions = pd.DatetimeIndex(session_list)
    broad, broad_features = build_broad(panel, prices, sessions, end)
    tape, tape_features = build_tape(prices, sessions, end)
    datasets = {"broad_event": broad, **tape}
    features = {"broad_event": broad_features, "tape_gap": tape_features, "tape_yday": tape_features}
    return datasets, features


def make_model(name: str):
    if name == "ridge":
        return Ridge(alpha=100.0, fit_intercept=True)
    if name == "hgb":
        return HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=0.05, max_iter=100, max_leaf_nodes=7,
            min_samples_leaf=200, l2_regularization=10.0, random_state=271828,
        )
    raise ValueError(name)


def fit_and_score(train: pd.DataFrame, test: pd.DataFrame, features: list[str],
                  model_name: str, horizon: str) -> pd.DataFrame:
    target = f"ret_{horizon}"
    clean = train.dropna(subset=[target]).copy()
    clean["fit_target"] = clean.groupby("entry_date")[target].transform(
        lambda values: values.clip(values.quantile(0.01), values.quantile(0.99))
    )
    weights = 1.0 / clean.groupby("entry_date")["ticker"].transform("size")
    model = make_model(model_name)
    model.fit(clean[features].to_numpy(dtype=float), clean["fit_target"].to_numpy(dtype=float), sample_weight=weights)
    scored = test.copy()
    scored["score"] = model.predict(scored[features].to_numpy(dtype=float))
    return scored


def score_year(frame: pd.DataFrame, features: list[str], spec: dict[str, str], year: int) -> pd.DataFrame:
    frame = frame.copy()
    horizon_target = f"target_date_{spec['horizon']}"
    if horizon_target in frame.columns:
        frame["target_date"] = frame[horizon_target]
    cutoff = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year, month=12, day=31)
    train = frame[(frame["entry_date"] < cutoff) & (frame["target_date"] < cutoff)].copy()
    test = frame[frame["entry_date"].between(cutoff, end) & frame["target_date"].le(end)].copy()
    if train.empty or test.empty:
        return pd.DataFrame()
    scored = fit_and_score(train, test, features, spec["model"], spec["horizon"])
    scored["candidate"] = spec["candidate"]
    scored["score_year"] = year
    return scored


def daily_cohort_spreads(scored: pd.DataFrame, horizon: str) -> pd.DataFrame:
    target = f"ret_{horizon}"
    rows = []
    for date, group in scored.groupby("entry_date", sort=True):
        ranked = group.sort_values(["score", "ticker"], ascending=[False, True]).copy()
        count = len(ranked)
        side = max(1, int(math.ceil(count * 0.20)))
        top = ranked.head(side)
        bottom = ranked.tail(side)
        rows.append({
            "date": date, "gross_spread": float(top[target].mean() - bottom[target].mean()),
            "net_spread": float(top[target].mean() - bottom[target].mean() - ROUND_TRIP_SPREAD_COST),
            "top_obs": len(top), "bottom_obs": len(bottom), "universe_obs": count,
            "fallbacks": int(top[f"exit_fallback_{horizon}"].sum() + bottom[f"exit_fallback_{horizon}"].sum())
                if f"exit_fallback_{horizon}" in ranked else int(top["exit_fallback"].sum() + bottom["exit_fallback"].sum()),
            "writeoffs": int(top[f"exit_writeoff_{horizon}"].sum() + bottom[f"exit_writeoff_{horizon}"].sum())
                if f"exit_writeoff_{horizon}" in ranked else int(top["exit_writeoff"].sum() + bottom["exit_writeoff"].sum()),
        })
    return pd.DataFrame(rows)


def summarize(spreads: pd.DataFrame) -> dict[str, float]:
    values = spreads["net_spread"]
    std = float(values.std())
    t_value = float(values.mean() / std * math.sqrt(len(values))) if len(values) > 1 and std > 0 else np.nan
    return {
        "grossSpread": float(spreads["gross_spread"].mean()), "netSpread": float(values.mean()),
        "tNet": t_value, "p": normal_pvalue(t_value), "dates": int(len(spreads)),
        "topObs": int(spreads["top_obs"].sum()), "bottomObs": int(spreads["bottom_obs"].sum()),
        "fallbacks": int(spreads["fallbacks"].sum()), "writeoffs": int(spreads["writeoffs"].sum()),
    }


def main() -> None:
    prereg = json.loads(PREREG.read_text(encoding="ascii"))
    if not prereg["frozen_before_performance"] or prereg["script_hash"] != sha256(Path(__file__)):
        raise RuntimeError("preregistration mismatch")

    datasets, feature_sets = build_datasets(pd.Timestamp("2021-12-31"))
    result_rows = []
    yearly_rows = []
    daily_frames = []
    for spec in CANDIDATES:
        frame, features = datasets[spec["context"]], feature_sets[spec["context"]]
        scored_parts = [score_year(frame, features, spec, year) for year in DEV_YEARS]
        scored = pd.concat([part for part in scored_parts if not part.empty], ignore_index=True)
        spreads = daily_cohort_spreads(scored, spec["horizon"])
        summary = summarize(spreads)
        result_rows.append({**spec, **summary})
        spreads["candidate"] = spec["candidate"]; spreads["stage"] = "development_oof"
        daily_frames.append(spreads)
        for year, group in spreads.groupby(spreads["date"].dt.year):
            yearly_rows.append({"candidate": spec["candidate"], "stage": "development_oof", "year": int(year), **summarize(group)})

    results = pd.DataFrame(result_rows)
    results["q"] = bh_qvalues(results["p"])
    yearly = pd.DataFrame(yearly_rows)
    year_pivot = yearly.pivot(index="candidate", columns="year", values="netSpread")
    results["developmentPass"] = (
        results["q"].le(0.10) & results["netSpread"].ge(results["horizon"].map(MIN_NET_EDGE))
        & results["tNet"].ge(2.0) & results["dates"].ge(80)
        & results["topObs"].ge(400) & results["bottomObs"].ge(400)
        & results["candidate"].map(year_pivot[2019]).gt(0)
        & results["candidate"].map(year_pivot[2020]).gt(0)
    )

    replication_rows = []
    for spec in CANDIDATES:
        if not bool(results.loc[results["candidate"].eq(spec["candidate"]), "developmentPass"].iloc[0]):
            continue
        frame, features = datasets[spec["context"]], feature_sets[spec["context"]]
        scored = score_year(frame, features, spec, REP_YEAR)
        spreads = daily_cohort_spreads(scored, spec["horizon"])
        row = {"candidate": spec["candidate"], "stage": "replication", "year": REP_YEAR, **summarize(spreads)}
        replication_rows.append(row); yearly_rows.append(row)
        spreads["candidate"] = spec["candidate"]; spreads["stage"] = "replication"
        daily_frames.append(spreads)
    replication = pd.DataFrame(replication_rows)
    replication_fields = ["grossSpread", "netSpread", "tNet", "dates", "topObs", "bottomObs"]
    if replication.empty:
        for column in replication_fields:
            results[f"rep_{column}"] = np.nan
    else:
        results = results.merge(
            replication[["candidate", *replication_fields]].rename(
                columns={column: f"rep_{column}" for column in replication_fields}
            ),
            on="candidate", how="left", validate="one_to_one",
        )
    results["replicationPass"] = (
        results["developmentPass"] & results["rep_netSpread"].gt(0) & results["rep_tNet"].ge(1.0)
        & results["rep_netSpread"].ge(results["netSpread"] * 0.25)
        & results["rep_dates"].ge(40) & results["rep_topObs"].ge(200) & results["rep_bottomObs"].ge(200)
    )

    confirmation_rows = []
    if results["replicationPass"].any():
        conf_datasets, conf_features = build_datasets(pd.Timestamp("2022-12-30"))
        for spec in CANDIDATES:
            if not bool(results.loc[results["candidate"].eq(spec["candidate"]), "replicationPass"].iloc[0]):
                continue
            scored = score_year(conf_datasets[spec["context"]], conf_features[spec["context"]], spec, CONF_YEAR)
            spreads = daily_cohort_spreads(scored, spec["horizon"])
            row = {"candidate": spec["candidate"], "stage": "confirmation", "year": CONF_YEAR, **summarize(spreads)}
            row["confirmationPass"] = row["netSpread"] > 0 and row["tNet"] >= 0.5
            confirmation_rows.append(row); yearly_rows.append(row)
            spreads["candidate"] = spec["candidate"]; spreads["stage"] = "confirmation"
            daily_frames.append(spreads)

    confirmation = pd.DataFrame(confirmation_rows)
    pd.DataFrame(result_rows).to_csv(f"{PREFIX}_RAW_DEVELOPMENT.csv", index=False)
    results.to_csv(f"{PREFIX}_SELECTION.csv", index=False)
    pd.DataFrame(yearly_rows).to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(f"{PREFIX}_DAILY_SPREADS.csv", index=False)
    confirmation.to_csv(f"{PREFIX}_CONFIRMATION.csv", index=False)
    selection = {
        "candidates": len(results), "developmentPasses": int(results["developmentPass"].sum()),
        "replicationPasses": int(results["replicationPass"].sum()),
        "confirmationOpened": bool(results["replicationPass"].any()),
        "confirmationPasses": int(confirmation.get("confirmationPass", pd.Series(dtype=bool)).sum()),
        "productionPassAllowed": False,
    }
    Path(f"{PREFIX}_SUMMARY.json").write_text(json.dumps(selection, indent=2) + "\n", encoding="ascii")
    manifest = {
        "script": str(Path(__file__)).replace("\\", "/"), "scriptHash": sha256(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": sha256(PREREG),
        "sklearnVersion": __import__("sklearn").__version__, "candidates": CANDIDATES,
        "selection": selection, "oldManual62Used": False,
        "post2022Consumed": False, "post2021PerformanceConsumed": bool(selection["confirmationOpened"]),
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(results.to_string(index=False)); print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
