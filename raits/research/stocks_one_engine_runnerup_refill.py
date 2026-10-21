from __future__ import annotations

from pathlib import Path
import re

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine
import stocks_wfo_clean_retest as yday
import stocks_databento_daily_xs_mtm as broad_src


OUT = Path("STOCKS_ONE_ENGINE_NO_ML_RUNNERUP_REFILL_2026-09-09.csv")
DETAIL_OUT = Path("STOCKS_ONE_ENGINE_NO_ML_RUNNERUP_REFILL_DETAIL_2026-09-09.csv")

PORTFOLIOS = {
    "A_no_ml_all_cap40": engine.PORTFOLIOS["A_no_ml_all_cap40"],
    "B_no_ml_all_cap40": engine.PORTFOLIOS["B_no_ml_all_cap40"],
}


def build_yday_candidates() -> dict[str, pd.DataFrame]:
    daily = pd.read_pickle("raits/data/cache/stocks_clean_daily_features_2026-09-08.pkl")
    daily["date"] = pd.to_datetime(daily["date"])
    out: dict[str, pd.DataFrame] = {}
    for rule in yday.DECLARED_RULE_POOL:
        df = daily[daily["prev_dayret"] <= rule.yday_threshold].copy()
        if rule.gap_mode == "gapdown":
            df = df[df["gap"] < 0.0]
        elif rule.gap_mode == "no_deep_gap":
            df = df[df["gap"] >= -0.02]
        if rule.spy_mode == "spy_bigdown":
            df = df[df["spy_prev_dayret"] <= -0.01]
        if rule.mom20_mode == "mom20_pos":
            df = df[df["ret20_pre"] > 0.0]
        elif rule.mom20_mode == "mom20_neg":
            df = df[df["ret20_pre"] <= 0.0]
        df = df.sort_values(["date", "prev_dayret"]).copy()
        df["rule"] = rule.name
        df["entry_style"] = "entry935" if rule.needs_open_confirmation else "open930"
        out[rule.name] = df
    return out


def build_broad_candidates() -> pd.DataFrame:
    panel = broad_src.load_panel()
    data = panel.dropna(subset=["ret5", "adv20", "exit_date20"]).copy()
    data = data[
        (data["date"] >= engine.START)
        & (data["date"] <= engine.END)
        & (data["adv20"] >= 10_000_000.0)
        & (data["ret5"] >= -0.50)
    ].copy()
    return data.sort_values(["date", "ret5"]).rename(columns={"symbol": "ticker", "exit_date20": "exit_date"})


def build_local_candidates(daily_px: pd.DataFrame) -> pd.DataFrame:
    daily = pd.read_pickle("raits/data/cache/stocks_clean_daily_features_2026-09-08.pkl")
    daily["date"] = pd.to_datetime(daily["date"])
    daily = daily.sort_values(["ticker", "date"]).copy()
    g = daily.groupby("ticker", sort=False)
    prev_close = g["close_1555"].shift(1)
    daily["ret5_pre_clean"] = prev_close / g["close_1555"].shift(6) - 1.0
    daily["exit_date"] = g["date"].shift(-(20 - 1))
    data = daily[
        (daily["date"] >= engine.START)
        & (daily["date"] <= engine.END)
        & daily["ret5_pre_clean"].notna()
        & daily["exit_date"].notna()
        & (daily["open_0930"] > 0)
    ].copy()
    data = data.sort_values(["date", "ret5_pre_clean"]).copy()
    price = daily_px.rename(columns={"open": "daily_open", "close": "daily_close"})
    data = data.drop(columns=["daily_open", "daily_close"], errors="ignore").merge(
        price[["date", "ticker", "daily_open", "daily_close"]],
        on=["date", "ticker"],
        how="left",
    )
    data = data.dropna(subset=["daily_open", "daily_close"])
    return data


def build_intraday_candidates() -> pd.DataFrame:
    daily = pd.read_pickle("raits/data/cache/stocks_clean_daily_features_2026-09-08.pkl")
    daily["date"] = pd.to_datetime(daily["date"])
    keep = [
        "date",
        "ticker",
        "prev_dayret",
        "spy_prev_dayret",
        "gap",
        "ret20_pre",
        "vol20_pre",
    ]
    intraday = pd.read_pickle("raits/data/cache/stocks_intraday_0935_features_2026-09-08.pkl")
    intraday["date"] = pd.to_datetime(intraday["date"])
    df = intraday.merge(daily[keep], on=["date", "ticker"], how="left")
    df = df.rename(columns={"rvol930": "rvol", "ret935_eod": "target"})
    df = df[(df["date"] >= engine.START) & (df["date"] <= engine.END)].copy()
    for col in ["prev_dayret", "spy_prev_dayret", "gap", "rvol", "target", "entry935", "exit1555"]:
        df = df[df[col].notna()]
    return df


def intraday_rule_mask(pool: pd.DataFrame, rule: str) -> pd.DataFrame:
    x = pool.copy()
    m = re.match(r"rvol([0-9.]+)_gapup([0-9.]+)_short", rule)
    if m:
        rvol = float(m.group(1))
        gap = float(m.group(2))
        return x[(x["rvol"] >= rvol) & (x["gap"] >= gap)].sort_values(["date", "rvol", "gap"], ascending=[True, False, False])
    m = re.match(r"prevdown_(-?[0-9.]+)_spy_down_long", rule)
    if m:
        prev = float(m.group(1))
        return x[(x["prev_dayret"] <= prev) & (x["spy_prev_dayret"] <= 0.0)].sort_values(["date", "prev_dayret"])
    m = re.match(r"gapup_ge_([0-9.]+)_short", rule)
    if m:
        gap = float(m.group(1))
        return x[x["gap"] >= gap].sort_values(["date", "gap"], ascending=[True, False])
    return x.iloc[0:0].copy()


def copy_slot(template: pd.Series, ticker: str, entry_style: str, entry_price: float, exit_price: float, raw_strength: float) -> pd.Series:
    row = template.copy()
    row["ticker"] = ticker
    row["entry_style"] = entry_style
    row["exit_style"] = "exit1555"
    row["exit_date"] = pd.Timestamp(template["date"])
    row["entry_price"] = entry_price
    row["exit_price_same_day"] = exit_price
    row["raw_strength"] = raw_strength
    row["strength"] = 1.0
    row["daily_open"] = np.nan
    row["daily_close"] = np.nan
    return row


def make_replacements(
    removed: pd.DataFrame,
    signals: pd.DataFrame,
    mode: str,
    pools: dict[str, object],
    excluded_tickers: set[str] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    excluded_tickers = excluded_tickers or set()
    selected_by_date_sleeve = {
        (d, s): set(g["ticker"].astype(str))
        for (d, s), g in signals.groupby(["date", "sleeve"], sort=False)
    }
    replacements: list[pd.Series] = []
    details: list[dict[str, object]] = []

    yday_selected = pd.read_csv("STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_2026-09-08.csv", parse_dates=["date"])
    yday_selected = yday_selected[yday_selected["wfo_mode"].eq("rolling3")]
    intraday_trades = pd.read_csv("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_2026-09-08.csv", parse_dates=["date"])

    for _, rem in removed.iterrows():
        date = pd.Timestamp(rem["date"])
        ticker = str(rem["ticker"])
        sleeve = str(rem["sleeve"])
        template = signals[(signals["date"].eq(date)) & (signals["ticker"].eq(ticker)) & (signals["sleeve"].eq(sleeve))]
        if template.empty:
            details.append({"date": date, "sleeve": sleeve, "removed": ticker, "status": "missing_template"})
            continue
        tmpl = template.iloc[0]
        selected = selected_by_date_sleeve.get((date, sleeve), set())
        blocked = set(selected) | excluded_tickers
        cand = pd.DataFrame()
        method = ""

        if sleeve == "yday_ex6_actual" and mode in {"yday", "all"}:
            orig = yday_selected[(yday_selected["date"].eq(date)) & (yday_selected["ticker"].eq(ticker))]
            if not orig.empty:
                rule = str(orig.iloc[0]["rule"])
                pool = pools["yday"][rule]  # type: ignore[index]
                cand = pool[(pool["date"].eq(date)) & (~pool["ticker"].astype(str).isin(blocked))].head(1).copy()
                method = f"yday:{rule}"
                if not cand.empty:
                    c = cand.iloc[0]
                    entry_style = str(c["entry_style"])
                    entry_price = float(c["open_0935"] if entry_style == "entry935" else c["open_0930"])
                    exit_price = float(c["close_1555"])
                    replacements.append(copy_slot(tmpl, str(c["ticker"]), entry_style, entry_price, exit_price, 1.0))
        elif sleeve == "broad_adv10_g2_dd85" and mode == "all":
            pool = pools["broad"]  # type: ignore[assignment]
            cand = pool[(pool["date"].eq(date)) & (~pool["ticker"].astype(str).isin(blocked))].head(1).copy()
            method = "broad:ret5_next"
            if not cand.empty:
                c = cand.iloc[0]
                row = tmpl.copy()
                row["ticker"] = str(c["ticker"])
                row["exit_date"] = pd.Timestamp(c["exit_date"])
                row["entry_price"] = float(c["open"])
                row["daily_open"] = float(c["open"])
                row["daily_close"] = float(c["close"])
                row["raw_strength"] = -float(c["ret5"])
                row["strength"] = 1.0
                row["exit_price_same_day"] = np.nan
                replacements.append(row)
        elif sleeve == "local_xs_full_s10" and mode == "all":
            pool = pools["local"]  # type: ignore[assignment]
            cand = pool[(pool["date"].eq(date)) & (~pool["ticker"].astype(str).isin(blocked))].head(1).copy()
            method = "local:ret5_next_reconstructed"
            if not cand.empty:
                c = cand.iloc[0]
                row = tmpl.copy()
                row["ticker"] = str(c["ticker"])
                row["exit_date"] = pd.Timestamp(c["exit_date"])
                row["entry_price"] = float(c["daily_open"])
                row["daily_open"] = float(c["daily_open"])
                row["daily_close"] = float(c["daily_close"])
                row["raw_strength"] = -float(c["ret5_pre_clean"])
                row["strength"] = 1.0
                row["exit_price_same_day"] = np.nan
                replacements.append(row)
        elif sleeve == "intraday_ex10" and mode == "all":
            orig = intraday_trades[(intraday_trades["date"].eq(date)) & (intraday_trades["ticker"].eq(ticker))]
            if not orig.empty:
                rule = str(orig.sort_values("train_score", ascending=False).iloc[0]["rule"])
                pool = intraday_rule_mask(pools["intraday"], rule)  # type: ignore[arg-type]
                cand = pool[(pool["date"].eq(date)) & (~pool["ticker"].astype(str).isin(blocked))].head(1).copy()
                method = f"intraday_best_effort:{rule}"
                if not cand.empty:
                    c = cand.iloc[0]
                    replacements.append(
                        copy_slot(
                            tmpl,
                            str(c["ticker"]),
                            "entry935",
                            float(c["entry935"]),
                            float(c["exit1555"]),
                            float(orig["train_score"].max()),
                        )
                    )

        if cand.empty:
            status = "no_runnerup_or_not_in_mode"
        else:
            status = "replaced"
            selected_by_date_sleeve.setdefault((date, sleeve), set()).add(str(cand.iloc[0]["ticker"]))
        details.append({"date": date, "sleeve": sleeve, "removed": ticker, "status": status, "method": method})

    if not replacements:
        return signals.iloc[0:0].copy(), details
    repl = pd.DataFrame(replacements)
    return repl[signals.columns], details


def main() -> None:
    daily_px = engine.load_daily_prices()
    base_signals = engine.load_signals()
    base_trades = pd.read_csv(engine.TRADES_OUT, parse_dates=["date"])
    pools = {
        "yday": build_yday_candidates(),
        "broad": build_broad_candidates(),
        "local": build_local_candidates(daily_px),
        "intraday": build_intraday_candidates(),
    }

    rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    for portfolio, cfg in PORTFOLIOS.items():
        summary, _, _ = engine.simulate(f"{portfolio}_base", cfg, base_signals, daily_px)
        rows.append({"portfolio": portfolio, "mode": "base", "removeTopTrades": 0, "removed": 0, "replaced": 0, **summary})
        closed = base_trades[(base_trades["portfolio"].eq(portfolio)) & base_trades["pnl"].notna()].sort_values("pnl", ascending=False)
        for n in [10, 20, 50, 100]:
            removed = closed.head(n)[["date", "ticker", "sleeve"]].drop_duplicates()
            key = pd.MultiIndex.from_frame(removed)
            sig_key = pd.MultiIndex.from_frame(base_signals[["date", "ticker", "sleeve"]])
            stripped = base_signals.loc[~sig_key.isin(key)].copy()
            for mode in ["none", "yday", "all"]:
                signals = stripped.copy()
                details: list[dict[str, object]] = []
                if mode != "none":
                    repl, details = make_replacements(removed, base_signals, mode, pools)
                    if not repl.empty:
                        signals = pd.concat([signals, repl], ignore_index=True)
                summary, _, _ = engine.simulate(f"{portfolio}_top{n}_{mode}", cfg, signals, daily_px)
                replaced = sum(1 for d in details if d.get("status") == "replaced")
                rows.append(
                    {
                        "portfolio": portfolio,
                        "mode": mode,
                        "removeTopTrades": n,
                        "removed": int(len(removed)),
                        "replaced": int(replaced),
                        **summary,
                    }
                )
                for d in details:
                    d.update({"portfolio": portfolio, "mode": mode, "removeTopTrades": n})
                    detail_rows.append(d)
                print(portfolio, n, mode, "removed", len(removed), "replaced", replaced, "pnl", summary["pnl"], flush=True)

    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.DataFrame(detail_rows).to_csv(DETAIL_OUT, index=False)
    print("WROTE", OUT, DETAIL_OUT)


if __name__ == "__main__":
    main()
