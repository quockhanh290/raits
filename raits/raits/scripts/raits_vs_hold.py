"""
raits_vs_hold.py — IS analysis: RAITS vs buy-and-hold, 2017-2022.

Usage:
    python raits_vs_hold.py [--trade-log PATH] [--spy-parquet PATH]
                            [--qqq-csv PATH] [--capital FLOAT]
                            [--out-png PATH]

Defaults:
    --trade-log  : raits/configs/wfo_trade_log.csv  (auto-detected)
    --spy-parquet: raits/data/cache/daily/SPY_daily_2017-01-03_2024-12-31.parquet (auto-detected)
    --qqq-csv    : (no default; if omitted Curve B' is skipped with a notice)
    --capital    : 50000
    --out-png    : raits_vs_hold_curves.png

SCOPE: IN-SAMPLE ONLY (2017-01-01 to 2022-12-31). No 2023+ data touched.
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IS_START = "2017-01-01"
IS_END = "2022-12-31"

# Auto-detected default paths (resolved relative to this file's location)
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent.parent.parent  # raits/raits/scripts -> raits/raits -> raits/raits -> raits

_DEFAULT_TRADE_LOG = _REPO_ROOT / "raits" / "configs" / "wfo_trade_log.csv"
_DEFAULT_SPY_PARQUET = (
    _REPO_ROOT / "raits" / "data" / "cache" / "daily" /
    "SPY_daily_2017-01-03_2024-12-31.parquet"
)


# ---------------------------------------------------------------------------
# Regime classification — pure functions, no I/O
# ---------------------------------------------------------------------------

def _classify_single_day(close: float, sma50: float, sma200: float) -> str:
    """Classify one calendar day into BULL / BEAR / CHOPPY.

    Rule (fixed, pre-specified — not tuned):
      BULL    : SMA50 > SMA200  AND  close > SMA50
      BEAR    : SMA50 < SMA200  (downtrend, regardless of close)
      CHOPPY  : everything else (SMA50 >= SMA200 but close <= SMA50, or NaN SMAs)
    """
    if np.isnan(sma50) or np.isnan(sma200):
        return "CHOPPY"
    if sma50 < sma200:
        return "BEAR"
    if sma50 > sma200 and close > sma50:
        return "BULL"
    return "CHOPPY"


def classify_regimes(spy_prices: pd.DataFrame) -> pd.Series:
    """Return a Series of 'BULL'/'BEAR'/'CHOPPY' indexed by the same DatetimeIndex.

    Args:
        spy_prices: DataFrame with 'close' column and DatetimeIndex.
    """
    close = spy_prices["close"]
    sma50 = close.rolling(50, min_periods=50).mean()
    sma200 = close.rolling(200, min_periods=200).mean()

    regimes = pd.Series(index=spy_prices.index, dtype=str)
    for dt in spy_prices.index:
        regimes[dt] = _classify_single_day(
            float(close[dt]), float(sma50[dt]), float(sma200[dt])
        )
    return regimes


# ---------------------------------------------------------------------------
# Equity curve builders — pure functions, no I/O
# ---------------------------------------------------------------------------

def build_raits_equity_curve(
    trades_df: pd.DataFrame,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """Build a daily equity curve from the RAITS trade log.

    P&L is realized on the exit date of each trade (exit_time).
    Capital on day T = start_capital + sum(net_pnl for trades exited on or before T).

    Args:
        trades_df: DataFrame with 'exit_time' (datetime-like) and 'net_pnl' columns.
        start_capital: Starting capital.
        date_range: Ordered DatetimeIndex of business days to include.

    Returns:
        Series of equity values indexed by date_range.
    """
    if len(trades_df) == 0:
        return pd.Series(start_capital, index=date_range, dtype=float)

    df = trades_df.copy()
    df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.normalize()

    daily_pnl = (
        df.groupby("exit_date")["net_pnl"]
        .sum()
        .reindex(date_range, fill_value=0.0)
    )
    cumulative = daily_pnl.cumsum() + start_capital
    cumulative.name = None
    return cumulative


def build_hold_equity_curve(
    prices: pd.DataFrame,
    start_capital: float,
) -> pd.Series:
    """Build a buy-and-hold equity curve (price return, no dividends).

    Buys on the first available date in `prices` at that day's close price.

    Args:
        prices: DataFrame with 'close' column and DatetimeIndex.
        start_capital: Starting capital.

    Returns:
        Series of equity values indexed by prices.index.
    """
    close = prices["close"].astype(float)
    entry_price = float(close.iloc[0])
    curve = start_capital * (close / entry_price)
    return curve


def build_overlay_equity_curve(
    trades_df: pd.DataFrame,
    spy_prices: pd.DataFrame,
    regimes: pd.Series,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """Build Curve C: RAITS with a bull-hold overlay.

    On BULL days: capital earns SPY price return for that day (no RAITS trades applied).
    On non-BULL days: apply RAITS net_pnl (same as Curve A), ignore SPY return.

    The SPY daily return is computed from consecutive closes in spy_prices.
    Equity is tracked incrementally day by day.

    Args:
        trades_df: DataFrame with 'exit_time' and 'net_pnl'.
        spy_prices: DataFrame with 'close' column indexed by business dates.
        regimes: Series of 'BULL'/'BEAR'/'CHOPPY' indexed by business dates.
        start_capital: Starting capital.
        date_range: Ordered DatetimeIndex of business days.

    Returns:
        Series of equity values indexed by date_range.
    """
    # Pre-compute daily RAITS P&L per date
    if len(trades_df) > 0:
        df = trades_df.copy()
        df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.normalize()
        daily_raits_pnl = (
            df.groupby("exit_date")["net_pnl"]
            .sum()
            .reindex(date_range, fill_value=0.0)
        )
    else:
        daily_raits_pnl = pd.Series(0.0, index=date_range)

    # SPY daily returns: ret[t] = close[t] / close[t-1] - 1
    spy_close = spy_prices["close"].reindex(date_range)
    spy_ret = spy_close.pct_change().fillna(0.0)

    equity = start_capital
    values = []
    for dt in date_range:
        regime = regimes.get(dt, "CHOPPY")
        if regime == "BULL":
            equity *= 1.0 + float(spy_ret[dt])
        else:
            equity += float(daily_raits_pnl[dt])
        values.append(equity)

    return pd.Series(values, index=date_range, dtype=float)


# ---------------------------------------------------------------------------
# Two genuinely distinct conventions (the real unit-consistency fix)
# ---------------------------------------------------------------------------

def _daily_raits_pnl_series(trades_df: pd.DataFrame, date_range: pd.DatetimeIndex) -> pd.Series:
    """Helper: sum of RAITS net_pnl per calendar date, reindexed to date_range."""
    if len(trades_df) == 0:
        return pd.Series(0.0, index=date_range)
    df = trades_df.copy()
    df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.normalize()
    return (
        df.groupby("exit_date")["net_pnl"]
        .sum()
        .reindex(date_range, fill_value=0.0)
    )


def _spy_daily_ret(spy_prices: pd.DataFrame, date_range: pd.DatetimeIndex) -> pd.Series:
    """Helper: SPY daily % returns, day 0 = 0."""
    return spy_prices["close"].reindex(date_range).pct_change().fillna(0.0)


# ---- FIXED MODE: no compounding for any curve ----

def build_fixed_raits_curve(
    trades_df: pd.DataFrame,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """FIXED mode — add raw RAITS net_pnl each day; no compounding.

    All three fixed-mode curves use the same non-compounding basis.
    """
    daily_pnl = _daily_raits_pnl_series(trades_df, date_range)
    return (daily_pnl.cumsum() + start_capital).rename(None)


def build_fixed_spy_curve(
    spy_prices: pd.DataFrame,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """FIXED mode — SPY P&L = spy_daily_return * start_capital, summed.

    Keeps SPY on the same non-compounding basis as RAITS.
    No path-dependency; each day's dollar gain uses the fixed starting notional.
    """
    daily_pnl = _spy_daily_ret(spy_prices, date_range) * start_capital
    return (daily_pnl.cumsum() + start_capital).rename(None)


def build_fixed_overlay_curve(
    trades_df: pd.DataFrame,
    spy_prices: pd.DataFrame,
    regimes: pd.Series,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """FIXED mode — BULL days: spy_ret * start_capital; non-BULL: RAITS net_pnl. Sum.

    Both sides use fixed-dollar P&L on the same starting notional.
    """
    raits_pnl = _daily_raits_pnl_series(trades_df, date_range)
    spy_fixed_pnl = _spy_daily_ret(spy_prices, date_range) * start_capital

    equity = start_capital
    values = []
    for dt in date_range:
        if regimes.get(dt, "CHOPPY") == "BULL":
            equity += float(spy_fixed_pnl[dt])
        else:
            equity += float(raits_pnl[dt])
        values.append(equity)
    return pd.Series(values, index=date_range, dtype=float)


# ---- COMPOUND MODE: everything compounds on one running balance ----

def build_compound_raits_curve(
    trades_df: pd.DataFrame,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """COMPOUND mode — equity *= (1 + pnl/start_capital) each day.

    RAITS P&L is normalized to start_capital to express it as a % return,
    then that same % is applied to the current (growing) equity. This assumes
    positions are re-sized proportionally as the account grows — consistent with
    how SPY compound mode works.

    PROOF of difference from simple-sum:
      equity[t] = start * product(1 + pnl_t/start)
      ≠ start + sum(pnl_t)   when account grows (Jensen's inequality / compounding)
    """
    daily_pnl = _daily_raits_pnl_series(trades_df, date_range)
    equity = start_capital
    values = []
    for dt in date_range:
        pnl = float(daily_pnl[dt])
        equity *= 1.0 + pnl / start_capital  # normalize to starting base
        values.append(equity)
    return pd.Series(values, index=date_range, dtype=float)


def build_compound_spy_curve(
    spy_prices: pd.DataFrame,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """COMPOUND mode — equity *= (1 + SPY daily return) each day.

    Standard price-ratio hold: equity[t] = start_capital * (close[t] / close[0]).
    """
    close = spy_prices["close"].reindex(date_range).astype(float)
    return (start_capital * close / float(close.iloc[0])).rename(None)


def build_compound_overlay_curve(
    trades_df: pd.DataFrame,
    spy_prices: pd.DataFrame,
    regimes: pd.Series,
    start_capital: float,
    date_range: pd.DatetimeIndex,
) -> pd.Series:
    """COMPOUND mode — BULL days: SPY % return; non-BULL: pnl/start_capital.

    Both sides express returns as a percentage and compound on the same
    running balance. No mixing: BULL uses SPY %, non-BULL uses RAITS %.
    """
    raits_pnl = _daily_raits_pnl_series(trades_df, date_range)
    spy_ret = _spy_daily_ret(spy_prices, date_range)

    equity = start_capital
    values = []
    for dt in date_range:
        if regimes.get(dt, "CHOPPY") == "BULL":
            daily_return = float(spy_ret[dt])
        else:
            daily_return = float(raits_pnl[dt]) / start_capital
        equity *= 1.0 + daily_return
        values.append(equity)
    return pd.Series(values, index=date_range, dtype=float)


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _cagr(curve: pd.Series) -> float:
    years = len(curve) / 252.0
    if years == 0 or curve.iloc[0] == 0:
        return float("nan")
    return (curve.iloc[-1] / curve.iloc[0]) ** (1.0 / years) - 1.0


def _sharpe(curve: pd.Series) -> float:
    daily_ret = curve.pct_change().dropna()
    if daily_ret.std() == 0:
        return float("nan")
    return float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))


def sortino(curve: pd.Series, annual_factor: float = 252) -> float:
    """Annualized Sortino ratio with 0% MAR (downside deviation uses all periods).

    Returns +inf when mean > 0 but no negative return days exist.
    Returns 0.0 when mean == 0 and no downside (flat curve).
    """
    daily_ret = curve.pct_change().dropna()
    if len(daily_ret) == 0:
        return float("nan")
    mean_ret = float(daily_ret.mean())
    downside = daily_ret[daily_ret < 0]
    if len(downside) == 0:
        return 0.0 if mean_ret == 0.0 else float("inf")
    downside_dev = float(np.sqrt((downside ** 2).mean()))
    if downside_dev == 0.0:
        return float("nan")
    return float(mean_ret / downside_dev * np.sqrt(annual_factor))


def verify_bull_day_return_equality(
    curve_c: pd.Series,
    curve_b: pd.Series,
    regimes: pd.Series,
    tol: float = 1e-9,
) -> bool:
    """Return True if Curve C's daily % return equals Curve B's on every BULL day.

    Skips the first calendar day of each curve (pct_change is NaN there).
    """
    bull_dates = regimes[regimes == "BULL"].index
    if len(bull_dates) == 0:
        return True
    c_ret = curve_c.pct_change()
    b_ret = curve_b.pct_change()
    for dt in bull_dates:
        if dt not in c_ret.index or dt not in b_ret.index:
            continue
        cr = float(c_ret[dt])
        br = float(b_ret[dt])
        if np.isnan(cr) or np.isnan(br):
            continue
        if abs(cr - br) > tol:
            return False
    return True


def _max_drawdown(curve: pd.Series) -> float:
    running_max = curve.cummax()
    dd = (curve - running_max) / running_max
    return float(dd.min())


def _summary_row(label: str, curve: pd.Series) -> dict:
    total_ret = (curve.iloc[-1] / curve.iloc[0] - 1.0) * 100.0
    sor = sortino(curve)
    sor_str = f"{sor:.2f}" if np.isfinite(sor) else ("inf" if sor > 0 else "nan")
    return {
        "Curve": label,
        "Start $": f"${curve.iloc[0]:,.0f}",
        "End $": f"${curve.iloc[-1]:,.0f}",
        "Total Return": f"{total_ret:.1f}%",
        "CAGR": f"{_cagr(curve) * 100:.1f}%",
        "Sharpe": f"{_sharpe(curve):.2f}",
        "Sortino": sor_str,
        "Max DD": f"{_max_drawdown(curve) * 100:.1f}%",
    }


# ---------------------------------------------------------------------------
# Regime-split analysis
# ---------------------------------------------------------------------------

def regime_split_analysis(
    trades_df: pd.DataFrame,
    spy_prices: pd.DataFrame,
    regimes: pd.Series,
    start_capital: float,
) -> pd.DataFrame:
    """For each regime bucket, compare RAITS P&L vs SPY buy-and-hold P&L.

    SPY P&L is computed as simple daily % return * start_capital (non-compounding),
    so it reconciles directly with the dollar P&L from the trade log.

    Returns a DataFrame with one row per regime.
    """
    rows = []
    for regime_label in ["BULL", "CHOPPY", "BEAR"]:
        regime_days = regimes[regimes == regime_label].index

        # RAITS: sum of net_pnl on trades whose exit_time falls on regime days
        if len(trades_df) > 0:
            df = trades_df.copy()
            df["exit_date"] = pd.to_datetime(df["exit_time"]).dt.normalize()
            mask = df["exit_date"].isin(regime_days)
            raits_pnl = float(df.loc[mask, "net_pnl"].sum())
            raits_trades = int(mask.sum())
        else:
            raits_pnl = 0.0
            raits_trades = 0

        # Buy-and-hold SPY: sum of daily $ return if fully invested in SPY
        all_spy = spy_prices["close"]
        spy_pnl = 0.0
        for dt in regime_days:
            loc = all_spy.index.get_loc(dt)
            if loc == 0:
                continue
            prev_close = float(all_spy.iloc[loc - 1])
            curr_close = float(all_spy.iloc[loc])
            daily_ret = (curr_close - prev_close) / prev_close
            spy_pnl += daily_ret * start_capital

        n_days = len(regime_days)
        raits_pct = raits_pnl / start_capital * 100.0
        spy_pct = spy_pnl / start_capital * 100.0
        winner = (
            "RAITS" if raits_pnl > spy_pnl
            else ("SPY hold" if spy_pnl > raits_pnl else "tie")
        )
        rows.append({
            "Regime": regime_label,
            "Days": n_days,
            "RAITS trades": raits_trades,
            "RAITS P&L $": f"${raits_pnl:+,.0f}",
            "RAITS %": f"{raits_pct:+.1f}%",
            "SPY hold P&L $": f"${spy_pnl:+,.0f}",
            "SPY hold %": f"{spy_pct:+.1f}%",
            "Winner": winner,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trade-log", default=str(_DEFAULT_TRADE_LOG))
    p.add_argument("--spy-parquet", default=str(_DEFAULT_SPY_PARQUET))
    p.add_argument("--qqq-csv", default=None,
                   help="Path to QQQ daily CSV (date,close). If omitted Curve B (QQQ) is skipped.")
    p.add_argument("--capital", type=float, default=50_000.0)
    p.add_argument("--out-png", default="raits_vs_hold_curves.png")
    p.add_argument("--mode", choices=["fixed", "compound", "both"], default="both",
                   help="Convention: fixed (non-compounding notional), "
                        "compound (proportional re-sizing), or both (default).")
    return p.parse_args()


def _load_spy(path: str, start: str, end: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
    df.index = pd.to_datetime(df.index).normalize()
    df = df.sort_index()
    return df.loc[start:end]


def _load_qqq(path: str, start: str, end: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=[0], index_col=0)
    df.columns = [c.strip().lower() for c in df.columns]
    if "close" not in df.columns:
        raise ValueError(f"QQQ CSV must have a 'close' column. Found: {list(df.columns)}")
    df.index = pd.to_datetime(df.index).normalize()
    df = df.sort_index()
    return df.loc[start:end][["close"]]


def _load_trades(path: str, start: str, end: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["exit_date"] = df["exit_time"].dt.normalize()
    mask = (df["exit_date"] >= start) & (df["exit_date"] <= end)
    return df[mask].reset_index(drop=True)


def _print_mode_results(
    label: str,
    curve_a: pd.Series,
    curve_b: pd.Series,
    curve_c: pd.Series,
    curve_b_label: str = "B  Hold SPY",
) -> None:
    """Print summary table, honest delta, and verdict for one mode."""
    SEP = "=" * 72
    print(f"\n{SEP}")
    print(f"  MODE: {label}")
    print(SEP)

    rows = [
        _summary_row("A  RAITS active", curve_a),
        _summary_row(curve_b_label, curve_b),
        _summary_row("C  RAITS + bull-hold overlay", curve_c),
    ]
    col_order = ["Curve", "Start $", "End $", "Total Return", "CAGR",
                 "Sharpe", "Sortino", "Max DD"]
    print(pd.DataFrame(rows, columns=col_order).to_string(index=False))

    cagr_a = _cagr(curve_a) * 100.0
    cagr_c = _cagr(curve_c) * 100.0
    delta_cagr = cagr_c - cagr_a
    delta_final = float(curve_c.iloc[-1] - curve_a.iloc[-1])
    ratio = float(curve_c.iloc[-1] / curve_a.iloc[-1])

    print(f"\n  Honest overlay delta (C - A):  CAGR +{delta_cagr:.1f}pp,  "
          f"final ${delta_final:+,.0f}")
    print(f"  Ratio C/A: {ratio:.2f}x", end="")
    if ratio > 2.0:
        print("  <<< WARNING: ratio >2x — check for unit mixing >>>", end="")
    print()

    sign = "BEATS" if delta_cagr > 0 else "TRAILS"
    worth = "large enough to justify building a bull-detection branch" if delta_cagr > 3 else "marginal"
    print(f"\n  VERDICT ({label}): The overlay {sign} RAITS-as-is by "
          f"CAGR {delta_cagr:+.1f}pp (${delta_final:+,.0f}). "
          f"{'Improvement is ' + worth + '.' if delta_cagr > 0 else 'Overlay does not help.'}")


def main():
    args = _parse_args()
    start, end = IS_START, IS_END
    capital = args.capital

    print(f"\n{'='*72}")
    print("RAITS vs Buy-and-Hold  |  IN-SAMPLE 2017-2022  |  Unit-consistent")
    print(f"{'='*72}")
    print(f"Capital: ${capital:,.0f}  |  Mode: {args.mode}")
    print(f"Trade log: {args.trade_log}")
    print(f"SPY data:  {args.spy_parquet}")

    # ---- Load data -------------------------------------------------------
    trades = _load_trades(args.trade_log, start, end)
    print(f"Trades loaded: {len(trades)}  "
          f"(exit dates {trades['exit_date'].min().date()} - {trades['exit_date'].max().date()})")

    spy = _load_spy(args.spy_parquet, start, end)
    print(f"SPY daily rows: {len(spy)} ({spy.index[0].date()} - {spy.index[-1].date()})")

    if args.qqq_csv:
        qqq = _load_qqq(args.qqq_csv, start, end)
        print(f"QQQ daily rows: {len(qqq)}")
    else:
        print("QQQ CSV not provided. Pass --qqq-csv if needed.")

    date_range = spy.index

    # ---- Classify regimes -----------------------------------------------
    print("\nClassifying market regimes (SPY SMA50/SMA200)...")
    regimes = classify_regimes(spy)
    rc = regimes.value_counts()
    print(f"  BULL: {rc.get('BULL', 0)}  CHOPPY: {rc.get('CHOPPY', 0)}  BEAR: {rc.get('BEAR', 0)}")

    # ---- Build equity curves (all compounding) --------------------------
    # Curve A: equity[t] = equity[t-1] * (1 + pnl[t]/equity[t-1]) = equity[t-1] + pnl[t]
    # Curve B: equity[t] = equity[t-1] * (1 + spy_ret[t])
    # ---- Build curves for both conventions ----------------------------------
    # Fixed mode: all additive dollar P&L; no compounding
    fixed_a = build_fixed_raits_curve(trades, capital, date_range)
    fixed_b = build_fixed_spy_curve(spy, capital, date_range)
    fixed_c = build_fixed_overlay_curve(trades, spy, regimes, capital, date_range)

    # Compound mode: equity *= (1 + return_t); RAITS return = pnl/start_capital
    cmpd_a = build_compound_raits_curve(trades, capital, date_range)
    cmpd_b = build_compound_spy_curve(spy, capital, date_range)
    cmpd_c = build_compound_overlay_curve(trades, spy, regimes, capital, date_range)

    # ---- Assertion #1: compound Curve A must DIFFER from simple-sum ----
    simple_sum_final = float(capital + trades["net_pnl"].sum())
    cmpd_a_final = float(cmpd_a.iloc[-1])
    diff1 = abs(cmpd_a_final - simple_sum_final)
    print(f"\n[ASSERT-1] compound Curve A: ${cmpd_a_final:,.2f}  |  "
          f"simple-sum: ${simple_sum_final:,.2f}  |  diff: ${diff1:,.2f}")
    assert diff1 > 1.0, (
        f"FAIL: compound Curve A (${cmpd_a_final:,.2f}) == simple-sum (${simple_sum_final:,.2f}). "
        "Use pnl/start_capital, not pnl/current_equity."
    )
    print("           PASS: compound != simple-sum (fix is genuine)")

    # ---- Assertion #2: fixed Curve B must DIFFER from compound SPY ----
    fixed_b_final = float(fixed_b.iloc[-1])
    cmpd_b_final = float(cmpd_b.iloc[-1])
    diff2 = abs(fixed_b_final - cmpd_b_final)
    print(f"\n[ASSERT-2] fixed Curve B: ${fixed_b_final:,.2f}  |  "
          f"compound Curve B: ${cmpd_b_final:,.2f}  |  diff: ${diff2:,.2f}")
    assert diff2 > 1.0, (
        f"FAIL: fixed Curve B (${fixed_b_final:,.2f}) == compound Curve B (${cmpd_b_final:,.2f}). "
        "Fixed SPY must use ret*start_capital, not price-ratio compounding."
    )
    print("           PASS: fixed != compound for SPY (fixed mode is genuine)")

    # ---- Assertion #3: bull-day equality in each mode -------------------
    print("\n[ASSERT-3] Bull-day equality within each mode:")
    fixed_spy_ret = _spy_daily_ret(spy, date_range)
    fixed_spy_pnl = fixed_spy_ret * capital
    bull_days = regimes[regimes == "BULL"].index
    date_list = list(date_range)
    for dt in bull_days[:5]:
        idx = date_list.index(dt)
        if idx == 0:
            continue
        overlay_inc = float(fixed_c.iloc[idx] - fixed_c.iloc[idx - 1])
        spy_inc = float(fixed_spy_pnl.get(dt, 0.0))
        assert abs(overlay_inc - spy_inc) < 1e-6, (
            f"FIXED bull-day mismatch at {dt}: overlay={overlay_inc:.6f} spy={spy_inc:.6f}"
        )
        ret_overlay = float(cmpd_c.iloc[idx] / cmpd_c.iloc[idx - 1] - 1)
        ret_spy = float(fixed_spy_ret.get(dt, 0.0))
        assert abs(ret_overlay - ret_spy) < 1e-9, (
            f"COMPOUND bull-day return mismatch at {dt}: "
            f"overlay={ret_overlay:.9f} spy={ret_spy:.9f}"
        )
    print(f"           PASS: first-5 BULL days checked in fixed and compound modes "
          f"({len(bull_days)} total BULL days)")

    # ---- Regime-split table (fixed-dollar basis) --------------------------
    print(f"\n{'='*72}")
    print("REGIME-SPLIT ANALYSIS  (fixed-dollar basis)")
    print(f"{'='*72}")
    split_df = regime_split_analysis(trades, spy, regimes, capital)
    print(split_df.to_string(index=False))

    # ---- Per-mode output --------------------------------------------------
    run_fixed    = args.mode in ("fixed", "both")
    run_compound = args.mode in ("compound", "both")

    if run_fixed:
        _print_mode_results("FIXED (non-compounding notional)", fixed_a, fixed_b, fixed_c)

    if run_compound:
        _print_mode_results("COMPOUND (proportional re-sizing)", cmpd_a, cmpd_b, cmpd_c)

    # ---- Assertion #4: ratio C/A (flag if >2x) ----------------------------
    print(f"\n{'='*72}")
    print("RATIO CHECK (Assertion #4)")
    print(f"{'='*72}")
    for label, a, c in [("FIXED",    fixed_a, fixed_c),
                         ("COMPOUND", cmpd_a,  cmpd_c)]:
        ratio = float(c.iloc[-1] / a.iloc[-1])
        flag = "  <<< WARNING: ratio >2x — possible unit mixing >>>" if ratio > 2.0 else ""
        print(f"  {label}: Curve C / Curve A = {ratio:.2f}x{flag}")

    # ---- Caveats ----------------------------------------------------------
    print(f"\n{'='*72}")
    print("CAVEATS")
    print(f"{'='*72}")
    print("- FIXED mode: SPY uses ret * start_capital (non-compounding). Under-")
    print("  states SPY's true $ gain on a growing balance but gives a fair")
    print("  apples-to-apples comparison against RAITS's fixed-dollar P&L.")
    print("- COMPOUND mode: RAITS daily return = pnl/start_capital. Scales P&L")
    print("  proportionally as the account grows. Over-states actual RAITS earn")
    print("  (trades sized at $50k), but is the correct compound convention.")
    print("- Hold SPY excludes dividends (~1.3-1.5%/yr, slight understatement).")
    print("- This is in-sample 2017-2022. OOS data remains sealed.")

    # ---- Plot (compound if available, else fixed) -------------------------
    if run_compound:
        pa, pb, pc = cmpd_a, cmpd_b, cmpd_c
        ptitle = "RAITS vs Buy-and-Hold (COMPOUND) -- In-Sample 2017-2022"
    else:
        pa, pb, pc = fixed_a, fixed_b, fixed_c
        ptitle = "RAITS vs Buy-and-Hold (FIXED) -- In-Sample 2017-2022"

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(pa.index, pa.values, label="A  RAITS active", linewidth=1.6, color="#1f77b4")
    ax.plot(pb.index, pb.values, label="B  Hold SPY",     linewidth=1.6, color="#ff7f0e", linestyle="--")
    ax.plot(pc.index, pc.values, label="C  RAITS + bull overlay",
            linewidth=1.6, color="#2ca02c", linestyle="-.")
    ax.axhline(capital, color="gray", linewidth=0.7, linestyle=":")
    ax.set_title(ptitle, fontsize=13)
    ax.set_xlabel("Date")
    ax.set_ylabel("Portfolio Value ($)")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(args.out_png, dpi=150)
    print(f"\nChart saved -> {args.out_png}")


if __name__ == "__main__":
    main()
