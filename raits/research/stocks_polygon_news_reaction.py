from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


PREREG = Path("STOCKS_POLYGON_NEWS_REACTION_PREREG_2026-09-24.json")
NEWS_DIR = Path("raits/data/cache/external_events/polygon_2018_2024/news")
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_FEATURES = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP = Path("raits/data/cache/external_universes/market_cap_polygon/polygon_market_cap_snapshots_pit_eligible_2018_2024.csv")
ELIGIBLE = Path("raits/data/cache/stocks_survivorship/polygon_universe_bulk/daily_20180102_20241231_resumable/liquidity_filter_daily_20180102_20241231_px5_adv10m_unadjusted/filtered_daily_universe.parquet")
PREFIX = "STOCKS_POLYGON_NEWS_REACTION_2026-09-24"
START_CAPITAL = 100_000.0
DEV_START = pd.Timestamp("2021-04-05")
DEV_END = pd.Timestamp("2022-12-30")
VAL_START = pd.Timestamp("2023-01-03")
VAL_END = pd.Timestamp("2024-02-29")

VARIANTS = [
    {"variant": "all_single_confirmed_cont", "publisher": "all", "min_articles": 1, "direction": 1},
    {"variant": "all_single_confirmed_reversal_control", "publisher": "all", "min_articles": 1, "direction": -1},
    {"variant": "issuer_wire_confirmed_cont", "publisher": "GlobeNewswire Inc.", "min_articles": 1, "direction": 1},
    {"variant": "burst2_single_confirmed_cont", "publisher": "all", "min_articles": 2, "direction": 1},
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peaks = equity.cummax()
    dollar = equity - peaks
    pct = equity / peaks - 1.0
    return float(dollar.min()), float(pct.min())


def performance(daily: pd.DataFrame) -> dict[str, float | int]:
    if daily.empty:
        return {"days": 0, "entries": 0, "pnl": 0.0, "cagr": 0.0, "sharpe": np.nan, "ddDollar": 0.0, "ddPct": 0.0, "maxGross": 0.0}
    prior = daily["equity"] - daily["daily_pnl"]
    returns = daily["daily_pnl"] / prior.clip(lower=1e-9)
    vol = returns.std(ddof=1)
    sharpe = float(returns.mean() / vol * math.sqrt(252)) if vol > 0 else np.nan
    dd_dollar, dd_pct = max_drawdown(daily["equity"])
    cagr = float((daily.iloc[-1]["equity"] / START_CAPITAL) ** (252.0 / len(daily)) - 1.0)
    return {
        "days": len(daily), "entries": int(daily["entries"].sum()),
        "pnl": float(daily["daily_pnl"].sum()), "cagr": cagr, "sharpe": sharpe,
        "ddDollar": dd_dollar, "ddPct": dd_pct, "maxGross": float(daily["gross"].max()),
    }


def load_feature_panels() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_pickle(DAILY_FEATURES)[["date", "ticker", "gap"]].copy()
    intra = pd.read_pickle(INTRADAY_FEATURES)[["date", "ticker", "entry935", "exit1555", "first5_ret", "rvol930"]].copy()
    for frame in (daily, intra):
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        frame["ticker"] = frame["ticker"].astype(str).str.upper()
    return daily, intra


def load_top500() -> pd.DataFrame:
    frame = pd.read_csv(MARKET_CAP, low_memory=False)
    frame["snapshot_date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["ticker"] = frame["ticker_query"].astype(str).str.upper()
    frame["market_cap"] = pd.to_numeric(frame["market_cap"], errors="coerce")
    frame = frame[frame["status_code"].eq(200) & frame["market_cap"].notna()].copy()
    frame = frame.sort_values(["snapshot_date", "ticker", "market_cap"], ascending=[True, True, False]).drop_duplicates(["snapshot_date", "ticker"])
    frame["rank_market_cap"] = frame.groupby("snapshot_date")["market_cap"].rank(method="first", ascending=False)
    return frame[frame["rank_market_cap"].le(500)][["snapshot_date", "ticker", "market_cap", "rank_market_cap"]]


def news_paths(start: pd.Timestamp, end: pd.Timestamp) -> list[Path]:
    months = pd.period_range(start.to_period("M"), end.to_period("M"), freq="M")
    paths = [NEWS_DIR / f"news_{month}.parquet" for month in months]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing news inputs: {missing}")
    return paths


def load_and_assign_news(start: pd.Timestamp, end: pd.Timestamp, sessions: list[pd.Timestamp]) -> tuple[pd.DataFrame, list[Path]]:
    paths = news_paths(start, end)
    raw = pd.concat(
        [pd.read_parquet(path, columns=["id", "published_utc", "publisher_name", "tickers_json"]) for path in paths],
        ignore_index=True,
    ).drop_duplicates("id")
    raw["published_utc"] = pd.to_datetime(raw["published_utc"], utc=True, errors="coerce")

    def single_ticker(value: object) -> str | None:
        try:
            values = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(values, list) or len(values) != 1:
            return None
        ticker = str(values[0]).strip().upper()
        return ticker or None

    raw["ticker"] = raw["tickers_json"].map(single_ticker)
    raw = raw[raw["published_utc"].notna() & raw["ticker"].notna()].copy()
    session_index = pd.DatetimeIndex(sessions)
    cutoffs = (session_index.tz_localize("America/New_York") + pd.Timedelta(hours=9, minutes=25)).tz_convert("UTC")
    published_ns = raw["published_utc"].astype("int64").to_numpy()
    assigned_index = np.searchsorted(cutoffs.asi8, published_ns, side="left")
    valid = (assigned_index > 0) & (assigned_index < len(sessions))
    raw = raw.loc[valid].copy()
    assigned_index = assigned_index[valid]
    previous_closes = (session_index[assigned_index - 1].tz_localize("America/New_York") + pd.Timedelta(hours=16)).tz_convert("UTC")
    raw["date"] = session_index[assigned_index].to_numpy()
    raw["previous_close_utc"] = previous_closes.to_numpy()
    raw = raw[raw["published_utc"] >= raw["previous_close_utc"]].copy()
    raw = raw[(raw["date"] >= start) & (raw["date"] <= end)].copy()
    raw["is_issuer_wire"] = raw["publisher_name"].eq("GlobeNewswire Inc.")
    return raw.sort_values(["date", "ticker", "published_utc", "id"]), paths


def build_panel(start: pd.Timestamp, end: pd.Timestamp, daily: pd.DataFrame, intra: pd.DataFrame, top500: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, list[Path]]:
    stage_intra = intra[(intra["date"] >= start - pd.Timedelta(days=10)) & (intra["date"] <= end)].copy()
    sessions = sorted(stage_intra["date"].drop_duplicates())
    mapped_news, paths = load_and_assign_news(start, end, sessions)
    counts = mapped_news.groupby(["date", "ticker"], as_index=False).agg(
        article_count=("id", "nunique"), wire_article_count=("is_issuer_wire", "sum"),
        first_published_utc=("published_utc", "min"), last_published_utc=("published_utc", "max"),
    )
    dates = pd.DataFrame({"date": sorted(counts["date"].drop_duplicates())})
    snapshots = top500[["snapshot_date"]].drop_duplicates().sort_values("snapshot_date")
    dates = pd.merge_asof(dates, snapshots, left_on="date", right_on="snapshot_date", direction="backward")
    counts = counts.merge(dates, on="date", how="left", validate="many_to_one")
    counts = counts.merge(top500, on=["snapshot_date", "ticker"], how="inner", validate="many_to_one")
    eligible = pd.read_parquet(
        ELIGIBLE, columns=["date", "ticker", "adv20"],
        filters=[("date", ">=", start.date()), ("date", "<=", end.date()), ("eligible_final", "==", True)],
    )
    eligible["date"] = pd.to_datetime(eligible["date"]).dt.normalize()
    eligible["ticker"] = eligible["ticker"].astype(str).str.upper()
    eligible = eligible.groupby(["date", "ticker"], as_index=False)["adv20"].min()
    panel = counts.merge(eligible, on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.merge(daily[["date", "ticker", "gap"]], on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.merge(stage_intra, on=["date", "ticker"], how="inner", validate="one_to_one")
    panel = panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["gap", "rvol930", "first5_ret", "entry935", "exit1555", "adv20"])
    panel = panel[(panel["entry935"] > 0) & (panel["exit1555"] > 0) & (panel["adv20"] > 0)].copy()
    panel["confirmed"] = (
        panel["gap"].abs().ge(0.02) & panel["rvol930"].ge(1.5) & panel["first5_ret"].abs().ge(0.0025)
        & np.sign(panel["gap"]).eq(np.sign(panel["first5_ret"]))
    )
    return mapped_news, panel, paths


def variant_signals(panel: pd.DataFrame, variant: dict[str, object]) -> pd.DataFrame:
    signals = panel[panel["confirmed"] & panel["article_count"].ge(int(variant["min_articles"]))].copy()
    if variant["publisher"] == "GlobeNewswire Inc.":
        signals = signals[signals["wire_article_count"].ge(1)].copy()
    signals["direction"] = (np.sign(signals["gap"]) * int(variant["direction"])).astype(int)
    signals["variant"] = str(variant["variant"])
    return signals.sort_values(["date", "ticker"])


def simulate(signals: pd.DataFrame, sessions: list[pd.Timestamp], scenario: str, cost_bps_per_side: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cost_rate = cost_bps_per_side / 10_000.0
    signal_by_date = {date: group for date, group in signals.groupby("date", sort=True)}
    equity = START_CAPITAL
    daily_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    contrib_rows: list[dict[str, object]] = []
    for date in sessions:
        day_start = equity
        candidates = signal_by_date.get(date, signals.iloc[0:0]).copy()
        requested_each = equity * 0.03
        if requested_each > 0 and not candidates.empty:
            candidates = candidates[(requested_each / candidates["adv20"]).le(0.01)].copy()
        scale = min(1.0, equity / (requested_each * len(candidates))) if requested_each > 0 and len(candidates) else 0.0
        total_gross = 0.0
        for row in candidates.itertuples(index=False):
            entry_notional = requested_each * scale
            shares = float(row.direction) * entry_notional / float(row.entry935)
            exit_notional = abs(shares * float(row.exit1555))
            gross_pnl = shares * (float(row.exit1555) - float(row.entry935))
            trade_cost = (entry_notional + exit_notional) * cost_rate
            borrow_cost = entry_notional * 0.01 / 252.0 if shares < 0 else 0.0
            net_pnl = gross_pnl - trade_cost - borrow_cost
            equity += net_pnl
            total_gross += entry_notional
            common = {
                "scenario": scenario, "date": date, "ticker": row.ticker, "direction": int(row.direction),
                "article_count": int(row.article_count), "wire_article_count": int(row.wire_article_count),
                "gap": float(row.gap), "first5_ret": float(row.first5_ret), "rvol930": float(row.rvol930),
                "entry935": float(row.entry935), "exit1555": float(row.exit1555), "shares": shares,
                "entry_notional": entry_notional, "exit_notional": exit_notional, "gross_pnl": gross_pnl,
                "trade_cost": trade_cost, "borrow_cost": borrow_cost, "net_pnl": net_pnl,
            }
            trade_rows.append(common)
            contrib_rows.append({"scenario": scenario, "date": date, "ticker": row.ticker, "pnl": net_pnl})
        daily_rows.append({
            "scenario": scenario, "date": date, "daily_pnl": equity - day_start, "equity": equity,
            "gross": total_gross / max(day_start, 1e-9), "entries": len(candidates),
        })
    return pd.DataFrame(daily_rows), pd.DataFrame(trade_rows), pd.DataFrame(contrib_rows)


def concentration(contrib: pd.DataFrame, total_pnl: float) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False) if not contrib.empty else pd.Series(dtype=float)
    positive = by_ticker[by_ticker > 0]
    effective = float(positive.sum() ** 2 / positive.pow(2).sum()) if not positive.empty else 0.0
    result: dict[str, object] = {
        "tickers": int(len(by_ticker)), "effectiveTickerCount": effective,
        "topTicker": str(by_ticker.index[0]) if len(by_ticker) else None,
    }
    for count in (1, 3, 5, 10):
        value = float(by_ticker.head(count).sum()) if len(by_ticker) else 0.0
        result[f"top{count}Pnl"] = value
        result[f"top{count}Share"] = value / total_pnl if total_pnl > 0 else np.nan
        result[f"top{count}PositivePoolShare"] = value / positive.sum() if not positive.empty else np.nan
    return result


def yearly_rows(daily: pd.DataFrame, run_scope: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (scenario, year), group in daily.groupby(["scenario", daily["date"].dt.year], sort=True):
        stats = performance(group.reset_index(drop=True))
        rows.append({"scenario": scenario, "run_scope": run_scope, "year": int(year), **stats})
    return rows


def evaluate_stage(stage: str, start: pd.Timestamp, end: pd.Timestamp, variants: list[dict[str, object]], daily_features: pd.DataFrame, intra: pd.DataFrame, top500: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[Path]]:
    mapped_news, panel, paths = build_panel(start, end, daily_features, intra, top500)
    sessions = sorted(intra[(intra["date"] >= start) & (intra["date"] <= end)]["date"].drop_duplicates())
    summary_rows: list[dict[str, object]] = []
    daily_frames: list[pd.DataFrame] = []
    trade_frames: list[pd.DataFrame] = []
    contrib_frames: list[pd.DataFrame] = []
    signal_frames: list[pd.DataFrame] = []
    for order, variant in enumerate(variants):
        signals = variant_signals(panel, variant)
        base_scenario = f"{variant['variant']}_cost4"
        stress_scenario = f"{variant['variant']}_cost8"
        base_daily, base_trades, base_contrib = simulate(signals, sessions, base_scenario, 4.0)
        stress_daily, _, _ = simulate(signals, sessions, stress_scenario, 8.0)
        stats = performance(base_daily)
        stress = performance(stress_daily)
        conc = concentration(base_contrib, float(stats["pnl"]))
        pnl_2021 = float(base_daily.loc[base_daily["date"].dt.year.eq(2021), "daily_pnl"].sum())
        pnl_2022 = float(base_daily.loc[base_daily["date"].dt.year.eq(2022), "daily_pnl"].sum())
        row = {
            "variant": variant["variant"], "order": order, **stats, "pnl2021Partial": pnl_2021,
            "pnl2022": pnl_2022, "stressPnl": stress["pnl"], "stressCagr": stress["cagr"], **conc,
        }
        if stage == "development":
            row["developmentPass"] = bool(
                stats["entries"] >= 100 and stats["cagr"] >= 0.03 and stats["sharpe"] >= 0.75
                and stats["ddPct"] >= -0.08 and pnl_2021 > 0 and pnl_2022 > 0 and stress["pnl"] > 0
                and conc["top1Share"] <= 0.25 and conc["top5Share"] <= 0.60
            )
        else:
            row["validationPass"] = bool(
                stats["cagr"] > 0 and stats["sharpe"] >= 0.50 and stats["ddPct"] >= -0.12
                and float(base_daily.loc[base_daily["date"].dt.year.eq(2023), "daily_pnl"].sum()) > 0
                and stress["pnl"] > 0
            )
        summary_rows.append(row)
        daily_frames.extend([base_daily, stress_daily])
        if not base_trades.empty:
            trade_frames.append(base_trades)
            contrib_frames.append(base_contrib)
        signal_frames.append(signals)
    return (
        pd.DataFrame(summary_rows), pd.concat(daily_frames, ignore_index=True),
        pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame(),
        pd.concat(contrib_frames, ignore_index=True) if contrib_frames else pd.DataFrame(),
        pd.concat(signal_frames, ignore_index=True) if signal_frames else pd.DataFrame(), paths,
    )


def main() -> None:
    daily_features, intra = load_feature_panels()
    top500 = load_top500()
    development, dev_daily, dev_trades, dev_contrib, dev_signals, used_paths = evaluate_stage(
        "development", DEV_START, DEV_END, VARIANTS, daily_features, intra, top500
    )
    passing = development[development["developmentPass"]].copy()
    validation = pd.DataFrame()
    val_daily = pd.DataFrame()
    val_trades = pd.DataFrame()
    val_contrib = pd.DataFrame()
    val_signals = pd.DataFrame()
    if passing.empty:
        selection = {"selectedVariant": None, "status": "KILL_NO_DEVELOPMENT_PASS", "validationOpened": False, "productionPassAllowed": False}
    else:
        selected_name = passing.sort_values(["sharpe", "cagr", "ddPct", "order"], ascending=[False, False, False, True]).iloc[0]["variant"]
        selected_variant = [variant for variant in VARIANTS if variant["variant"] == selected_name]
        validation, val_daily, val_trades, val_contrib, val_signals, val_paths = evaluate_stage(
            "validation", VAL_START, VAL_END, selected_variant, daily_features, intra, top500
        )
        used_paths.extend(val_paths)
        val_pass = bool(validation.iloc[0]["validationPass"])
        selection = {
            "selectedVariant": selected_name, "status": "NEEDS_AUDIT" if val_pass else "KILL_VALIDATION_FAIL",
            "validationOpened": True, "validationPass": val_pass, "productionPassAllowed": False,
        }

    all_daily = pd.concat([frame for frame in (dev_daily, val_daily) if not frame.empty], ignore_index=True)
    all_trades = pd.concat([frame for frame in (dev_trades, val_trades) if not frame.empty], ignore_index=True) if not dev_trades.empty or not val_trades.empty else pd.DataFrame()
    all_contrib = pd.concat([frame for frame in (dev_contrib, val_contrib) if not frame.empty], ignore_index=True) if not dev_contrib.empty or not val_contrib.empty else pd.DataFrame()
    all_signals = pd.concat([frame for frame in (dev_signals, val_signals) if not frame.empty], ignore_index=True)
    yearly = pd.DataFrame(yearly_rows(dev_daily, "development") + (yearly_rows(val_daily, "touched_validation") if not val_daily.empty else []))
    qa_rows = []
    ledger_scenarios = sorted(all_trades["scenario"].unique()) if not all_trades.empty else []
    for scenario in ledger_scenarios:
        group = all_daily[all_daily["scenario"].eq(scenario)]
        trades = all_trades[all_trades["scenario"].eq(scenario)]
        contrib = all_contrib[all_contrib["scenario"].eq(scenario)]
        qa_rows.append({
            "scenario": scenario, "dailyPnl": group["daily_pnl"].sum(),
            "endingDelta": group.iloc[-1]["equity"] - START_CAPITAL,
            "tradePnl": trades["net_pnl"].sum() if not trades.empty else 0.0,
            "contribPnl": contrib["pnl"].sum() if not contrib.empty else 0.0,
        })
    qa = pd.DataFrame(qa_rows)
    if not qa.empty:
        qa["dailyMinusEnding"] = qa["dailyPnl"] - qa["endingDelta"]
        qa["dailyMinusTrades"] = qa["dailyPnl"] - qa["tradePnl"]
        qa["dailyMinusContrib"] = qa["dailyPnl"] - qa["contribPnl"]

    development.to_csv(f"{PREFIX}_DEVELOPMENT.csv", index=False)
    validation.to_csv(f"{PREFIX}_VALIDATION.csv", index=False)
    Path(f"{PREFIX}_SELECTION.json").write_text(json.dumps(selection, indent=2), encoding="utf-8")
    all_signals.to_csv(f"{PREFIX}_SIGNALS.csv", index=False)
    all_daily.to_csv(f"{PREFIX}_DAILY.csv", index=False)
    all_trades.to_csv(f"{PREFIX}_TRADES.csv", index=False)
    all_contrib.to_csv(f"{PREFIX}_TICKER_CONTRIB.csv", index=False)
    yearly.to_csv(f"{PREFIX}_YEARLY.csv", index=False)
    qa.to_csv(f"{PREFIX}_QA.csv", index=False)
    inputs = list(dict.fromkeys(used_paths + [DAILY_FEATURES, INTRADAY_FEATURES, MARKET_CAP, ELIGIBLE, PREREG]))
    manifest = {
        "script": "raits/research/stocks_polygon_news_reaction.py", "scriptHash": file_hash(Path(__file__)),
        "preregistration": str(PREREG), "preregistrationHash": file_hash(PREREG),
        "inputHashes": {str(path).replace("\\", "/"): file_hash(path) for path in inputs},
        "developmentPeriod": [str(DEV_START.date()), str(DEV_END.date())],
        "validationPeriodIfOpened": [str(VAL_START.date()), str(VAL_END.date())],
        "selection": selection, "oos2025_2026Consumed": False, "oldManual62Used": False,
        "ruleSelectionEffect": "At most one of four pre-registered rules is selected on development; validation cannot replace it.",
        "tradeSelectionEffect": "News timing, PIT top500 membership, daily eligibility, ADV, exact prices, sizing, gross cap, and costs are replayed.",
        "outputs": [
            f"{PREFIX}_DEVELOPMENT.csv", f"{PREFIX}_VALIDATION.csv", f"{PREFIX}_SELECTION.json",
            f"{PREFIX}_SIGNALS.csv", f"{PREFIX}_DAILY.csv", f"{PREFIX}_TRADES.csv",
            f"{PREFIX}_TICKER_CONTRIB.csv", f"{PREFIX}_YEARLY.csv", f"{PREFIX}_QA.csv", f"{PREFIX}_MANIFEST.json",
        ],
    }
    Path(f"{PREFIX}_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(development.sort_values(["developmentPass", "sharpe", "cagr"], ascending=[False, False, False]).to_string(index=False))
    print(validation.to_string(index=False))
    print(json.dumps(selection, indent=2))


if __name__ == "__main__":
    main()
