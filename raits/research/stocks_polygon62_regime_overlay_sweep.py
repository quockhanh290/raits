from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import pickle

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine
import stocks_polygon_2018_2024_no_ml_pipeline as poly


PORTFOLIO = "B_polygon62_no_intraday_cap40"
BASE_CFG = poly.LEAD_PORTFOLIOS[PORTFOLIO]
START_CAPITAL = poly.START_CAPITAL
COST_BPS = 4.0

OUT = Path("STOCKS_POLYGON62_REGIME_OVERLAY_SWEEP_2018_2024.csv")
YEARLY_OUT = Path("STOCKS_POLYGON62_REGIME_OVERLAY_YEARLY_2018_2024.csv")


def max_drawdown(equity: pd.Series) -> float:
    return float((equity - equity.cummax()).min())


def spy_regimes() -> pd.DataFrame:
    with poly.BARS.open("rb") as f:
        bars = pickle.load(f)
    spy = bars["SPY"].copy().reset_index()
    spy = spy.rename(columns={spy.columns[0]: "ts"})
    spy["ts"] = pd.to_datetime(spy["ts"])
    spy["date"] = spy["ts"].dt.normalize()
    open_px = spy[spy["ts"].dt.strftime("%H:%M").eq("09:30")][["date", "open"]].rename(columns={"open": "spy_open"})
    close_px = spy[spy["ts"].dt.strftime("%H:%M").eq("15:55")][["date", "close"]].rename(columns={"close": "spy_close"})
    daily = open_px.merge(close_px, on="date", how="inner").sort_values("date").reset_index(drop=True)
    daily["spy_ret"] = daily["spy_close"].pct_change()
    daily["spy_prev_ret"] = daily["spy_ret"].shift(1)
    daily["spy_prev_close"] = daily["spy_close"].shift(1)
    daily["spy_prev_ma20"] = daily["spy_close"].rolling(20, min_periods=20).mean().shift(1)
    daily["spy_prev_ma50"] = daily["spy_close"].rolling(50, min_periods=50).mean().shift(1)
    daily["spy_prev_vol20"] = daily["spy_ret"].rolling(20, min_periods=20).std().shift(1)
    prev_peak = daily["spy_close"].cummax().shift(1)
    daily["spy_prev_dd"] = daily["spy_prev_close"] / prev_peak - 1.0
    daily["bear_stack"] = (daily["spy_prev_close"] < daily["spy_prev_ma20"]) & (daily["spy_prev_ma20"] < daily["spy_prev_ma50"])
    daily["below_ma50"] = daily["spy_prev_close"] < daily["spy_prev_ma50"]
    daily["dd10"] = daily["spy_prev_dd"] <= -0.10
    daily["dd15"] = daily["spy_prev_dd"] <= -0.15
    daily["prev_down_1"] = daily["spy_prev_ret"] <= -0.01
    daily["vol20_015"] = daily["spy_prev_vol20"] >= 0.015
    daily["vol20_020"] = daily["spy_prev_vol20"] >= 0.020
    daily["bear_or_dd10"] = daily["bear_stack"] | daily["dd10"]
    daily["bear_or_vol015"] = daily["bear_stack"] | daily["vol20_015"]
    return daily[
        [
            "date",
            "bear_stack",
            "below_ma50",
            "dd10",
            "dd15",
            "prev_down_1",
            "vol20_015",
            "vol20_020",
            "bear_or_dd10",
            "bear_or_vol015",
        ]
    ].copy()


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_pickle(poly.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily_px = poly.load_daily_prices_from_polygon(daily)
    intraday = pd.read_pickle(poly.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    intraday = intraday[["date", "ticker", "open930", "entry935", "exit1555"]]
    signals = poly.load_signals(daily_px, intraday)
    signals = signals[signals["sleeve"].isin(BASE_CFG["weights"])].copy()
    regimes = spy_regimes()
    signals = signals.merge(regimes, on="date", how="left")
    for col in regimes.columns:
        if col != "date":
            signals[col] = signals[col].fillna(False).astype(bool)
    return daily_px, signals


def simulate_overlay(
    name: str,
    condition: str,
    throttle: float,
    signals: pd.DataFrame,
    daily_px: pd.DataFrame,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    weights: dict[str, float] = BASE_CFG["weights"]  # type: ignore[assignment]
    ticker_cap_pct = float(BASE_CFG["ticker_cap_pct"])
    gross_cap = float(BASE_CFG["gross_cap"])
    cost_rate = COST_BPS / 10_000.0
    throttle_sleeves = {"broad_adv10_g2_dd85", "local_xs_full_s10"}

    dates = sorted(daily_px["date"].drop_duplicates())
    price_by_date = {d: x.set_index("ticker") for d, x in daily_px.groupby("date")}
    sig = signals.copy()
    sig["portfolio_weight"] = sig["sleeve"].map(weights).astype(float)
    sig["weighted_strength"] = sig["strength"] * sig["portfolio_weight"]
    sig_by_date = {d: x for d, x in sig.groupby("date")}
    same_day_exit = sig.dropna(subset=["exit_price_same_day"]).drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"])[
        "exit_price_same_day"
    ]

    positions: list[engine.Position] = []
    cash = START_CAPITAL
    last_equity = START_CAPITAL
    trade_id = 0
    eq_rows: list[dict[str, object]] = []
    tr_rows: list[dict[str, object]] = []
    throttled_days: set[pd.Timestamp] = set()

    for date in dates:
        price_day = price_by_date.get(date)
        if price_day is None:
            continue

        def price_for(ticker: str, field: str, fallback: float) -> float:
            if ticker in price_day.index and pd.notna(price_day.loc[ticker, field]):
                return float(price_day.loc[ticker, field])
            return fallback

        open_values = [p.side * p.shares * price_for(p.ticker, "open", p.last_price) for p in positions]
        equity_open = cash + float(np.sum(open_values))
        if equity_open <= 0:
            break
        gross_open = float(np.sum([abs(v) for v in open_values]))

        day_signals = sig_by_date.get(date, pd.DataFrame()).copy()
        if not day_signals.empty:
            day_signals["target_notional"] = 0.0
            for sleeve, group in day_signals.groupby("sleeve"):
                sleeve_gross = float(weights[str(sleeve)])
                hold = max(1.0, float(group["hold_days"].replace(0, 1).median()))
                day_budget = equity_open * sleeve_gross / hold
                mult = 1.0
                if str(sleeve) in throttle_sleeves and bool(group[condition].iloc[0]):
                    mult = throttle
                    throttled_days.add(date)
                day_signals.loc[group.index, "target_notional"] = mult * day_budget / len(group)

            target_by_ticker = day_signals.groupby("ticker")["target_notional"].sum()
            cap_abs = ticker_cap_pct * equity_open
            ticker_scale = (cap_abs / target_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
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
                    engine.Position(
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
                        "entry_notional": notional,
                        "throttled": bool(str(s["sleeve"]) in throttle_sleeves and bool(s[condition])),
                    }
                )

        remaining: list[engine.Position] = []
        realized = 0.0
        exit_cost = 0.0
        for p in positions:
            close_px = price_for(p.ticker, "close", p.last_price)
            if p.exit_date <= date:
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
                for row in reversed(tr_rows):
                    if row["trade_id"] == p.trade_id:
                        row["exit_date"] = date
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
    pnl = float(eq["equity"].iloc[-1] - START_CAPITAL)
    years = (eq["date"].max() - eq["date"].min()).days / 365.25
    ending = float(eq["equity"].iloc[-1])
    summary = {
        "portfolio": name,
        "condition": condition,
        "throttle": throttle,
        "throttledDays": len(throttled_days),
        "pnl": pnl,
        "cagr": (ending / START_CAPITAL) ** (1 / years) - 1,
        "dd": max_drawdown(eq["equity"]),
        "sharpe": float(eq["daily_pnl"].mean() / eq["daily_pnl"].std() * np.sqrt(252)),
        "avgGross": float(eq["gross"].mean()),
        "maxGross": float(eq["gross"].max()),
        "cashNegativeDays": int((eq["cash"] < 0).sum()),
        "y2018": float(yearly.get(2018, 0.0)),
        "y2019": float(yearly.get(2019, 0.0)),
        "y2020": float(yearly.get(2020, 0.0)),
        "y2021": float(yearly.get(2021, 0.0)),
        "y2022": float(yearly.get(2022, 0.0)),
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }
    return summary, eq, tr


def main() -> None:
    daily_px, signals = load_inputs()
    rows: list[dict[str, object]] = []
    yearly_rows: list[dict[str, object]] = []
    for condition in [
        "bear_stack",
        "below_ma50",
        "dd10",
        "dd15",
        "prev_down_1",
        "vol20_015",
        "vol20_020",
        "bear_or_dd10",
        "bear_or_vol015",
    ]:
        for throttle in [0.0, 0.25, 0.50, 0.75]:
            name = f"{PORTFOLIO}_{condition}_x{throttle:g}"
            summary, eq, _ = simulate_overlay(name, condition, throttle, signals, daily_px)
            rows.append(summary)
            for year, group in eq.assign(year=eq["date"].dt.year).groupby("year"):
                yearly_rows.append(
                    {
                        "portfolio": name,
                        "condition": condition,
                        "throttle": throttle,
                        "year": int(year),
                        "pnl": float(group["daily_pnl"].sum()),
                        "ddSubset": max_drawdown(START_CAPITAL + group["daily_pnl"].cumsum()),
                        "sharpe": float(group["daily_pnl"].mean() / group["daily_pnl"].std() * np.sqrt(252))
                        if group["daily_pnl"].std() > 0
                        else np.nan,
                    }
                )
            print("OVERLAY", condition, throttle, f"pnl={summary['pnl']:.2f}", f"y2022={summary['y2022']:.2f}", flush=True)
    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.DataFrame(yearly_rows).to_csv(YEARLY_OUT, index=False)
    print("WROTE", OUT, YEARLY_OUT)


if __name__ == "__main__":
    main()
