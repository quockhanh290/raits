from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


START_CAPITAL = 50_000.0
COST_BPS = 4.0
START_DATE = pd.Timestamp("2023-03-28")
END_DATE = pd.Timestamp("2024-12-31")

OUT = Path("STOCKS_DATABENTO_DAILY_XS_MTM_SWEEP_2026-09-08.csv")
BEST_TRADES = Path("STOCKS_DATABENTO_DAILY_XS_MTM_BEST_TRADES_2026-09-08.csv")
BEST_EQUITY = Path("STOCKS_DATABENTO_DAILY_XS_MTM_BEST_EQUITY_2026-09-08.csv")


@dataclass(frozen=True)
class Config:
    adv: float
    slots: int
    hold: int
    gross_cap: float
    layer_gross: float
    min_ret5: float
    max_ticker_gross: float
    active_ticker_cap: int
    overlay: str = "none"
    dd_trigger: float = 0.10
    throttle_mult: float = 0.50
    spy_vol_trigger: float = 0.018

    @property
    def name(self) -> str:
        adv_m = int(self.adv / 1_000_000)
        return (
            f"adv{adv_m}m_s{self.slots}_h{self.hold}_cap{self.gross_cap:g}_"
            f"layer{self.layer_gross:g}_min{self.min_ret5:g}_tc{self.active_ticker_cap}_ov{self.overlay}"
        )


def load_panel() -> pd.DataFrame:
    px = pd.read_parquet(
        "raits/data/cache/research_daily/databento_ohlcv1d.parquet",
        columns=["symbol", "date", "open", "close", "volume"],
    )
    px["date"] = pd.to_datetime(px["date"])
    px = px.dropna(subset=["symbol", "date", "open", "close", "volume"])
    px = px[(px["open"] > 3.0) & (px["close"] > 3.0) & (px["volume"] > 0)].copy()
    spy = px[px["symbol"].eq("SPY")][["date", "close"]].sort_values("date").copy()
    if not spy.empty:
        spy["spy_ret"] = spy["close"].pct_change()
        spy["spy_vol20"] = spy["spy_ret"].rolling(20, min_periods=10).std()
        spy_vol = spy[["date", "spy_vol20"]]
    else:
        spy_vol = pd.DataFrame(columns=["date", "spy_vol20"])

    cls = pd.read_parquet("raits/data/cache/research_daily/universe_classification.parquet")
    common = set(cls.loc[cls["security_type"].eq("C"), "symbol"].astype(str))
    px = px[px["symbol"].isin(common)].copy()
    px = px.sort_values(["symbol", "date"]).reset_index(drop=True)

    g = px.groupby("symbol", sort=False)
    px["dollar"] = px["close"] * px["volume"]
    px["adv20"] = g["dollar"].transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    prev_close = g["close"].shift(1)
    px["ret5"] = prev_close / g["close"].shift(6) - 1.0
    for hold in [10, 20, 30]:
        px[f"exit_date{hold}"] = g["date"].shift(-(hold - 1))
    px = px.merge(spy_vol, on="date", how="left")
    px = px[(px["date"] >= START_DATE) & (px["date"] <= END_DATE)].copy()
    px = px.replace([np.inf, -np.inf], np.nan)
    return px


def max_drawdown(equity: pd.Series) -> float:
    return float((equity - equity.cummax()).min())


def simulate(panel: pd.DataFrame, cfg: Config) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    price_panel = panel.dropna(subset=["open", "close"]).copy()
    data = panel.dropna(subset=["ret5", "adv20", f"exit_date{cfg.hold}"]).copy()
    data = data[(data["adv20"] >= cfg.adv) & (data["ret5"] >= cfg.min_ret5)]
    dates = sorted(data["date"].drop_duplicates())
    candidates_by_date = {d: x for d, x in data.groupby("date", sort=False)}
    prices_by_date = {d: x for d, x in price_panel.groupby("date", sort=False)}

    positions: list[dict[str, object]] = []
    cash = START_CAPITAL
    last_equity = START_CAPITAL
    equity_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    cost_rate = COST_BPS / 10_000.0

    for date in dates:
        day = candidates_by_date[date]
        price_day = prices_by_date.get(date)
        if price_day is None:
            continue
        open_map = price_day.set_index("symbol")["open"].to_dict()
        close_map = price_day.set_index("symbol")["close"].to_dict()

        # If a held symbol is missing for a day, keep the position and use the last
        # available close carried in the position for valuation.
        for p in positions:
            sym = str(p["symbol"])
            if sym not in open_map:
                open_map[sym] = float(p["last_close"])
            if sym not in close_map:
                close_map[sym] = float(p["last_close"])

        open_values = [float(p["shares"]) * float(open_map[p["symbol"]]) for p in positions]
        equity_open = cash + float(np.sum(open_values))
        if equity_open <= 0:
            break

        peak_equity = max([START_CAPITAL, *[float(r["equity"]) for r in equity_rows]]) if equity_rows else START_CAPITAL
        current_dd = equity_open / peak_equity - 1.0
        overlay_mult = 1.0
        if cfg.overlay in {"dd", "dd_spyvol"} and current_dd <= -cfg.dd_trigger:
            overlay_mult *= cfg.throttle_mult
        if cfg.overlay in {"spyvol", "dd_spyvol"}:
            spy_vol = day["spy_vol20"].dropna()
            if not spy_vol.empty and float(spy_vol.iloc[0]) >= cfg.spy_vol_trigger:
                overlay_mult *= cfg.throttle_mult

        gross_open = float(np.sum(np.abs(open_values)))
        active_counts: dict[str, int] = {}
        active_gross: dict[str, float] = {}
        for p, value in zip(positions, open_values):
            sym = str(p["symbol"])
            active_counts[sym] = active_counts.get(sym, 0) + 1
            active_gross[sym] = active_gross.get(sym, 0.0) + abs(value)

        effective_gross_cap = cfg.gross_cap * overlay_mult
        effective_layer_gross = cfg.layer_gross * overlay_mult
        capacity = max(0.0, effective_gross_cap * equity_open - gross_open)
        target_new = effective_layer_gross * equity_open
        new_budget = min(target_new, capacity)
        picks: list[pd.Series] = []

        if new_budget > 0:
            ranked = day.sort_values("ret5", ascending=True)
            for _, row in ranked.iterrows():
                sym = str(row["symbol"])
                if active_counts.get(sym, 0) >= cfg.active_ticker_cap:
                    continue
                if active_gross.get(sym, 0.0) >= cfg.max_ticker_gross * equity_open:
                    continue
                picks.append(row)
                active_counts[sym] = active_counts.get(sym, 0) + 1
                if len(picks) >= cfg.slots:
                    break

        if picks:
            per_trade = new_budget / len(picks)
            for row in picks:
                sym = str(row["symbol"])
                entry_px = float(row["open"])
                entry_notional = per_trade
                shares = entry_notional / entry_px
                cost = entry_notional * cost_rate
                cash -= entry_notional + cost
                positions.append(
                    {
                        "symbol": sym,
                        "shares": shares,
                        "entry_date": date,
                        "entry_price": entry_px,
                        "entry_notional": entry_notional,
                        "entry_cost": cost,
                        "exit_date": pd.Timestamp(row[f"exit_date{cfg.hold}"]),
                        "ret5": float(row["ret5"]),
                        "adv20": float(row["adv20"]),
                        "last_close": float(row["close"]),
                    }
                )
                trade_rows.append(
                    {
                        "config": cfg.name,
                        "entry_date": date,
                        "symbol": sym,
                        "entry_price": entry_px,
                        "shares": shares,
                        "entry_notional": entry_notional,
                        "entry_cost": cost,
                        "planned_exit_date": pd.Timestamp(row[f"exit_date{cfg.hold}"]),
                        "ret5": float(row["ret5"]),
                        "adv20": float(row["adv20"]),
                    }
                )

        close_values = [float(p["shares"]) * float(close_map[p["symbol"]]) for p in positions]
        equity_close_before_exit = cash + float(np.sum(close_values))

        remaining: list[dict[str, object]] = []
        realized_exit_cost = 0.0
        for p in positions:
            sym = str(p["symbol"])
            value = float(p["shares"]) * float(close_map[sym])
            if pd.Timestamp(p["exit_date"]) <= date:
                exit_cost = value * cost_rate
                cash += value - exit_cost
                realized_exit_cost += exit_cost
            else:
                p["last_close"] = float(close_map[sym])
                remaining.append(p)
        positions = remaining

        close_values_after_exit = [float(p["shares"]) * float(close_map[p["symbol"]]) for p in positions]
        equity_close = cash + float(np.sum(close_values_after_exit))
        gross_close = float(np.sum(np.abs(close_values_after_exit)))
        daily_pnl = equity_close - last_equity
        last_equity = equity_close

        equity_rows.append(
            {
                "date": date,
                "equity": equity_close,
                "daily_pnl": daily_pnl,
                "gross": gross_close / equity_close if equity_close > 0 else np.nan,
                "active_positions": len(positions),
                "new_trades": len(picks),
                "entry_cost": float(sum(r["entry_cost"] for r in trade_rows[-len(picks) :])) if picks else 0.0,
                "exit_cost": realized_exit_cost,
                "overlay_mult": overlay_mult,
                "effective_gross_cap": effective_gross_cap,
            }
        )

    eq = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    if eq.empty:
        return {"config": cfg.name, "pnl": 0.0}, trades, eq

    pnl = float(eq["equity"].iloc[-1] - START_CAPITAL)
    yearly = eq.assign(year=eq["date"].dt.year).groupby("year")["daily_pnl"].sum()
    top = pd.Series(dtype=float)
    if not trades.empty:
        # Attribute MTM P&L approximately by completed trade open-to-planned-exit return.
        close_lookup = panel.set_index(["date", "symbol"])["close"]
        approx = []
        for _, t in trades.iterrows():
            key = (pd.Timestamp(t["planned_exit_date"]), t["symbol"])
            if key in close_lookup.index:
                exit_px = float(close_lookup.loc[key])
                gross = float(t["shares"]) * (exit_px - float(t["entry_price"]))
                cost = float(t["entry_cost"]) + float(t["shares"]) * exit_px * cost_rate
                approx.append((t["symbol"], gross - cost))
        if approx:
            top = pd.DataFrame(approx, columns=["symbol", "pnl"]).groupby("symbol")["pnl"].sum().sort_values(ascending=False)

    summary = {
        "config": cfg.name,
        "adv": cfg.adv,
        "slots": cfg.slots,
        "hold": cfg.hold,
        "grossCap": cfg.gross_cap,
        "layerGross": cfg.layer_gross,
        "minRet5": cfg.min_ret5,
        "maxTickerGross": cfg.max_ticker_gross,
        "activeTickerCap": cfg.active_ticker_cap,
        "overlay": cfg.overlay,
        "ddTrigger": cfg.dd_trigger,
        "throttleMult": cfg.throttle_mult,
        "spyVolTrigger": cfg.spy_vol_trigger,
        "N": int(len(trades)),
        "days": int(eq["date"].nunique()),
        "ending": float(eq["equity"].iloc[-1]),
        "pnl": pnl,
        "dd": max_drawdown(eq.set_index("date")["equity"]),
        "dailySharpe": float(eq["daily_pnl"].mean() / eq["daily_pnl"].std() * np.sqrt(252)) if eq["daily_pnl"].std() > 0 else np.nan,
        "avgGross": float(eq["gross"].mean()),
        "p95Gross": float(eq["gross"].quantile(0.95)),
        "maxGross": float(eq["gross"].max()),
        "avgActive": float(eq["active_positions"].mean()),
        "p95Active": float(eq["active_positions"].quantile(0.95)),
        "maxActive": int(eq["active_positions"].max()),
        "throttledDays": int((eq["overlay_mult"] < 1.0).sum()),
        "negYears": int((yearly < 0).sum()),
        "minYear": float(yearly.min()) if len(yearly) else 0.0,
        "y2023": float(yearly.get(2023, 0.0)),
        "y2024": float(yearly.get(2024, 0.0)),
        "topTicker": str(top.index[0]) if len(top) else "",
        "topTickerApproxPnl": float(top.iloc[0]) if len(top) else 0.0,
        "topTickerApproxShare": float(top.iloc[0] / pnl) if pnl > 0 and len(top) else np.nan,
    }
    return summary, trades, eq


def main() -> None:
    panel = load_panel()
    configs = []
    for adv in [5_000_000.0, 10_000_000.0]:
        for slots in [20]:
            for gross_cap in [2.0]:
                for min_ret5 in [-0.5, -0.1]:
                    for overlay in ["none", "dd", "spyvol", "dd_spyvol"]:
                        dd_values = [0.08, 0.12] if overlay in {"dd", "dd_spyvol"} else [0.10]
                        vol_values = [0.015, 0.020, 0.025] if overlay in {"spyvol", "dd_spyvol"} else [0.018]
                        throttle_values = [1.0] if overlay == "none" else [0.50, 0.70, 0.85]
                        for dd_trigger in dd_values:
                            for spy_vol_trigger in vol_values:
                                for throttle_mult in throttle_values:
                                    configs.append(
                                        Config(
                                            adv=adv,
                                            slots=slots,
                                            hold=20,
                                            gross_cap=gross_cap,
                                            layer_gross=gross_cap / 20.0,
                                            min_ret5=min_ret5,
                                            max_ticker_gross=0.10,
                                            active_ticker_cap=3,
                                            overlay=overlay,
                                            dd_trigger=dd_trigger,
                                            throttle_mult=throttle_mult,
                                            spy_vol_trigger=spy_vol_trigger,
                                        )
                                    )

    rows = []
    best = None
    best_trades = pd.DataFrame()
    best_eq = pd.DataFrame()
    for cfg in configs:
        summary, trades, eq = simulate(panel, cfg)
        rows.append(summary)
        ok = (
            summary.get("pnl", 0.0) > 0
            and summary.get("negYears", 1) == 0
            and summary.get("topTickerApproxShare", 1.0) <= 0.15
            and summary.get("maxGross", 99.0) <= cfg.gross_cap * 1.10
        )
        score = summary.get("pnl", 0.0) / max(abs(float(summary.get("dd", -1.0))), 1.0)
        if ok and (best is None or score > best[0]):
            best = (score, summary)
            best_trades = trades
            best_eq = eq
        print(
            cfg.name,
            round(float(summary.get("pnl", 0.0)), 2),
            round(float(summary.get("dd", 0.0)), 2),
            round(float(summary.get("maxGross", 0.0)), 2),
            summary.get("topTicker"),
            round(float(summary.get("topTickerApproxShare", np.nan)), 3),
            flush=True,
        )

    out = pd.DataFrame(rows).sort_values("pnl", ascending=False)
    out.to_csv(OUT, index=False)
    if best is not None:
        best_trades.to_csv(BEST_TRADES, index=False)
        best_eq.to_csv(BEST_EQUITY, index=False)
        print("BEST", best[1])
    print("WROTE", OUT, BEST_TRADES, BEST_EQUITY)


if __name__ == "__main__":
    main()
