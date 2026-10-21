from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine


DATE_TAG = "2026-09-09"
OUT = Path(f"STOCKS_ONE_ENGINE_NO_ML_CONCENTRATION_CONTROL_SWEEP_{DATE_TAG}.csv")
DETAIL_OUT = Path(f"STOCKS_ONE_ENGINE_NO_ML_CONCENTRATION_CONTROL_TRADES_{DATE_TAG}.csv")

BASE_PORTFOLIOS = {
    "A_no_ml_all": {
        "weights": {
            "broad_adv10_g2_dd85": 0.40,
            "local_xs_full_s10": 0.40,
            "yday_ex6_actual": 0.40,
            "intraday_ex10": 0.40,
        },
        "top_k": None,
        "gross_cap": 2.0,
    },
    "B_no_ml_all": {
        "weights": {
            "broad_adv10_g2_dd85": 0.35,
            "local_xs_full_s10": 0.35,
            "yday_ex6_actual": 0.35,
            "intraday_ex10": 0.35,
        },
        "top_k": None,
        "gross_cap": 1.75,
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
            "top5NetShare": np.nan,
            "top10NetShare": np.nan,
            "topTickerPositiveShare": np.nan,
            "top5PositiveShare": np.nan,
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
        "top5NetShare": float(ticker_pnl.head(5).sum() / total) if total else np.nan,
        "top10NetShare": float(ticker_pnl.head(10).sum() / total) if total else np.nan,
        "topTickerPositiveShare": float(pos_shares.iloc[0]) if len(pos_shares) else np.nan,
        "top5PositiveShare": float(pos_shares.head(5).sum()) if len(pos_shares) else np.nan,
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


def simulate_control(
    name: str,
    cfg: dict[str, object],
    signals: pd.DataFrame,
    daily_px: pd.DataFrame,
    *,
    same_day_ticker_cap_pct: float,
    active_ticker_cap_pct: float | None,
    overlap_mode: str,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    weights: dict[str, float] = cfg["weights"]  # type: ignore[assignment]
    top_k: int | None = cfg["top_k"]  # type: ignore[assignment]
    gross_cap = float(cfg["gross_cap"])
    cost_rate = engine.COST_BPS / 10_000.0

    dates = sorted(daily_px["date"].drop_duplicates())
    price_by_date = {d: x.set_index("ticker") for d, x in daily_px.groupby("date")}
    signals = signals[signals["sleeve"].isin(weights)].copy()
    same_day_exit = signals.dropna(subset=["exit_price_same_day"]).drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"])[
        "exit_price_same_day"
    ]
    signals["portfolio_weight"] = signals["sleeve"].map(weights).astype(float)
    signals["weighted_strength"] = signals["strength"] * signals["portfolio_weight"]
    signals["base_weighted_notional"] = signals["base_notional"] * signals["portfolio_weight"]
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

        open_values_by_pos = []
        active_gross_by_ticker: dict[str, float] = {}
        for p in positions:
            px = price_for(p.ticker, "open", p.last_price)
            open_value = p.side * p.shares * px
            open_values_by_pos.append(open_value)
            active_gross_by_ticker[p.ticker] = active_gross_by_ticker.get(p.ticker, 0.0) + abs(open_value)
        equity_open = cash + float(np.sum(open_values_by_pos))
        if equity_open <= 0:
            break
        gross_open = float(np.sum([abs(v) for v in open_values_by_pos]))

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

            day_signals = apply_overlap_mode(day_signals, overlap_mode)

            if not day_signals.empty:
                requested_by_ticker = day_signals.groupby("ticker")["base_weighted_notional"].sum()
                same_day_cap_abs = same_day_ticker_cap_pct * equity_open
                same_day_scale = (same_day_cap_abs / requested_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
                day_signals["same_day_ticker_scale"] = day_signals["ticker"].map(same_day_scale).astype(float)
                day_signals["target_notional"] = day_signals["base_weighted_notional"] * day_signals["same_day_ticker_scale"]

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
    summary = summarize(name, eq, tr)
    return summary, eq, tr


def main() -> None:
    daily_px = engine.load_daily_prices()
    signals = engine.load_signals()

    rows = pd.read_csv(OUT).to_dict("records") if OUT.exists() else []
    done = {
        (
            r["basePortfolio"],
            str(r["overlapMode"]),
            str(r["activeTickerCapPct"]),
            float(r["sameDayTickerCapPct"]),
        )
        for r in rows
    }
    detail_rows = []
    grids: list[tuple[str, float | None, float]] = []
    grids.append(("allow", None, 0.40))
    for overlap_mode in ["allow", "strongest_only"]:
        for active_cap in [0.05, 0.075, 0.10, 0.15, 0.20, 0.40]:
            for same_day_cap in [0.05, 0.10, 0.20, 0.40]:
                grids.append((overlap_mode, active_cap, same_day_cap))

    for base_name, cfg in BASE_PORTFOLIOS.items():
        for overlap_mode, active_cap, same_day_cap in grids:
            active_label = "none" if active_cap is None else f"{active_cap:.3f}"
            key = (base_name, overlap_mode, active_label, same_day_cap)
            if key in done:
                continue
            label = f"{base_name}_overlap-{overlap_mode}_active-{active_label}_sameDay-{same_day_cap:.2f}"
            summary, _, trades = simulate_control(
                label,
                cfg,
                signals,
                daily_px,
                same_day_ticker_cap_pct=same_day_cap,
                active_ticker_cap_pct=active_cap,
                overlap_mode=overlap_mode,
            )
            row = {
                "basePortfolio": base_name,
                "overlapMode": overlap_mode,
                "activeTickerCapPct": active_label,
                "sameDayTickerCapPct": same_day_cap,
                **summary,
            }
            rows.append(row)
            done.add(key)
            pd.DataFrame(rows).to_csv(OUT, index=False)
            detail = trades.groupby("ticker", as_index=False)["pnl"].sum().sort_values("pnl", ascending=False).head(20)
            detail.insert(0, "portfolio", label)
            detail_rows.append(detail)
            print(label, "pnl", round(float(summary["pnl"]), 2), "dd", round(float(summary["dd"]), 2), "top10+", round(float(summary["top10PositiveShare"]), 4), flush=True)

    if detail_rows:
        detail_new = pd.concat(detail_rows, ignore_index=True)
        if DETAIL_OUT.exists():
            detail_old = pd.read_csv(DETAIL_OUT)
            detail_new = pd.concat([detail_old, detail_new], ignore_index=True).drop_duplicates(["portfolio", "ticker"], keep="last")
        detail_new.to_csv(DETAIL_OUT, index=False)
    print("WROTE", OUT, DETAIL_OUT)


if __name__ == "__main__":
    main()
