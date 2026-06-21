"""
VMR signal quality analysis.
Với mỗi VMR trade, load touch bar (bar T-1) từ 5-min data.
Tìm features discriminate winners vs losers.

Usage:
    cd d:\raits\raits
    python raits/scripts/vmr_signal_quality.py
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd
import numpy as np

PKL_RESULTS = r'd:\raits\raits\data\cache\snapshots\results_scenario_g.pkl'
PKL_5MIN    = r'd:\raits\raits\data\cache\window_debug_5min.pkl'

# ── Load trades ───────────────────────────────────────────────────────────────
with open(PKL_RESULTS, "rb") as f:
    results = pickle.load(f)

rows = []
for window in results:
    yr = window.get("label", "?")
    for t in window.get("trades", []):
        d = vars(t).copy() if hasattr(t, "__dict__") else {}
        d["year"] = yr
        rows.append(d)

all_df = pd.DataFrame(rows)
vmr = all_df[all_df["strategy"] == "VWAP_MR"].copy()
vmr["entry_time"] = pd.to_datetime(vmr["entry_time"])
vmr["win"]  = vmr["net_pnl"] > 0
vmr["atr"]  = (vmr["entry_price"] - vmr["stop"]).abs() / 1.5

# ── Load 5-min data ───────────────────────────────────────────────────────────
print("Loading 5-min data...")
with open(PKL_5MIN, "rb") as f:
    data_5min = pickle.load(f)

# Reindex all tickers
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

# SPY for VWAP
spy = data_5min.get("SPY", pd.DataFrame()).sort_index()
spy["tp"]  = (spy["high"] + spy["low"] + spy["close"]) / 3
spy["tpv"] = spy["tp"] * spy["volume"]
spy["date"] = spy.index.normalize()
spy["cum_tpv"] = spy.groupby("date")["tpv"].cumsum()
spy["cum_vol"] = spy.groupby("date")["volume"].cumsum()
spy["vwap"]    = spy["cum_tpv"] / spy["cum_vol"]

# ── Feature extraction per trade ──────────────────────────────────────────────
FIVE_MIN = pd.Timedelta("5min")

def get_touch_features(row):
    ticker     = row["ticker"]
    entry_ts   = row["entry_time"]
    direction  = row["direction"]
    entry_px   = row["entry_price"]
    atr        = row["atr"]

    if ticker not in data_5min:
        return {}

    bars = data_5min[ticker].sort_index()

    # Touch bar = bar that closed just before entry
    touch_ts = entry_ts - FIVE_MIN
    if touch_ts not in bars.index:
        # Find closest bar at or before touch_ts
        candidates = bars.index[bars.index <= touch_ts]
        if len(candidates) == 0:
            return {}
        touch_ts = candidates[-1]

    touch = bars.loc[touch_ts]
    day_bars = bars[bars.index.normalize() == touch_ts.normalize()]

    # ── Feature 1: Wick outside band ─────────────────────────────────────────
    # Approximate BB upper/lower ≈ entry_price (entry is at bar T open,
    # which opens near where bar T-1 closed relative to the band)
    # More precisely: for SHORT, bb_upper is somewhere between touch.close and touch.high
    # We use entry_price as proxy for bb_upper/lower (it's where price was at open of T)
    if direction == "SHORT":
        wick_outside = max(0, touch["high"] - entry_px)   # how far above "band" it went
        close_back   = max(0, entry_px - touch["close"])  # how far it closed back
        bar_range    = touch["high"] - touch["low"]
        rejection    = close_back / bar_range if bar_range > 0 else 0
        wick_ratio   = wick_outside / atr if atr > 0 else 0
    else:  # LONG
        wick_outside = max(0, entry_px - touch["low"])
        close_back   = max(0, touch["close"] - entry_px)
        bar_range    = touch["high"] - touch["low"]
        rejection    = close_back / bar_range if bar_range > 0 else 0
        wick_ratio   = wick_outside / atr if atr > 0 else 0

    # ── Feature 2: Bar body ratio (pin bar quality) ───────────────────────────
    # High body_ratio = strong close in reversal direction
    body = abs(touch["close"] - touch["open"])
    body_ratio = body / bar_range if bar_range > 0 else 0

    # ── Feature 3: Volume at touch bar vs day avg ─────────────────────────────
    # Low volume = settling/consolidation → good for MR
    # High volume = momentum → bad for MR
    day_avg_vol = day_bars["volume"].mean()
    vol_ratio   = touch["volume"] / day_avg_vol if day_avg_vol > 0 else 1.0

    # ── Feature 4: SPY direction at touch time ────────────────────────────────
    spy_at_touch = spy[spy.index <= touch_ts]
    if len(spy_at_touch):
        spy_row = spy_at_touch.iloc[-1]
        spy_above_vwap = float(spy_row["close"]) > float(spy_row["vwap"])
    else:
        spy_above_vwap = None

    # ── Feature 5: Time of day bucket ────────────────────────────────────────
    h = touch_ts.hour
    bucket = "11-12" if h == 11 else ("12-13" if h == 12 else "13-14")

    # ── Feature 6: Distance entry → VWAP in ATR units ────────────────────────
    # (proxy for R:R quality — larger = more room to VWAP = better reward)
    reward  = abs(entry_px - row["target"])
    rr      = reward / (atr * 1.5) if atr > 0 else 0

    return {
        "wick_ratio":      round(wick_ratio, 3),
        "rejection":       round(rejection, 3),    # fraction of bar that "closed back"
        "body_ratio":      round(body_ratio, 3),
        "vol_ratio":       round(vol_ratio, 3),
        "spy_above_vwap":  spy_above_vwap,
        "bucket":          bucket,
        "rr":              round(rr, 3),
        "touch_volume":    int(touch["volume"]),
        "bar_range_atr":   round(bar_range / atr, 3) if atr > 0 else 0,
    }

print("Extracting touch bar features...")
features = vmr.apply(get_touch_features, axis=1)
feat_df  = pd.DataFrame(list(features))
vmr = pd.concat([vmr.reset_index(drop=True), feat_df], axis=1)
vmr_f = vmr[feat_df.apply(lambda x: len(x) > 0, axis=1)].copy()

def div(label, w=72):
    print(f"\n{'─'*w}\n  {label}\n{'─'*w}")

W = 8
def show(label, sub, indent="  "):
    n   = len(sub)
    pnl = sub["net_pnl"].sum() if n else 0
    wr  = sub["win"].mean() * 100 if n else 0
    avg = sub["net_pnl"].mean() if n else 0
    print(f"{indent}{label:<42} n={n:>3}  P&L={pnl:>+7,.0f}  WR={wr:>3.0f}%  avg={avg:>+5.1f}")

print(f"\n{'='*72}")
print(f"  VMR SIGNAL QUALITY  —  {len(vmr_f)} trades with features")
print(f"{'='*72}")

# ── 1. Winners vs Losers — feature comparison ─────────────────────────────────
div("1. MEAN FEATURES: WINNERS vs LOSERS")
winners = vmr_f[vmr_f["win"] == True]
losers  = vmr_f[vmr_f["win"] == False]
for feat in ["wick_ratio", "rejection", "body_ratio", "vol_ratio", "rr", "bar_range_atr"]:
    if feat in vmr_f.columns:
        wv = winners[feat].mean()
        lv = losers[feat].mean()
        delta = wv - lv
        print(f"  {feat:<20}  winners={wv:>6.3f}   losers={lv:>6.3f}   delta={delta:>+6.3f}")

# ── 2. Wick ratio splits ──────────────────────────────────────────────────────
div("2. WICK RATIO (wick outside band / ATR) — bigger = stronger rejection")
print(f"\n  {'Bucket':42} {'n':>4}  {'P&L':>8}  {'WR':>5}  {'avg':>6}")
for lo, hi, lbl in [(0, 0.1, "tiny  <0.1×ATR"),
                    (0.1, 0.3, "small 0.1–0.3×ATR"),
                    (0.3, 0.6, "med   0.3–0.6×ATR"),
                    (0.6, 99,  "large >0.6×ATR")]:
    s = vmr_f[(vmr_f["wick_ratio"] >= lo) & (vmr_f["wick_ratio"] < hi)]
    if len(s): show(lbl, s)

# ── 3. Rejection ratio splits ─────────────────────────────────────────────────
div("3. REJECTION RATIO (close_back / bar_range) — bigger = stronger close back inside")
for lo, hi, lbl in [(0, 0.3,  "weak   <30% of bar"),
                    (0.3, 0.6, "med  30–60% of bar"),
                    (0.6, 0.8, "good 60–80% of bar"),
                    (0.8, 1.0, "strong >80% of bar")]:
    s = vmr_f[(vmr_f["rejection"] >= lo) & (vmr_f["rejection"] < hi)]
    if len(s): show(lbl, s)

# ── 4. Volume at touch ────────────────────────────────────────────────────────
div("4. VOLUME AT TOUCH BAR vs DAY AVG — low vol = settling, high vol = momentum")
for lo, hi, lbl in [(0, 0.5,   "very low  <0.5×avg"),
                    (0.5, 0.8,  "low   0.5–0.8×avg"),
                    (0.8, 1.2,  "normal 0.8–1.2×avg"),
                    (1.2, 2.0,  "high  1.2–2.0×avg"),
                    (2.0, 99,   "spike >2.0×avg")]:
    s = vmr_f[(vmr_f["vol_ratio"] >= lo) & (vmr_f["vol_ratio"] < hi)]
    if len(s): show(lbl, s)

# ── 5. Combined: wick + rejection filter ─────────────────────────────────────
div("5. COMBINED: strong wick (>0.3×ATR) AND strong rejection (>60%)")
strong = vmr_f[(vmr_f["wick_ratio"] >= 0.3) & (vmr_f["rejection"] >= 0.6)]
weak   = vmr_f[~((vmr_f["wick_ratio"] >= 0.3) & (vmr_f["rejection"] >= 0.6))]
show("Strong signal (wick>0.3 AND rejection>60%)", strong)
show("Weak signal  (everything else)",             weak)

# Also combined with SPY filter
if "spy_above_vwap" in vmr_f.columns:
    strong_spy = strong[
        ~(((strong["direction"] == "SHORT") & (strong["spy_above_vwap"] == True)) |
          ((strong["direction"] == "LONG")  & (strong["spy_above_vwap"] == False)))
    ]
    show("  + SPY aligned", strong_spy)

# ── 6. Threshold grid: find best wick × rejection cutoff ─────────────────────
div("6. THRESHOLD GRID — wick_ratio × rejection cutoff")
print(f"\n  {'wick≥':>6} {'rej≥':>6}  {'n':>4}  {'WR':>5}  {'P&L':>8}  {'sys_pnl':>9}")
non_vmr = all_df[all_df["strategy"] != "VWAP_MR"]["net_pnl"].sum()
best = []
for wt in [0.0, 0.2, 0.3, 0.4, 0.5]:
    for rt in [0.0, 0.4, 0.5, 0.6, 0.7]:
        s = vmr_f[(vmr_f["wick_ratio"] >= wt) & (vmr_f["rejection"] >= rt)]
        if len(s) < 20:
            continue
        wr  = s["win"].mean() * 100
        pnl = s["net_pnl"].sum()
        sys = pnl + non_vmr
        best.append((wt, rt, len(s), wr, pnl, sys))

best.sort(key=lambda x: x[4], reverse=True)
for wt, rt, n, wr, pnl, sys in best[:15]:
    print(f"  {wt:>6.1f} {rt:>6.1f}  {n:>4}  {wr:>4.0f}%  {pnl:>+8,.0f}  {sys:>+9,.0f}")

# ── 7. Low volume touch bar ───────────────────────────────────────────────────
div("7. SIMULATION: vol_ratio < 1.0 at touch (settling, not momentum)")
low_vol = vmr_f[vmr_f["vol_ratio"] < 1.0]
high_vol = vmr_f[vmr_f["vol_ratio"] >= 1.0]
show("Low vol touch (<1.0× day avg)", low_vol)
show("High vol touch (≥1.0× day avg)", high_vol)

# ── 8. Year breakdown for best filter combo ───────────────────────────────────
if best:
    best_wt, best_rt = best[0][0], best[0][1]
    div(f"8. BEST COMBO (wick≥{best_wt} AND rej≥{best_rt}) — year breakdown")
    top = vmr_f[(vmr_f["wick_ratio"] >= best_wt) & (vmr_f["rejection"] >= best_rt)]
    for yr in ["2020", "2021", "2022"]:
        s = top[top["year"] == yr]
        if len(s):
            show(yr, s)
