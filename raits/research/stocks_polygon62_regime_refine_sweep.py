from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine
import stocks_polygon62_regime_overlay_sweep as overlay
import stocks_polygon_2018_2024_no_ml_pipeline as poly


PORTFOLIO = "B_polygon62_no_intraday_cap40"
BASE_CFG = poly.LEAD_PORTFOLIOS[PORTFOLIO]
START_CAPITAL = poly.START_CAPITAL
COST_BPS = 4.0

OUT = Path("STOCKS_POLYGON62_REGIME_REFINE_SWEEP_2018_2024.csv")
YEARLY_OUT = Path("STOCKS_POLYGON62_REGIME_REFINE_YEARLY_2018_2024.csv")


def max_drawdown(equity: pd.Series) -> float:
    return float((equity - equity.cummax()).min())


def nth_exit_dates(px: pd.DataFrame, hold: int) -> pd.DataFrame:
    out = px[["date", "ticker"]].drop_duplicates().sort_values(["ticker", "date"]).copy()
    out[f"exit_date_{hold}"] = out.groupby("ticker")["date"].shift(-(hold - 1))
    return out


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily_px, signals = overlay.load_inputs()
    exit5 = nth_exit_dates(daily_px, 5)
    exit10 = nth_exit_dates(daily_px, 10)
    signals = signals.merge(exit5, on=["date", "ticker"], how="left")
    signals = signals.merge(exit10, on=["date", "ticker"], how="left")
    return daily_px, signals


def apply_action(day_signals: pd.DataFrame, condition: str, action: str, throttle: float, hold: int, sleeves: set[str]) -> pd.DataFrame:
    out = day_signals.copy()
    mask = out["sleeve"].isin(sleeves) & out[condition].astype(bool)
    if action == "throttle":
        out["regime_mult"] = 1.0
        out.loc[mask, "regime_mult"] = throttle
    elif action == "hold":
        out["regime_mult"] = 1.0
        exit_col = f"exit_date_{hold}"
        out.loc[mask & out[exit_col].notna(), "exit_date"] = out.loc[mask & out[exit_col].notna(), exit_col]
        out.loc[mask & out[exit_col].notna(), "hold_days"] = hold
    elif action == "throttle_hold":
        out["regime_mult"] = 1.0
        out.loc[mask, "regime_mult"] = throttle
        exit_col = f"exit_date_{hold}"
        out.loc[mask & out[exit_col].notna(), "exit_date"] = out.loc[mask & out[exit_col].notna(), exit_col]
        out.loc[mask & out[exit_col].notna(), "hold_days"] = hold
    else:
        raise ValueError(action)
    out["regime_hit"] = mask
    return out


def simulate_variant(
    name: str,
    condition: str,
    action: str,
    sleeves: set[str],
    throttle: float,
    hold: int,
    signals: pd.DataFrame,
    daily_px: pd.DataFrame,
) -> tuple[dict[str, object], pd.DataFrame]:
    weights: dict[str, float] = BASE_CFG["weights"]  # type: ignore[assignment]
    cost_rate = COST_BPS / 10_000.0
    ticker_cap_pct = float(BASE_CFG["ticker_cap_pct"])
    gross_cap = float(BASE_CFG["gross_cap"])

    dates = sorted(daily_px["date"].drop_duplicates())
    price_by_date = {d: x.set_index("ticker") for d, x in daily_px.groupby("date")}
    sig = signals[signals["sleeve"].isin(weights)].copy()
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
    hit_days: set[pd.Timestamp] = set()

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
            day_signals = apply_action(day_signals, condition, action, throttle, hold, sleeves)
            if bool(day_signals["regime_hit"].any()):
                hit_days.add(date)
            day_signals["target_notional"] = 0.0
            for sleeve, group in day_signals.groupby("sleeve"):
                sleeve_gross = float(weights[str(sleeve)])
                group_hold = group["hold_days"].replace(0, 1).astype(float)
                day_budget = equity_open * sleeve_gross / group_hold
                day_signals.loc[group.index, "target_notional"] = day_budget / len(group) * group["regime_mult"].astype(float)

            target_by_ticker = day_signals.groupby("ticker")["target_notional"].sum()
            cap_abs = ticker_cap_pct * equity_open
            ticker_scale = (cap_abs / target_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
            day_signals["target_notional"] *= day_signals["ticker"].map(ticker_scale).astype(float)

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
                        "entry_notional": notional,
                        "regime_hit": bool(s["regime_hit"]),
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
        "action": action,
        "sleeves": "+".join(sorted(sleeves)),
        "throttle": throttle,
        "hold": hold,
        "hitDays": len(hit_days),
        "pnl": pnl,
        "cagr": (ending / START_CAPITAL) ** (1 / years) - 1,
        "dd": max_drawdown(eq["equity"]),
        "sharpe": float(eq["daily_pnl"].mean() / eq["daily_pnl"].std() * np.sqrt(252)),
        "avgGross": float(eq["gross"].mean()),
        "maxGross": float(eq["gross"].max()),
        "cashNegativeDays": int((eq["cash"] < 0).sum()),
        "closedTrades": int(tr["pnl"].notna().sum()) if "pnl" in tr.columns else 0,
        "y2018": float(yearly.get(2018, 0.0)),
        "y2019": float(yearly.get(2019, 0.0)),
        "y2020": float(yearly.get(2020, 0.0)),
        "y2021": float(yearly.get(2021, 0.0)),
        "y2022": float(yearly.get(2022, 0.0)),
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }
    return summary, eq


def main() -> None:
    daily_px, signals = load_inputs()
    rows: list[dict[str, object]] = []
    yearly_rows: list[dict[str, object]] = []
    sleeve_sets = {
        "broad": {"broad_adv10_g2_dd85"},
        "local": {"local_xs_full_s10"},
        "broad_local": {"broad_adv10_g2_dd85", "local_xs_full_s10"},
    }
    variants: list[tuple[str, str, set[str], float, int]] = []
    for condition in ["vol20_020", "prev_down_1", "bear_stack", "below_ma50"]:
        for sleeve_name, sleeves in sleeve_sets.items():
            for throttle in [0.5, 0.75]:
                variants.append((condition, f"throttle_{sleeve_name}", sleeves, throttle, 20))
            for hold in [5, 10]:
                variants.append((condition, f"hold_{sleeve_name}", sleeves, 1.0, hold))
            variants.append((condition, f"throttle75_hold10_{sleeve_name}", sleeves, 0.75, 10))

    for condition, action_name, sleeves, throttle, hold in variants:
        action = "throttle_hold" if action_name.startswith("throttle75_hold") else ("hold" if action_name.startswith("hold") else "throttle")
        name = f"{PORTFOLIO}_{condition}_{action_name}"
        summary, eq = simulate_variant(name, condition, action, sleeves, throttle, hold, signals, daily_px)
        rows.append(summary)
        for year, group in eq.assign(year=eq["date"].dt.year).groupby("year"):
            yearly_rows.append(
                {
                    "portfolio": name,
                    "condition": condition,
                    "action": action_name,
                    "year": int(year),
                    "pnl": float(group["daily_pnl"].sum()),
                    "ddSubset": max_drawdown(START_CAPITAL + group["daily_pnl"].cumsum()),
                    "sharpe": float(group["daily_pnl"].mean() / group["daily_pnl"].std() * np.sqrt(252))
                    if group["daily_pnl"].std() > 0
                    else np.nan,
                }
            )
        print(
            "REFINE",
            condition,
            action_name,
            f"pnl={summary['pnl']:.2f}",
            f"y2022={summary['y2022']:.2f}",
            f"dd={summary['dd']:.2f}",
            flush=True,
        )
    pd.DataFrame(rows).to_csv(OUT, index=False)
    pd.DataFrame(yearly_rows).to_csv(YEARLY_OUT, index=False)
    print("WROTE", OUT, YEARLY_OUT)


if __name__ == "__main__":
    main()
