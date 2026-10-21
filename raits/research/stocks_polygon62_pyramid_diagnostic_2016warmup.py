from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

import stocks_one_engine_mtm_portfolio as engine
import stocks_polygon_2018_2024_no_ml_pipeline as poly


START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2024-12-31")
START_CAPITAL = 50_000.0
COST_BPS = 4.0

SUMMARY_OUT = Path("STOCKS_POLYGON62_B_LEAD_PYRAMID_DIAGNOSTIC_SUMMARY_2016WARMUP_2018_2024.csv")
YEARLY_OUT = Path("STOCKS_POLYGON62_B_LEAD_PYRAMID_DIAGNOSTIC_YEARLY_2016WARMUP_2018_2024.csv")
TRADES_OUT = Path("STOCKS_POLYGON62_B_LEAD_PYRAMID_DIAGNOSTIC_TRADES_2016WARMUP_2018_2024.csv")

PYRAMID_SLEEVES = {"broad_adv10_g2_dd85", "local_xs_full_s10"}


@dataclass
class Position:
    trade_id: int
    parent_id: int
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
    is_addon: bool
    addon_done: bool


def configure_poly() -> None:
    poly.BARS = Path("raits/data/cache/window_debug_5min_POLYGON_2016WARMUP_2018_2024_62.pkl")
    poly.DAILY_FEATURES = Path("raits/data/cache/stocks_clean_daily_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.INTRADAY_0935 = Path("raits/data/cache/stocks_intraday_0935_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.GAP_RVOL30 = Path("raits/data/cache/stocks_gap_rvol30_features_POLYGON62_2016WARMUP_2018_2024.pkl")
    poly.BROAD_TRADES = Path("STOCKS_POLYGON62_BROAD_ADV10_G2_DD85_TRADES_2016WARMUP_2018_2024.csv")
    poly.LOCAL_TRADES = Path("STOCKS_POLYGON62_LOCAL_XS_FULL_S10_TRADES_2016WARMUP_2018_2024.csv")
    poly.YDAY_TRADES = Path("STOCKS_POLYGON62_YDAY_EX6_ACTUAL_TRADES_2016WARMUP_2018_2024.csv")
    poly.INTRADAY_TRADES = Path("STOCKS_POLYGON62_INTRADAY_FOCUSED_TRADES_2016WARMUP_2018_2024.csv")
    poly.START = START
    poly.END = END


def max_drawdown(equity: pd.Series) -> float:
    return float((equity - equity.cummax()).min())


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    configure_poly()
    daily = pd.read_pickle(poly.DAILY_FEATURES)
    daily["date"] = pd.to_datetime(daily["date"])
    daily_px = poly.load_daily_prices_from_polygon(daily)
    daily_px["date"] = pd.to_datetime(daily_px["date"])
    daily_px = daily_px[(daily_px["date"] >= START) & (daily_px["date"] <= END)].copy()

    intraday = pd.read_pickle(poly.INTRADAY_0935)
    intraday["date"] = pd.to_datetime(intraday["date"])
    intraday = intraday[["date", "ticker", "open930", "entry935", "exit1555"]]

    signals = poly.load_signals(daily_px, intraday)
    cfg = poly.LEAD_PORTFOLIOS["B_polygon62_no_intraday_cap40"]
    signals = signals[signals["sleeve"].isin(cfg["weights"])].copy()
    return daily_px, signals


def cfg_with_weight(weight: float) -> dict[str, object]:
    return {
        "weights": {
            "broad_adv10_g2_dd85": weight,
            "local_xs_full_s10": weight,
            "yday_ex6_actual": weight,
        },
        "top_k": None,
        "ticker_cap_pct": 0.40,
        "gross_cap": 1.75,
    }


def simulate(
    name: str,
    cfg: dict[str, object],
    signals: pd.DataFrame,
    daily_px: pd.DataFrame,
    *,
    pyramid: bool,
    trigger_days: int = 5,
    trigger_return: float = 0.05,
    add_fraction: float = 0.25,
    addon_sleeves: set[str] | None = None,
    addon_hold_days: int | None = None,
    max_ticker_exposure_pct: float | None = None,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    weights: dict[str, float] = cfg["weights"]  # type: ignore[assignment]
    top_k: int | None = cfg["top_k"]  # type: ignore[assignment]
    ticker_cap_pct = float(cfg["ticker_cap_pct"])
    gross_cap = float(cfg["gross_cap"])
    cost_rate = COST_BPS / 10_000.0
    allowed_addon_sleeves = addon_sleeves or PYRAMID_SLEEVES

    dates = sorted(daily_px["date"].drop_duplicates())
    date_pos = {date: i for i, date in enumerate(dates)}
    price_by_date = {d: x.set_index("ticker") for d, x in daily_px.groupby("date")}
    sig = signals[signals["sleeve"].isin(weights)].copy()
    sig["portfolio_weight"] = sig["sleeve"].map(weights).astype(float)
    sig["weighted_strength"] = sig["strength"] * sig["portfolio_weight"]
    sig_by_date = {d: x for d, x in sig.groupby("date")}
    same_day_exit = sig.dropna(subset=["exit_price_same_day"]).drop_duplicates(["date", "ticker"]).set_index(["date", "ticker"])[
        "exit_price_same_day"
    ]

    positions: list[Position] = []
    cash = START_CAPITAL
    last_equity = START_CAPITAL
    trade_id = 0
    eq_rows: list[dict[str, object]] = []
    tr_rows: list[dict[str, object]] = []
    addon_count = 0

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
        gross_open = float(sum(abs(v) for v in open_values))

        addon_notional = 0.0
        if pyramid:
            for p in list(positions):
                if p.is_addon or p.addon_done or p.sleeve not in allowed_addon_sleeves:
                    continue
                if date_pos[date] - date_pos.get(p.entry_date, date_pos[date]) < trigger_days:
                    continue
                entry_ret = price_for(p.ticker, "open", p.last_price) / p.entry_price - 1.0
                if entry_ret < trigger_return:
                    continue
                open_by_ticker = sum(
                    abs(q.side * q.shares * price_for(q.ticker, "open", q.last_price))
                    for q in positions
                    if q.ticker == p.ticker
                )
                capacity = max(0.0, gross_cap * equity_open - gross_open - addon_notional)
                effective_ticker_cap = min(ticker_cap_pct, max_ticker_exposure_pct) if max_ticker_exposure_pct is not None else ticker_cap_pct
                ticker_room = max(0.0, effective_ticker_cap * equity_open - open_by_ticker)
                notional = min(add_fraction * p.entry_notional, capacity, ticker_room)
                p.addon_done = True
                if notional <= 1.0:
                    continue
                entry_px = price_for(p.ticker, "open", p.last_price)
                shares = notional / entry_px
                cost = notional * cost_rate
                cash -= notional + cost
                trade_id += 1
                addon_count += 1
                addon_notional += notional
                exit_date = p.exit_date
                if addon_hold_days is not None:
                    target_idx = min(date_pos[date] + addon_hold_days - 1, len(dates) - 1)
                    exit_date = min(p.exit_date, dates[target_idx])
                positions.append(
                    Position(
                        trade_id=trade_id,
                        parent_id=p.trade_id,
                        sleeve=p.sleeve,
                        ticker=p.ticker,
                        side=p.side,
                        shares=shares,
                        entry_date=date,
                        entry_price=entry_px,
                        entry_notional=notional,
                        exit_date=exit_date,
                        exit_style=p.exit_style,
                        last_price=entry_px,
                        is_addon=True,
                        addon_done=True,
                    )
                )
                tr_rows.append(
                    {
                        "portfolio": name,
                        "trade_id": trade_id,
                        "parent_id": p.trade_id,
                        "date": date,
                        "ticker": p.ticker,
                        "sleeve": p.sleeve,
                        "side": p.side,
                        "entry_price": entry_px,
                        "entry_notional": notional,
                        "entry_cost": cost,
                        "planned_exit_date": exit_date,
                        "is_addon": True,
                    }
                )

        day_signals = sig_by_date.get(date, pd.DataFrame()).copy()
        if not day_signals.empty:
            td_rank = (
                day_signals.groupby(["date", "ticker"])
                .agg(sleeve_count=("sleeve", "nunique"), weighted_strength=("weighted_strength", "sum"), strength_avg=("strength", "mean"))
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
                cap_abs = ticker_cap_pct * equity_open
                ticker_scale = (cap_abs / target_by_ticker.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
                day_signals["ticker_scale"] = day_signals["ticker"].map(ticker_scale).astype(float)
                day_signals["target_notional"] *= day_signals["ticker_scale"]

                gross_open_after_addons = gross_open + addon_notional
                capacity = max(0.0, gross_cap * equity_open - gross_open_after_addons)
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
                    cost = notional * cost_rate
                    if side == 1:
                        cash -= notional + cost
                    else:
                        cash += notional - cost
                    trade_id += 1
                    positions.append(
                        Position(
                            trade_id=trade_id,
                            parent_id=trade_id,
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
                            is_addon=False,
                            addon_done=False,
                        )
                    )
                    tr_rows.append(
                        {
                            "portfolio": name,
                            "trade_id": trade_id,
                            "parent_id": trade_id,
                            "date": date,
                            "ticker": str(s["ticker"]),
                            "sleeve": str(s["sleeve"]),
                            "side": side,
                            "entry_price": entry_px,
                            "entry_notional": notional,
                            "entry_cost": cost,
                            "planned_exit_date": pd.Timestamp(s["exit_date"]),
                            "ticker_scale": float(s.get("ticker_scale", 1.0)),
                            "gross_scale": gross_scale,
                            "is_addon": False,
                        }
                    )

        remaining: list[Position] = []
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
        gross_close = float(sum(abs(v) for v in close_values))
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
                "addon_count_cum": addon_count,
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
        "pyramid": pyramid,
        "triggerDays": trigger_days if pyramid else None,
        "triggerReturn": trigger_return if pyramid else None,
        "addFraction": add_fraction if pyramid else None,
        "addonSleeves": "+".join(sorted(allowed_addon_sleeves)) if pyramid else "",
        "addonHoldDays": addon_hold_days if pyramid else None,
        "maxTickerExposurePct": max_ticker_exposure_pct if pyramid else None,
        "start": eq["date"].min().date(),
        "end": eq["date"].max().date(),
        "years": years,
        "trades": int(len(tr)),
        "baseTrades": int((~tr.get("is_addon", pd.Series(False, index=tr.index)).astype(bool)).sum()) if not tr.empty else 0,
        "addonTrades": int(tr.get("is_addon", pd.Series(False, index=tr.index)).astype(bool).sum()) if not tr.empty else 0,
        "closedTrades": int(tr["pnl"].notna().sum()) if "pnl" in tr.columns else 0,
        "pnl": pnl,
        "ending": ending,
        "totalReturn": pnl / START_CAPITAL,
        "cagr": (ending / START_CAPITAL) ** (1 / years) - 1,
        "dd": max_drawdown(eq["equity"]),
        "sharpe": float(eq["daily_pnl"].mean() / eq["daily_pnl"].std() * np.sqrt(252)),
        "avgGross": float(eq["gross"].mean()),
        "maxGross": float(eq["gross"].max()),
        "cashNegativeDays": int((eq["cash"] < 0).sum()),
        "minCash": float(eq["cash"].min()),
        "avgActive": float(eq["active_positions"].mean()),
        "maxActive": int(eq["active_positions"].max()),
        "y2018": float(yearly.get(2018, 0.0)),
        "y2019": float(yearly.get(2019, 0.0)),
        "y2020": float(yearly.get(2020, 0.0)),
        "y2021": float(yearly.get(2021, 0.0)),
        "y2022": float(yearly.get(2022, 0.0)),
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
    }
    return summary, eq, tr


def yearly_metrics(eq: pd.DataFrame, name: str) -> pd.DataFrame:
    rows = []
    for year, group in eq.assign(year=eq["date"].dt.year).groupby("year", sort=True):
        curve = group["daily_pnl"].cumsum()
        rows.append(
            {
                "portfolio": name,
                "year": int(year),
                "pnl": float(group["daily_pnl"].sum()),
                "ddSubset": float((curve - curve.cummax()).min()),
                "sharpe": float(group["daily_pnl"].mean() / group["daily_pnl"].std() * np.sqrt(252))
                if group["daily_pnl"].std() > 0
                else np.nan,
                "avgGross": float(group["gross"].mean()),
                "maxGross": float(group["gross"].max()),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    daily_px, signals = load_inputs()
    cases = [
        {"name": "B_base_repro", "cfg": cfg_with_weight(0.35), "pyramid": False},
        {"name": "B_pyramid_d5_r5_add25", "cfg": cfg_with_weight(0.35), "pyramid": True},
        {
            "name": "B_pyramid_local_d5_r7p5_add15_cap20",
            "cfg": cfg_with_weight(0.35),
            "pyramid": True,
            "trigger_return": 0.075,
            "add_fraction": 0.15,
            "addon_sleeves": {"local_xs_full_s10"},
            "max_ticker_exposure_pct": 0.20,
        },
        {
            "name": "B_pyramid_local_d5_r5_add20_hold5",
            "cfg": cfg_with_weight(0.35),
            "pyramid": True,
            "trigger_return": 0.05,
            "add_fraction": 0.20,
            "addon_sleeves": {"local_xs_full_s10"},
            "addon_hold_days": 5,
        },
        {
            "name": "B_pyramid_broad_local_d5_r5_add20_hold5",
            "cfg": cfg_with_weight(0.35),
            "pyramid": True,
            "trigger_return": 0.05,
            "add_fraction": 0.20,
            "addon_sleeves": {"broad_adv10_g2_dd85", "local_xs_full_s10"},
            "addon_hold_days": 5,
        },
        {"name": "B_gross037_control", "cfg": cfg_with_weight(0.37), "pyramid": False},
        {"name": "B_gross040_control", "cfg": cfg_with_weight(0.40), "pyramid": False},
    ]
    summaries = []
    yearly = []
    trades = []
    for case in cases:
        name = str(case["name"])
        summary, eq, tr = simulate(
            name,
            case["cfg"],  # type: ignore[arg-type]
            signals,
            daily_px,
            pyramid=bool(case["pyramid"]),
            trigger_return=float(case.get("trigger_return", 0.05)),
            add_fraction=float(case.get("add_fraction", 0.25)),
            addon_sleeves=case.get("addon_sleeves"),  # type: ignore[arg-type]
            addon_hold_days=case.get("addon_hold_days"),  # type: ignore[arg-type]
            max_ticker_exposure_pct=case.get("max_ticker_exposure_pct"),  # type: ignore[arg-type]
        )
        summaries.append(summary)
        yearly.append(yearly_metrics(eq, name))
        trades.append(tr)
        print(name, f"pnl={summary['pnl']:.2f}", f"dd={summary['dd']:.2f}", f"sharpe={summary['sharpe']:.3f}", f"addons={summary['addonTrades']}", flush=True)

    pd.DataFrame(summaries).to_csv(SUMMARY_OUT, index=False)
    pd.concat(yearly, ignore_index=True).to_csv(YEARLY_OUT, index=False)
    pd.concat(trades, ignore_index=True).to_csv(TRADES_OUT, index=False)
    print("WROTE", SUMMARY_OUT, YEARLY_OUT, TRADES_OUT)


if __name__ == "__main__":
    main()
