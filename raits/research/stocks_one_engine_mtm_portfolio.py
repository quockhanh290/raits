from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


START = pd.Timestamp("2023-03-28")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 50_000.0
COST_BPS = 4.0

OUT = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_2026-09-09.csv")
EQUITY_OUT = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_EQUITY_2026-09-09.csv")
TRADES_OUT = Path("STOCKS_ONE_ENGINE_MTM_PORTFOLIO_TRADES_2026-09-09.csv")


PORTFOLIOS = {
    "A_no_ml_all_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
            "intraday_ex10": 0.40,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 2.0,
    },
    "A_no_ml_top40_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
            "intraday_ex10": 0.40,
        },
        "top_k": 40,
        "ticker_cap_pct": 0.40,
        "gross_cap": 2.0,
    },
    "B_no_ml_all_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
            "intraday_ex10": 0.35,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 1.75,
    },
    "B_no_ml_top40_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
            "intraday_ex10": 0.35,
        },
        "top_k": 40,
        "ticker_cap_pct": 0.40,
        "gross_cap": 1.75,
    },
    "A_no_ml_intraday_full_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
            "intraday_full": 0.40,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 2.0,
    },
    "B_no_ml_intraday_full_cap40": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
            "intraday_full": 0.35,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 1.75,
    },
}


@dataclass
class Position:
    trade_id: int
    sleeve: str
    ticker: str
    side: int
    shares: float
    entry_date: pd.Timestamp
    entry_price: float
    entry_notional: float
    exit_date: pd.Timestamp
    exit_style: str
    last_price: float


def max_drawdown(equity: pd.Series) -> float:
    return float((equity - equity.cummax()).min())


def load_daily_prices() -> pd.DataFrame:
    px = pd.read_parquet(
        "raits/data/cache/research_daily/databento_ohlcv1d.parquet",
        columns=["symbol", "date", "open", "close"],
    )
    px["date"] = pd.to_datetime(px["date"])
    px = px[(px["date"] >= START) & (px["date"] <= END)].copy()
    px = px.dropna(subset=["symbol", "date", "open", "close"])
    px = px[(px["open"] > 0) & (px["close"] > 0)]
    px["ticker"] = px["symbol"].astype(str)
    return px[["date", "ticker", "open", "close"]]


def load_intraday_prices() -> pd.DataFrame:
    intraday = pd.read_pickle("raits/data/cache/stocks_intraday_0935_features_CAUSEQA_2026-09-10.pkl")
    intraday["date"] = pd.to_datetime(intraday["date"])
    intraday = intraday[(intraday["date"] >= START) & (intraday["date"] <= END)].copy()
    intraday["ticker"] = intraday["ticker"].astype(str)
    return intraday[["date", "ticker", "open930", "entry935", "exit1555"]]


def nth_exit_dates(px: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = px[["date", "ticker"]].drop_duplicates().sort_values(["ticker", "date"]).copy()
    out[f"exit_date_{hold}"] = out.groupby("ticker")["date"].shift(-(hold - 1))
    return out


def infer_notional(pnl: pd.Series, ret: pd.Series) -> pd.Series:
    out = (pnl.astype(float) / ret.astype(float).replace(0.0, np.nan)).abs()
    med = float(out.replace([np.inf, -np.inf], np.nan).dropna().median()) if out.notna().any() else 0.0
    return out.replace([np.inf, -np.inf], np.nan).fillna(med)


def load_signals() -> pd.DataFrame:
    daily_px = load_daily_prices()
    intraday_px = load_intraday_prices()
    exit20 = nth_exit_dates(daily_px, 20)
    signals = []

    broad = pd.read_csv("STOCKS_DATABENTO_DAILY_XS_MTM_DD_OVERLAY_BEST_TRADES_2026-09-08.csv", parse_dates=["entry_date", "planned_exit_date"])
    broad = broad[(broad["entry_date"] >= START) & (broad["entry_date"] <= END)].copy()
    b = broad.rename(columns={"entry_date": "date", "symbol": "ticker", "planned_exit_date": "exit_date"})
    b["ticker"] = b["ticker"].astype(str)
    b["sleeve"] = "broad_adv10_g2_dd85"
    b["side"] = 1
    b["hold_days"] = 20
    b["entry_style"] = "daily_open"
    b["exit_style"] = "daily_close"
    b["base_notional"] = b["entry_notional"].astype(float)
    b["raw_strength"] = -b["ret5"].astype(float)
    signals.append(b[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    local = pd.read_csv("STOCKS_DAILY_XS_RET5_BOTTOM_H20_FULL_TRADES_REGEN_2026-09-09.csv", parse_dates=["date"])
    local = local[(local["date"] >= START) & (local["date"] <= END)].copy()
    local = local.merge(exit20, on=["date", "ticker"], how="left").rename(columns={"exit_date_20": "exit_date"})
    local["sleeve"] = "local_xs_full_s10"
    local["side"] = 1
    local["hold_days"] = 20
    local["entry_style"] = "daily_open"
    local["exit_style"] = "daily_close"
    local["base_pnl"] = local["pnl"].astype(float)
    local["base_notional"] = infer_notional(local["base_pnl"], local["ret"])
    local["raw_strength"] = -local["ret5_pre_clean"].astype(float)
    signals.append(local[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    yday = pd.read_csv("STOCKS_WFO_CLEAN_RETEST_MAX1_80_TRADES_CAUSEQA_2026-09-10.csv", parse_dates=["date"])
    yday = yday[(yday["date"] >= START) & (yday["date"] <= END) & (yday["wfo_mode"].eq("rolling3"))].copy()
    yday["sleeve"] = "yday_ex6_actual"
    yday["side"] = 1
    yday["hold_days"] = 0
    yday["entry_style"] = np.where(yday["entry_time"].astype(str).str.contains("09:35"), "entry935", "open930")
    yday["exit_style"] = "exit1555"
    yday["exit_date"] = yday["date"]
    yday["base_pnl"] = yday["pnl"].astype(float)
    yday["base_notional"] = infer_notional(yday["base_pnl"], yday["gross_ret"])
    yday["raw_strength"] = 1.0
    signals.append(yday[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    intraday = pd.read_csv("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_CAUSEQA_2026-09-10.csv", parse_dates=["date"])
    intraday = intraday[
        (intraday["date"] >= START)
        & (intraday["date"] <= END)
        & (intraday["dropSet"].astype(str).str.contains("DE", regex=False))
        & (intraday["slots"].eq(20))
    ].copy()
    intraday["sleeve"] = "intraday_ex10"
    intraday["side"] = np.where(intraday["side"].eq("short"), -1, 1)
    intraday["hold_days"] = 0
    intraday["entry_style"] = "entry935"
    intraday["exit_style"] = "exit1555"
    intraday["exit_date"] = intraday["date"]
    intraday["base_pnl"] = intraday["ret"].astype(float)
    intraday["base_notional"] = 1.0
    intraday["raw_strength"] = intraday["train_score"].astype(float)
    signals.append(intraday[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    intraday_full = pd.read_csv("STOCKS_INTRADAY_FOCUSED_RULES_TRADES_CAUSEQA_2026-09-10.csv", parse_dates=["date"])
    intraday_full = intraday_full[
        (intraday_full["date"] >= START)
        & (intraday_full["date"] <= END)
        & (intraday_full["dropSet"].eq("FULL"))
    ].copy()
    intraday_full["sleeve"] = "intraday_full"
    intraday_full["side"] = np.where(intraday_full["side"].eq("short"), -1, 1)
    intraday_full["hold_days"] = 0
    intraday_full["entry_style"] = "entry935"
    intraday_full["exit_style"] = "exit1555"
    intraday_full["exit_date"] = intraday_full["date"]
    intraday_full["base_pnl"] = intraday_full["ret"].astype(float)
    intraday_full["base_notional"] = 1.0
    intraday_full["raw_strength"] = intraday_full["train_score"].astype(float)
    signals.append(intraday_full[["date", "ticker", "sleeve", "side", "hold_days", "entry_style", "exit_style", "exit_date", "base_notional", "raw_strength"]])

    sig = pd.concat(signals, ignore_index=True)
    sig["date"] = pd.to_datetime(sig["date"])
    sig["exit_date"] = pd.to_datetime(sig["exit_date"])
    sig = sig.dropna(subset=["exit_date", "base_notional", "raw_strength"])
    sig = sig.drop_duplicates(["date", "ticker", "sleeve", "entry_style", "exit_style"])

    sig["strength"] = sig.groupby(["date", "sleeve"])["raw_strength"].rank(pct=True, method="average").fillna(1.0)

    daily_entry = daily_px.rename(columns={"open": "daily_open", "close": "daily_close"})
    sig = sig.merge(daily_entry, on=["date", "ticker"], how="left")
    sig = sig.merge(intraday_px, on=["date", "ticker"], how="left")

    sig["entry_price"] = np.nan
    sig.loc[sig["entry_style"].eq("daily_open"), "entry_price"] = sig.loc[sig["entry_style"].eq("daily_open"), "daily_open"]
    sig.loc[sig["entry_style"].eq("entry935"), "entry_price"] = sig.loc[sig["entry_style"].eq("entry935"), "entry935"]
    sig.loc[sig["entry_style"].eq("open930"), "entry_price"] = sig.loc[sig["entry_style"].eq("open930"), "open930"]
    sig["exit_price_same_day"] = sig["exit1555"]
    sig = sig.dropna(subset=["entry_price"])
    return sig


def simulate(name: str, cfg: dict[str, object], signals: pd.DataFrame, daily_px: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    weights: dict[str, float] = cfg["weights"]  # type: ignore[assignment]
    top_k: int | None = cfg["top_k"]  # type: ignore[assignment]
    ticker_cap_pct = float(cfg["ticker_cap_pct"])
    gross_cap = float(cfg["gross_cap"])
    dyn_lookback_days = int(cfg.get("dyn_lookback_days", 0))
    dyn_conc_limit = float(cfg.get("dyn_conc_limit", 1.0))
    dyn_ticker_cap_pct = float(cfg.get("dyn_ticker_cap_pct", ticker_cap_pct))
    cost_rate = COST_BPS / 10_000.0

    dates = sorted(daily_px["date"].drop_duplicates())
    price_by_date = {d: x.set_index("ticker") for d, x in daily_px.groupby("date")}
    signals = signals[signals["sleeve"].isin(weights)].copy()
    same_day_exit = signals.dropna(subset=["exit_price_same_day"]).drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"])[
        "exit_price_same_day"
    ]
    signals["portfolio_weight"] = signals["sleeve"].map(weights).astype(float)
    signals["weighted_strength"] = signals["strength"] * signals["portfolio_weight"]
    signals_by_date = {d: x for d, x in signals.groupby("date")}

    positions: list[Position] = []
    cash = START_CAPITAL
    last_equity = START_CAPITAL
    trade_id = 0
    eq_rows = []
    tr_rows = []
    realized_by_ticker: list[tuple[pd.Timestamp, str, float]] = []

    for date in dates:
        price_day = price_by_date.get(date)
        if price_day is None:
            continue

        def price_for(ticker: str, field: str, fallback: float) -> float:
            if ticker in price_day.index and pd.notna(price_day.loc[ticker, field]):
                return float(price_day.loc[ticker, field])
            return fallback

        open_values = []
        for p in positions:
            px = price_for(p.ticker, "open", p.last_price)
            open_values.append(p.side * p.shares * px)
        equity_open = cash + float(np.sum(open_values))
        if equity_open <= 0:
            break
        gross_open = float(np.sum([abs(v) for v in open_values]))

        day_signals = signals_by_date.get(date, pd.DataFrame()).copy()
        if not day_signals.empty:
            td_rank = (
                day_signals.groupby(["date", "ticker"])
                .agg(
                    sleeve_count=("sleeve", "nunique"),
                    weighted_strength=("weighted_strength", "sum"),
                    strength_avg=("strength", "mean"),
                )
                .reset_index()
            )
            td_rank["rank_score"] = td_rank["sleeve_count"] + td_rank["weighted_strength"]
            td_rank = td_rank.sort_values(["rank_score", "strength_avg"], ascending=[False, False])
            if top_k is not None:
                keep = set(td_rank.head(top_k)["ticker"])
                day_signals = day_signals[day_signals["ticker"].isin(keep)].copy()

            if not day_signals.empty:
                day_signals["target_notional"] = 0.0
                for sleeve, group in day_signals.groupby("sleeve"):
                    sleeve_gross = float(weights[str(sleeve)])
                    hold = max(1.0, float(group["hold_days"].replace(0, 1).median()))
                    day_budget = equity_open * sleeve_gross / hold
                    day_signals.loc[group.index, "target_notional"] = day_budget / len(group)

                target_by_ticker = day_signals.groupby("ticker")["target_notional"].sum()
                cap_pct_by_ticker = pd.Series(ticker_cap_pct, index=target_by_ticker.index, dtype=float)
                if dyn_lookback_days > 0 and realized_by_ticker:
                    cutoff = date - pd.Timedelta(days=dyn_lookback_days)
                    trail = pd.DataFrame(
                        [(d, t, p) for d, t, p in realized_by_ticker if d >= cutoff],
                        columns=["date", "ticker", "pnl"],
                    )
                    if not trail.empty:
                        abs_pnl = trail.assign(abs_pnl=trail["pnl"].abs()).groupby("ticker")["abs_pnl"].sum()
                        total_abs = float(abs_pnl.sum())
                        if total_abs > 0:
                            over = set(abs_pnl[abs_pnl / total_abs > dyn_conc_limit].index)
                            cap_pct_by_ticker.loc[cap_pct_by_ticker.index.isin(over)] = dyn_ticker_cap_pct
                cap_abs_by_ticker = cap_pct_by_ticker * equity_open
                ticker_scale = (cap_abs_by_ticker / target_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
                day_signals["ticker_scale"] = day_signals["ticker"].map(ticker_scale).astype(float)
                day_signals["target_notional"] *= day_signals["ticker_scale"]

                capacity = max(0.0, gross_cap * equity_open - gross_open)
                requested = float(day_signals["target_notional"].sum())
                gross_scale = min(1.0, capacity / requested) if requested > 0 else 1.0
                day_signals["target_notional"] *= gross_scale

                for _, s in day_signals.iterrows():
                    notional = float(s["target_notional"])
                    if notional <= 1.0:
                        continue
                    entry_px = float(s["entry_price"])
                    side = int(s["side"])
                    shares = notional / entry_px
                    entry_cost = notional * cost_rate
                    if side == 1:
                        cash -= notional + entry_cost
                    else:
                        cash += notional - entry_cost
                    trade_id += 1
                    positions.append(
                        Position(
                            trade_id=trade_id,
                            sleeve=str(s["sleeve"]),
                            ticker=str(s["ticker"]),
                            side=side,
                            shares=shares,
                            entry_date=date,
                            entry_price=entry_px,
                            entry_notional=notional,
                            exit_date=pd.Timestamp(s["exit_date"]),
                            exit_style=str(s["exit_style"]),
                            last_price=entry_px,
                        )
                    )
                    tr_rows.append(
                        {
                            "portfolio": name,
                            "trade_id": trade_id,
                            "date": date,
                            "ticker": str(s["ticker"]),
                            "sleeve": str(s["sleeve"]),
                            "side": side,
                            "entry_price": entry_px,
                            "entry_notional": notional,
                            "entry_cost": entry_cost,
                            "planned_exit_date": pd.Timestamp(s["exit_date"]),
                            "ticker_scale": float(s.get("ticker_scale", 1.0)),
                            "gross_scale": gross_scale,
                        }
                    )

        remaining: list[Position] = []
        exit_cost = 0.0
        realized = 0.0
        for p in positions:
            close_px = price_for(p.ticker, "close", p.last_price)
            if p.exit_date <= date:
                # Same-day sleeves exit at 15:55 if available; daily sleeves exit at close.
                if p.exit_style == "exit1555":
                    same_px = same_day_exit.get((date, p.ticker), np.nan)
                    if pd.notna(same_px):
                        close_px = float(same_px)
                value = p.shares * close_px
                cost = abs(value) * cost_rate
                if p.side == 1:
                    cash += value - cost
                    pnl = p.shares * (close_px - p.entry_price) - p.entry_notional * cost_rate - cost
                else:
                    cash -= value + cost
                    pnl = p.shares * (p.entry_price - close_px) - p.entry_notional * cost_rate - cost
                exit_cost += cost
                realized += pnl
                realized_by_ticker.append((date, p.ticker, pnl))
                for row in reversed(tr_rows):
                    if row["trade_id"] == p.trade_id:
                        row["exit_date"] = date
                        row["exit_price"] = close_px
                        row["pnl"] = pnl
                        break
            else:
                p.last_price = close_px
                remaining.append(p)
        positions = remaining

        close_values = []
        for p in positions:
            close_px = price_for(p.ticker, "close", p.last_price)
            p.last_price = close_px
            close_values.append(p.side * p.shares * close_px)
        equity_close = cash + float(np.sum(close_values))
        gross_close = float(np.sum([abs(v) for v in close_values]))
        daily_pnl = equity_close - last_equity
        last_equity = equity_close
        eq_rows.append(
            {
                "portfolio": name,
                "date": date,
                "equity": equity_close,
                "daily_pnl": daily_pnl,
                "cash": cash,
                "gross": gross_close / equity_close if equity_close > 0 else np.nan,
                "active_positions": len(positions),
                "exit_cost": exit_cost,
                "realized_exit_pnl": realized,
            }
        )

    eq = pd.DataFrame(eq_rows)
    tr = pd.DataFrame(tr_rows)
    yearly = eq.assign(year=eq["date"].dt.year).groupby("year")["daily_pnl"].sum()
    pnl = float(eq["equity"].iloc[-1] - START_CAPITAL) if not eq.empty else 0.0
    years = (eq["date"].max() - eq["date"].min()).days / 365.25 if not eq.empty else np.nan
    ending = float(eq["equity"].iloc[-1]) if not eq.empty else START_CAPITAL
    summary = {
        "portfolio": name,
        "start": eq["date"].min().date() if not eq.empty else "",
        "end": eq["date"].max().date() if not eq.empty else "",
        "years": years,
        "trades": int(len(tr)),
        "closedTrades": int(tr["pnl"].notna().sum()) if "pnl" in tr.columns else 0,
        "pnl": pnl,
        "ending": ending,
        "totalReturn": pnl / START_CAPITAL,
        "cagr": (ending / START_CAPITAL) ** (1 / years) - 1 if years and years > 0 else np.nan,
        "dd": max_drawdown(eq["equity"]) if not eq.empty else 0.0,
        "sharpe": float(eq["daily_pnl"].mean() / eq["daily_pnl"].std() * np.sqrt(252)) if not eq.empty and eq["daily_pnl"].std() > 0 else np.nan,
        "avgGross": float(eq["gross"].mean()) if not eq.empty else np.nan,
        "maxGross": float(eq["gross"].max()) if not eq.empty else np.nan,
        "avgActive": float(eq["active_positions"].mean()) if not eq.empty else np.nan,
        "maxActive": int(eq["active_positions"].max()) if not eq.empty else 0,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }
    return summary, eq, tr


def main() -> None:
    daily_px = load_daily_prices()
    signals = load_signals()
    summaries = []
    equities = []
    trades = []
    for name, cfg in PORTFOLIOS.items():
        summary, eq, tr = simulate(name, cfg, signals, daily_px)
        summaries.append(summary)
        equities.append(eq)
        trades.append(tr)
        print(name, summary, flush=True)
    pd.DataFrame(summaries).to_csv(OUT, index=False)
    pd.concat(equities, ignore_index=True).to_csv(EQUITY_OUT, index=False)
    pd.concat(trades, ignore_index=True).to_csv(TRADES_OUT, index=False)
    print("WROTE", OUT, EQUITY_OUT, TRADES_OUT)


if __name__ == "__main__":
    main()
