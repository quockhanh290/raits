"""
vwap_mr_dynamic_sim.py — Dynamic BB std for VWAP Mean Reversion.

Hypothesis: scaling bb_std with intraday volatility (instead of fixed 2.5)
selects better entries — tighter bands on calm days, wider on volatile days.

Scenarios tested:
  A) Fixed 2.5σ (engine baseline)
  B) VIX bucketing: <15→1.5 | 15-20→2.0 | 20-25→2.5 | ≥25→3.0
  C) Morning realized vol scaling (9:30-10:15 std → scale base_std=2.5)
  D) Combined: VIX bucket × morning vol fine-tune

Universe: XLF XLE XLV XLU XLI XLK XLP XLB XLY GLD QQQ IWM
Regime:   Calm days only (from results PKL)
Signal:   prev_bar.high >= bb_upper AND prev_bar.close < bb_upper → SHORT
          prev_bar.low  <= bb_lower AND prev_bar.close > bb_lower → LONG
Entry:    current bar open
Stop:     entry ± 1.5×ATR
Target:   session VWAP
R:R gate: (entry→VWAP) / stop_dist >= 1.5
Exit:     target / stop / time-stop 14:00

Usage:
    cd d:\\raits\\raits
    python raits\\scripts\\vwap_mr_dynamic_sim.py
"""
import sys, os, pickle
sys.path.insert(0, r'd:\raits\raits')
sys.path.insert(0, r'd:\raits')

import pandas as pd
import numpy as np
from datetime import time as dtime

PKL_RESULTS = r'd:\raits\raits\data\cache\window_debug_results.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
VIX_PATH    = r'd:\raits\raits\data\cache\daily\vix_daily.parquet'

ACCOUNT_START  = 50_000.0
MAX_RISK_PCT   = 0.01
MAX_POS_PCT    = 0.20
KELLY_FRAC     = 0.5
KELLY_STATS    = {"win_rate": 0.42, "avg_win": 2.80, "avg_loss": 1.50}
COMMISSION     = 0.01
STOP_ATR_MULT  = 1.5
MIN_RR         = 1.5
BB_PERIOD      = 20
TIME_STOP_T    = dtime(14, 0)
SIGNAL_START   = dtime(10, 15)

MR_UNIVERSE = [
    "XLF", "XLE", "XLV", "XLU", "XLI",
    "XLK", "XLP", "XLB", "XLY", "GLD", "QQQ", "IWM",
]
MAX_SLOTS = 3

# ── Load data ─────────────────────────────────────────────────────────────────
print("Loading data...")
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.DatetimeIndex(data_5min[tk].index)

vix_df = pd.read_parquet(VIX_PATH)
vix_df.index = pd.DatetimeIndex(vix_df.index).normalize()
vix_map = vix_df["vix"].to_dict()

# ── Identify Calm days ────────────────────────────────────────────────────────
calm_days = set()
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "hmm_state", "") == "Calm":
            calm_days.add(pd.Timestamp(t.entry_time).normalize())
calm_days = sorted(calm_days)
print(f"Calm days: {len(calm_days)}")

# ── Precompute day bars ───────────────────────────────────────────────────────
day_bars: dict = {}
for ticker in MR_UNIVERSE:
    if ticker not in data_5min:
        continue
    bars = data_5min[ticker].sort_index()
    for day in calm_days:
        db = bars[bars.index.normalize() == day]
        if len(db) >= 10:
            day_bars[(ticker, day)] = db

# ── Helpers ───────────────────────────────────────────────────────────────────
def compute_vwap(bars: pd.DataFrame) -> float:
    tp  = (bars["high"] + bars["low"] + bars["close"]) / 3
    vol = bars["volume"].sum()
    return float((tp * bars["volume"]).sum() / vol) if vol > 0 else float(bars["close"].iloc[-1])


def compute_atr(bars: pd.DataFrame, period: int = 14) -> float:
    if len(bars) < 2:
        return float(bars["close"].iloc[-1]) * 0.015
    hl  = bars["high"] - bars["low"]
    hpc = (bars["high"] - bars["close"].shift(1)).abs()
    lpc = (bars["low"]  - bars["close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    return float(tr.tail(period).mean())


def compute_adx(bars: pd.DataFrame, period: int = 14) -> float:
    """EWM ADX — exact replica of engine._compute_adx."""
    if len(bars) < period + 1:
        return 0.0
    try:
        high  = bars["high"]
        low   = bars["low"]
        close = bars["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        up   = high.diff()
        down = -low.diff()
        plus_dm  = up.where((up > down) & (up > 0), 0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)
        atr_s    = tr.ewm(span=period, adjust=False).mean()
        plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
        minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr_s.replace(0, 1e-9)
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9)
        adx      = dx.ewm(span=period, adjust=False).mean()
        return float(adx.iloc[-1])
    except Exception:
        return 0.0


def morning_vol(bars: pd.DataFrame, day: pd.Timestamp) -> float:
    """Annualized realized vol from 9:30-10:15 returns."""
    am = bars[(bars.index.time >= dtime(9, 30)) &
              (bars.index.time <= dtime(10, 15))]
    if len(am) < 3:
        return 0.15   # default
    rets = am["close"].pct_change().dropna()
    return float(rets.std() * np.sqrt(252 * 78))


# Pre-compute avg morning vol across all calm days for SPY
_spy_bars = data_5min.get("SPY", pd.DataFrame()).sort_index()
_am_vols = []
for day in calm_days:
    db = _spy_bars[_spy_bars.index.normalize() == day]
    if len(db) >= 3:
        am = db[(db.index.time >= dtime(9, 30)) & (db.index.time <= dtime(10, 15))]
        rets = am["close"].pct_change().dropna()
        if len(rets) >= 2:
            _am_vols.append(float(rets.std() * np.sqrt(252 * 78)))
AVG_MORNING_VOL = float(np.mean(_am_vols)) if _am_vols else 0.20
print(f"Avg morning vol (SPY, calm days): {AVG_MORNING_VOL:.3f}")


def dynamic_std_vix(vix: float) -> float:
    """Scenario B: VIX bucket."""
    if vix is None:   return 2.5
    if vix < 15:      return 1.5
    if vix < 20:      return 2.0
    if vix < 25:      return 2.5
    return 3.0


def dynamic_std_vol(mv: float) -> float:
    """Scenario C: morning vol scaling."""
    ratio = mv / AVG_MORNING_VOL if AVG_MORNING_VOL > 0 else 1.0
    return float(np.clip(2.5 * ratio, 1.2, 4.0))


def dynamic_std_combined(vix: float, mv: float) -> float:
    """Scenario D: VIX base × morning vol fine-tune."""
    base = dynamic_std_vix(vix)
    ratio = mv / AVG_MORNING_VOL if AVG_MORNING_VOL > 0 else 1.0
    return float(np.clip(base * ratio, 1.2, 4.0))


def kelly_size(entry_px: float, stop_px: float, equity: float) -> int:
    p  = KELLY_STATS["win_rate"]
    q  = 1.0 - p
    b  = KELLY_STATS["avg_win"] / KELLY_STATS["avg_loss"]
    fk = (p * b - q) / b
    if fk <= 0: return 0
    hk       = fk * KELLY_FRAC
    kelly_sh = int(equity * hk / max(entry_px, 1))
    risk_ps  = abs(entry_px - stop_px)
    if risk_ps <= 0: return 0
    vol_sh   = int(equity * MAX_RISK_PCT / risk_ps)
    limit_sh = int(equity * MAX_POS_PCT  / max(entry_px, 1))
    return max(0, min(kelly_sh, vol_sh, limit_sh))


# ── Core sim function ─────────────────────────────────────────────────────────
def run_scenario(std_fn) -> list:
    """Run VWAP_MR with a given bb_std function(vix, morning_vol) → float."""
    equity = ACCOUNT_START
    trades = []

    for day in calm_days:
        day_vix = vix_map.get(day)
        slots   = 0
        entered = set()

        # Compute morning vol for this day using SPY
        db_spy = _spy_bars[_spy_bars.index.normalize() == day]
        mv = morning_vol(db_spy, day) if len(db_spy) >= 3 else AVG_MORNING_VOL
        bb_std = std_fn(day_vix, mv)

        for ticker in MR_UNIVERSE:
            if slots >= MAX_SLOTS or ticker in entered:
                continue
            tk_db = day_bars.get((ticker, day))
            if tk_db is None:
                continue

            session = tk_db[tk_db.index.time >= dtime(9, 30)].copy()
            if len(session) < BB_PERIOD + 2:
                continue

            # Compute session VWAP (full session up to each bar)
            tp      = (session["high"] + session["low"] + session["close"]) / 3
            cum_tpv = (tp * session["volume"]).cumsum()
            cum_vol = session["volume"].cumsum().replace(0, np.nan)
            vwap_s  = (cum_tpv / cum_vol)

            # Signal window: 10:15 → 14:00
            sig_bars = session[(session.index.time >= SIGNAL_START) &
                               (session.index.time <  TIME_STOP_T)]
            if len(sig_bars) < 2:
                continue

            for i in range(1, len(sig_bars)):
                curr_bar = sig_bars.iloc[i]
                prev_bar = sig_bars.iloc[i - 1]
                bar_ts   = sig_bars.index[i]
                prev_ts  = sig_bars.index[i - 1]

                # bars_to_curr: up to and including current bar (for scanner filters)
                # bars_to_prev: up to and including prev bar   (for BB calculation)
                bars_to_curr = session.loc[:bar_ts]
                bars_to_prev = session.loc[:prev_ts]

                if len(bars_to_curr) < 22:
                    continue

                # ── Engine scanner filters (replicate _build_vwap_candidates) ──
                current_price  = float(curr_bar["close"])
                current_volume = float(curr_bar["volume"])
                avg_bar_vol    = float(bars_to_curr["volume"].mean())
                sma_20         = float(bars_to_curr["close"].rolling(20).mean().iloc[-1])
                if pd.isna(sma_20) or sma_20 <= 0:
                    continue
                # SMA distance ≤ 3%
                if abs(current_price - sma_20) / sma_20 > 0.03:
                    continue
                # ADX < 25 (trendless)
                if compute_adx(bars_to_curr) >= 25.0:
                    continue
                # ATR decreasing
                atr_curr = compute_atr(bars_to_curr)
                atr_5ago = compute_atr(bars_to_curr.iloc[:-5]) if len(bars_to_curr) > 19 else atr_curr
                if atr_curr >= atr_5ago:
                    continue
                # Volume spike < 3× intraday avg
                if avg_bar_vol > 0 and current_volume / avg_bar_vol >= 3.0:
                    continue

                # Bollinger Bands (20-period on bars up to prev bar)
                if len(bars_to_prev) < BB_PERIOD:
                    continue
                closes       = bars_to_prev["close"]
                rm           = closes.rolling(BB_PERIOD).mean().iloc[-1]
                rs           = closes.rolling(BB_PERIOD).std(ddof=1).iloc[-1]
                if pd.isna(rm) or pd.isna(rs) or rs == 0:
                    continue
                bb_upper = rm + bb_std * rs
                bb_lower = rm - bb_std * rs

                # Signal confirmation
                short_ok = (float(prev_bar["high"]) >= bb_upper and
                            float(prev_bar["close"]) < bb_upper)
                long_ok  = (float(prev_bar["low"])  <= bb_lower and
                            float(prev_bar["close"]) > bb_lower)

                if short_ok:   direction = "SHORT"
                elif long_ok:  direction = "LONG"
                else:          continue

                entry_px = float(curr_bar["open"])
                atr      = compute_atr(bars_to_prev)
                stop_dist = STOP_ATR_MULT * atr
                vwap_val  = float(vwap_s.loc[bar_ts])

                if direction == "SHORT":
                    stop_px   = entry_px + stop_dist
                    reward    = entry_px - vwap_val
                else:
                    stop_px   = entry_px - stop_dist
                    reward    = vwap_val - entry_px

                if stop_dist <= 0 or reward / stop_dist < MIN_RR:
                    continue

                target_px = vwap_val
                n_shares  = kelly_size(entry_px, stop_px, equity)
                if n_shares < 1:
                    continue

                # Forward simulate
                fwd = session[(session.index > bar_ts) &
                              (session.index.time <= TIME_STOP_T)]
                exit_px = entry_px
                reason  = "TIME_STOP"
                for _, b in fwd.iterrows():
                    bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
                    if direction == "SHORT":
                        if bh >= stop_px:  exit_px = stop_px;  reason = "STOP_HIT";   break
                        if bl <= target_px: exit_px = target_px; reason = "TARGET_HIT"; break
                    else:
                        if bl <= stop_px:  exit_px = stop_px;  reason = "STOP_HIT";   break
                        if bh >= target_px: exit_px = target_px; reason = "TARGET_HIT"; break
                    exit_px = bc

                mult    = -1 if direction == "SHORT" else 1
                net_pnl = mult * (exit_px - entry_px) * n_shares - n_shares * COMMISSION * 2
                equity += net_pnl

                trades.append(dict(
                    ticker=ticker, day=day, year=str(day.year),
                    direction=direction, bb_std=round(bb_std, 2),
                    vix=round(day_vix, 1) if day_vix else None,
                    morning_vol=round(mv, 3),
                    entry_px=entry_px, stop_px=stop_px,
                    target_px=target_px, stop_dist=stop_dist,
                    shares=n_shares, exit_px=exit_px,
                    reason=reason, net_pnl=net_pnl, win=net_pnl > 0,
                ))
                entered.add(ticker)
                slots += 1
                break

    return trades


# ── Run all scenarios ─────────────────────────────────────────────────────────
def report(label: str, trades: list):
    if not trades:
        print(f"  {label}: 0 trades")
        return
    df   = pd.DataFrame(trades)
    tot  = df["net_pnl"].sum()
    wr   = df["win"].mean() * 100
    avg  = df["net_pnl"].mean()
    rng  = np.random.default_rng(42)
    boot = np.array([rng.choice(df["net_pnl"].values, len(df), replace=True).sum()
                     for _ in range(10_000)])
    p    = float((boot <= 0).mean())
    ci   = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))

    # By std bucket
    by_std = df.groupby("bb_std")["net_pnl"].agg(n="count", total="sum",
                                                   wr=lambda x: (x>0).mean())
    std_str = "  ".join(f"σ={s}({int(r['n'])}t {r['total']:+.0f} WR={r['wr']:.0%})"
                        for s, r in by_std.iterrows())

    print(f"  {label:<35} {len(df):4}t  {tot:>+8,.0f}  WR={wr:.0f}%  "
          f"avg={avg:>+5.1f}  p={p:.3f}  CI=[{ci[0]:+,.0f},{ci[1]:+,.0f}]")
    print(f"    By σ: {std_str}")
    for yr in ["2020", "2021", "2022"]:
        y = df[df.year == yr]
        if len(y):
            print(f"    {yr}: {len(y):3}t  {y['net_pnl'].sum():>+7,.0f}  WR={y['win'].mean()*100:.0f}%")
    print()


HDR = "=" * 70
print(f"\n{HDR}")
print(f"  VWAP_MR DYNAMIC BB STD SIM — Calm days 2020-2022")
print(f"  Universe: {MR_UNIVERSE}")
print(f"  Current WFO param: bb_std=2.5 (fixed)")
print(f"{HDR}\n")

scenarios = [
    ("A  Fixed 2.5σ (baseline)",
     lambda vix, mv: 2.5),
    ("B  VIX bucket (1.5/2.0/2.5/3.0)",
     lambda vix, mv: dynamic_std_vix(vix)),
    ("C  Morning vol scaling",
     lambda vix, mv: dynamic_std_vol(mv)),
    ("D  Combined (VIX × morning vol)",
     lambda vix, mv: dynamic_std_combined(vix, mv)),
]

for label, fn in scenarios:
    print(f"Running {label}...")
    trades = run_scenario(fn)
    report(label, trades)

print(f"{HDR}\n")
