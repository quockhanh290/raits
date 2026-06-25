"""
options_proxy_analysis.py
--------------------------
Level-1 Black-Scholes option proxy analysis for RAITS directional trades.

STANDALONE READ-ONLY -- no engine imports. Reads the WFO snapshot PKL and the
daily Parquet price cache; never writes or imports project engine code.

Answers: "Would expressing RAITS trades as options have improved P&L,
          after theta decay and bid/ask spread?"

This is an OPTIMISTIC proxy (no real IV skew/term structure, no real spread
depth). A negative verdict here is a definitive "no." A positive verdict
warrants real-quote validation (ORATS or similar).

Usage (from d:\\raits\\raits):
    python raits/scripts/options_proxy_analysis.py
    python raits/scripts/options_proxy_analysis.py --pkl PATH --dte 21
    python raits/scripts/options_proxy_analysis.py --csv PATH --dte 14

All CLI flags:
    --pkl PATH          WFO snapshot .pkl (default: latest baseline)
    --csv PATH          Trade-log CSV (alternative to --pkl)
    --daily_cache DIR   Directory with {TICKER}_daily_*.parquet files
    --out_dir DIR       Where to write the comparison CSV + scatter PNG
    --dte INT           Option DTE at entry (default 21; try 14, 30, 45)
    --skew FLOAT        IV multiplier for vol premium/skew (default 1.15)
    --iv_fallback FLOAT IV to use when no price cache (default 0.45)
    --rate FLOAT        Risk-free rate (default 0.04)
    --spread FLOAT      Bid/ask spread as fraction of premium (default 0.05)

Sanity-check modes:
    --audit-trade INT   Print full BS intermediate values for trade at index INT
                        (0-based, in the vault-filtered trade list) then exit.
                        Use any external BS calculator to cross-check the numbers.
    --no-theta          Force T_exit = T_entry (remove all theta decay), re-run
                        full analysis, then assert total option P&L > stock P&L.
                        If assertion fails, a bug outside theta is reported.

Allowed imports: pandas, numpy, scipy, matplotlib, stdlib, pickle only.
No project-engine imports.
"""

from __future__ import annotations

import argparse
import glob as _glob
import math
import pickle
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

# ── Default path detection ────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).parent.resolve()
# raits/raits/scripts -> up 2 = raits/raits (where data/ lives)
_RAITS_DIR = (_SCRIPT_DIR / ".." / "..").resolve()
# raits/raits -> up 1 = raits/ (project root, where configs/ lives)
_PROJECT_ROOT = (_RAITS_DIR / "..").resolve()

_DEFAULT_PKL = str(
    _RAITS_DIR / "data" / "cache" / "snapshots" / "results_20260624_200216.pkl"
)
_DEFAULT_DAILY = str(_RAITS_DIR / "data" / "cache" / "daily")
_DEFAULT_OUT = str(_PROJECT_ROOT / "configs")

VAULT_END = pd.Timestamp("2022-12-31 23:59:59")
_TDAYS_YEAR = 252

# ── Black-Scholes pricers ─────────────────────────────────────────────────────


def bs_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European call price. Returns intrinsic value when T <= 0."""
    if T <= 0:
        return max(S - K, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bs_put(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes European put price. Returns intrinsic value when T <= 0."""
    if T <= 0:
        return max(K - S, 0.0)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def _bs_intermediates(
    S: float, K: float, T: float, r: float, sigma: float
) -> dict:
    """
    Return all Black-Scholes intermediate values for one option pricing point.
    Used by --audit-trade to expose every number for hand-verification.
    """
    if T <= 0:
        return {
            "T": T, "d1": None, "d2": None,
            "Nd1": None, "Nd2": None, "Nmd1": None, "Nmd2": None,
            "disc": None,
            "call": max(S - K, 0.0),
            "put": max(K - S, 0.0),
        }
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    disc = math.exp(-r * T)
    Nd1, Nd2 = float(norm.cdf(d1)), float(norm.cdf(d2))
    Nmd1, Nmd2 = 1.0 - Nd1, 1.0 - Nd2
    call = S * Nd1 - K * disc * Nd2
    put = K * disc * Nmd2 - S * Nmd1
    return {
        "T": T, "d1": d1, "d2": d2,
        "Nd1": Nd1, "Nd2": Nd2, "Nmd1": Nmd1, "Nmd2": Nmd2,
        "disc": disc,
        "call": call, "put": put,
    }


# ── STEP 0 -- Reconciliation gate ─────────────────────────────────────────────


def reconcile_gross(
    df: pd.DataFrame, tol: float = 0.50
) -> Tuple[int, int, int]:
    """
    Verify gross_pnl == dir * shares * (exit_price - entry_price) within tol.
    Returns (n_match, n_mismatch, total).
    """
    dir_sign = df["direction"].map({"LONG": 1, "SHORT": -1}).astype(float)
    recon = dir_sign * df["shares"].astype(float) * (
        df["exit_price"].astype(float) - df["entry_price"].astype(float)
    )
    diff = (recon - df["gross_pnl"].astype(float)).abs()
    n_match = int((diff <= tol).sum())
    n_mismatch = int((diff > tol).sum())
    return n_match, n_mismatch, len(df)


# ── Data loading ──────────────────────────────────────────────────────────────


class _AnyObj:
    """Stand-in for any raits.* class during unpickling; avoids all engine imports."""
    pass


class _SafeUnpickler(pickle.Unpickler):
    """Map every raits.* class to _AnyObj so the PKL loads with no engine imports."""

    def find_class(self, module: str, name: str):
        if module.startswith("raits."):
            return _AnyObj
        return super().find_class(module, name)


def load_trades_pkl(pkl_path: str) -> pd.DataFrame:
    """Load trade log from a WFO snapshot PKL without importing any engine code."""
    with open(pkl_path, "rb") as fh:
        results = _SafeUnpickler(fh).load()

    rows: List[dict] = []
    for w in results:
        if isinstance(w, dict):
            trade_list = w.get("trades", [])
        else:
            # BacktestResult-style object (trade_log attribute)
            trade_list = getattr(w, "trade_log", None) or getattr(w, "trades", [])
        for t in trade_list:
            rows.append(vars(t))

    df = pd.DataFrame(rows)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    return df


def load_trades_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    return df


def load_daily_cache(daily_dir: str) -> Dict[str, pd.DataFrame]:
    """
    Load all {TICKER}_daily_*.parquet files from daily_dir.
    Returns {ticker: DataFrame(DatetimeIndex, 'close', ...)}.
    """
    cache: Dict[str, pd.DataFrame] = {}
    for fpath in _glob.glob(str(Path(daily_dir) / "*.parquet")):
        fname = Path(fpath).stem  # e.g. AAPL_daily_2017-01-03_2024-12-31
        parts = fname.split("_daily_")
        if len(parts) != 2:
            continue
        ticker = parts[0]
        try:
            df = pd.read_parquet(fpath)
            df.index = pd.DatetimeIndex(df.index)
            df.columns = [c.lower() for c in df.columns]
            if "close" not in df.columns:
                continue
            df = df.sort_index()
            df = df[~df.index.duplicated(keep="first")]
        except Exception:
            continue

        if ticker not in cache:
            cache[ticker] = df
        else:
            combined = pd.concat([cache[ticker], df]).sort_index()
            cache[ticker] = combined[~combined.index.duplicated(keep="first")]

    return cache


# ── Per-trade option analysis ─────────────────────────────────────────────────


def analyze_trade_option(
    row: dict,
    dte: int,
    skew: float,
    iv_fallback: float,
    rate: float,
    spread: float,
    price_cache: Dict[str, pd.DataFrame],
    no_theta: bool = False,
) -> dict:
    """
    Black-Scholes option proxy for one trade.

    row must contain: ticker, direction, entry_price, exit_price,
                      entry_time, exit_time, shares, net_pnl
    Returns a dict with all computed option fields (no net_pnl to avoid
    confusion when merging back into the main DataFrame).
    """
    ticker = str(row["ticker"])
    direction = str(row["direction"])
    S_entry = float(row["entry_price"])
    S_exit = float(row["exit_price"])
    entry_time = pd.Timestamp(row["entry_time"])
    exit_time = pd.Timestamp(row["exit_time"])
    shares = int(row["shares"])
    stock_net = float(row.get("net_pnl", 0.0))

    # (b) Holding period
    holding_calendar_days = int(
        (exit_time.normalize() - entry_time.normalize()).days
    )
    holding_hours = (exit_time - entry_time).total_seconds() / 3600.0
    holding_tdays = round(holding_calendar_days * _TDAYS_YEAR / 365)

    # (c) Time parameters
    T_entry = dte / 365.0
    T_exit = T_entry if no_theta else max(dte - holding_calendar_days, 0) / 365.0

    # (d) IV from trailing realized vol (close-to-close, ~20 trading days)
    iv_source = "fallback"
    iv = iv_fallback

    if ticker in price_cache:
        closes_df = price_cache[ticker]
        entry_date = entry_time.normalize()
        closes_before = closes_df[closes_df.index.normalize() < entry_date]
        if len(closes_before) >= 6:
            recent_closes = closes_before["close"].iloc[-21:]  # 21 bars -> 20 returns
            log_rets = np.log(recent_closes / recent_closes.shift(1)).dropna()
            if len(log_rets) >= 5:
                rv = float(log_rets.std() * math.sqrt(_TDAYS_YEAR))
                if rv > 0:
                    iv = rv * skew
                    iv_source = "cache"

    # (e) Price option at entry and exit; strike = entry_price (ATM at entry)
    K = S_entry
    if direction == "LONG":
        entry_premium = bs_call(S_entry, K, T_entry, rate, iv)
        exit_premium = bs_call(S_exit, K, T_exit, rate, iv)
    else:
        entry_premium = bs_put(S_entry, K, T_entry, rate, iv)
        exit_premium = bs_put(S_exit, K, T_exit, rate, iv)

    # (f) Capital deployment and contract count
    capital = shares * S_entry
    contracts = int(capital / (entry_premium * 100)) if entry_premium > 0 else 0
    zero_contracts = contracts == 0

    # (g) Option P&L
    if contracts == 0:
        option_gross = 0.0
        spread_cost = 0.0
        option_net = 0.0
    else:
        option_gross = float(contracts * 100 * (exit_premium - entry_premium))
        spread_cost = float(contracts * 100 * entry_premium * spread)
        option_net = option_gross - spread_cost

    # (i) Classification flags
    expired_worthless = bool(exit_premium < 0.01)
    hit_full_loss = bool(
        not zero_contracts
        and option_net <= -(entry_premium * contracts * 100)
    )
    theta_dominated = bool(stock_net >= 0 and option_net < 0)

    return {
        "iv": iv,
        "iv_source": iv_source,
        "holding_calendar_days": holding_calendar_days,
        "holding_hours": holding_hours,
        "holding_tdays": holding_tdays,
        "T_entry": T_entry,
        "T_exit": T_exit,
        "entry_premium": entry_premium,
        "exit_premium": exit_premium,
        "contracts": contracts,
        "capital": capital,
        "option_gross": option_gross,
        "spread_cost": spread_cost,
        "option_net": option_net,
        "expired_worthless": expired_worthless,
        "hit_full_loss": hit_full_loss,
        "theta_dominated": theta_dominated,
        "zero_contracts": zero_contracts,
    }


# ── Reporting helpers ─────────────────────────────────────────────────────────


def _metrics(pnls: pd.Series) -> dict:
    """Compute summary stats for a P&L series."""
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    n = len(pnls)
    return {
        "total": float(pnls.sum()),
        "n": n,
        "win_rate": len(wins) / n if n else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "worst": float(pnls.min()) if n else 0.0,
    }


def _fmt_row(label: str, stock: dict, opt: dict, pct_opt_beats: float) -> str:
    return (
        f"  {label:<22}"
        f"  Stock: total={stock['total']:>+9,.0f}  WR={stock['win_rate']:.0%}"
        f"  avgW={stock['avg_win']:>+7,.0f}  avgL={stock['avg_loss']:>+7,.0f}"
        f"  worst={stock['worst']:>+8,.0f}"
        f"  |  Option: total={opt['total']:>+9,.0f}  WR={opt['win_rate']:.0%}"
        f"  avgW={opt['avg_win']:>+7,.0f}  avgL={opt['avg_loss']:>+7,.0f}"
        f"  worst={opt['worst']:>+8,.0f}"
        f"  |  opt_beats={pct_opt_beats:.0%}"
    )


def _print_headline(df: pd.DataFrame) -> None:
    s_m = _metrics(df["net_pnl"])
    o_m = _metrics(df["option_net"])
    pct_beats = float((df["option_net"] > df["net_pnl"]).mean())
    theta_drag = float(df.loc[df["theta_dominated"], "option_net"].sum())
    n_theta = int(df["theta_dominated"].sum())
    n_zero = int(df["zero_contracts"].sum())
    n_expired = int(df["expired_worthless"].sum())

    print("\n" + "=" * 100)
    print("  HEADLINE: STOCK vs OPTION  (all valid vault trades)")
    print("=" * 100)
    print(f"  {'Metric':<22}  {'STOCK':>14}  {'OPTION':>14}")
    print(f"  {'-'*22}  {'-'*14}  {'-'*14}")
    print(f"  {'Total P&L':<22}  {s_m['total']:>+14,.0f}  {o_m['total']:>+14,.0f}")
    print(f"  {'Win rate':<22}  {s_m['win_rate']:>14.1%}  {o_m['win_rate']:>14.1%}")
    print(f"  {'Avg win':<22}  {s_m['avg_win']:>+14,.0f}  {o_m['avg_win']:>+14,.0f}")
    print(f"  {'Avg loss':<22}  {s_m['avg_loss']:>+14,.0f}  {o_m['avg_loss']:>+14,.0f}")
    print(f"  {'Worst trade':<22}  {s_m['worst']:>+14,.0f}  {o_m['worst']:>+14,.0f}")
    print(f"  {'Trade count':<22}  {s_m['n']:>14,}  {o_m['n']:>14,}")
    print()
    print(f"  Option beats stock in {pct_beats:.1%} of trades  "
          f"({int(pct_beats * len(df))}/{len(df)})")
    print(f"  Zero-contract trades (excluded from option stats): {n_zero}")
    print(f"  Expired worthless: {n_expired}  "
          f"  Theta-dominated: {n_theta}")
    print(f"  THETA DRAG total: ${theta_drag:+,.0f} "
          f"across {n_theta} theta-dominated trades")


def _print_by_strategy(df: pd.DataFrame) -> None:
    print("\n" + "=" * 100)
    print("  BREAKDOWN BY STRATEGY")
    print("=" * 100)
    header = (
        f"  {'Strategy':<16}  {'N':>5}  "
        f"{'Stk Total':>10}  {'Stk WR':>7}  "
        f"{'Opt Total':>10}  {'Opt WR':>7}  "
        f"{'Diff':>10}  {'Opt Beats':>9}"
    )
    print(header)
    print("  " + "-" * 98)
    for strat, grp in df.groupby("strategy"):
        s_m = _metrics(grp["net_pnl"])
        o_m = _metrics(grp["option_net"])
        diff = o_m["total"] - s_m["total"]
        pct = float((grp["option_net"] > grp["net_pnl"]).mean())
        print(
            f"  {strat:<16}  {len(grp):>5}  "
            f"{s_m['total']:>+10,.0f}  {s_m['win_rate']:>7.1%}  "
            f"{o_m['total']:>+10,.0f}  {o_m['win_rate']:>7.1%}  "
            f"{diff:>+10,.0f}  {pct:>9.1%}"
        )


def _print_by_holding(df: pd.DataFrame) -> None:
    def bucket(days: int) -> str:
        if days == 0:
            return "<1 day"
        if days <= 3:
            return "1-3 days"
        return ">3 days"

    df = df.copy()
    df["hold_bucket"] = df["holding_calendar_days"].apply(bucket)
    order = ["<1 day", "1-3 days", ">3 days"]

    print("\n" + "=" * 100)
    print("  BREAKDOWN BY HOLDING PERIOD")
    print("=" * 100)
    header = (
        f"  {'Bucket':<12}  {'N':>5}  "
        f"{'Stk Total':>10}  {'Stk WR':>7}  "
        f"{'Opt Total':>10}  {'Opt WR':>7}  "
        f"{'Diff':>10}  {'Opt Beats':>9}"
    )
    print(header)
    print("  " + "-" * 98)
    for b in order:
        grp = df[df["hold_bucket"] == b]
        if grp.empty:
            continue
        s_m = _metrics(grp["net_pnl"])
        o_m = _metrics(grp["option_net"])
        diff = o_m["total"] - s_m["total"]
        pct = float((grp["option_net"] > grp["net_pnl"]).mean())
        print(
            f"  {b:<12}  {len(grp):>5}  "
            f"{s_m['total']:>+10,.0f}  {s_m['win_rate']:>7.1%}  "
            f"{o_m['total']:>+10,.0f}  {o_m['win_rate']:>7.1%}  "
            f"{diff:>+10,.0f}  {pct:>9.1%}"
        )


def _print_verdict(df: pd.DataFrame) -> None:
    stock_total = float(df["net_pnl"].sum())
    opt_total = float(df["option_net"].sum())
    diff = opt_total - stock_total
    diff_pct = diff / abs(stock_total) * 100 if stock_total != 0 else 0.0
    verdict = "BETTER" if opt_total > stock_total else "WORSE"

    print("\n" + "=" * 100)
    print("  VERDICT")
    print("=" * 100)
    print(f"  Stock net P&L : ${stock_total:+,.0f}")
    print(f"  Option net P&L: ${opt_total:+,.0f}")
    print(f"  Difference    : ${diff:+,.0f} ({diff_pct:+.1f}%)")
    print()
    print(f"  -> OPTIONS are {verdict} than stock in this BS proxy.")
    if opt_total <= stock_total:
        print("  -> OPTIMISTIC proxy already negative -> idea is DEAD. Skip ORATS.")
    else:
        print("  -> Positive in optimistic proxy -> validate with real quotes (ORATS).")


def _save_scatter(df: pd.DataFrame, out_path: Path, dte: int, skew: float) -> None:
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm

    strategies = sorted(df["strategy"].unique())
    colors = cm.tab10(np.linspace(0, 1, max(len(strategies), 1)))

    fig, ax = plt.subplots(figsize=(10, 8))
    for i, strat in enumerate(strategies):
        mask = df["strategy"] == strat
        ax.scatter(
            df.loc[mask, "net_pnl"],
            df.loc[mask, "option_net"],
            alpha=0.45,
            label=strat,
            color=colors[i],
            s=25,
        )

    # Break-even diagonal y = x
    all_vals = pd.concat([df["net_pnl"], df["option_net"]])
    lo, hi = all_vals.min(), all_vals.max()
    margin = (hi - lo) * 0.05
    ax.plot([lo - margin, hi + margin], [lo - margin, hi + margin],
            "k--", alpha=0.35, lw=1.2, label="y = x (break-even)")
    ax.axhline(0, color="gray", lw=0.5, alpha=0.4)
    ax.axvline(0, color="gray", lw=0.5, alpha=0.4)

    ax.set_xlabel("Stock net P&L ($)")
    ax.set_ylabel("Option net P&L ($)")
    ax.set_title(
        f"RAITS: Stock vs Option P&L per trade -- BS proxy\n"
        f"DTE={dte}  skew={skew}  (n={len(df)})"
    )
    ax.legend(loc="upper left", fontsize=8)
    plt.tight_layout()
    plt.savefig(str(out_path), dpi=120)
    plt.close(fig)


def _print_caveats(df: pd.DataFrame, dte: int) -> None:
    pct_short_hold = float((df["holding_calendar_days"] < 3).mean())
    pct_intraday = float((df["holding_calendar_days"] == 0).mean())
    print("\n" + "=" * 100)
    print("  HONESTY CAVEATS")
    print("=" * 100)
    print(
        "  1. BS PROXY IS OPTIMISTIC: no real skew/term structure; IV is realized-vol x "
        f"{df['iv'].mean():.2f} (mean).\n"
        "     Actual IV typically exceeds realized vol -> option costs are higher in practice.\n"
        "     If options lose here, they lose worse in reality -> 'no' verdict is safe."
    )
    print(
        f"\n  2. SHORT-HOLD WARNING: {pct_short_hold:.0%} of trades have <3-day hold "
        f"({pct_intraday:.0%} intraday).\n"
        "     BS is unreliable for <3-day / intraday gamma/theta dynamics.\n"
        f"     0DTE/1DTE options behave very differently from {dte}-DTE proxied here.\n"
        "     Treat the <1-day bucket as INDICATIVE ONLY."
    )
    print(
        "\n  3. LIQUIDITY: RAITS tickers are high-beta single names. Real spreads on\n"
        f"     near-ATM options may far exceed the {5:.0f}% spread assumption used here."
    )
    print(
        "\n  4. CAPITAL EQUIVALENCE: analysis holds option notional = stock notional\n"
        "     (same $ deployed). In practice options deploy less capital, freeing\n"
        "     margin -- this analysis does NOT credit that leverage benefit."
    )


# ── Sanity-check helpers ──────────────────────────────────────────────────────


def _print_audit_trade(
    row: dict,
    dte: int,
    skew: float,
    iv_fallback: float,
    rate: float,
    spread: float,
    price_cache: Dict[str, pd.DataFrame],
    idx: int,
) -> None:
    """
    Print every BS intermediate value for one trade so the user can cross-check
    against an external Black-Scholes calculator.
    """
    ticker = str(row["ticker"])
    direction = str(row["direction"])
    S_entry = float(row["entry_price"])
    S_exit = float(row["exit_price"])
    entry_time = pd.Timestamp(row["entry_time"])
    exit_time = pd.Timestamp(row["exit_time"])
    shares = int(row["shares"])
    stock_net = float(row.get("net_pnl", 0.0))
    K = S_entry  # ATM strike

    holding_calendar_days = int(
        (exit_time.normalize() - entry_time.normalize()).days
    )
    holding_hours = (exit_time - entry_time).total_seconds() / 3600.0
    T_entry = dte / 365.0
    T_exit = max(dte - holding_calendar_days, 0) / 365.0

    # IV (same logic as analyze_trade_option)
    iv_source = "fallback"
    iv = iv_fallback
    rv_raw = None
    if ticker in price_cache:
        closes_df = price_cache[ticker]
        entry_date = entry_time.normalize()
        closes_before = closes_df[closes_df.index.normalize() < entry_date]
        if len(closes_before) >= 6:
            recent_closes = closes_before["close"].iloc[-21:]
            log_rets = np.log(recent_closes / recent_closes.shift(1)).dropna()
            if len(log_rets) >= 5:
                rv_raw = float(log_rets.std() * math.sqrt(_TDAYS_YEAR))
                if rv_raw > 0:
                    iv = rv_raw * skew
                    iv_source = "cache"

    # BS intermediates at entry and exit
    opt_type = "CALL" if direction == "LONG" else "PUT"
    entry_bs = _bs_intermediates(S_entry, K, T_entry, rate, iv)
    exit_bs = _bs_intermediates(S_exit, K, T_exit, rate, iv)
    entry_premium = entry_bs["call"] if direction == "LONG" else entry_bs["put"]
    exit_premium = exit_bs["call"] if direction == "LONG" else exit_bs["put"]

    capital = shares * S_entry
    contracts = int(capital / (entry_premium * 100)) if entry_premium > 0 else 0
    option_notional = contracts * 100 * entry_premium
    capital_ratio = option_notional / capital if capital > 0 else 0.0

    option_gross = contracts * 100 * (exit_premium - entry_premium) if contracts else 0.0
    spread_cost = contracts * 100 * entry_premium * spread if contracts else 0.0
    option_net = option_gross - spread_cost

    W = 80
    print("\n" + "=" * W)
    print(f"  AUDIT TRADE  idx={idx}")
    print("=" * W)
    print(f"  Ticker    : {ticker}")
    print(f"  Strategy  : {row.get('strategy', '?')}")
    print(f"  Direction : {direction}  ->  instrument: ATM {opt_type}")
    print(f"  Entry     : {entry_time}  @  ${S_entry:.4f}")
    print(f"  Exit      : {exit_time}  @  ${S_exit:.4f}")
    print(f"  Shares    : {shares}")
    print(f"  Stock net : ${stock_net:+.4f}  (from log)")
    print()
    print(f"  Holding   : {holding_calendar_days} calendar days  "
          f"({holding_hours:.2f} hours)")
    print()
    print(f"  --- IV ---")
    print(f"  Source    : {iv_source}")
    if rv_raw is not None:
        print(f"  RV (20-day ann.)  = {rv_raw:.6f}  ({rv_raw*100:.2f}%)")
        print(f"  skew factor       = {skew}")
        print(f"  IV = RV * skew    = {iv:.6f}  ({iv*100:.2f}%)")
    else:
        print(f"  IV (fallback)     = {iv:.6f}  ({iv*100:.2f}%)")
    print()
    print(f"  --- ENTRY OPTION ({opt_type}) ---")
    print(f"  S={S_entry:.4f}  K={K:.4f}  T={T_entry:.6f}  r={rate}  sigma={iv:.6f}")
    if entry_bs["d1"] is not None:
        print(f"  d1 = {entry_bs['d1']:+.6f}")
        print(f"  d2 = {entry_bs['d2']:+.6f}")
        print(f"  N(d1)={entry_bs['Nd1']:.6f}  N(d2)={entry_bs['Nd2']:.6f}  "
              f"N(-d1)={entry_bs['Nmd1']:.6f}  N(-d2)={entry_bs['Nmd2']:.6f}")
        print(f"  disc=e^(-r*T)={entry_bs['disc']:.6f}")
    print(f"  BS call = {entry_bs['call']:.6f}")
    print(f"  BS put  = {entry_bs['put']:.6f}")
    print(f"  => entry_premium ({opt_type}) = ${entry_premium:.6f}")
    print()
    print(f"  --- EXIT OPTION ({opt_type}) ---")
    print(f"  S={S_exit:.4f}  K={K:.4f}  T={T_exit:.6f}  r={rate}  sigma={iv:.6f}")
    if exit_bs["d1"] is not None:
        print(f"  d1 = {exit_bs['d1']:+.6f}")
        print(f"  d2 = {exit_bs['d2']:+.6f}")
        print(f"  N(d1)={exit_bs['Nd1']:.6f}  N(d2)={exit_bs['Nd2']:.6f}  "
              f"N(-d1)={exit_bs['Nmd1']:.6f}  N(-d2)={exit_bs['Nmd2']:.6f}")
        print(f"  disc=e^(-r*T)={exit_bs['disc']:.6f}")
    print(f"  BS call = {exit_bs['call']:.6f}")
    print(f"  BS put  = {exit_bs['put']:.6f}")
    print(f"  => exit_premium ({opt_type}) = ${exit_premium:.6f}")
    print()
    print(f"  --- CAPITAL & CONTRACTS ---")
    print(f"  capital          = shares * entry_price = {shares} * {S_entry:.4f} = ${capital:.4f}")
    print(f"  entry_premium    = ${entry_premium:.6f}")
    print(f"  contracts        = floor({capital:.4f} / ({entry_premium:.6f} * 100))"
          f" = floor({capital / (entry_premium * 100) if entry_premium > 0 else 0:.4f})"
          f" = {contracts}")
    print(f"  option_notional  = {contracts} * 100 * {entry_premium:.6f} = ${option_notional:.4f}")
    print(f"  capital_ratio    = {option_notional:.4f} / {capital:.4f} = {capital_ratio:.4f}"
          f"  {'[OK ~1.0]' if 0.5 <= capital_ratio <= 1.05 else '[WARN: unexpected ratio]'}")
    print()
    print(f"  --- OPTION P&L ---")
    print(f"  option_gross = {contracts} * 100 * ({exit_premium:.6f} - {entry_premium:.6f})"
          f" = ${option_gross:.4f}")
    print(f"  spread_cost  = {contracts} * 100 * {entry_premium:.6f} * {spread}"
          f" = ${spread_cost:.4f}")
    print(f"  option_net   = {option_gross:.4f} - {spread_cost:.4f} = ${option_net:.4f}")
    print(f"  stock_net    = ${stock_net:.4f}")
    outcome = "OPTION WINS" if option_net > stock_net else "STOCK WINS"
    print(f"  => {outcome}  (diff = ${option_net - stock_net:+.4f})")
    print("=" * W)
    print("  Verify with any BS calculator: plug in the S/K/T/r/sigma values above.")
    print("  Note: T is in years (e.g. 21/365=0.05753). sigma is annualized decimal.")
    print("=" * W)


def _print_capital_ratio_check(df: pd.DataFrame) -> None:
    """
    Report median (contracts*100*entry_premium) / (shares*entry_price).
    Expected ~1.0. Flag if near 100 (x100 unit bug) or 0.01 (divide-by-100 bug).
    """
    capital = df["capital"]
    notional = df["contracts"].astype(float) * 100.0 * df["entry_premium"]
    ratio = notional / capital.replace(0, float("nan"))
    med = float(ratio.median())
    p10 = float(ratio.quantile(0.10))
    p90 = float(ratio.quantile(0.90))

    if med > 50:
        flag = "[BUG] median ~{:.0f}: likely x100 unit error in premium (premium in cents?)".format(med)
    elif med < 0.05:
        flag = "[BUG] median ~{:.4f}: likely divide-by-100 error (premium too large?)".format(med)
    elif med < 0.5:
        flag = "[WARN] median {:.3f}: below 0.5 -- many trades only 1 contract on large positions?".format(med)
    else:
        flag = "[OK]"

    print(f"\n[CAPITAL RATIO] (contracts*100*entry_premium) / (shares*entry_price)")
    print(f"  median={med:.4f}  p10={p10:.4f}  p90={p90:.4f}  {flag}")


def _print_no_theta_run(
    df_vault: pd.DataFrame,
    args: argparse.Namespace,
    price_cache: Dict[str, pd.DataFrame],
) -> None:
    """
    Re-run the full analysis with T_exit = T_entry (no theta), then assert
    total option P&L > stock P&L. If the assertion fails, report a likely bug.
    """
    print("\n" + "=" * 100)
    print("  NO-THETA SANITY CHECK  (T_exit = T_entry for all trades)")
    print("=" * 100)
    print("  Theta removed: exit option priced at same DTE as entry.")
    print("  P&L change is now PURELY directional (delta effect + spread cost).")
    print("  Assert: total option P&L > stock P&L.  Failure = bug outside theta.")

    results_nt = []
    for _, row in df_vault.iterrows():
        res = analyze_trade_option(
            row.to_dict(), args.dte, args.skew,
            args.iv_fallback, args.rate, args.spread,
            price_cache,
            no_theta=True,
        )
        results_nt.append(res)

    df_nt = df_vault.copy().reset_index(drop=True)
    for col in results_nt[0]:
        df_nt[col] = [r[col] for r in results_nt]

    stock_total = float(df_nt["net_pnl"].sum())
    opt_total_nt = float(df_nt["option_net"].sum())
    diff = opt_total_nt - stock_total

    print()
    _print_headline(df_nt)
    _print_by_strategy(df_nt)
    _print_by_holding(df_nt)

    print("\n" + "=" * 100)
    print("  NO-THETA VERDICT + ASSERTION")
    print("=" * 100)
    print(f"  Stock total  : ${stock_total:+,.0f}")
    print(f"  Option total : ${opt_total_nt:+,.0f}  (no theta)")
    print(f"  Difference   : ${diff:+,.0f}")
    print()
    if opt_total_nt > stock_total:
        print("  [ASSERT PASS] No-theta option P&L > stock P&L -- theta is the sole culprit.")
        print("  Interpretation: the DIRECTIONAL edge exists; options just can't hold it")
        print("  long enough before DTE decay erases the gain.")
    else:
        print("  [ASSERT FAIL] No-theta option P&L STILL <= stock P&L.")
        print("  This means the drag is NOT purely from theta. Investigate:")
        print("    a) Capital ratio -- run without --no-theta and check [CAPITAL RATIO] line")
        print("    b) IV level -- if iv_fallback=0.45 is too high, entry premium overpays")
        print("    c) Spread cost -- try --spread 0.0 to isolate")
        print("    d) Direction alignment -- are short trades pricing puts correctly?")
        print("    e) Use --audit-trade on a few losers to inspect intermediate values")


# ── Main ──────────────────────────────────────────────────────────────────────


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="BS option proxy analysis for RAITS trade log."
    )
    p.add_argument("--pkl", default=_DEFAULT_PKL,
                   help="WFO snapshot .pkl (default: latest baseline)")
    p.add_argument("--csv", default=None,
                   help="Trade-log CSV (overrides --pkl)")
    p.add_argument("--daily_cache", default=_DEFAULT_DAILY,
                   help="Directory with {TICKER}_daily_*.parquet files")
    p.add_argument("--out_dir", default=_DEFAULT_OUT,
                   help="Output directory for CSV + PNG")
    p.add_argument("--dte", type=int, default=21,
                   help="Option DTE at entry (default 21)")
    p.add_argument("--skew", type=float, default=1.15,
                   help="IV multiplier for vol premium (default 1.15)")
    p.add_argument("--iv_fallback", type=float, default=0.45,
                   help="IV when no price cache for ticker (default 0.45)")
    p.add_argument("--rate", type=float, default=0.04,
                   help="Risk-free rate (default 0.04)")
    p.add_argument("--spread", type=float, default=0.05,
                   help="Bid/ask spread as fraction of entry premium (default 0.05)")
    p.add_argument("--audit-trade", dest="audit_trade", type=int, default=None,
                   metavar="IDX",
                   help="Print full BS intermediates for trade at index IDX (0-based "
                        "in vault-filtered list) then exit")
    p.add_argument("--no-theta", dest="no_theta", action="store_true",
                   help="Force T_exit=T_entry (remove theta), re-run, assert option "
                        "total > stock total")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)

    # ── Load trades ────────────────────────────────────────────────────────────
    if args.csv:
        print(f"[LOAD] CSV: {args.csv}")
        df = load_trades_csv(args.csv)
    else:
        print(f"[LOAD] PKL: {args.pkl}")
        df = load_trades_pkl(args.pkl)
    print(f"[LOAD] {len(df)} total trades")

    # ── STEP 0: Reconciliation gate ────────────────────────────────────────────
    n_match, n_mismatch, total = reconcile_gross(df)
    mismatch_rate = n_mismatch / total if total else 0.0
    print(f"\n[STEP 0] Reconcile gross_pnl: {n_match}/{total} match, "
          f"{n_mismatch} mismatch ({mismatch_rate:.1%})")
    if mismatch_rate > 0.01:
        print(f"[ABORT] >1% gross_pnl mismatch -- trade log not internally consistent.")
        sys.exit(1)

    # Print baseline totals for eyeballing against known baseline
    print(f"\n[BASELINE CHECK]")
    print(f"  Trades : {len(df)}")
    print(f"  Net P&L: ${df['net_pnl'].sum():+,.0f}")
    print(f"  Gross  : ${df['gross_pnl'].sum():+,.0f}")
    print(f"  By strategy:")
    for strat, grp in df.groupby("strategy"):
        print(f"    {strat:<16}: {len(grp):>4}t  ${grp['net_pnl'].sum():>+9,.0f}")
    print(f"  By direction:")
    for d, grp in df.groupby("direction"):
        print(f"    {d:<8}: {len(grp):>4}t  ${grp['net_pnl'].sum():>+9,.0f}")

    # ── VAULT filter ───────────────────────────────────────────────────────────
    pre = len(df)
    df = df[df["entry_time"] <= VAULT_END].copy().reset_index(drop=True)
    skipped = pre - len(df)
    if skipped:
        print(f"\n[VAULT] Skipped {skipped} trades with entry > 2022-12-31.")
    print(f"[VAULT] Analyzing {len(df)} trades (entry <= 2022-12-31)")

    # ── Load daily price cache ─────────────────────────────────────────────────
    print(f"\n[DATA] Loading daily cache: {args.daily_cache}")
    price_cache = load_daily_cache(args.daily_cache)
    tickers_in_log = set(df["ticker"].unique())
    tickers_in_cache = set(price_cache.keys())
    covered = tickers_in_log & tickers_in_cache
    missing = tickers_in_log - tickers_in_cache
    print(f"[DATA] Cache tickers: {len(price_cache)}  "
          f"| In trade log: {len(tickers_in_log)}  "
          f"| Covered: {len(covered)}  | Missing: {len(missing)}")
    if missing:
        print(f"[DATA] No daily data for: {sorted(missing)}")

    # ── AUDIT MODE: single trade, then exit ───────────────────────────────────
    if args.audit_trade is not None:
        idx = args.audit_trade
        if idx < 0 or idx >= len(df):
            print(f"[ERROR] --audit-trade {idx} out of range (valid: 0..{len(df)-1})")
            sys.exit(1)
        _print_audit_trade(
            df.iloc[idx].to_dict(),
            args.dte, args.skew, args.iv_fallback,
            args.rate, args.spread,
            price_cache, idx,
        )
        return

    # ── NO-THETA MODE: theta-free re-run, then exit ───────────────────────────
    if args.no_theta:
        print(
            f"\n[MODE] --no-theta  DTE={args.dte}  skew={args.skew}  "
            f"iv_fallback={args.iv_fallback}  rate={args.rate}  spread={args.spread}"
        )
        _print_no_theta_run(df, args, price_cache)
        return

    # ── NORMAL ANALYSIS ────────────────────────────────────────────────────────
    print(
        f"\n[ANALYSIS] DTE={args.dte}  skew={args.skew}  "
        f"iv_fallback={args.iv_fallback}  rate={args.rate}  spread={args.spread}"
    )
    results = []
    for _, row in df.iterrows():
        res = analyze_trade_option(
            row.to_dict(), args.dte, args.skew,
            args.iv_fallback, args.rate, args.spread,
            price_cache,
        )
        results.append(res)

    # Merge option columns back into df
    for col in results[0]:
        df[col] = [r[col] for r in results]

    # IV distribution report
    fallback_pct = float((df["iv_source"] == "fallback").mean())
    iv_desc = df["iv"].describe()
    print(f"\n[IV] Fallback rate: {fallback_pct:.1%}"
          f"  (cache-derived: {1-fallback_pct:.1%})")
    print(f"[IV] Distribution -- min={iv_desc['min']:.2f}  p25={iv_desc['25%']:.2f}"
          f"  median={iv_desc['50%']:.2f}  p75={iv_desc['75%']:.2f}"
          f"  max={iv_desc['max']:.2f}")

    n_zero = int(df["zero_contracts"].sum())
    if n_zero:
        print(f"[WARN] {n_zero} trades assigned 0 contracts "
              f"(capital < 1 contract x 100 x premium)")

    # Capital deployment ratio sanity check
    _print_capital_ratio_check(df)

    # ── STEP 2: Output ─────────────────────────────────────────────────────────
    _print_headline(df)
    _print_by_strategy(df)
    _print_by_holding(df)
    _print_verdict(df)

    # ── Save outputs ───────────────────────────────────────────────────────────
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "options_proxy_comparison.csv"
    out_df = df.copy()
    out_df = out_df.rename(columns={"net_pnl": "stock_net_pnl"})
    out_df.to_csv(str(csv_path), index=False)
    print(f"\n[SAVED] {csv_path}")

    png_path = out_dir / "options_proxy_scatter.png"
    _save_scatter(df, png_path, args.dte, args.skew)
    print(f"[SAVED] {png_path}")

    _print_caveats(df, args.dte)


if __name__ == "__main__":
    main()
