"""
nonequity/swing_tf_daily.py — daily-bar trend discovery harness (Gate 0)
========================================================================
Session-AGNOSTIC daily-bar trend-following. NOT the equity power-hour engine:
no 14:00-15:55 window, no HOD/LOD/RVol, no intraday gap detection. One bar per
trading day across the full continuous session (daily_bars), chandelier ATR exit.

Runs a 2x2 comparison so each cell is a control for the others — only ENTRY and
HOLD differ; exit / cost / sizing are identical:

                 max_hold = 5 (equity-style)   max_hold = None (CTA: let it run)
    Donchian-20            A                              B
    EMA-30                 C                              D

Pre-committed params (NOT tuned on results): Donchian N=20, EMA period=30,
chandelier mult=2.5, cost = MGC (pv=10, tick=0.10, 1-tick slippage/side).

Reads ONLY nonequity._core + nonequity.specs. Self-contained.

Usage
-----
    python -m nonequity.swing_tf_daily --parquet nonequity/data/GC_continuous_1m_8y.parquet
    # optional roll diagnostic (needs the *_raw.parquet sidecar with instrument_id):
    python -m nonequity.swing_tf_daily --parquet ...GC...parquet \
        --raw nonequity/data/GC_continuous_1m_8y_raw.parquet
"""
from __future__ import annotations
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from nonequity._core import load_parquet, daily_bars, daily_atr_series, Trade, FuturesCost
    from nonequity import specs
except ImportError:                      # run as a script from inside nonequity/
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from nonequity._core import load_parquet, daily_bars, daily_atr_series, Trade, FuturesCost
    from nonequity import specs


# ── entry signal series (computed on daily close; no lookahead) ──────────────
def ema_state(close: pd.Series, period: int) -> pd.Series:
    """+1 when close above EMA, -1 below. Entry = a flip in this state."""
    e = close.ewm(span=period, adjust=False).mean()
    return np.sign(close - e)


def donchian_levels(daily: pd.DataFrame, n: int):
    """Prior-N-day high/low (excludes today → no lookahead). Long break = close >
    prior high; short break = close < prior low."""
    prior_high = daily["high"].rolling(n).max().shift(1)
    prior_low = daily["low"].rolling(n).min().shift(1)
    return prior_high, prior_low


# ── one backtest (one entry mechanism, one hold rule) ────────────────────────
def backtest(daily: pd.DataFrame, atr: pd.Series, cost: FuturesCost, *,
             entry: str, n_or_period: int, mult: float, max_hold):
    """Walk daily bars. One position at a time, long & short. Entry at the close
    of the signal day. Chandelier trailing stop (highest-high-since-entry −
    mult*ATR for longs, symmetric for shorts), checked against the day's low/high;
    a stop that GAPS THROUGH fills at the (worse) open — honest, not optimistic.
    Returns (trades, equity_curve)."""
    idx = daily.index
    close = daily["close"]; high = daily["high"]; low = daily["low"]; op = daily["open"]
    rt = cost.round_turn_cost(); pv = cost.point_value

    if entry == "donchian":
        p_high, p_low = donchian_levels(daily, n_or_period)
        long_sig = (close > p_high)
        short_sig = (close < p_low)
        warm = n_or_period
    elif entry == "ema":
        st = ema_state(close, n_or_period)
        long_sig = (st > 0) & (st.shift(1) <= 0)     # cross up
        short_sig = (st < 0) & (st.shift(1) >= 0)    # cross down
        warm = n_or_period
    else:
        raise ValueError(entry)

    trades: list[Trade] = []
    pos = None  # dict: dir, entry, entry_i, peak (extreme high/low since entry)

    def atr_at(day):
        v = atr.get(pd.Timestamp(day).normalize(), np.nan)
        return float(v)

    for i in range(len(idx)):
        if i < warm:
            continue
        day = idx[i]
        a = atr_at(day)

        # ── manage open position ────────────────────────────────────────────
        if pos is not None:
            held = i - pos["entry_i"]
            exit_px = None
            if not np.isnan(a):
                if pos["dir"] == "LONG":
                    pos["peak"] = max(pos["peak"], float(high.iloc[i]))
                    stop = pos["peak"] - mult * a
                    if float(low.iloc[i]) <= stop:
                        exit_px = min(stop, float(op.iloc[i]))   # gap-through honest fill
                else:
                    pos["peak"] = min(pos["peak"], float(low.iloc[i]))
                    stop = pos["peak"] + mult * a
                    if float(high.iloc[i]) >= stop:
                        exit_px = max(stop, float(op.iloc[i]))
            if exit_px is None and max_hold is not None and held >= max_hold:
                exit_px = float(close.iloc[i])               # time exit at close
            if exit_px is not None:
                pts = (exit_px - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - exit_px)
                trades.append(Trade(day=pos["entry_day"], regime="-", direction=pos["dir"],
                                    entry=round(pos["entry"], 2), exit=round(exit_px, 2),
                                    points=round(pts, 4), pnl=round(pts * pv - rt, 2),
                                    exit_time=day, meta={"held": held}))
                pos = None

        # ── new entry (only when flat) ──────────────────────────────────────
        if pos is None:
            d = None
            if bool(long_sig.iloc[i]):
                d = "LONG"
            elif bool(short_sig.iloc[i]):
                d = "SHORT"
            if d is not None:
                e = float(close.iloc[i])
                pos = dict(dir=d, entry=e, entry_i=i, entry_day=day,
                           peak=float(high.iloc[i]) if d == "LONG" else float(low.iloc[i]))

    eq = np.cumsum([t.pnl for t in trades]) if trades else np.array([])
    return trades, eq


# ── metrics ──────────────────────────────────────────────────────────────────
def max_drawdown(eq: np.ndarray) -> float:
    if len(eq) == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    return float(np.max(peak - eq))


def metrics(trades: list[Trade], eq: np.ndarray) -> dict:
    if not trades:
        return dict(n=0, net=0.0, pf=float("nan"), wr=float("nan"), maxdd=0.0, ret_dd=float("nan"))
    pnl = np.array([t.pnl for t in trades])
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl < 0].sum()
    dd = max_drawdown(eq)
    return dict(
        n=len(trades), net=float(pnl.sum()),
        pf=(float(wins / losses) if losses > 0 else float("inf")),
        wr=float((pnl > 0).mean()),
        maxdd=dd, ret_dd=(float(pnl.sum() / dd) if dd > 0 else float("inf")),
    )


def by_year(trades: list[Trade]) -> dict:
    y = {}
    for t in trades:
        yr = pd.Timestamp(t.day).year
        y[yr] = y.get(yr, 0.0) + t.pnl
    return dict(sorted(y.items()))


# ── roll-boundary diagnostic (optional, needs raw sidecar) ───────────────────
def roll_dates_from_raw(raw_path: str) -> set:
    raw = pd.read_parquet(raw_path)
    if "instrument_id" not in raw.columns:
        return set()
    iid = raw["instrument_id"]
    changed = iid.ne(iid.shift(1)); changed.iloc[0] = False
    roll_idx = raw.index[changed.to_numpy()]
    return {pd.Timestamp(d).tz_convert("America/New_York").normalize().tz_localize(None)
            for d in roll_idx}


def roll_pnl_share(trades: list[Trade], rolls: set) -> tuple:
    """Fraction of trades whose hold window touches a roll date, and their net."""
    if not rolls or not trades:
        return 0.0, 0.0
    touch = []
    for t in trades:
        a = pd.Timestamp(t.day).normalize()
        b = pd.Timestamp(t.exit_time).normalize() if t.exit_time is not None else a
        if any(a <= r <= b for r in rolls):
            touch.append(t)
    net_touch = sum(t.pnl for t in touch)
    return len(touch) / len(trades), net_touch


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description="Daily-bar trend discovery (2x2).")
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--raw", help="optional *_raw.parquet sidecar for roll diagnostic")
    ap.add_argument("--instrument", default="MGC", choices=list(specs.SPECS.keys()))
    ap.add_argument("--donchian-n", type=int, default=20)
    ap.add_argument("--ema-period", type=int, default=30)
    ap.add_argument("--mult", type=float, default=2.5)
    a = ap.parse_args()

    c = specs.SPECS[a.instrument]
    cost = FuturesCost(point_value=c.point_value, tick=c.tick,
                       commission_rt=c.commission_rt, slippage_ticks_per_side=1.0)
    print(f"instrument {a.instrument}: pv=${c.point_value} tick={c.tick} "
          f"round_turn=${cost.round_turn_cost():.2f}  | mult={a.mult} "
          f"donchian_n={a.donchian_n} ema={a.ema_period}\n")

    df = load_parquet(a.parquet)
    daily = daily_bars(df)
    atr = daily_atr_series(df)
    print(f"daily bars: {len(daily)}  {daily.index[0].date()} → {daily.index[-1].date()}\n")

    rolls = roll_dates_from_raw(a.raw) if a.raw else set()

    configs = [
        ("A  Donchian-20  hold=5",    "donchian", a.donchian_n, 5),
        ("B  Donchian-20  hold=None", "donchian", a.donchian_n, None),
        ("C  EMA-30       hold=5",    "ema",      a.ema_period, 5),
        ("D  EMA-30       hold=None", "ema",      a.ema_period, None),
    ]

    print(f"{'config':<26}{'n':>5}{'PF':>7}{'WR':>7}{'net$':>11}{'maxDD$':>10}{'net/DD':>8}")
    print("-" * 74)
    results = {}
    for label, entry, p, hold in configs:
        tr, eq = backtest(daily, atr, cost, entry=entry, n_or_period=p, mult=a.mult, max_hold=hold)
        m = metrics(tr, eq)
        results[label] = (tr, m)
        pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else "inf"
        rd = f"{m['ret_dd']:.2f}" if np.isfinite(m['ret_dd']) else "inf"
        print(f"{label:<26}{m['n']:>5}{pf:>7}{m['wr']*100:>6.0f}%"
              f"{m['net']:>11,.0f}{m['maxdd']:>10,.0f}{rd:>8}")

    print("\nyear-by-year net$ (falsification: no single year may carry it — QQQ rule):")
    years = sorted({pd.Timestamp(t.day).year for tr, _ in results.values() for t in tr})
    print(f"{'config':<26}" + "".join(f"{y:>9}" for y in years))
    for label, (tr, _) in results.items():
        yb = by_year(tr)
        print(f"{label:<26}" + "".join(f"{yb.get(y,0):>9,.0f}" for y in years))

    if rolls:
        print(f"\nroll-boundary diagnostic ({len(rolls)} rolls) — share of trades touching a "
              "roll & their net$ (high net here = roll artifact, not edge):")
        for label, (tr, _) in results.items():
            frac, net_t = roll_pnl_share(tr, rolls)
            print(f"  {label:<26} {frac*100:>5.1f}% of trades   net@roll ${net_t:>10,.0f}")
    else:
        print("\n(no --raw sidecar given → roll-boundary diagnostic skipped)")


if __name__ == "__main__":
    main()
