"""
dip_buy_sim.py -- IS only (2017-2022), standalone, read-only

Hypothesis: "Dip-Buy in Confirmed Uptrend"
Tests whether buying pullbacks in uptrending large-cap stocks BEATS simply
holding the same stock over the same period.

Fixed rules (pre-committed, not tuned):
  Universe : 37 stocks in CANDIDATE_POOL (from universe_scanner.py)
  Uptrend  : Close > SMA50 AND SMA50 > SMA200
  Dip      : Close < roll_high_20 * 0.95 AND Close > SMA50
  Signal   : dip_active AND today green (close > prev_close) AND uptrend
  Fill     : next session's open (signal on close, fill next open)
  Exit A   : HIGH >= peak_target (20-session high on signal day) -> fill at peak_target
  Exit B   : No target; hold until close < SMA50 OR loss >= -8%
  Both     : time stop at 20 sessions (sell at close)
  Stop     : close < SMA50 OR loss >= -8% from entry -> sell at close

COST MODEL (stated, not tuned):
  $5 flat commission per side + 0.05% slippage per side on trade value.
  $10,000 position per trade (int shares, no fractional).
  Round-trip for a $10,000 trade: $10 commission + $10 slippage = $20.

BUY-AND-HOLD COUNTERFACTUAL:
  Same entry (same day, same open, same shares).
  Exit at CLOSE on the SAME day as dip-buy exit.
  For Exit A target hits: dip-buy fills at peak_target (limit order), while
  buy-and-hold fills at close. This is the only case where P&Ls differ.
  For stop/time exits: both fill at close -> edge = 0.

REGIME PROXY:
  SPY 5-day realized vol, IS tercile -> Calm / Normal / Stress.
  (HMM module not imported; pandas/numpy/matplotlib only.)

Run:
    cd d:/raits/raits
    python raits/scripts/dip_buy_sim.py [--spy-daily PATH] [--cache-dir PATH] [--output-dir PATH]
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRADE_SIZE_USD  = 10_000.0      # $ per trade position
COMM_USD        = 5.0           # flat commission per side ($)
SLIPPAGE_PCT    = 0.0005        # slippage per side (0.05% of trade value)
DIP_PCT         = 0.05          # 5% below 20-session high = dip
DIP_LOOKBACK    = 20            # sessions for rolling high
TIME_STOP_DAYS  = 20            # max sessions to hold
STOP_LOSS_PCT   = 0.08          # 8% loss from entry -> stop
SMA_FAST        = 50
SMA_SLOW        = 200
VOL_WINDOW      = 5             # 5-day realized vol for HMM proxy
N_BOOT          = 1000
BOOT_SEED       = 42
IS_START        = "2017-01-01"
IS_END          = "2022-12-31"

# All tickers that have daily parquets in the cache (subset of CANDIDATE_POOL)
UNIVERSE = [
    "AAPL", "ADBE", "AMAT", "AMD",  "AMGN", "AMZN", "AVGO", "BIIB",
    "COST", "CRM",  "CSCO", "CVX",  "EBAY", "GILD", "GOOGL","GS",
    "HON",  "INTC", "INTU", "JPM",  "MA",   "META", "MMM",  "MS",
    "MSFT", "MU",   "NFLX", "NVDA", "ORCL", "QCOM", "REGN", "SBUX",
    "TSLA", "TXN",  "V",    "VRTX", "XOM",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]   # d:/raits

# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def compute_indicators(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (sma_fast, sma_slow, roll_high_lookback) aligned to close."""
    sma50     = close.rolling(SMA_FAST, min_periods=SMA_FAST).mean()
    sma200    = close.rolling(SMA_SLOW, min_periods=SMA_SLOW).mean()
    roll_high = close.rolling(DIP_LOOKBACK, min_periods=DIP_LOOKBACK).max()
    return sma50, sma200, roll_high


# ---------------------------------------------------------------------------
# Per-stock simulation
# ---------------------------------------------------------------------------

def simulate_stock(
    ticker: str,
    close:      pd.Series,
    open_:      pd.Series,
    high:       pd.Series,
    sma50:      pd.Series,
    sma200:     pd.Series,
    roll_high:  pd.Series,
    variant:    str,
    trade_size: float = TRADE_SIZE_USD,
    comm:       float = COMM_USD,
    slippage:   float = SLIPPAGE_PCT,
) -> list[dict]:
    """
    Simulate dip-buy trades on a single stock using pre-computed indicators.

    variant: 'A' (peak-target exit) or 'B' (trailing SMA stop, no target).

    Returns list of completed trade dicts.
    """
    n      = len(close)
    trades: list[dict] = []

    # State
    in_trade    = False
    dip_active  = False
    entry_px    = 0.0
    entry_date  = None
    entry_cost  = 0.0
    peak_target = 0.0
    shares      = 0
    hold_days   = 0

    i = 1
    while i < n:
        c      = close.iloc[i]
        o      = open_.iloc[i]
        h      = high.iloc[i]
        s50    = sma50.iloc[i]
        s200   = sma200.iloc[i]
        rh     = roll_high.iloc[i]
        d      = close.index[i]
        c_prev = close.iloc[i - 1]

        # --- OUT OF TRADE ---
        if not in_trade:
            if any(pd.isna(v) for v in (c, s50, s200, rh)):
                i += 1
                continue

            uptrend = (c > s50) and (s50 > s200)
            dip     = uptrend and (c < rh * (1.0 - DIP_PCT))

            if not uptrend:
                dip_active = False
            elif dip:
                dip_active = True

            # Signal: dip was active AND today is green AND uptrend holds
            if dip_active and (c > c_prev) and uptrend and (i + 1 < n):
                fill_idx = i + 1
                fill_o   = open_.iloc[fill_idx]

                if pd.isna(fill_o) or fill_o <= 0.0:
                    dip_active = False
                    i += 1
                    continue

                n_shares = int(trade_size / fill_o)
                if n_shares == 0:
                    dip_active = False
                    i += 1
                    continue

                # Enter trade
                in_trade    = True
                dip_active  = False
                entry_px    = fill_o
                entry_date  = close.index[fill_idx]
                entry_cost  = comm + slippage * fill_o * n_shares
                peak_target = rh           # roll_high on signal day
                shares      = n_shares
                hold_days   = 0
                i           = fill_idx
                continue    # process fill_idx in next iteration as in-trade

            i += 1
            continue

        # --- IN TRADE ---
        if any(pd.isna(v) for v in (c, s50)):
            hold_days += 1
            i += 1
            continue

        hold_days   += 1
        above_sma50  = c > s50
        loss_pct     = (c - entry_px) / entry_px

        exit_px     = None
        bah_exit_px = c           # buy-and-hold always exits at close
        exit_reason = None

        # Check exits (target -> stop -> time)
        if variant == "A" and (not pd.isna(h)) and h >= peak_target:
            # Dip-buy fills limit order at peak_target;
            # BAH exits at close -> the only case where edge != 0.
            exit_px     = peak_target
            exit_reason = "TARGET"

        elif (not above_sma50) or (loss_pct <= -STOP_LOSS_PCT):
            exit_px     = c
            exit_reason = "STOP_LOSS"

        elif hold_days >= TIME_STOP_DAYS:
            exit_px     = c
            exit_reason = "TIME_STOP"

        if exit_px is not None:
            exit_cost  = comm + slippage * exit_px * shares
            total_cost = entry_cost + exit_cost
            gross_pnl  = (exit_px - entry_px) * shares
            net_pnl    = gross_pnl - total_cost

            bah_exit_cost = comm + slippage * bah_exit_px * shares
            bah_gross  = (bah_exit_px - entry_px) * shares
            bah_net    = bah_gross - (entry_cost + bah_exit_cost)
            edge       = net_pnl - bah_net

            trades.append({
                "ticker"      : ticker,
                "entry_date"  : entry_date,
                "exit_date"   : d,
                "entry_px"    : entry_px,
                "exit_px"     : exit_px,
                "bah_exit_px" : bah_exit_px,
                "shares"      : shares,
                "hold_days"   : hold_days,
                "exit_reason" : exit_reason,
                "gross_pnl"   : gross_pnl,
                "costs"       : total_cost,
                "net_pnl"     : net_pnl,
                "bah_net_pnl" : bah_net,
                "edge"        : edge,
            })

            in_trade  = False
            hold_days = 0

        i += 1

    return trades


# ---------------------------------------------------------------------------
# Vol proxy for HMM state tagging (Calm / Normal / Stress)
# ---------------------------------------------------------------------------

def compute_vol_proxy(spy_close: pd.Series, is_start: str, is_end: str) -> pd.Series:
    """
    5-day realized vol, tercile-bucketed over IS period -> Calm / Normal / Stress.
    Returns a Series indexed by date (IS window only).
    """
    log_ret  = np.log(spy_close / spy_close.shift(1))
    rvol     = log_ret.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std() * np.sqrt(252)
    is_rvol  = rvol.loc[is_start:is_end].dropna()

    t33, t67 = float(is_rvol.quantile(0.333)), float(is_rvol.quantile(0.667))

    def _label(v: float) -> str:
        if v < t33:
            return "Calm"
        if v < t67:
            return "Normal"
        return "Stress"

    full_rvol = rvol.loc[is_start:is_end]
    return full_rvol.map(lambda v: _label(v) if not pd.isna(v) else None)


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------

def compute_stats(df: pd.DataFrame) -> dict:
    """Compute standard strategy statistics from a trades DataFrame."""
    if df.empty:
        return {k: 0.0 for k in (
            "n_trades", "win_rate", "total_net_pnl", "avg_win",
            "avg_loss", "profit_factor", "avg_hold_days", "max_drawdown",
        )}

    wins   = df.loc[df["net_pnl"] > 0, "net_pnl"]
    losses = df.loc[df["net_pnl"] <= 0, "net_pnl"]

    if len(losses) > 0 and abs(losses.sum()) > 0:
        pf = float(wins.sum()) / abs(float(losses.sum()))
    elif len(wins) > 0:
        pf = float("inf")
    else:
        pf = 0.0

    # Drawdown on time-ordered equity curve
    eq   = df.sort_values("exit_date")["net_pnl"].cumsum()
    peak = eq.cummax()
    mdd  = float((eq - peak).min())

    return {
        "n_trades"       : int(len(df)),
        "win_rate"       : float(len(wins) / len(df)),
        "total_net_pnl"  : float(df["net_pnl"].sum()),
        "avg_win"        : float(wins.mean()) if len(wins) > 0 else 0.0,
        "avg_loss"       : float(losses.mean()) if len(losses) > 0 else 0.0,
        "profit_factor"  : pf,
        "avg_hold_days"  : float(df["hold_days"].mean()),
        "max_drawdown"   : mdd,
    }


# ---------------------------------------------------------------------------
# Bootstrap p-value
# ---------------------------------------------------------------------------

def bootstrap_pvalue(edges: np.ndarray, n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> float:
    """
    One-sided bootstrap p-value for H0: mean(edge) <= 0.
    p = fraction of bootstrap resamples with mean <= 0.
    p < 0.05 -> reject H0 -> dip-buy beats buy-and-hold (95% confidence).
    """
    if len(edges) == 0:
        return 1.0
    rng     = np.random.default_rng(seed)
    means   = np.array([
        rng.choice(edges, size=len(edges), replace=True).mean()
        for _ in range(n_boot)
    ])
    return float(np.mean(means <= 0.0))


# ---------------------------------------------------------------------------
# Portfolio buy-and-hold comparison (equal-weight basket, full IS)
# ---------------------------------------------------------------------------

def compute_portfolio_bah(tickers: list[str], cache_dir: Path) -> dict:
    """
    Equal-weight basket: buy each available ticker at first 2017 close,
    hold to last 2022 close. Returns per-ticker and aggregate returns.
    """
    per_ticker = {}
    for tkr in tickers:
        files = sorted(cache_dir.glob(f"{tkr}_daily_*.parquet"))
        if not files:
            continue
        df  = pd.read_parquet(files[0])
        is_ = df.loc[IS_START:IS_END, "close"].dropna()
        if len(is_) < 5:
            per_ticker[tkr] = float("nan")
            continue
        per_ticker[tkr] = float(is_.iloc[-1] / is_.iloc[0] - 1.0)

    valid = {k: v for k, v in per_ticker.items() if not pd.isna(v)}
    if not valid:
        return {"per_ticker": per_ticker, "equal_weight_return": float("nan")}

    eq_ret = float(np.mean(list(valid.values())))
    return {
        "per_ticker"           : per_ticker,
        "equal_weight_return"  : eq_ret,
        "n_stocks"             : len(valid),
    }


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_edge_distribution(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    output_path: Path,
) -> None:
    """
    Histogram of per-trade edge (dip-buy - buy-and-hold) for both variants.
    Only non-zero edges carry information; they are shown with a note.
    """
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Dip-Buy vs Buy-and-Hold: Per-Trade Edge Distribution (IS 2017-2022)")

    for ax, df, label in zip(axes, (df_a, df_b), ("A: Peak Target", "B: Trailing Stop")):
        edges = df["edge"].dropna().values
        nonzero = edges[edges != 0.0]

        if len(nonzero) > 0:
            ax.hist(nonzero, bins=30, color="steelblue", edgecolor="white", alpha=0.8)
        else:
            ax.text(0.5, 0.5, "All edges = 0\n(same exit price as BAH)",
                    ha="center", va="center", transform=ax.transAxes, fontsize=11)

        ax.axvline(0, color="red", linewidth=1.5, linestyle="--", label="Edge = 0")
        if len(edges) > 0:
            ax.axvline(edges.mean(), color="orange", linewidth=1.5,
                       linestyle="-", label=f"Mean = ${edges.mean():.1f}")

        ax.set_title(f"Variant {label}")
        ax.set_xlabel("Per-Trade Edge ($): dip-buy minus buy-and-hold")
        ax.set_ylabel("Frequency")
        ax.legend(fontsize=9)

        total = len(edges)
        n_pos = int((edges > 0).sum())
        n_neg = int((edges < 0).sum())
        n_tie = total - n_pos - n_neg
        ax.text(0.02, 0.97, f"n={total}  beat={n_pos}  lose={n_neg}  tie={n_tie}",
                transform=ax.transAxes, va="top", fontsize=9,
                bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow"))

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=120)
    plt.close()
    print(f"Plot saved: {output_path}")


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(
    spy_daily_path: Path,
    cache_dir:      Path,
    output_dir:     Path,
) -> None:
    # -- Load SPY for vol proxy ----------------------------------------------
    spy_df    = pd.read_parquet(spy_daily_path)
    spy_close = spy_df["close"].loc[:IS_END]
    vol_proxy = compute_vol_proxy(spy_close, IS_START, IS_END)

    # -- Simulate all stocks, both variants ---------------------------------
    all_trades_a: list[dict] = []
    all_trades_b: list[dict] = []
    skipped: list[str] = []

    for tkr in UNIVERSE:
        files = sorted(cache_dir.glob(f"{tkr}_daily_*.parquet"))
        if not files:
            skipped.append(tkr)
            continue

        df = pd.read_parquet(files[0])
        df = df.loc[IS_START:IS_END].copy()

        if len(df) < SMA_SLOW + 10:
            skipped.append(tkr)
            continue

        close  = df["close"]
        open_  = df["open"]
        high   = df["high"]

        sma50, sma200, roll_high = compute_indicators(close)

        for variant, bucket in (("A", all_trades_a), ("B", all_trades_b)):
            tr = simulate_stock(
                tkr, close, open_, high, sma50, sma200, roll_high, variant
            )
            bucket.extend(tr)

    if skipped:
        print(f"  Skipped (no cache): {skipped}")

    df_a = pd.DataFrame(all_trades_a)
    df_b = pd.DataFrame(all_trades_b)

    # -- Tag HMM proxy state on entry --------------------------------------
    for df in (df_a, df_b):
        if df.empty:
            df["hmm_proxy"] = pd.Series(dtype=str)
            continue
        entry_dates = pd.DatetimeIndex(df["entry_date"]).normalize()
        df["hmm_proxy"] = [
            vol_proxy.get(d.date() if hasattr(d, "date") else d, "Unknown")
            for d in entry_dates
        ]
        # Safer mapping via nearest date
        df["hmm_proxy"] = df["entry_date"].apply(
            lambda d: _map_proxy(vol_proxy, d)
        )

    # -- Compute statistics -------------------------------------------------
    stats_a = compute_stats(df_a)
    stats_b = compute_stats(df_b)

    # Bootstrap
    edges_a = df_a["edge"].values if not df_a.empty else np.array([])
    edges_b = df_b["edge"].values if not df_b.empty else np.array([])
    pval_a  = bootstrap_pvalue(edges_a)
    pval_b  = bootstrap_pvalue(edges_b)

    # Portfolio BAH
    bah     = compute_portfolio_bah(UNIVERSE, cache_dir)

    # -- Print results -----------------------------------------------------
    sep = "=" * 66

    print()
    print(sep)
    print("  DIP-BUY IN CONFIRMED UPTREND -- IS 2017-2022")
    print(sep)
    print()
    print("COST MODEL: $5/side commission + 0.05%/side slippage on trade value.")
    print("            $10,000 position per trade (int shares, no fractional).")
    print("            Round-trip for $10,000 trade: ~$20.")
    print()
    print("CAVEATS:")
    print("  - Fixed pre-committed rules; no parameter tuning (that is overfitting).")
    print("  - Buy-and-hold same stock is the honest benchmark; beating zero is not enough.")
    print("  - In-sample only (2017-2022). 2023+ data never loaded.")
    print("  - META has only ~290 IS bars (starts 2021-06-30) -- effectively absent.")
    print("  - CANDIDATE_POOL selected for being large-caps as of 2017 (mild")
    print("    survivorship bias; unavoidable with a fixed known-in-advance universe).")
    print()

    for label, stats, df, pval in (
        ("A: PEAK TARGET EXIT", stats_a, df_a, pval_a),
        ("B: TRAILING STOP EXIT (no target)", stats_b, df_b, pval_b),
    ):
        print(f"{'-' * 66}")
        print(f"  VARIANT {label}")
        print(f"{'-' * 66}")
        print(f"  n_trades      : {stats['n_trades']}")
        print(f"  win_rate      : {stats['win_rate']:.1%}")
        print(f"  total net P&L : ${stats['total_net_pnl']:,.0f}")
        print(f"  avg win       : ${stats['avg_win']:,.0f}  |  avg loss: ${stats['avg_loss']:,.0f}")
        print(f"  profit factor : {stats['profit_factor']:.2f}")
        print(f"  avg hold days : {stats['avg_hold_days']:.1f}")
        print(f"  max drawdown  : ${stats['max_drawdown']:,.0f}")
        print()

        if not df.empty:
            exit_dist = df["exit_reason"].value_counts()
            print(f"  Exit breakdown:")
            for reason, cnt in exit_dist.items():
                print(f"    {reason:<12} {cnt:>4} ({cnt/len(df):.0%})")
            print()

        # vs buy-and-hold
        if not df.empty:
            total_bah  = float(df["bah_net_pnl"].sum())
            total_dip  = float(df["net_pnl"].sum())
            n_beat     = int((df["edge"] > 0).sum())
            n_lose     = int((df["edge"] < 0).sum())
            n_tie      = len(df) - n_beat - n_lose
            net_adv    = float(df["edge"].sum())

            print(f"  vs BUY-AND-HOLD (same stock, same period):")
            print(f"    dip-buy total      : ${total_dip:>10,.0f}")
            print(f"    buy-hold total     : ${total_bah:>10,.0f}")
            print(f"    net $ advantage    : ${net_adv:>+10,.0f}")
            print(f"    trades: beat={n_beat}  lose={n_lose}  tie={n_tie}"
                  f"  ({n_beat/len(df):.0%} beat rate)")
            print(f"    Bootstrap p-value  : {pval:.4f}  (H0: mean edge <= 0)")
            verdict = "ALIVE" if pval < 0.05 else "DEAD"
            print(f"    Verdict            : {verdict} (p {'<' if pval < 0.05 else '>='} 0.05)")
        print()

    # Regime distribution
    print(f"{'-' * 66}")
    print("  REGIME DISTRIBUTION (HMM proxy: SPY 5-day rvol, IS tercile)")
    print(f"{'-' * 66}")
    for label, df in (("Variant A", df_a), ("Variant B", df_b)):
        if df.empty:
            print(f"  {label}: no trades")
            continue
        dist = df["hmm_proxy"].value_counts()
        total = len(df)
        parts = "  ".join(
            f"{state}={dist.get(state, 0)} ({dist.get(state,0)/total:.0%})"
            for state in ("Calm", "Normal", "Stress")
        )
        print(f"  {label}: {parts}")
    print()

    # Portfolio comparison
    print(f"{'-' * 66}")
    print("  PORTFOLIO COMPARISON (2017-2022 full IS)")
    print(f"{'-' * 66}")
    ew = bah.get("equal_weight_return", float("nan"))
    n_st = bah.get("n_stocks", 0)
    print(f"  Equal-weight basket ({n_st} stocks, hold full IS 2017-2022):")
    print(f"    Return: {ew:.1%}  (avg stock return over 6 years)")
    print(f"    On $370k (37 stocks x $10k): ${370_000 * ew:+,.0f} hypothetical")
    if not df_a.empty:
        print(f"  Dip-buy Variant A: ${stats_a['total_net_pnl']:+,.0f} "
              f"across {stats_a['n_trades']} trades ($10k/trade)")
    if not df_b.empty:
        print(f"  Dip-buy Variant B: ${stats_b['total_net_pnl']:+,.0f} "
              f"across {stats_b['n_trades']} trades ($10k/trade)")
    print()
    print("  NOTE: The basket comparison is approximate -- dip-buy is not always")
    print("  in the market; idle capital opportunity cost is not modeled.")
    print()

    # Plot
    out_png = output_dir / "dip_buy_edge_distribution.png"
    plot_edge_distribution(df_a, df_b, out_png)

    print(sep)


def _map_proxy(vol_proxy: pd.Series, entry_date) -> str:
    """Map entry_date to vol proxy state, tolerating minor index misalignment."""
    try:
        d = pd.Timestamp(entry_date).normalize()
        if d in vol_proxy.index:
            v = vol_proxy.loc[d]
            return v if v is not None else "Unknown"
        # Nearest available date
        idx = vol_proxy.index.get_indexer([d], method="nearest")
        if idx[0] >= 0:
            v = vol_proxy.iloc[idx[0]]
            return v if v is not None else "Unknown"
    except Exception:
        pass
    return "Unknown"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _default_spy() -> Path:
    return _REPO_ROOT / "raits" / "data" / "cache" / "daily" / "SPY_daily_2007_2024.parquet"


def _default_cache() -> Path:
    return _REPO_ROOT / "raits" / "data" / "cache" / "daily"


def _default_output() -> Path:
    return _REPO_ROOT / "raits" / "configs"


def main() -> None:
    p = argparse.ArgumentParser(description="Dip-buy in confirmed uptrend -- IS simulation")
    p.add_argument("--spy-daily",   type=Path, default=_default_spy(),
                   help="Path to SPY daily parquet (for vol proxy)")
    p.add_argument("--cache-dir",   type=Path, default=_default_cache(),
                   help="Directory containing daily stock parquets")
    p.add_argument("--output-dir",  type=Path, default=_default_output(),
                   help="Directory for PNG output")
    args = p.parse_args()

    if not args.spy_daily.exists():
        sys.exit(f"SPY daily not found: {args.spy_daily}")
    if not args.cache_dir.is_dir():
        sys.exit(f"Cache dir not found: {args.cache_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    analyze(args.spy_daily, args.cache_dir, args.output_dir)


if __name__ == "__main__":
    main()
