"""
Exact reconciliation: standalone FADE sim → engine count, step by step.

Funnel:
  Step 0: All days, full day window (9:45-14:00), no filters    → standalone baseline
  Step 1: Restrict to 9:45-10:15 engine window                  → window filter
  Step 2: Remove Stress-regime days (from engine pkl)            → regime filter
  Step 3: Apply SPY=UP filter on SHORT FADE                      → SPY filter
  Step 4: Apply top-2 ATR% filter on LONG FADE                   → ATR filter
  Step 5: Apply MAX_FADE=5 cap per day                           → position cap
  Engine: actual engine count from pkl                           → target

Usage:
    cd d:\raits\raits
    python raits/scripts/fade_reconcile.py
"""
import os, sys, pickle
import pandas as pd
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR    = os.path.join(SCRIPT_DIR, "..", "..", "data", "cache")
SNAP_DIR     = os.path.join(CACHE_DIR, "snapshots")
PICKLE_5MIN  = os.path.join(CACHE_DIR, "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(CACHE_DIR, "window_debug_daily.pkl")
SCENE_G_PKL  = os.path.join(SNAP_DIR, "results_scenario_g.pkl")

# ── Same constants as fade_scanner_test.py ────────────────────────────────────
OR_PERIOD_MIN = 15
LOOKBACK_DAYS = 60
GAP_THRESHOLD = 0.01
MIN_GAP_FREQ  = 0.05
RVOL_MULT     = 1.5
TOP_N         = 10
STOP_PCT      = 0.005
ACCOUNT       = 50_000
MAX_RISK_PCT  = 0.01
COMMISSION    = 0.005
MAX_FADE_DAY  = 5

WINDOWS = [
    ("2020-01-01", "2020-12-31", "2020"),
    ("2021-01-01", "2021-12-31", "2021"),
    ("2022-01-01", "2022-12-31", "2022"),
]

CANDIDATE_POOL = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AMD",
    "QCOM", "INTC", "MU", "AVGO", "TXN", "AMAT",
    "ADBE", "CRM", "ORCL", "INTU", "CSCO",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX",
    "COST", "SBUX", "NFLX", "EBAY",
    "JPM", "GS", "MS", "V", "MA",
    "HON", "MMM", "XOM", "CVX",
]

# ── Load caches ───────────────────────────────────────────────────────────────
print("Loading caches...")
with open(PICKLE_5MIN,  "rb") as f: data_5min  = pickle.load(f)
with open(PICKLE_DAILY, "rb") as f: data_daily = pickle.load(f)
with open(SCENE_G_PKL,  "rb") as f: engine_results = pickle.load(f)
print(f"  5-min: {len(data_5min)} tickers | daily: {len(data_daily)} tickers")

# ── Step A: extract per-day regime from engine pkl ────────────────────────────
# For each trading day, record the HMM state. If a day has no trades at all,
# infer Stress if the engine had only TF trades OR use the closest day.
# Method: use majority hmm_state across all trades on that day.
print("\nBuilding per-day regime map from engine pkl...")
day_regime: dict = {}  # Timestamp(normalize) → "Calm"/"Normal"/"Stress"
day_regime_votes: dict = defaultdict(lambda: defaultdict(int))

for window in engine_results:
    for t in window.get("trades", []):
        entry_ts = pd.Timestamp(getattr(t, "entry_time", None))
        if pd.isna(entry_ts):
            continue
        day_norm = entry_ts.normalize()
        regime   = getattr(t, "hmm_state", "Normal")
        day_regime_votes[day_norm][regime] += 1

for day_norm, votes in day_regime_votes.items():
    day_regime[day_norm] = max(votes, key=votes.get)

# Days with no trades at all are not in day_regime_votes.
# We'll mark them as unknown → treated as "not Stress" (conservative).
print(f"  Regime known for {len(day_regime)} trading days")

# Count how many Stress days per year
for start, end, yr in WINDOWS:
    ts, te = pd.Timestamp(start), pd.Timestamp(end)
    stress = sum(1 for d, r in day_regime.items() if ts <= d <= te and r == "Stress")
    total  = sum(1 for d in day_regime if ts <= d <= te)
    print(f"  {yr}: {stress} Stress days / {total} days with trades")

# ── Step B: normalize data ────────────────────────────────────────────────────
print("\nNormalizing 5-min data...")
normed_5min = {}
for ticker in CANDIDATE_POOL + ["SPY"]:
    df = data_5min.get(ticker, pd.DataFrame())
    if df.empty: continue
    if df.index.tzinfo:
        df = df.copy(); df.index = df.index.tz_localize(None)
    normed_5min[ticker] = df

# ── Step C: pre-compute FADE scanner stats ────────────────────────────────────
print("Pre-computing FADE scanner stats...")
normed_daily = {}
for ticker in CANDIDATE_POOL:
    df = data_daily.get(ticker, pd.DataFrame())
    if df.empty: continue
    if df.index.tzinfo:
        df = df.copy(); df.index = df.index.tz_localize(None)
    normed_daily[ticker] = df

all_days_set = set()
for ticker in CANDIDATE_POOL:
    df = normed_5min.get(ticker, pd.DataFrame())
    if df.empty: continue
    all_days_set.update(df.index.normalize().unique())

window_start = min(pd.Timestamp(s) for s, _, _ in WINDOWS)
window_end   = max(pd.Timestamp(e) for _, e, _ in WINDOWS)
window_days  = sorted(d for d in all_days_set if window_start <= d <= window_end)

scanner_data = {}
total = len(window_days)
for i, day in enumerate(window_days):
    if i % 50 == 0:
        print(f"  {i}/{total}", end="\r")
    day_str = str(day.date())
    scanner_data[day_str] = {}
    for ticker, df in normed_daily.items():
        df_cut = df[df.index.normalize() <= day]
        if len(df_cut) < LOOKBACK_DAYS + 1: continue
        if float(df_cut["volume"].iloc[-20:].mean()) < 500_000: continue
        window     = df_cut.iloc[-(LOOKBACK_DAYS + 1):]
        prev_close = window["close"].shift(1)
        gap_pct    = (window["open"] - prev_close).abs() / prev_close
        gap_dir    = window["open"] - prev_close
        intraday   = window["close"] - window["open"]
        gap_pct    = gap_pct.iloc[1:]; gap_dir = gap_dir.iloc[1:]; intraday = intraday.iloc[1:]
        is_gap   = gap_pct >= GAP_THRESHOLD
        gap_freq = float(is_gap.mean())
        if gap_freq < MIN_GAP_FREQ: continue
        followthrough = float(((gap_dir * intraday) > 0)[is_gap].mean()) if is_gap.any() else 0.0
        scanner_data[day_str][ticker] = (gap_freq, followthrough)
print(f"  {total}/{total} done.   ")

def get_fade_universe(day_str, top_n=TOP_N):
    stats = scanner_data.get(day_str, {})
    scored = [(t, f * (1-ft)) for t, (f, ft) in stats.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:top_n]]

# ── Step D: pre-compute ATR% top-2 per day ───────────────────────────────────
print("Pre-computing ATR% top-2 per day...")
ATR_PERIOD = 14

# Build ATR% series per ticker
ticker_atr_pct = {}
for ticker, df in normed_daily.items():
    if ticker == "SPY": continue
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_index()
    if len(df) < ATR_PERIOD + 1: continue
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=ATR_PERIOD, adjust=False).mean()
    ticker_atr_pct[ticker] = atr / df["close"]

# For each trading day, compute top-2
atr_top2_by_day = {}
for i, day in enumerate(window_days):
    if i % 50 == 0:
        print(f"  {i}/{total}", end="\r")
    day_atrs = {}
    for ticker, series in ticker_atr_pct.items():
        prior = series[series.index < day]
        if prior.empty: continue
        day_atrs[ticker] = float(prior.iloc[-1])
    if day_atrs:
        ranked = sorted(day_atrs.items(), key=lambda x: x[1], reverse=True)
        atr_top2_by_day[day] = {t for t, _ in ranked[:2]}
    else:
        atr_top2_by_day[day] = set()
print(f"  {total}/{total} done.   ")

# ── Step E: pre-compute SPY OR high/low per day ───────────────────────────────
spy_df = normed_5min.get("SPY", pd.DataFrame())
spy_or_by_day = {}
if not spy_df.empty:
    for day in window_days:
        day_spy = spy_df[spy_df.index.normalize() == day]
        or_bars = day_spy[
            (day_spy.index.time >= pd.Timestamp("09:30").time()) &
            (day_spy.index.time <= pd.Timestamp("09:44").time())
        ]
        if or_bars.empty:
            spy_or_by_day[day] = (None, None)
        else:
            spy_or_by_day[day] = (float(or_bars["high"].max()), float(or_bars["low"].min()))

def spy_up_at(day, entry_ts):
    """True if SPY close at entry_ts > SPY OR high."""
    or_high, _ = spy_or_by_day.get(day, (None, None))
    if or_high is None: return False
    day_spy = spy_df[spy_df.index.normalize() == day]
    bars = day_spy[day_spy.index <= entry_ts]
    if bars.empty: return False
    return float(bars.iloc[-1]["close"]) > or_high

# ── Step F: run standalone simulation ────────────────────────────────────────
print("\nRunning standalone simulation...")

def simulate_day_full(ticker, day, full_window=True):
    """Returns all FADE trades with direction and entry_time tagged."""
    df = normed_5min.get(ticker)
    if df is None: return []
    day_bars = df[df.index.normalize() == day]
    if len(day_bars) < OR_PERIOD_MIN // 5 + 2: return []

    market_open = day + pd.Timedelta(hours=9, minutes=30)
    or_end      = market_open + pd.Timedelta(minutes=OR_PERIOD_MIN)
    sig_end     = day + pd.Timedelta(hours=14) if full_window else day + pd.Timedelta(hours=10, minutes=15)

    or_bars      = day_bars[day_bars.index < or_end]
    post_or_bars = day_bars[(day_bars.index >= or_end) & (day_bars.index < sig_end)].reset_index()
    if len(or_bars) == 0 or len(post_or_bars) < 2: return []

    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    if or_high <= or_low: return []

    all_prior = df[df.index < market_open]
    vol_avg   = float(all_prior["volume"].tail(20).mean()) if len(all_prior) >= 5 else 0.0

    _ts_col = post_or_bars.columns[0]
    trades  = []

    for i, bar_b in post_or_bars.iterrows():
        close_b = float(bar_b["close"])
        vol_b   = float(bar_b["volume"])
        if close_b > or_high:       direction = "LONG_BREAK"
        elif close_b < or_low:      direction = "SHORT_BREAK"
        else:                       continue
        if vol_avg > 0 and vol_b < RVOL_MULT * vol_avg: continue
        if i + 1 >= len(post_or_bars): continue
        bar_b1   = post_or_bars.iloc[i + 1]
        close_b1 = float(bar_b1["close"])
        if direction == "LONG_BREAK"  and close_b1 >= or_high: continue
        if direction == "SHORT_BREAK" and close_b1 <= or_low:  continue

        if direction == "LONG_BREAK":
            fade_dir  = "SHORT"
            stop_loss = or_high * (1 + STOP_PCT)
            target    = or_low
        else:
            fade_dir  = "LONG"
            stop_loss = or_low  * (1 - STOP_PCT)
            target    = or_high

        entry  = close_b1
        risk   = abs(entry - stop_loss)
        if risk <= 0 or abs(target - entry) <= 0: continue
        dir_sign = 1 if fade_dir == "LONG" else -1
        shares   = max(1, int((ACCOUNT * MAX_RISK_PCT) / risk))

        remaining = post_or_bars.iloc[i + 2:]
        exit_px, exit_rsn = None, "EOD"
        for _, rb in remaining.iterrows():
            if fade_dir == "SHORT":
                if float(rb["high"]) >= stop_loss: exit_px = stop_loss; exit_rsn = "STOP_HIT";   break
                if float(rb["low"])  <= target:    exit_px = target;    exit_rsn = "TARGET_HIT"; break
            else:
                if float(rb["low"])  <= stop_loss: exit_px = stop_loss; exit_rsn = "STOP_HIT";   break
                if float(rb["high"]) >= target:    exit_px = target;    exit_rsn = "TARGET_HIT"; break
        if exit_px is None:
            exit_px = float(remaining.iloc[-1]["close"]) if not remaining.empty else entry

        net = shares * (exit_px - entry) * dir_sign - shares * COMMISSION * 2
        trades.append({
            "date": day, "ticker": ticker, "direction": fade_dir,
            "entry_time": bar_b1[_ts_col], "net_pnl": net,
            "exit_rsn": exit_rsn,
        })
        break  # one FADE per ticker per day (first signal only)

    return trades


# ── Funnel ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("  RECONCILIATION FUNNEL")
print("=" * 72)

header = f"  {'Step':<42} {'2020':>6} {'2021':>6} {'2022':>6} {'Total':>7}"
print(header)
print(f"  {'-'*65}")

def count_yr(trades_by_yr):
    return {yr: len(t) for yr, t in trades_by_yr.items()}

def show_row(label, counts_by_yr):
    total = sum(counts_by_yr.values())
    cols  = "".join(f"{counts_by_yr.get(yr, 0):>6}" for _, _, yr in WINDOWS)
    print(f"  {label:<42}{cols}  {total:>6}")

# ── Step 0: full day window, all days ─────────────────────────────────────────
step0 = {}
for _, _, yr in WINDOWS:
    yr_start = pd.Timestamp(f"{yr}-01-01")
    yr_end   = pd.Timestamp(f"{yr}-12-31")
    yr_trades = []
    yr_days   = [d for d in window_days if yr_start <= d <= yr_end]
    for day in yr_days:
        day_str  = str(day.date())
        universe = get_fade_universe(day_str)
        for ticker in universe:
            yr_trades.extend(simulate_day_full(ticker, day, full_window=True))
    step0[yr] = yr_trades
show_row("0. Standalone (full day, all days)", count_yr(step0))

# ── Step 1: restrict to 9:45-10:15 engine window ──────────────────────────────
ENG_START = pd.Timestamp("1970-01-01 09:45").time()
ENG_END   = pd.Timestamp("1970-01-01 10:15").time()

def in_engine_window(entry_ts):
    t = pd.Timestamp(entry_ts).time()
    return ENG_START <= t <= ENG_END

step1 = {yr: [t for t in trades if in_engine_window(t["entry_time"])]
         for yr, trades in step0.items()}
show_row("1. Filter: 9:45-10:15 window only", count_yr(step1))

# ── Step 2: remove Stress-regime days ─────────────────────────────────────────
def is_stress_day(day):
    regime = day_regime.get(day.normalize())
    return regime == "Stress"

step2 = {yr: [t for t in trades if not is_stress_day(t["date"])]
         for yr, trades in step1.items()}
show_row("2. Filter: remove Stress-regime days", count_yr(step2))

# ── Step 3: SPY=UP filter (SHORT FADE only) ───────────────────────────────────
step3 = {}
for yr, trades in step2.items():
    kept = []
    for t in trades:
        if t["direction"] == "SHORT":
            entry_ts = pd.Timestamp(t["entry_time"])
            if spy_up_at(t["date"], entry_ts):
                continue  # blocked by SPY=UP filter
        kept.append(t)
    step3[yr] = kept
show_row("3. Filter: SHORT skip when SPY=UP", count_yr(step3))

# ── Step 4: ATR% top-2 filter (LONG FADE only) ────────────────────────────────
step4 = {}
for yr, trades in step3.items():
    kept = []
    for t in trades:
        if t["direction"] == "LONG":
            top2 = atr_top2_by_day.get(t["date"], set())
            if t["ticker"] in top2:
                continue  # blocked by ATR% filter
        kept.append(t)
    step4[yr] = kept
show_row("4. Filter: LONG skip top-2 ATR%", count_yr(step4))

# ── Step 5a: Opening volume filter (run_scanner at 9:35) ──────────────────────
# Engine: opening_5min_volume > 1.2 × avg_opening_5min_volume (prior 20 days)
# fade_orb config: opening_vol_multiplier=1.2, premarket_vol_threshold=10000
# premarket_volume = 0 (not available) → only Option B (opening volume) applies.
OPEN_VOL_MULT = 1.2

# Precompute per-ticker: daily opening (9:30–9:35) volume as a Series indexed by date.
# Then rolling(20).mean() shifted by 1 gives T-1 avg → compare to today's vol.
print("\nPre-computing opening volume lookup tables (vectorized)...")
_open_vol_lookup = {}  # ticker → pd.Series(date → passes_bool)
for ticker, df in normed_5min.items():
    if df.empty: continue
    # Extract only 9:30 bars (first 5-min slot)
    open_slot = df[
        (df.index.time >= pd.Timestamp("09:30").time()) &
        (df.index.time <  pd.Timestamp("09:35").time())
    ].copy()
    if open_slot.empty: continue
    # Sum volume per day (in case of multiple bars in slot)
    daily_open_vol = open_slot.groupby(open_slot.index.normalize())["volume"].sum()
    # Rolling 20-day avg of prior days (shift(1) = T-1)
    avg_20 = daily_open_vol.rolling(20, min_periods=1).mean().shift(1)
    passes = (avg_20 <= 0) | (daily_open_vol > OPEN_VOL_MULT * avg_20)
    _open_vol_lookup[ticker] = passes
print(f"  Done ({len(_open_vol_lookup)} tickers)")

all_ticker_days = set((t["date"], t["ticker"]) for trades in step4.values() for t in trades)
_open_vol_cache = {}
for day, ticker in all_ticker_days:
    series = _open_vol_lookup.get(ticker)
    if series is None:
        _open_vol_cache[(day, ticker)] = False
        continue
    day_norm = day.normalize() if hasattr(day, "normalize") else pd.Timestamp(day).normalize()
    _open_vol_cache[(day, ticker)] = bool(series.get(day_norm, False))

step4b = {yr: [t for t in trades if _open_vol_cache.get((t["date"], t["ticker"]), True)]
          for yr, trades in step4.items()}
show_row("5a. Filter: opening vol > 1.2×avg (run_scanner)", count_yr(step4b))

# ── Step 5b: OR range validity (calculate_opening_range) ──────────────────────
# Engine: or_range >= max(0.5×ATR, $0.20) AND or_range <= 5×ATR
# ATR computed from intraday bars (engine uses _compute_atr on bars_so_far)
MIN_RANGE_ATR = 0.5
MAX_RANGE_ATR = 5.0
MIN_RANGE_ABS = 0.20

def compute_atr_intraday(bars, period=14):
    """ATR(14) from intraday bars (same logic as engine._compute_atr)."""
    if len(bars) < 2: return 0.0
    prev_close = bars["close"].shift(1)
    tr = pd.concat([
        bars["high"] - bars["low"],
        (bars["high"] - prev_close).abs(),
        (bars["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1).dropna()
    if tr.empty: return 0.0
    return float(tr.ewm(span=period, adjust=False).mean().iloc[-1])

def passes_or_range_validity(ticker, day):
    """True if OR range passes narrow/wide validation against ATR."""
    df = normed_5min.get(ticker)
    if df is None: return False
    day_bars = df[df.index.normalize() == day]
    if day_bars.empty: return False
    market_open = day + pd.Timedelta(hours=9, minutes=30)
    or_end      = market_open + pd.Timedelta(minutes=OR_PERIOD_MIN)
    or_bars     = day_bars[day_bars.index < or_end]
    if len(or_bars) < 2: return False
    or_high = float(or_bars["high"].max())
    or_low  = float(or_bars["low"].min())
    or_range = or_high - or_low
    # ATR from bars up to OR end
    bars_for_atr = day_bars[day_bars.index <= or_end]
    atr = compute_atr_intraday(bars_for_atr)
    if atr <= 0: return or_range >= MIN_RANGE_ABS
    min_range = max(MIN_RANGE_ATR * atr, MIN_RANGE_ABS)
    max_range = MAX_RANGE_ATR * atr
    return min_range <= or_range <= max_range

print("\nPre-computing OR range validity per (day, ticker)...")
_or_valid_cache = {}
# Group by ticker to process all days for each ticker at once
from collections import defaultdict as _dd
by_ticker = _dd(list)
for day, ticker in all_ticker_days:
    by_ticker[ticker].append(day)

for ticker, days in by_ticker.items():
    df = normed_5min.get(ticker)
    if df is None:
        for day in days: _or_valid_cache[(day, ticker)] = False
        continue
    for day in days:
        _or_valid_cache[(day, ticker)] = passes_or_range_validity(ticker, day)
print(f"  Done ({len(_or_valid_cache)} entries)")

step4c = {yr: [t for t in trades if _or_valid_cache.get((t["date"], t["ticker"]), True)]
          for yr, trades in step4b.items()}
show_row("5b. Filter: OR range valid (ATR bounds)", count_yr(step4c))

# ── Step 5: MAX_FADE=5 cap per day ────────────────────────────────────────────
step5 = {}
for yr, trades in step4c.items():
    by_day = defaultdict(list)
    for t in sorted(trades, key=lambda x: x["entry_time"]):
        by_day[t["date"]].append(t)
    kept = []
    for day_trades in by_day.values():
        kept.extend(day_trades[:MAX_FADE_DAY])
    step5[yr] = kept
show_row("5c. Cap: MAX_FADE=5 per day", count_yr(step5))

# ── Engine count from pkl ──────────────────────────────────────────────────────
engine_counts = {}
for window in engine_results:
    yr     = window.get("label", "?")
    trades = window.get("trades", [])
    engine_counts[yr] = sum(1 for t in trades if getattr(t, "strategy", "") == "FADE")
show_row("ENGINE (actual pkl)", engine_counts)

print(f"\n  {'─'*65}")
print(f"  Remaining gap (Step5 - Engine):")
for _, _, yr in WINDOWS:
    diff = step5.get(yr, [])
    eng  = engine_counts.get(yr, 0)
    print(f"    {yr}: standalone_filtered={len(diff)}  engine={eng}  delta={len(diff)-eng:+d}")

print(f"\n  Note: residual delta comes from:")
print(f"    - MAX_TOTAL=8 cross-strategy position cap (ORB/TF/VMR compete for slots)")
print(f"    - Circuit breaker fires (stops day early after -4% or 5 losses)")
print(f"    - PDT guard (blocks trades if < 25k buying power)")
print(f"    - HMM state unknown for 0-trade days (treated as Normal by default)")
print(f"    - Standalone uses simpler stop/target calc vs engine exact VWAP stop")
print("=" * 72)
