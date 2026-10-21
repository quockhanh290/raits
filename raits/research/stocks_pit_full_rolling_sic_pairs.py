from __future__ import annotations

from pathlib import Path

import json
import math

import numpy as np
import pandas as pd


OUT_PREFIX = "STOCKS_PIT_FULL_ROLLING_SIC_PAIRS_2026-09-17"
DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_PIT_FULL_2018_2024_NOWARMUP.pkl")
MARKET_CAP_CSV = Path(
    "raits/data/cache/external_universes/market_cap_polygon/"
    "polygon_market_cap_snapshots_pit_eligible_2018_2024.csv"
)

START = pd.Timestamp("2018-03-29")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 100_000.0
POOL_TOP_N = 500
FORMATION_DAYS = 120
MIN_OBSERVATIONS = 100
MIN_CORRELATION = 0.60
MAX_PAIRS_PER_SIC = 2
MAX_ACTIVE_PAIRS = 10
ENTRY_Z = 2.0
EXIT_Z = 0.5
TRADE_COST_BPS = 4.0
SHORT_BORROW_ANNUAL_RATE = 0.01

# Fixed before measuring. Pair parameters remain frozen until the next
# formation date; every trading decision is executed at the next 09:35 bar.
VARIANTS = [
    {"variant": "sic_pairs_monthly_z2_hold5", "frequency": "monthly", "max_hold": 5},
    {"variant": "sic_pairs_monthly_z2_hold10", "frequency": "monthly", "max_hold": 10},
    {"variant": "sic_pairs_quarterly_z2_hold10", "frequency": "quarterly", "max_hold": 10},
]

SUMMARY_OUT = Path(f"{OUT_PREFIX}_SUMMARY.csv")
YEARLY_OUT = Path(f"{OUT_PREFIX}_YEARLY.csv")
CONCENTRATION_OUT = Path(f"{OUT_PREFIX}_CONCENTRATION.csv")
DAILY_OUT = Path(f"{OUT_PREFIX}_DAILY.csv")
CONTRIB_OUT = Path(f"{OUT_PREFIX}_TICKER_CONTRIB.csv")
FORMATIONS_OUT = Path(f"{OUT_PREFIX}_FORMATIONS.csv")
SIGNALS_OUT = Path(f"{OUT_PREFIX}_SIGNALS.csv")
EVENTS_OUT = Path(f"{OUT_PREFIX}_TRADE_EVENTS.csv")
QA_OUT = Path(f"{OUT_PREFIX}_QA.csv")
MANIFEST_OUT = Path(f"{OUT_PREFIX}_MANIFEST.json")


def max_drawdown(equity: pd.Series) -> tuple[float, float]:
    peak = equity.cummax()
    return float((equity - peak).min()), float((equity / peak - 1.0).min())


def sharpe(pnl: pd.Series) -> float:
    std = float(pnl.std())
    return float(pnl.mean() / std * math.sqrt(252)) if std > 0 else float("nan")


def cagr(equity: pd.Series, dates: pd.Series) -> float:
    years = max((dates.max() - dates.min()).days / 365.25, 1e-9)
    return float((equity.iloc[-1] / START_CAPITAL) ** (1.0 / years) - 1.0)


def load_raw() -> pd.DataFrame:
    daily = pd.read_pickle(DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily["ticker"] = daily["ticker"].astype(str).str.upper()
    intra = pd.read_pickle(INTRADAY_0935)
    intra["date"] = pd.to_datetime(intra["date"]).dt.normalize()
    intra["ticker"] = intra["ticker"].astype(str).str.upper()
    x = daily[["date", "ticker", "close_1555", "prev_close_1555"]].merge(
        intra[["date", "ticker", "entry935"]], on=["date", "ticker"], how="inner"
    )
    x = x[(x["date"] >= START) & (x["date"] <= END)].copy()
    x = x.dropna(subset=["date", "ticker", "close_1555", "prev_close_1555", "entry935"])
    x = x[(x["close_1555"] > 0) & (x["prev_close_1555"] > 0) & (x["entry935"] > 0)].copy()
    x["daily_ret"] = x["close_1555"] / x["prev_close_1555"] - 1.0
    x["log_close"] = np.log(x["close_1555"])
    return x.sort_values(["date", "ticker"]).reset_index(drop=True)


def load_caps() -> pd.DataFrame:
    caps = pd.read_csv(MARKET_CAP_CSV, low_memory=False)
    caps["date"] = pd.to_datetime(caps["date"]).dt.normalize()
    caps["ticker"] = caps["ticker_query"].astype(str).str.upper()
    caps["market_cap"] = pd.to_numeric(caps["market_cap"], errors="coerce")
    caps["sic_bucket"] = caps["sic_description"].fillna("UNKNOWN").astype(str).str.upper()
    caps = caps[caps["status_code"].eq(200) & caps["market_cap"].notna()].copy()
    caps = caps.sort_values(["date", "market_cap"], ascending=[True, False])
    caps["rank_market_cap"] = caps.groupby("date")["market_cap"].rank(method="first", ascending=False)
    return caps[caps["rank_market_cap"].le(POOL_TOP_N)][["date", "ticker", "sic_bucket"]].rename(
        columns={"date": "snapshot_date"}
    )


def formation_dates(dates: list[pd.Timestamp], frequency: str) -> list[pd.Timestamp]:
    frame = pd.DataFrame({"date": dates})
    period = frame["date"].dt.to_period("M" if frequency == "monthly" else "Q")
    return frame.groupby(period, sort=True)["date"].max().tolist()


def members_for_date(caps: pd.DataFrame, date: pd.Timestamp) -> pd.DataFrame:
    available = caps[caps["snapshot_date"] <= date]
    if available.empty:
        return available
    snapshot = available["snapshot_date"].max()
    return available[available["snapshot_date"].eq(snapshot)][["ticker", "sic_bucket"]].copy()


def form_pairs(raw: pd.DataFrame, caps: pd.DataFrame, frequency: str) -> pd.DataFrame:
    dates = sorted(raw["date"].drop_duplicates())
    all_rows = []
    for form_date in formation_dates(dates, frequency):
        end_index = dates.index(form_date)
        if end_index + 1 < FORMATION_DAYS:
            continue
        window_dates = dates[end_index - FORMATION_DAYS + 1 : end_index + 1]
        window = raw[raw["date"].isin(window_dates)]
        members = members_for_date(caps, form_date)
        if members.empty:
            continue
        member_map = dict(zip(members["ticker"], members["sic_bucket"]))
        returns = window.pivot(index="date", columns="ticker", values="daily_ret")
        closes = window.pivot(index="date", columns="ticker", values="log_close")
        candidates = []
        for sic_bucket, bucket_members in members.groupby("sic_bucket", sort=True):
            tickers = [ticker for ticker in bucket_members["ticker"] if ticker in returns.columns]
            if len(tickers) < 2:
                continue
            valid = [ticker for ticker in tickers if returns[ticker].notna().sum() >= MIN_OBSERVATIONS]
            if len(valid) < 2:
                continue
            corr = returns[valid].corr(min_periods=MIN_OBSERVATIONS)
            for i, ticker_a in enumerate(valid):
                for ticker_b in valid[i + 1 :]:
                    value = corr.at[ticker_a, ticker_b]
                    if pd.notna(value) and value >= MIN_CORRELATION:
                        candidates.append((float(value), str(sic_bucket), ticker_a, ticker_b))

        candidates.sort(reverse=True)
        used: set[str] = set()
        count_by_sic: dict[str, int] = {}
        for correlation, sic_bucket, ticker_a, ticker_b in candidates:
            if ticker_a in used or ticker_b in used:
                continue
            if count_by_sic.get(sic_bucket, 0) >= MAX_PAIRS_PER_SIC:
                continue
            pair_data = pd.concat(
                [returns[ticker_a].rename("ret_a"), returns[ticker_b].rename("ret_b"), closes[ticker_a].rename("log_a"), closes[ticker_b].rename("log_b")],
                axis=1,
            ).dropna()
            if len(pair_data) < MIN_OBSERVATIONS or float(pair_data["ret_b"].var()) <= 0:
                continue
            beta = float(pair_data["ret_a"].cov(pair_data["ret_b"]) / pair_data["ret_b"].var())
            if not 0.25 <= beta <= 4.0:
                continue
            spread = pair_data["log_a"] - beta * pair_data["log_b"]
            spread_std = float(spread.std())
            if not np.isfinite(spread_std) or spread_std <= 0:
                continue
            all_rows.append(
                {
                    "frequency": frequency,
                    "formation_date": form_date,
                    "window_start": window_dates[0],
                    "window_end": window_dates[-1],
                    "sic_bucket": member_map[ticker_a],
                    "ticker_a": ticker_a,
                    "ticker_b": ticker_b,
                    "pair_id": f"{ticker_a}|{ticker_b}",
                    "correlation": correlation,
                    "beta": beta,
                    "spread_mean": float(spread.mean()),
                    "spread_std": spread_std,
                    "observations": int(len(pair_data)),
                }
            )
            used.update((ticker_a, ticker_b))
            count_by_sic[sic_bucket] = count_by_sic.get(sic_bucket, 0) + 1
    return pd.DataFrame(all_rows)


def build_signals(raw: pd.DataFrame, formations: pd.DataFrame, frequency: str) -> pd.DataFrame:
    dates = sorted(raw["date"].drop_duplicates())
    next_date = pd.Series(dates[1:], index=dates[:-1]).to_dict()
    prices_by_date = {date: group.set_index("ticker")["log_close"] for date, group in raw.groupby("date", sort=True)}
    freq_forms = formations[formations["frequency"].eq(frequency)]
    form_dates = sorted(freq_forms["formation_date"].drop_duplicates())
    rows = []
    for i, form_date in enumerate(form_dates):
        end_date = form_dates[i + 1] if i + 1 < len(form_dates) else pd.Timestamp.max
        pairs = freq_forms[freq_forms["formation_date"].eq(form_date)]
        active_dates = [date for date in dates if form_date <= date < end_date and date in next_date]
        for date in active_dates:
            prices = prices_by_date[date]
            for pair in pairs.itertuples(index=False):
                if pair.ticker_a not in prices.index or pair.ticker_b not in prices.index:
                    continue
                spread = float(prices[pair.ticker_a] - pair.beta * prices[pair.ticker_b])
                zscore = (spread - pair.spread_mean) / pair.spread_std
                rows.append(
                    {
                        "frequency": frequency,
                        "formation_date": form_date,
                        "signal_date": date,
                        "execution_date": next_date[date],
                        "pair_id": pair.pair_id,
                        "ticker_a": pair.ticker_a,
                        "ticker_b": pair.ticker_b,
                        "zscore": float(zscore),
                    }
                )
    return pd.DataFrame(rows)


def weights_from_active(active: dict[str, dict[str, object]]) -> pd.Series:
    if not active:
        return pd.Series(dtype=float)
    pair_gross = 1.0 / len(active)
    weights: dict[str, float] = {}
    for state in active.values():
        direction = int(state["direction"])
        ticker_a = str(state["ticker_a"])
        ticker_b = str(state["ticker_b"])
        weights[ticker_a] = weights.get(ticker_a, 0.0) + direction * pair_gross / 2.0
        weights[ticker_b] = weights.get(ticker_b, 0.0) - direction * pair_gross / 2.0
    return pd.Series(weights, dtype=float)


def simulate(
    raw: pd.DataFrame, signals: pd.DataFrame, spec: dict[str, object]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = sorted(raw["date"].drop_duplicates())
    prices_by_date = {date: group.set_index("ticker")["entry935"] for date, group in raw.groupby("date", sort=True)}
    decision_by_date = {date: group for date, group in signals.groupby("execution_date", sort=True)}
    equity = START_CAPITAL
    previous_prices = pd.Series(dtype=float)
    weights = pd.Series(dtype=float)
    active: dict[str, dict[str, object]] = {}
    rows = []
    contrib_rows = []
    event_rows = []

    for day_index, date in enumerate(dates):
        prices = prices_by_date[date]
        common = weights.index.intersection(prices.index).intersection(previous_prices.index)
        returns = prices.reindex(common) / previous_prices.reindex(common) - 1.0
        pnl_by_ticker = equity * weights.reindex(common) * returns if len(common) else pd.Series(dtype=float)
        short_gross = float(weights[weights < 0].abs().sum()) if not weights.empty else 0.0
        borrow_cost = equity * short_gross * SHORT_BORROW_ANNUAL_RATE / 252.0
        if borrow_cost > 0 and short_gross > 0:
            allocation = weights[weights < 0].abs() / short_gross * borrow_cost
            for ticker, cost in allocation.items():
                pnl_by_ticker.loc[ticker] = pnl_by_ticker.get(ticker, 0.0) - cost
        daily_pnl = float(pnl_by_ticker.sum()) if not pnl_by_ticker.empty else 0.0
        equity += daily_pnl

        decisions = decision_by_date.get(date, signals.iloc[0:0])
        decision_map = {row.pair_id: row for row in decisions.itertuples(index=False)}
        for pair_id, state in list(active.items()):
            signal = decision_map.get(pair_id)
            held_days = day_index - int(state["entry_index"])
            direction = int(state["direction"])
            reason = None
            if signal is None:
                reason = "formation_drop"
            elif abs(float(signal.zscore)) <= EXIT_Z or direction * float(signal.zscore) >= 0:
                reason = "mean_revert"
            elif held_days >= int(spec["max_hold"]):
                reason = "timeout"
            if reason:
                event_rows.append({"variant": spec["variant"], "date": date, "pair_id": pair_id, "event": "exit", "reason": reason, "zscore": float(signal.zscore) if signal else np.nan})
                del active[pair_id]

        slots = MAX_ACTIVE_PAIRS - len(active)
        if slots > 0 and not decisions.empty:
            candidates = decisions[~decisions["pair_id"].isin(active)].copy()
            candidates = candidates[candidates["zscore"].abs() >= ENTRY_Z]
            candidates["abs_z"] = candidates["zscore"].abs()
            candidates = candidates.sort_values(["abs_z", "pair_id"], ascending=[False, True]).head(slots)
            for signal in candidates.itertuples(index=False):
                direction = -1 if signal.zscore > 0 else 1
                active[signal.pair_id] = {
                    "ticker_a": signal.ticker_a,
                    "ticker_b": signal.ticker_b,
                    "direction": direction,
                    "entry_index": day_index,
                }
                event_rows.append({"variant": spec["variant"], "date": date, "pair_id": signal.pair_id, "event": "entry", "reason": "z_entry", "zscore": float(signal.zscore)})

        new_weights = weights_from_active(active)
        tickers = weights.index.union(new_weights.index)
        old_aligned = weights.reindex(tickers).fillna(0.0)
        new_aligned = new_weights.reindex(tickers).fillna(0.0)
        turnover = float((new_aligned - old_aligned).abs().sum())
        trade_cost = equity * turnover * TRADE_COST_BPS / 10_000.0
        equity -= trade_cost
        if turnover > 0:
            allocation = (new_aligned - old_aligned).abs() / turnover * trade_cost
            contrib_rows.extend(
                {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": -float(cost)}
                for ticker, cost in allocation.items()
            )
        contrib_rows.extend(
            {"variant": spec["variant"], "date": date, "ticker": ticker, "pnl": float(pnl)}
            for ticker, pnl in pnl_by_ticker.items()
            if float(pnl) != 0.0
        )
        weights = new_weights
        rows.append(
            {
                "variant": spec["variant"],
                "date": date,
                "daily_pnl": daily_pnl - trade_cost,
                "equity": equity,
                "trade_cost": trade_cost,
                "borrow_cost": borrow_cost,
                "turnover": turnover,
                "gross_exposure": float(weights.abs().sum()) if not weights.empty else 0.0,
                "net_exposure": float(weights.sum()) if not weights.empty else 0.0,
                "active_pairs": int(len(active)),
                "missing_positions": int(len(weights.index.difference(prices.index))),
            }
        )
        previous_prices = prices
    daily = pd.DataFrame(rows)
    daily["year"] = daily["date"].dt.year
    return daily, pd.DataFrame(contrib_rows), pd.DataFrame(event_rows)


def effective_ticker_count(by_ticker: pd.Series) -> float:
    positive = by_ticker[by_ticker > 0]
    source = positive if positive.sum() > 0 else by_ticker.abs()
    total = float(source.sum())
    if total <= 0:
        return 0.0
    weights = source / total
    return float(1.0 / weights.pow(2).sum())


def concentration_row(variant: str, contrib: pd.DataFrame) -> dict[str, object]:
    by_ticker = contrib.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(by_ticker.sum())
    denominator = total if total > 0 else float(by_ticker.abs().sum())
    row: dict[str, object] = {
        "variant": variant,
        "tickers": int(len(by_ticker)),
        "effectiveTickerCount": effective_ticker_count(by_ticker),
        "topTicker": str(by_ticker.index[0]) if not by_ticker.empty else "",
    }
    for n in (1, 3, 5, 10):
        top = float(by_ticker.head(n).sum()) if not by_ticker.empty else 0.0
        row[f"top{n}Pnl"] = top
        row[f"top{n}Share"] = top / denominator if denominator else float("nan")
    return row


def summary_row(spec: dict[str, object], daily: pd.DataFrame, events: pd.DataFrame) -> dict[str, object]:
    dd, dd_pct = max_drawdown(daily["equity"])
    pnl = float(daily["equity"].iloc[-1] - START_CAPITAL)
    trade_cost = float(daily["trade_cost"].sum())
    borrow_cost = float(daily["borrow_cost"].sum())
    return {
        "variant": spec["variant"],
        "frequency": spec["frequency"],
        "maxHold": int(spec["max_hold"]),
        "pnl": pnl,
        "grossPnlBeforeCostsBorrow": pnl + trade_cost + borrow_cost,
        "cagr": cagr(daily["equity"], daily["date"]),
        "ddDollar": dd,
        "ddPct": dd_pct,
        "sharpe": sharpe(daily["daily_pnl"]),
        "tradeCost": trade_cost,
        "borrowCost": borrow_cost,
        "avgGrossExposure": float(daily["gross_exposure"].mean()),
        "maxGrossExposure": float(daily["gross_exposure"].max()),
        "entries": int(events["event"].eq("entry").sum()) if not events.empty else 0,
    }


def yearly_rows(daily: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for (variant, year), group in daily.groupby(["variant", "year"], sort=True):
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
                "tradeCost": float(group["trade_cost"].sum()),
                "borrowCost": float(group["borrow_cost"].sum()),
            }
        )
    return rows


def main() -> None:
    raw = load_raw()
    caps = load_caps()
    formations = pd.concat(
        [form_pairs(raw, caps, "monthly"), form_pairs(raw, caps, "quarterly")], ignore_index=True
    )
    signals_by_frequency = {
        frequency: build_signals(raw, formations, frequency) for frequency in ("monthly", "quarterly")
    }
    summaries = []
    yearly = []
    concentration = []
    daily_frames = []
    contrib_frames = []
    event_frames = []
    qa_rows = []
    for spec in VARIANTS:
        signals = signals_by_frequency[str(spec["frequency"])]
        daily, contrib, events = simulate(raw, signals, spec)
        summaries.append(summary_row(spec, daily, events))
        yearly.extend(yearly_rows(daily))
        concentration.append(concentration_row(str(spec["variant"]), contrib))
        daily_frames.append(daily)
        contrib_frames.append(contrib)
        event_frames.append(events)
        qa_rows.append(
            {
                "variant": spec["variant"],
                "formationCount": int(formations[formations["frequency"].eq(spec["frequency"])]["formation_date"].nunique()),
                "avgPairsPerFormation": float(formations[formations["frequency"].eq(spec["frequency"])].groupby("formation_date").size().mean()),
                "maxMissingPositions": int(daily["missing_positions"].max()),
                "meanNetExposure": float(daily["net_exposure"].mean()),
                "maxAbsNetExposure": float(daily["net_exposure"].abs().max()),
            }
        )
        print("ROLLING_PAIRS", summaries[-1], flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.DataFrame(yearly).to_csv(YEARLY_OUT, index=False)
    pd.DataFrame(concentration).to_csv(CONCENTRATION_OUT, index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(DAILY_OUT, index=False)
    pd.concat(contrib_frames, ignore_index=True).to_csv(CONTRIB_OUT, index=False)
    formations.to_csv(FORMATIONS_OUT, index=False)
    pd.concat(signals_by_frequency.values(), ignore_index=True).to_csv(SIGNALS_OUT, index=False)
    pd.concat(event_frames, ignore_index=True).to_csv(EVENTS_OUT, index=False)
    pd.DataFrame(qa_rows).to_csv(QA_OUT, index=False)

    manifest = {
        "out_prefix": OUT_PREFIX,
        "script": "raits/research/stocks_pit_full_rolling_sic_pairs.py",
        "inputs": [str(DAILY_FEATURES).replace("\\", "/"), str(INTRADAY_0935).replace("\\", "/"), str(MARKET_CAP_CSV).replace("\\", "/")],
        "method": "Rolling PIT top500 same-SIC pairs; 120-session formation, frozen return-beta spread parameters, close signal and next-session 09:35 execution.",
        "pair_rules": {"formation_days": FORMATION_DAYS, "min_observations": MIN_OBSERVATIONS, "min_correlation": MIN_CORRELATION, "max_pairs_per_sic": MAX_PAIRS_PER_SIC, "ticker_reuse_per_formation": False},
        "trade_rules": {"entry_z": ENTRY_Z, "exit_z": EXIT_Z, "max_active_pairs": MAX_ACTIVE_PAIRS, "gross_cap": 1.0},
        "costs": f"{TRADE_COST_BPS} bps aggregate target-weight turnover and {SHORT_BORROW_ANNUAL_RATE:.1%} annual borrow on short gross.",
        "sample_label": "Research/touched 2018-2024 only; first valid formation requires 120 local sessions. 2023-2024 is touched, not clean unseen OOS. No 2025-2026 opened.",
        "leakage_controls": "Formation and frozen parameters use only sessions through formation close; signals execute next session at 09:35; PIT market-cap/SIC snapshots assigned backward; no old manual 62 list.",
        "rule_selection_effect": "None. Formation windows/frequencies, pair constraints, z thresholds, max holds, active-pair cap and costs were fixed before measuring.",
        "trade_selection_effect": "Pairs are fully re-formed from prior data at each scheduled formation; active positions are rebuilt by the state machine, not ticker-PnL subtraction.",
        "variants": VARIANTS,
        "outputs": [str(SUMMARY_OUT), str(YEARLY_OUT), str(CONCENTRATION_OUT), str(DAILY_OUT), str(CONTRIB_OUT), str(FORMATIONS_OUT), str(SIGNALS_OUT), str(EVENTS_OUT), str(QA_OUT)],
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, CONCENTRATION_OUT, DAILY_OUT, CONTRIB_OUT, FORMATIONS_OUT, SIGNALS_OUT, EVENTS_OUT, QA_OUT, MANIFEST_OUT, flush=True)


if __name__ == "__main__":
    main()
