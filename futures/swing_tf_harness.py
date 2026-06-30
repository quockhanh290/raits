"""
swing_tf_harness.py — test the REAL swing TREND_FOLLOW on futures (read-only)
============================================================================
The spike tested TF as INTRADAY (close at EOD). Production TF is SWING:
allow_swing_hold=True, max_hold_days=5, with a Chandelier trailing stop
recomputed EOD from the DAILY ATR (14, ×3.0). The intraday "TF fail" verdict
does NOT apply to this. This harness replicates the engine's swing semantics so
TF can finally be tested with the holding it actually uses.

ENGINE SEMANTICS REPLICATED (raits/backtest/engine.py):
  - Entry: intraday, 5-min, EMA pullback + volume, 14:00–15:55 window
    (reuses the real TrendFollowStrategy.generate_signal — identical to spike).
  - Initial stop: intraday chandelier from entry (generate_signal).
  - EOD each day: ratchet stop = running_extreme ∓ 3×daily_ATR (only tightens),
    daily_ATR = 14-period ATR on daily-resampled OHLC (_compute_daily_atr).
  - Within a day the stop is FIXED at the prior-EOD level; checked vs bars.
  - Force-close at max_hold_days (5 calendar days) at that day's open.

FUTURES ADAPTATION (stated, not hidden):
  Production was built for STOCKS where overnight = gap (stop checked at next
  open). Futures trade ~23h continuously, so the stop can be hit DURING the
  overnight session. This harness checks the stop across ALL held bars incl.
  overnight — more faithful to how a futures stop actually fills, but slightly
  different trigger timing than the stock engine.

    python swing_tf_harness.py --parquet ES_8y.parquet --regime-csv spy_daily.csv \
        --point-value 5 --hmm-train-end 2019-06-30 --dump-csv es_swingtf.csv
"""
from __future__ import annotations
import argparse, sys
from datetime import time as dtime
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path.cwd()))


def daily_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """14-period ATR on daily-resampled OHLC, indexed by (tz-naive) day."""
    d = df.resample("B").agg({"open": "first", "high": "max",
                              "low": "min", "close": "last"}).dropna()
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(),
                    (d["low"] - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    atr.index = pd.DatetimeIndex(atr.index).tz_localize(None).normalize()
    return atr.dropna()


_SWING_CACHE = {}

def _swing_cache(df):
    """Precompute per-df: daily ATR, day list, per-day high/low/open arrays (1m),
    per-day 5m frames. Keyed by id(df) so WFO reuses across param/fold calls."""
    k = id(df)
    if k in _SWING_CACHE:
        return _SWING_CACHE[k]
    import gate2_edge_harness as G
    datr = daily_atr_series(df)
    # real time-gaps: a bar preceded by a break > threshold (maintenance ~60m, weekend,
    # or RTH overnight) is where an overnight PRICE gap can occur. Continuous 1m bars
    # (24h data) have ~1m spacing → no gap flagged except the daily maintenance break.
    GAP_MIN = 15.0
    deltas = df.index.to_series().diff().dt.total_seconds().to_numpy() / 60.0
    is_gap_full = deltas > GAP_MIN          # True where a real time-break precedes the bar
    is_gap_full[0] = False
    df = df.assign(_isgap=is_gap_full)
    day_hl, day_b5 = {}, {}
    for d, g in df.groupby(df.index.normalize()):
        key = pd.Timestamp(d).tz_localize(None).normalize()
        day_hl[key] = (g["high"].to_numpy(), g["low"].to_numpy(),
                       g["open"].to_numpy(), g["_isgap"].to_numpy())
        day_b5[key] = G.resample_5m(g.drop(columns="_isgap"))
    days = sorted(day_hl.keys())
    cache = dict(datr=datr, days=days, hl=day_hl, b5=day_b5)
    _SWING_CACHE[k] = cache
    return cache


def backtest_swing_tf(df, labels, cost, *, ema_period=20, chandelier_atr_mult=3.0,
                      max_hold_days=5, entry_days=None, gap_fill=True, return_open=False):
    """Cross-day swing TF backtest (vectorized holding). gap_fill=True models a
    stop that GAPS THROUGH: if the bar that triggers the stop OPENED beyond the
    stop, fill at the (worse) open price, not the stop — realistic for overnight
    gaps. gap_fill=False = optimistic (always fill at stop, like the RAITS engine)."""
    import gate2_edge_harness as G
    from raits.strategies.trend_follow import TrendFollowStrategy
    s = TrendFollowStrategy({**TrendFollowStrategy().config, "ema_period": ema_period,
                             "chandelier_atr_mult": chandelier_atr_mult})
    allowed = set(s.config["allowed_regimes"])
    c = _swing_cache(df)
    datr, days, hl, b5 = c["datr"], c["days"], c["hl"], c["b5"]
    mult = chandelier_atr_mult
    trades = []
    pos = None

    for day in days:
        if pos is not None:
            hold = (day - pos["entry_day"]).days
            if hold >= max_hold_days:
                op = float(hl[day][2][0])
                pts = (op - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - op)
                trades.append(dict(day=pos["entry_day"].date(), exit_day=day.date(),
                                   regime=pos["regime"], direction=pos["dir"],
                                   entry=round(pos["entry"], 2), exit=round(op, 2),
                                   points=round(pts, 2),
                                   pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                                   hold_days=hold, reason="MAX_HOLD"))
                pos = None
            else:
                high, low, opn, isg = hl[day]
                da = float(datr.asof(day)) if len(datr) else np.nan
                if not np.isnan(da) and len(high):
                    if pos["dir"] == "LONG":
                        # stop IN FORCE at each bar's open = ratchet from extreme through PRIOR bar
                        run_full = np.maximum.accumulate(np.maximum(high, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.maximum.accumulate(np.maximum(run_prev - mult * da, pos["stop"]))
                        hit = np.where(low <= stop_prev)[0]
                    else:
                        run_full = np.minimum.accumulate(np.minimum(low, pos["extreme"]))
                        run_prev = np.concatenate(([pos["extreme"]], run_full[:-1]))
                        stop_prev = np.minimum.accumulate(np.minimum(run_prev + mult * da, pos["stop"]))
                        hit = np.where(high >= stop_prev)[0]
                    if len(hit):
                        i = hit[0]; stp = float(stop_prev[i])
                        # gap-through only when a REAL time-break precedes the hit bar
                        # (maintenance break / weekend / RTH overnight) AND it opened past stop
                        gapped = gap_fill and bool(isg[i]) and (
                            (pos["dir"] == "LONG"  and float(opn[i]) < stp) or
                            (pos["dir"] == "SHORT" and float(opn[i]) > stp))
                        if gapped:
                            ex = float(opn[i]); reason = "GAP"
                        else:
                            ex = stp; reason = "CHANDELIER"
                        pts = (ex - pos["entry"]) if pos["dir"] == "LONG" else (pos["entry"] - ex)
                        trades.append(dict(day=pos["entry_day"].date(), exit_day=day.date(),
                                           regime=pos["regime"], direction=pos["dir"],
                                           entry=round(pos["entry"], 2), exit=round(ex, 2),
                                           points=round(pts, 2),
                                           pnl=round(pts * cost.point_value - cost.round_turn_cost(), 2),
                                           hold_days=hold, reason=reason))
                        pos = None
                    else:
                        # carry ratcheted stop (based on ALL of today's highs) to next day
                        if pos["dir"] == "LONG":
                            pos["stop"] = float(np.maximum(pos["stop"], run_full[-1] - mult * da))
                        else:
                            pos["stop"] = float(np.minimum(pos["stop"], run_full[-1] + mult * da))
                        pos["extreme"] = float(run_full[-1])

        if pos is None:
            reg = labels.get(day)
            if reg in allowed and (entry_days is None or day in entry_days):
                bars5 = b5[day]; win = bars5.between_time("14:00", "15:55")
                idx = list(win.index)
                for n in range(1, len(idx)):
                    hist = bars5.loc[:idx[n]]
                    if len(hist) < max(ema_period, 14) + 1:
                        continue
                    ema = s.calculate_ema(hist, ema_period)
                    atr = G.atr14(hist)
                    avgv = float(win["volume"].iloc[max(0, n - 11):n - 1].mean())
                    if np.isnan(atr) or np.isnan(avgv):
                        continue
                    sig = s.generate_signal(win.loc[idx[n - 1]], win.loc[idx[n]], ema, atr, reg, avgv)
                    if sig:
                        pos = dict(dir=sig["direction"], entry=sig["entry_price"],
                                   entry_day=day, regime=reg,
                                   extreme=sig["entry_price"], stop=sig["initial_stop"])
                        break
    return (trades, pos) if return_open else trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--regime-csv", default=None)
    ap.add_argument("--point-value", type=float, default=5.0)
    ap.add_argument("--tick", type=float, default=0.25,
                    help="index points per tick (MES/MNQ 0.25, MYM 1.0, M2K/RTY 0.10)")
    ap.add_argument("--hmm-train-end", default="2019-06-30")
    ap.add_argument("--hmm-fit-end", default=None)
    ap.add_argument("--hmm-components", type=int, default=3)
    ap.add_argument("--ema-period", type=int, default=20)
    ap.add_argument("--chandelier-atr-mult", type=float, default=3.0)
    ap.add_argument("--max-hold-days", type=int, default=5)
    ap.add_argument("--no-gap-fill", action="store_true",
                    help="disable gap-through modeling (optimistic, fill always at stop)")
    ap.add_argument("--slippage-ticks", type=float, default=1.0,
                    help="slippage per side in ticks (default 1; raise to stress-test)")
    ap.add_argument("--dump-csv", default=None)
    a = ap.parse_args()

    import gate2_edge_harness as G
    df = G.load_parquet(a.parquet)
    daily = G.benchmark_daily(a.regime_csv) if a.regime_csv else G.daily_close_series(df)
    labels = G.label_regimes(daily, a.hmm_train_end, a.hmm_components, a.hmm_fit_end)
    cost = G.FuturesCost(point_value=a.point_value, tick=a.tick, slippage_ticks_per_side=a.slippage_ticks)

    trades = backtest_swing_tf(df, labels, cost, ema_period=a.ema_period,
                               chandelier_atr_mult=a.chandelier_atr_mult,
                               max_hold_days=a.max_hold_days, gap_fill=not a.no_gap_fill)

    # ── report ───────────────────────────────────────────────────────────────
    print(f"\n{'='*66}\nSWING TREND_FOLLOW (max_hold={a.max_hold_days}d) | {Path(a.parquet).name}\n{'='*66}")
    print(f"Regime: {'SPY '+a.regime_csv if a.regime_csv else 'instrument'} | "
          f"cost ${cost.round_turn_cost():.2f}/rt | ema {a.ema_period} mult {a.chandelier_atr_mult}")
    if not trades:
        print("No trades."); return
    t = pd.DataFrame(trades)
    pnl = t["pnl"].to_numpy()
    w = pnl[pnl > 0].sum(); l = -pnl[pnl < 0].sum()
    eq = np.cumsum(pnl); dd = float((np.maximum.accumulate(eq) - eq).max())
    ann = pnl.mean() * 252
    print(f"\nTrades {len(t)} | WR {(pnl>0).mean()*100:.0f}% | net ${pnl.sum():,.0f} | "
          f"PF {w/l if l>0 else float('inf'):.2f} | expectancy ${pnl.mean():.2f}")
    print(f"avg hold {t['hold_days'].mean():.1f}d | MaxDD ${dd:,.0f} | "
          f"Calmar {ann/dd if dd>0 else float('inf'):.2f}")
    print(f"exit reasons: {t['reason'].value_counts().to_dict()}")
    print("\nby regime:")
    for reg in ["Normal", "Stress"]:
        sub = t[t["regime"] == reg]["pnl"].to_numpy()
        if len(sub):
            w2 = sub[sub > 0].sum(); l2 = -sub[sub < 0].sum()
            print(f"  {reg:<7} {len(sub):>4} trades  net ${sub.sum():>8,.0f}  "
                  f"PF {w2/l2 if l2>0 else float('inf'):.2f}")
    if a.dump_csv:
        t.to_csv(a.dump_csv, index=False)
        print(f"\nWrote {a.dump_csv} ({len(t)} trades)")


if __name__ == "__main__":
    main()
