"""
scripts/orb_fade_combined_test.py
----------------------------------
Option A combined test: ORB + Failed Breakout Fade

On every qualifying breakout (9:30-9:44 range, 9:45-10:15 signal, vol > 1.5×):
  Calm / Normal days (ORB active):
    1. Enter ORB in breakout direction at next bar open
    2. Monitor for failure (price back inside range within ≤15 min)
       → Failure found: exit ORB at failure+1 bar open, enter Fade opposite
         Fade exits at EOD or stop (range × 0.5% buffer)
       → No failure: ORB exits at stop (range_high/low) or EOD

  Stress days (ORB inactive):
    Fade only — enter opposite after failure if detected within ≤15 min

Comparison table:
  Standalone Fade (all days):          +$825  (303 trades)
  Combined Option A (this script):     ?

Usage:
  cd D:\\raits\\raits
  python raits/scripts/orb_fade_combined_test.py
"""

import sys, os, warnings
warnings.filterwarnings("ignore")

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pandas as pd
import numpy as np
from datetime import time as dtime
from typing import Optional, List

from raits.data_cache import load_market_data

# ── Config ─────────────────────────────────────────────────────────────────────
ACCOUNT          = 50_000.0
MAX_RISK_PCT     = 0.01
MAX_TRADES_DAY   = 3
COST_PER_SHARE   = 0.005

ORB_RANGE_END_T  = dtime(9, 45)
BREAKOUT_END_T   = dtime(10, 15)
FAILURE_END_T    = dtime(11, 30)
EOD_T            = dtime(15, 55)

VOL_MULT         = 1.5
STOP_BUFFER_PCT  = 0.005    # 0.5% outside range for Fade stop
MAX_FAILURE_LAG  = 15       # minutes

CALM_THRESHOLD   = 0.12
STRESS_THRESHOLD = 0.25


UNIVERSE = [
    "TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL",
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
    "MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM",
]


# ── Regime classification ─────────────────────────────────────────────────────
def _compute_regime_dates(spy: pd.DataFrame) -> tuple[set, set]:
    daily_close = (spy.between_time("15:50", "16:00")
                      .resample("B")["close"].last().dropna())
    daily_ret   = daily_close.pct_change().dropna()
    calm, stress = set(), set()
    dates = daily_close.index.tolist()
    for i in range(5, len(dates)):
        rv = np.std(daily_ret.iloc[i-5:i].values) * np.sqrt(252)
        if rv <= CALM_THRESHOLD:
            calm.add(dates[i].date())
        elif rv > STRESS_THRESHOLD:
            stress.add(dates[i].date())
    return calm, stress


def _shares(entry: float, stop_dist: float) -> int:
    sizing = max(stop_dist, entry * 0.005)
    s = max(1, int((ACCOUNT * MAX_RISK_PCT) / sizing))
    return min(s, int(ACCOUNT * 0.05 / entry))


# ── Core simulation: one day / one ticker ────────────────────────────────────
def simulate_event(day_bars: pd.DataFrame, ticker: str, date,
                   orb_active: bool) -> Optional[dict]:
    """
    Returns a dict describing the combined trade event, or None if no breakout.

    Fields:
      date, ticker, breakout_dir, failure_lag
      mode: "ORB_ONLY" | "REVERSED" | "FADE_ONLY" (stress day with reversal)
      orb_entry, orb_exit, orb_reason, orb_pnl    (0 if FADE_ONLY)
      fade_entry, fade_exit, fade_reason, fade_pnl (0 if ORB_ONLY)
      combined_pnl
    """
    all_bars = day_bars[day_bars.index.time <= EOD_T]
    if len(all_bars) < 10:
        return None

    # ── Range ─────────────────────────────────────────────────────────────────
    range_bars = all_bars[all_bars.index.time < ORB_RANGE_END_T]
    if len(range_bars) < 3:
        return None

    range_high = float(range_bars["high"].max())
    range_low  = float(range_bars["low"].min())
    if range_high <= range_low:
        return None

    avg_vol = float(range_bars["volume"].mean())
    if avg_vol <= 0:
        return None

    # ── Breakout ──────────────────────────────────────────────────────────────
    breakout_bars = all_bars[
        (all_bars.index.time >= ORB_RANGE_END_T) &
        (all_bars.index.time < BREAKOUT_END_T)
    ]
    if len(breakout_bars) < 2:
        return None

    breakout_ts = breakout_dir = breakout_bar = None
    for ts, bar in breakout_bars.iterrows():
        close = float(bar["close"])
        if float(bar["volume"]) < VOL_MULT * avg_vol:
            continue
        if close > range_high:
            breakout_ts, breakout_dir, breakout_bar = ts, "LONG", bar
            break
        elif close < range_low:
            breakout_ts, breakout_dir, breakout_bar = ts, "SHORT", bar
            break

    if breakout_ts is None:
        return None

    # ── Features (computable at breakout time, before entry) ─────────────────
    range_width = range_high - range_low
    midpoint    = (range_high + range_low) / 2
    bvol_ratio  = float(breakout_bar["volume"]) / avg_vol
    rw_pct      = range_width / midpoint if midpoint > 0 else 0
    bclose      = float(breakout_bar["close"])
    bstr = ((bclose - range_high) / range_width if breakout_dir == "LONG"
            else (range_low - bclose) / range_width) if range_width > 0 else 0
    bt_min = (breakout_ts.hour * 60 + breakout_ts.minute) - (9 * 60 + 45)

    # ── ORB entry (Calm/Normal days only) ────────────────────────────────────
    post_breakout = all_bars[all_bars.index > breakout_ts]
    if post_breakout.empty:
        return None

    orb_entry_row = post_breakout.iloc[0]
    orb_entry = float(orb_entry_row["open"])

    # ORB stop: at range boundary (no buffer — price back at range = failed)
    orb_stop = range_high if breakout_dir == "LONG" else range_low
    orb_stop_dist = abs(orb_entry - orb_stop)
    if orb_stop_dist < 0.01:
        return None

    orb_shares = _shares(orb_entry, orb_stop_dist)

    # ── Failure detection (same logic as Fade test) ───────────────────────────
    post_breakout_for_fail = all_bars[
        (all_bars.index > breakout_ts) &
        (all_bars.index.time < FAILURE_END_T)
    ]
    failure_ts = None
    for ts, bar in post_breakout_for_fail.iterrows():
        close = float(bar["close"])
        if breakout_dir == "LONG" and close < range_high:
            failure_ts = ts
            break
        elif breakout_dir == "SHORT" and close > range_low:
            failure_ts = ts
            break

    failure_lag = None
    if failure_ts is not None:
        failure_lag = (failure_ts - breakout_ts).seconds // 60

    has_fast_failure = (failure_ts is not None and
                        failure_lag is not None and
                        failure_lag <= MAX_FAILURE_LAG)

    # ── Case 1: No fast failure → ORB runs to stop or EOD ───────────────────
    if not has_fast_failure:
        if not orb_active:
            return None  # Stress day + no fast failure → no trade at all

        exit_price = exit_reason = None
        for ts, b in post_breakout.iterrows():
            t = ts.time()
            bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
            if t >= EOD_T:
                exit_price, exit_reason = bc, "EOD"
                break
            if breakout_dir == "LONG":
                if bl <= orb_stop:
                    exit_price, exit_reason = orb_stop, "STOP_HIT"
                    break
            else:
                if bh >= orb_stop:
                    exit_price, exit_reason = orb_stop, "STOP_HIT"
                    break

        if exit_price is None:
            exit_price = float(post_breakout.iloc[-1]["close"])
            exit_reason = "EOD"

        raw = ((exit_price - orb_entry) * orb_shares if breakout_dir == "LONG"
               else (orb_entry - exit_price) * orb_shares)
        orb_pnl = raw - COST_PER_SHARE * orb_shares * 2

        return {
            "date": date, "ticker": ticker,
            "breakout_dir": breakout_dir, "failure_lag": None,
            "mode": "ORB_ONLY",
            "orb_entry": round(orb_entry, 2), "orb_exit": round(exit_price, 2),
            "orb_reason": exit_reason, "orb_pnl": round(orb_pnl, 2),
            "orb_shares": orb_shares,
            "fade_entry": None, "fade_exit": None,
            "fade_reason": None, "fade_pnl": 0.0, "fade_shares": 0,
            "combined_pnl": round(orb_pnl, 2),
            "vol_ratio": round(bvol_ratio, 2), "range_width_pct": round(rw_pct * 100, 3),
            "breakout_str": round(bstr, 3), "breakout_time_min": bt_min,
        }

    # ── Case 2: Fast failure detected ────────────────────────────────────────
    # Fade entry: next bar after failure confirmation
    post_failure = all_bars[all_bars.index > failure_ts]
    if post_failure.empty:
        return None

    fade_entry_row = post_failure.iloc[0]
    if fade_entry_row.name.time() >= FAILURE_END_T:
        return None

    fade_entry    = float(fade_entry_row["open"])
    fade_dir      = "SHORT" if breakout_dir == "LONG" else "LONG"

    # Fade stop: 0.5% outside the range boundary
    fade_stop = (range_high * (1 + STOP_BUFFER_PCT) if fade_dir == "SHORT"
                 else range_low  * (1 - STOP_BUFFER_PCT))
    fade_stop_dist = abs(fade_entry - fade_stop)
    if fade_stop_dist < 0.01:
        return None

    fade_shares = _shares(fade_entry, fade_stop_dist)

    # ── ORB leg P&L (if ORB was active) ──────────────────────────────────────
    orb_pnl = 0.0
    if orb_active:
        # ORB was open from orb_entry_ts to fade_entry_row.name
        # Exit ORB at fade_entry (same bar as Fade entry)
        orb_exit = fade_entry
        raw = ((orb_exit - orb_entry) * orb_shares if breakout_dir == "LONG"
               else (orb_entry - orb_exit) * orb_shares)
        orb_pnl = raw - COST_PER_SHARE * orb_shares * 2

    # ── Fade leg simulation ───────────────────────────────────────────────────
    fade_exit = fade_reason = None
    for ts, b in post_failure.iterrows():
        t = ts.time()
        bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
        if t >= EOD_T:
            fade_exit, fade_reason = bc, "EOD"
            break
        if fade_dir == "SHORT":
            if bh >= fade_stop:
                fade_exit, fade_reason = fade_stop, "STOP_HIT"
                break
        else:
            if bl <= fade_stop:
                fade_exit, fade_reason = fade_stop, "STOP_HIT"
                break

    if fade_exit is None:
        fade_exit   = float(post_failure.iloc[-1]["close"])
        fade_reason = "EOD"

    raw = ((fade_exit - fade_entry) * fade_shares if fade_dir == "LONG"
           else (fade_entry - fade_exit) * fade_shares)
    fade_pnl = raw - COST_PER_SHARE * fade_shares * 2

    mode = "REVERSED" if orb_active else "FADE_ONLY"

    return {
        "date": date, "ticker": ticker,
        "breakout_dir": breakout_dir, "failure_lag": failure_lag,
        "mode": mode,
        "orb_entry": round(orb_entry, 2) if orb_active else None,
        "orb_exit":  round(fade_entry, 2) if orb_active else None,
        "orb_reason": "REVERSED" if orb_active else None,
        "orb_pnl":   round(orb_pnl, 2),
        "orb_shares": orb_shares if orb_active else 0,
        "fade_entry": round(fade_entry, 2),
        "fade_exit":  round(fade_exit, 2),
        "fade_reason": fade_reason,
        "fade_pnl":   round(fade_pnl, 2),
        "fade_shares": fade_shares,
        "combined_pnl": round(orb_pnl + fade_pnl, 2),
        "vol_ratio": round(bvol_ratio, 2), "range_width_pct": round(rw_pct * 100, 3),
        "breakout_str": round(bstr, 3), "breakout_time_min": bt_min,
    }


# ── Summary printer ────────────────────────────────────────────────────────────
def _print_block(label: str, df: pd.DataFrame, pnl_col: str = "combined_pnl"):
    if df.empty:
        print(f"\n{label}: No trades")
        return
    wins   = df[df[pnl_col] > 0][pnl_col]
    losses = df[df[pnl_col] <= 0][pnl_col]
    pf     = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    wr     = (df[pnl_col] > 0).mean()
    print(f"\n{'=' * 70}")
    print(f"  {label}  (n={len(df)})")
    print(f"{'=' * 70}")
    print(f"  {'':18} {'2020':>8} {'2021':>8} {'2022':>8} {'Total':>8}")
    print("  " + "-" * 55)
    for metric, fn in [
        ("Trades",  lambda y: f"{len(y):>8}"),
        ("Win %",   lambda y: f"{(y[pnl_col] > 0).mean():>7.1%}"),
        ("Avg P&L", lambda y: f"${y[pnl_col].mean():>+7.2f}"),
        ("Total $", lambda y: f"${y[pnl_col].sum():>+7,.0f}"),
    ]:
        vals = "".join(fn(df[df["year"] == yr]) if len(df[df["year"] == yr]) else " " * 8
                       for yr in [2020, 2021, 2022])
        all_val = fn(df)
        print(f"  {metric:<18}{vals} {all_val:>8}")
    print(f"\n  PF {pf:.2f}  |  WR {wr:.1%}  |  "
          f"Avg Win ${wins.mean():+.2f}  |  Avg Loss ${losses.mean():+.2f}"
          if len(wins) and len(losses) else f"\n  PF {pf:.2f}  |  WR {wr:.1%}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("ORB + Fade Combined Test (Option A) — 2020-2022 OOS")
    print("=" * 70)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-cache", action="store_true")
    args = parser.parse_args()

    market = load_market_data(rebuild=args.rebuild_cache)
    spy    = market.get("SPY", pd.DataFrame())
    if spy.empty:
        print("[FAIL] SPY missing — run with --rebuild-cache")
        return

    print("Computing regime days...", flush=True)
    calm_dates, stress_dates = _compute_regime_dates(spy)
    print(f"  Calm: {len(calm_dates)}  Stress: {len(stress_dates)}", flush=True)

    all_days = sorted(spy.index.normalize().unique())
    oos_days = [d for d in all_days if 2020 <= d.year <= 2022]

    ticker_order = {t: i for i, t in enumerate(UNIVERSE)}
    events: List[dict] = []

    print(f"Simulating {len(UNIVERSE)} tickers × {len(oos_days)} days...", flush=True)

    for ticker in UNIVERSE:
        if ticker not in market:
            continue
        df = market[ticker]

        for day_ts in oos_days:
            day_bars = df[df.index.normalize() == day_ts]
            if len(day_bars) < 10:
                continue

            date      = day_ts.date()
            is_stress = date in stress_dates
            is_calm   = date in calm_dates
            # ORB active on Normal days only — engine.py: Calm→VWAP_MR, Normal→ORB+TF
            orb_active = not is_calm and not is_stress

            ev = simulate_event(day_bars, ticker, date, orb_active)
            if ev:
                ev["is_calm"]     = is_calm
                ev["is_stress"]   = is_stress
                ev["ticker_rank"] = ticker_order[ticker]
                events.append(ev)

    if not events:
        print("No events generated.")
        return

    df_e = pd.DataFrame(events)
    df_e = (df_e.sort_values(["date", "ticker_rank"])
                .groupby("date")
                .head(MAX_TRADES_DAY)
                .reset_index(drop=True))
    df_e["year"] = pd.to_datetime(df_e["date"]).dt.year

    # ── Overall combined P&L ─────────────────────────────────────────────────
    _print_block("ALL EVENTS — combined P&L", df_e)

    # ── By mode ──────────────────────────────────────────────────────────────
    for mode in ["ORB_ONLY", "REVERSED", "FADE_ONLY"]:
        sub = df_e[df_e["mode"] == mode]
        _print_block(f"Mode: {mode}", sub)

    # ── ORB leg only (REVERSED trades: what ORB contributed) ─────────────────
    rev = df_e[df_e["mode"] == "REVERSED"]
    if not rev.empty:
        print(f"\n{'=' * 70}")
        print(f"  ORB LEG P&L on REVERSED trades (n={len(rev)})")
        print(f"{'=' * 70}")
        orb_wins   = rev[rev["orb_pnl"] > 0]["orb_pnl"]
        orb_losses = rev[rev["orb_pnl"] <= 0]["orb_pnl"]
        print(f"  ORB net on these trades: ${rev['orb_pnl'].sum():+,.2f}")
        print(f"  WR: {(rev['orb_pnl'] > 0).mean():.1%}  "
              f"Avg: ${rev['orb_pnl'].mean():+.2f}  "
              f"Avg Win: ${orb_wins.mean():+.2f}  "
              f"Avg Loss: ${orb_losses.mean():+.2f}"
              if len(orb_wins) and len(orb_losses) else
              f"  ORB net on these trades: ${rev['orb_pnl'].sum():+,.2f}")
        print(f"  → ORB was in trade {rev['failure_lag'].mean():.0f} min on avg "
              f"before Fade reversed it")

    # ── Comparison table ─────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  SUMMARY COMPARISON")
    print(f"{'=' * 70}")
    orb_only_net  = df_e[df_e["mode"] == "ORB_ONLY"]["combined_pnl"].sum()
    rev_net       = df_e[df_e["mode"] == "REVERSED"]["combined_pnl"].sum()
    fade_only_net = df_e[df_e["mode"] == "FADE_ONLY"]["combined_pnl"].sum()
    total_net     = df_e["combined_pnl"].sum()
    n_orb   = len(df_e[df_e["mode"] == "ORB_ONLY"])
    n_rev   = len(df_e[df_e["mode"] == "REVERSED"])
    n_fade  = len(df_e[df_e["mode"] == "FADE_ONLY"])

    print(f"  ORB only (no failure)     : {n_orb:>4} events   ${orb_only_net:>+8,.2f}")
    print(f"  Reversed (ORB + Fade)     : {n_rev:>4} events   ${rev_net:>+8,.2f}")
    print(f"  Fade only (Stress days)   : {n_fade:>4} events   ${fade_only_net:>+8,.2f}")
    print(f"  {'─' * 45}")
    print(f"  Combined Option A total   : {n_orb+n_rev+n_fade:>4} events   ${total_net:>+8,.2f}")
    print(f"\n  Reference — Standalone Fade (+$825, 303 trades):")
    print(f"  Option A net vs Fade standalone: ${total_net - 825:+,.2f}")
    print(f"{'=' * 70}")

    # ── Feature Analysis: ORB_ONLY vs REVERSED ────────────────────────────────
    orb_only = df_e[df_e["mode"] == "ORB_ONLY"]
    reversed_ = df_e[df_e["mode"] == "REVERSED"]

    print(f"\n{'=' * 70}")
    print(f"  FEATURE ANALYSIS — ORB_ONLY vs REVERSED")
    print(f"  (features computable before entry — can they predict outcome?)")
    print(f"{'=' * 70}")
    print(f"  {'Feature':<22} {'ORB_ONLY':>12} {'REVERSED':>12} {'Diff':>10}  {'Signal?'}")
    print("  " + "-" * 65)

    features = [
        ("vol_ratio",        "Vol Ratio (×avg)",  "{:.2f}",  "higher = stronger breakout"),
        ("range_width_pct",  "Range Width (%)",   "{:.3f}",  "wider = cleaner setup?"),
        ("breakout_str",     "Breakout Strength", "{:.3f}",  "how far beyond range / width"),
        ("breakout_time_min","Breakout Time(min)","{:.1f}",  "minutes after 9:45"),
    ]
    for col, label, fmt, note in features:
        o = orb_only[col].mean()
        r = reversed_[col].mean()
        diff = o - r
        signal = "YES" if abs(diff) / max(abs(r), 0.001) > 0.10 else "weak"
        print(f"  {label:<22} {fmt.format(o):>12} {fmt.format(r):>12} {diff:>+10.3f}  {signal}  ({note})")

    # Per-bucket PF by vol_ratio
    print(f"\n  ORB_ONLY + REVERSED P&L by vol_ratio bucket:")
    print(f"  {'Vol Ratio':>12} {'n_ORB':>7} {'ORB PF':>8} {'n_REV':>7} {'REV PF':>8}  Ratio suggests?")
    print("  " + "-" * 70)
    for lo, hi in [(1.5, 2.5), (2.5, 3.5), (3.5, 5.0), (5.0, 99)]:
        o_sub = orb_only[(orb_only["vol_ratio"] >= lo) & (orb_only["vol_ratio"] < hi)]
        r_sub = reversed_[(reversed_["vol_ratio"] >= lo) & (reversed_["vol_ratio"] < hi)]
        o_pf = (o_sub[o_sub["combined_pnl"] > 0]["combined_pnl"].sum() /
                abs(o_sub[o_sub["combined_pnl"] <= 0]["combined_pnl"].sum())
                if o_sub[o_sub["combined_pnl"] <= 0]["combined_pnl"].sum() != 0 else float("inf"))
        r_pf = (r_sub[r_sub["combined_pnl"] > 0]["combined_pnl"].sum() /
                abs(r_sub[r_sub["combined_pnl"] <= 0]["combined_pnl"].sum())
                if r_sub[r_sub["combined_pnl"] <= 0]["combined_pnl"].sum() != 0 else float("inf"))
        label = f"{lo:.1f}–{hi:.1f}×" if hi < 99 else f"{lo:.1f}×+"
        print(f"  {label:>12} {len(o_sub):>7} {o_pf:>8.2f} {len(r_sub):>7} {r_pf:>8.2f}")

    # ── Delayed ORB entry: skip ORB if failure_lag == 5 ──────────────────────
    print(f"\n{'=' * 70}")
    print(f"  DELAYED ORB ENTRY — skip ORB when failure at ≤5 min (bar B+1)")
    print(f"  Logic: wait 1 bar after breakout, check if already failed.")
    print(f"  If B+1 already back inside range → enter Fade only, skip ORB.")
    print(f"{'=' * 70}")

    df_delayed = df_e.copy()
    mask_skip = (df_delayed["mode"] == "REVERSED") & (df_delayed["failure_lag"] <= 5)
    n_skipped = mask_skip.sum()
    saved = df_delayed.loc[mask_skip, "orb_pnl"].sum()
    df_delayed.loc[mask_skip, "orb_pnl"] = 0.0
    df_delayed.loc[mask_skip, "combined_pnl"] = df_delayed.loc[mask_skip, "fade_pnl"]

    delayed_net = df_delayed["combined_pnl"].sum()
    rev_delayed = df_delayed[df_delayed["mode"] == "REVERSED"]["combined_pnl"].sum()

    print(f"  Trades where ORB skipped (failure_lag ≤5): {n_skipped}")
    print(f"  ORB cost saved on those trades:            ${saved:+,.2f}")
    print(f"\n  {'':30} {'Original':>12} {'Delayed ORB':>12} {'Change':>10}")
    print("  " + "-" * 65)
    print(f"  {'REVERSED mode net':30} ${rev_net:>+10,.2f} ${rev_delayed:>+10,.2f} ${rev_delayed - rev_net:>+8,.2f}")
    print(f"  {'Option A total':30} ${total_net:>+10,.2f} ${delayed_net:>+10,.2f} ${delayed_net - total_net:>+8,.2f}")
    print(f"{'=' * 70}")

    # ── Breakout Strength Filter ──────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  BREAKOUT STRENGTH FILTER")
    print(f"  Skip ORB when breakout_str ≤ threshold")
    print(f"  (ORB_ONLY low-str = no trade | REVERSED low-str = Fade only)")
    print(f"{'=' * 70}")
    print(f"\n  {'Threshold':<12} {'ORB skip':>9} {'PnL lost':>12} "
          f"{'REV skip':>9} {'Cost saved':>12} {'Net total':>12} {'vs +$492':>10}")
    print("  " + "-" * 80)

    for thresh in [0.10, 0.20, 0.30, 0.40, 0.50]:
        df_s = df_e.copy()

        orb_skip = (df_s["mode"] == "ORB_ONLY") & (df_s["breakout_str"] <= thresh)
        rev_skip = (df_s["mode"] == "REVERSED") & (df_s["breakout_str"] <= thresh)

        pnl_lost   = df_s.loc[orb_skip, "combined_pnl"].sum()
        cost_saved = df_s.loc[rev_skip, "orb_pnl"].sum()

        df_s.loc[orb_skip, "combined_pnl"] = 0.0
        df_s.loc[rev_skip, "orb_pnl"] = 0.0
        df_s.loc[rev_skip, "combined_pnl"] = df_s.loc[rev_skip, "fade_pnl"]

        net = df_s["combined_pnl"].sum()
        print(f"  str≤{thresh:.2f}      {orb_skip.sum():>9} ${pnl_lost:>+10,.0f} "
              f"  {rev_skip.sum():>9} ${-cost_saved:>+10,.0f}   ${net:>+10,.0f} ${net-492:>+9,.0f}")

    # ── Combined: Delayed ORB + Strength Filter ───────────────────────────────
    print(f"\n  COMBINED: Delayed ORB (lag≤5) + Strength Filter")
    print(f"  {'Threshold':<12} {'Net total':>12} {'vs +$492':>10} {'vs delayed +$1,121':>20}")
    print("  " + "-" * 60)

    for thresh in [0.10, 0.20, 0.30, 0.40, 0.50]:
        df_c = df_e.copy()

        rev_skip = (df_c["mode"] == "REVERSED") & (
            (df_c["failure_lag"] <= 5) | (df_c["breakout_str"] <= thresh)
        )
        orb_skip = (df_c["mode"] == "ORB_ONLY") & (df_c["breakout_str"] <= thresh)

        df_c.loc[rev_skip, "orb_pnl"] = 0.0
        df_c.loc[rev_skip, "combined_pnl"] = df_c.loc[rev_skip, "fade_pnl"]
        df_c.loc[orb_skip, "combined_pnl"] = 0.0

        net = df_c["combined_pnl"].sum()
        print(f"  str≤{thresh:.2f}      ${net:>+10,.0f} ${net-492:>+9,.0f} ${net-1121:>+18,.0f}")

    # ── P&L by strength bucket ────────────────────────────────────────────────
    print(f"\n  ORB_ONLY P&L by strength bucket (what we'd LOSE by filtering):")
    print(f"  {'Strength':>12} {'n':>5} {'Net PnL':>10} {'WR':>7} {'PF':>7}")
    print("  " + "-" * 45)
    for lo, hi in [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 99)]:
        sub = orb_only[(orb_only["breakout_str"] >= lo) & (orb_only["breakout_str"] < hi)]
        if sub.empty:
            continue
        wins   = sub[sub["combined_pnl"] > 0]["combined_pnl"]
        losses = sub[sub["combined_pnl"] <= 0]["combined_pnl"]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        label = f"{lo:.1f}–{hi:.1f}" if hi < 99 else f"{lo:.1f}+"
        print(f"  {label:>12} {len(sub):>5} ${sub['combined_pnl'].sum():>+8,.0f} "
              f"{(sub['combined_pnl']>0).mean():>6.0%} {pf:>7.2f}")

    print(f"\n  REVERSED P&L by strength bucket (what we'd SAVE by filtering):")
    print(f"  {'Strength':>12} {'n':>5} {'ORB drag':>10} {'Fade leg':>10} {'Combined':>10}")
    print("  " + "-" * 55)
    for lo, hi in [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.5), (0.5, 99)]:
        sub = reversed_[(reversed_["breakout_str"] >= lo) & (reversed_["breakout_str"] < hi)]
        if sub.empty:
            continue
        label = f"{lo:.1f}–{hi:.1f}" if hi < 99 else f"{lo:.1f}+"
        print(f"  {label:>12} {len(sub):>5} ${sub['orb_pnl'].sum():>+8,.0f}   "
              f"${sub['fade_pnl'].sum():>+8,.0f}   ${sub['combined_pnl'].sum():>+8,.0f}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
