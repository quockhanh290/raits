from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine


DATE_TAG = "2026-09-09"
OUT = Path(f"STOCKS_ONE_ENGINE_CLEAN_NO_ML_CAUSAL_SIZING_{DATE_TAG}.csv")
TRADES_OUT = Path(f"STOCKS_ONE_ENGINE_CLEAN_NO_ML_CAUSAL_SIZING_BY_SLEEVE_{DATE_TAG}.csv")

NO_ML_SLEEVES = [
    "broad_adv10_g2_dd85",
    "local_xs_full_s10",
    "yday_ex6_actual",
    "intraday_ex10",
]

PORTFOLIO_GROSS_CAPS = {
    "A": 2.0,
    "B": 1.75,
}

CONTROL_MODES = {
    "open": {
        "overlap_mode": "allow",
        "active_ticker_cap_pct": None,
        "same_day_ticker_cap_pct": 0.40,
    },
    "balanced": {
        "overlap_mode": "strongest_only",
        "active_ticker_cap_pct": 0.20,
        "same_day_ticker_cap_pct": 0.20,
    },
    "strict": {
        "overlap_mode": "strongest_only",
        "active_ticker_cap_pct": 0.15,
        "same_day_ticker_cap_pct": 0.20,
    },
}


def max_drawdown(equity: pd.Series) -> float:
    return float((equity - equity.cummax()).min())


def concentration_metrics(trades: pd.DataFrame) -> dict[str, float | int | str]:
    closed = trades[trades["pnl"].notna()].copy()
    if closed.empty:
        return {
            "topTicker": "",
            "topTickerNetShare": np.nan,
            "top10NetShare": np.nan,
            "topTickerPositiveShare": np.nan,
            "top10PositiveShare": np.nan,
            "positiveHhi": np.nan,
            "effectivePositiveContributors": np.nan,
            "tickerDateCollisions": 0,
            "maxSleevesPerTickerDate": 0,
        }

    ticker_pnl = closed.groupby("ticker")["pnl"].sum().sort_values(ascending=False)
    total = float(closed["pnl"].sum())
    pos = ticker_pnl[ticker_pnl > 0]
    pos_sum = float(pos.sum())
    pos_shares = pos / pos_sum if pos_sum > 0 else pd.Series(dtype=float)
    collisions = trades.groupby(["date", "ticker"])["sleeve"].nunique()
    return {
        "topTicker": str(ticker_pnl.index[0]),
        "topTickerNetShare": float(ticker_pnl.iloc[0] / total) if total else np.nan,
        "top10NetShare": float(ticker_pnl.head(10).sum() / total) if total else np.nan,
        "topTickerPositiveShare": float(pos_shares.iloc[0]) if len(pos_shares) else np.nan,
        "top10PositiveShare": float(pos_shares.head(10).sum()) if len(pos_shares) else np.nan,
        "positiveHhi": float((pos_shares**2).sum()) if len(pos_shares) else np.nan,
        "effectivePositiveContributors": float(1.0 / (pos_shares**2).sum()) if len(pos_shares) and (pos_shares**2).sum() > 0 else np.nan,
        "tickerDateCollisions": int((collisions > 1).sum()),
        "maxSleevesPerTickerDate": int(collisions.max()) if len(collisions) else 0,
    }


def summarize(name: str, eq: pd.DataFrame, tr: pd.DataFrame) -> dict[str, object]:
    yearly = eq.assign(year=eq["date"].dt.year).groupby("year")["daily_pnl"].sum()
    pnl = float(eq["equity"].iloc[-1] - engine.START_CAPITAL) if not eq.empty else 0.0
    years = (eq["date"].max() - eq["date"].min()).days / 365.25 if not eq.empty else np.nan
    ending = float(eq["equity"].iloc[-1]) if not eq.empty else engine.START_CAPITAL
    return {
        "portfolio": name,
        "trades": int(len(tr)),
        "closedTrades": int(tr["pnl"].notna().sum()) if "pnl" in tr.columns else 0,
        "pnl": pnl,
        "ending": ending,
        "totalReturn": pnl / engine.START_CAPITAL,
        "cagr": (ending / engine.START_CAPITAL) ** (1 / years) - 1 if years and years > 0 and ending > 0 else np.nan,
        "dd": max_drawdown(eq["equity"]) if not eq.empty else 0.0,
        "sharpe": float(eq["daily_pnl"].mean() / eq["daily_pnl"].std() * np.sqrt(252)) if not eq.empty and eq["daily_pnl"].std() > 0 else np.nan,
        "avgGross": float(eq["gross"].mean()) if not eq.empty else np.nan,
        "maxGross": float(eq["gross"].max()) if not eq.empty else np.nan,
        "minCash": float(eq["cash"].min()) if not eq.empty else np.nan,
        "cashNegativeDays": int((eq["cash"] < 0).sum()) if not eq.empty else 0,
        "avgActive": float(eq["active_positions"].mean()) if not eq.empty else np.nan,
        "maxActive": int(eq["active_positions"].max()) if not eq.empty else 0,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
        **concentration_metrics(tr),
    }


def apply_overlap_mode(day_signals: pd.DataFrame, overlap_mode: str) -> pd.DataFrame:
    if overlap_mode == "allow" or day_signals.empty:
        return day_signals
    if overlap_mode != "strongest_only":
        raise ValueError(f"unknown overlap_mode: {overlap_mode}")
    idx = day_signals.groupby("ticker")["weighted_strength"].idxmax()
    return day_signals.loc[idx].copy()


def causal_targets(day_signals: pd.DataFrame, equity_open: float, sleeve_gross_targets: dict[str, float]) -> pd.Series:
    targets = pd.Series(0.0, index=day_signals.index, dtype=float)
    for sleeve, group in day_signals.groupby("sleeve"):
        sleeve_gross = sleeve_gross_targets[str(sleeve)]
        hold = max(1.0, float(group["hold_days"].replace(0, 1).median()))
        day_budget = equity_open * sleeve_gross / hold
        targets.loc[group.index] = day_budget / len(group)
    return targets


def simulate_causal(
    name: str,
    signals: pd.DataFrame,
    daily_px: pd.DataFrame,
    *,
    sleeve_gross_targets: dict[str, float],
    gross_cap: float,
    overlap_mode: str,
    active_ticker_cap_pct: float | None,
    same_day_ticker_cap_pct: float,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    cost_rate = engine.COST_BPS / 10_000.0
    dates = sorted(daily_px["date"].drop_duplicates())
    price_by_date = {d: x.set_index("ticker") for d, x in daily_px.groupby("date")}
    signals = signals[signals["sleeve"].isin(sleeve_gross_targets)].copy()
    same_day_exit = signals.dropna(subset=["exit_price_same_day"]).drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"])[
        "exit_price_same_day"
    ]
    signals["portfolio_weight"] = signals["sleeve"].map(sleeve_gross_targets).astype(float)
    signals["weighted_strength"] = signals["strength"] * signals["portfolio_weight"]
    signals_by_date = {d: x for d, x in signals.groupby("date")}

    positions: list[engine.Position] = []
    cash = engine.START_CAPITAL
    last_equity = engine.START_CAPITAL
    trade_id = 0
    eq_rows = []
    tr_rows = []

    for date in dates:
        price_day = price_by_date.get(date)
        if price_day is None:
            continue

        def price_for(ticker: str, field: str, fallback: float) -> float:
            if ticker in price_day.index and pd.notna(price_day.loc[ticker, field]):
                return float(price_day.loc[ticker, field])
            return fallback

        open_values = []
        active_gross_by_ticker: dict[str, float] = {}
        for p in positions:
            px = price_for(p.ticker, "open", p.last_price)
            open_value = p.side * p.shares * px
            open_values.append(open_value)
            active_gross_by_ticker[p.ticker] = active_gross_by_ticker.get(p.ticker, 0.0) + abs(open_value)
        equity_open = cash + float(np.sum(open_values))
        if equity_open <= 0:
            break
        gross_open = float(np.sum([abs(v) for v in open_values]))

        day_signals = signals_by_date.get(date, pd.DataFrame()).copy()
        if not day_signals.empty:
            day_signals = apply_overlap_mode(day_signals, overlap_mode)
            if not day_signals.empty:
                day_signals["target_notional"] = causal_targets(day_signals, equity_open, sleeve_gross_targets)

                requested_by_ticker = day_signals.groupby("ticker")["target_notional"].sum()
                same_day_cap_abs = same_day_ticker_cap_pct * equity_open
                same_day_scale = (same_day_cap_abs / requested_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
                day_signals["same_day_ticker_scale"] = day_signals["ticker"].map(same_day_scale).astype(float)
                day_signals["target_notional"] *= day_signals["same_day_ticker_scale"]

                if active_ticker_cap_pct is not None:
                    target_by_ticker = day_signals.groupby("ticker")["target_notional"].sum()
                    active_cap_abs = active_ticker_cap_pct * equity_open
                    capacity_by_ticker = target_by_ticker.copy()
                    for ticker in capacity_by_ticker.index:
                        capacity_by_ticker.loc[ticker] = max(0.0, active_cap_abs - active_gross_by_ticker.get(str(ticker), 0.0))
                    active_scale = (capacity_by_ticker / target_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
                    day_signals["active_ticker_scale"] = day_signals["ticker"].map(active_scale).astype(float)
                    day_signals["target_notional"] *= day_signals["active_ticker_scale"]
                else:
                    day_signals["active_ticker_scale"] = 1.0

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
                            "entry_price": entry_px,
                            "entry_notional": notional,
                            "entry_cost": entry_cost,
                            "planned_exit_date": pd.Timestamp(s["exit_date"]),
                            "same_day_ticker_scale": float(s["same_day_ticker_scale"]),
                            "active_ticker_scale": float(s["active_ticker_scale"]),
                            "gross_scale": gross_scale,
                        }
                    )

        remaining: list[engine.Position] = []
        exit_cost = 0.0
        realized = 0.0
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
    return summarize(name, eq, tr), eq, tr


def main() -> None:
    daily_px = engine.load_daily_prices()
    signals = engine.load_signals()

    rows = []
    detail_rows = []

    for book, gross_cap in PORTFOLIO_GROSS_CAPS.items():
        for gross_per_sleeve in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]:
            sleeve_gross_targets = {s: gross_per_sleeve for s in NO_ML_SLEEVES}
            for control_mode, controls in CONTROL_MODES.items():
                name = f"{book}_causal_equalGross{gross_per_sleeve:.2f}_{control_mode}"
                summary, _, trades = simulate_causal(
                    name,
                    signals,
                    daily_px,
                    sleeve_gross_targets=sleeve_gross_targets,
                    gross_cap=gross_cap,
                    overlap_mode=str(controls["overlap_mode"]),
                    active_ticker_cap_pct=controls["active_ticker_cap_pct"],  # type: ignore[arg-type]
                    same_day_ticker_cap_pct=float(controls["same_day_ticker_cap_pct"]),
                )
                row = {
                    "book": book,
                    "controlMode": control_mode,
                    "grossPerSleeve": gross_per_sleeve,
                    "grossCap": gross_cap,
                    **summary,
                }
                rows.append(row)
                pd.DataFrame(rows).to_csv(OUT, index=False)
                detail = trades.groupby(["sleeve"], as_index=False).agg(trades=("trade_id", "count"), pnl=("pnl", "sum"), avgNotional=("entry_notional", "mean"))
                detail.insert(0, "portfolio", name)
                detail_rows.append(detail)
                print(name, "pnl", round(float(summary["pnl"]), 2), "dd", round(float(summary["dd"]), 2), "sharpe", round(float(summary["sharpe"]), 3), flush=True)

    if detail_rows:
        pd.concat(detail_rows, ignore_index=True).to_csv(TRADES_OUT, index=False)
    print("WROTE", OUT, TRADES_OUT)


if __name__ == "__main__":
    main()
