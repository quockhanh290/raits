"""
nonequity/swing_tf_powerhour.py — "như Rổ 4" power-hour transfer to global index
=================================================================================
Tests whether the VALIDATED Rổ-4 swing-TF engine (power-hour pullback-resume,
swing hold, chandelier daily-ATR) transfers to a foreign equity index — Nikkei
(NKD) first, DAX later.

KEY IDEA — by construction == Rổ 4, zero re-implementation:
backtest_swing_tf() selects the entry window with between_time("14:00","15:55")
and groups days with index.normalize(), BOTH relative to the index timezone.
Convert the NKD index to Asia/Tokyo and that exact window becomes the Tokyo
power hour (end of the Nikkei cash session), days cut on the Japan session, and
TSE holidays (empty window) auto-skip. We call the SAME validated function — no
copy, no re-tuning. Only the data's tz and the contract specs change.

Trade-off vs the rest of nonequity/: this harness is NOT self-contained — it
imports the validated engine from futures/ (which pulls raits.strategies). That
is deliberate: to test "exactly Rổ 4" we must run the exact Rổ-4 code, not a
look-alike. (The daily-bar harness swing_tf_daily.py stays self-contained.)

First pass is REGIME-AGNOSTIC (every day labelled 'Normal') to isolate the one
question: does the power-hour pullback signal fire & work on the Nikkei session?
If it shows life, the SPY-HMM regime layer (with correct JST→ET day mapping to
avoid lookahead) is the next step — that is the full "shared regime brain" of
Rổ 4, deferred on purpose.

Usage
-----
    python -m nonequity.swing_tf_powerhour \
        --parquet nonequity/data/NKD_continuous_1m_8y.parquet \
        --raw nonequity/data/NKD_continuous_1m_8y_raw.parquet \
        --instrument MNKD --tz Asia/Tokyo
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# nonequity self-contained bits
try:
    from global_index._core import load_parquet, FuturesCost as _FC
    from global_index import specs
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from global_index._core import load_parquet, FuturesCost as _FC
    from global_index import specs


class AllNormal:
    """Regime stub: every day 'Normal' so the validated engine's regime gate
    ({'Normal','Stress'}) never blocks — regime-agnostic first pass."""
    def get(self, _day, default=None):
        return "Normal"


def metrics(trades: list[dict]) -> dict:
    if not trades:
        return dict(n=0, net=0.0, pf=float("nan"), wr=float("nan"), maxdd=0.0, ret_dd=float("nan"))
    pnl = np.array([t["pnl"] for t in trades])
    eq = np.cumsum(pnl)
    peak = np.maximum.accumulate(eq)
    dd = float(np.max(peak - eq)) if len(eq) else 0.0
    wins = pnl[pnl > 0].sum(); losses = -pnl[pnl < 0].sum()
    return dict(n=len(trades), net=float(pnl.sum()),
                pf=(float(wins / losses) if losses > 0 else float("inf")),
                wr=float((pnl > 0).mean()), maxdd=dd,
                ret_dd=(float(pnl.sum() / dd) if dd > 0 else float("inf")))


def by_year(trades: list[dict]) -> dict:
    y = {}
    for t in trades:
        yr = pd.Timestamp(t["day"]).year
        y[yr] = y.get(yr, 0.0) + t["pnl"]
    return dict(sorted(y.items()))


def roll_dates_from_raw(raw_path: str, tz: str) -> set:
    raw = pd.read_parquet(raw_path)
    if "instrument_id" not in raw.columns:
        return set()
    iid = raw["instrument_id"]
    changed = iid.ne(iid.shift(1)); changed.iloc[0] = False
    idx = pd.to_datetime(raw.index, utc=True)[changed.to_numpy()]
    return {pd.Timestamp(d).tz_convert(tz).date() for d in idx}


def main() -> None:
    ap = argparse.ArgumentParser(description='"Như Rổ 4" power-hour transfer to global index.')
    ap.add_argument("--parquet", required=True)
    ap.add_argument("--raw", help="optional *_raw sidecar for roll diagnostic")
    ap.add_argument("--instrument", default="MNKD", choices=list(specs.SPECS.keys()))
    ap.add_argument("--tz", default="Asia/Tokyo",
                    help="session tz so the 14:00-15:55 window = local power hour "
                         "(Asia/Tokyo for Nikkei, Europe/Berlin for DAX)")
    ap.add_argument("--ema-period", type=int, default=30)
    ap.add_argument("--mult", type=float, default=2.5)
    ap.add_argument("--max-hold-days", type=int, default=5)
    ap.add_argument("--cost-mult", type=float, default=1.0,
                    help="multiply commission AND slippage (2.0 = Gate-4 cost stress)")
    ap.add_argument("--regime-csv", help="SPY daily CSV → SPY-HMM regime gate "
                    "(\"như Rổ 4\" full). Omit = regime-agnostic.")
    ap.add_argument("--regime-lag", type=int, default=1,
                    help="session-day lag for lookahead-safe SPY regime (Nikkei=1)")
    a = ap.parse_args()

    # import the EXACT validated engine (pulls raits.* via D:\raits on path)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # D:\raits root
    try:
        from futures._validated_core import backtest_swing_tf
    except ImportError as e:
        raise SystemExit(f"cannot import validated engine (need raits package on path): {e}")

    c = specs.SPECS[a.instrument]
    cost = _FC(point_value=c.point_value, tick=c.tick,
               commission_rt=c.commission_rt, slippage_ticks_per_side=1.0)
    if a.cost_mult != 1.0:
        cost = cost.stressed(a.cost_mult)

    df = load_parquet(a.parquet)            # ET tz-aware
    df.index = df.index.tz_convert(a.tz)    # → session tz: window becomes local power hour

    if a.regime_csv:
        from global_index.regime import load_spy_regime, RegimeLabels
        spy = load_spy_regime(a.regime_csv)
        labels = RegimeLabels(spy, lag_days=a.regime_lag)
        regime_tag = f"SPY-HMM regime (lag {a.regime_lag}d, lookahead-safe)"
    else:
        labels = AllNormal()
        regime_tag = "REGIME-AGNOSTIC"

    print(f'"Như Rổ 4" power-hour transfer | instrument {a.instrument} '
          f'(pv=${c.point_value}, tick={c.tick}, round_turn=${cost.round_turn_cost():.2f})')
    print(f"session tz {a.tz} → entry window 14:00-15:55 = local power hour | "
          f"ema={a.ema_period} mult={a.mult} hold={a.max_hold_days}d | "
          f"cost×{a.cost_mult:g}\n")
    print(f"data {df.index[0].date()} → {df.index[-1].date()}  ({len(df):,} bars) | {regime_tag}\n")

    trades = backtest_swing_tf(df, labels, cost, ema_period=a.ema_period,
                               chandelier_atr_mult=a.mult, max_hold_days=a.max_hold_days,
                               gap_fill=True)
    m = metrics(trades)
    pf = f"{m['pf']:.2f}" if np.isfinite(m['pf']) else "inf"
    rd = f"{m['ret_dd']:.2f}" if np.isfinite(m['ret_dd']) else "inf"
    print(f"{'n':>5}{'PF':>7}{'WR':>7}{'net$':>11}{'maxDD$':>10}{'net/DD':>8}")
    print("-" * 48)
    print(f"{m['n']:>5}{pf:>7}{m['wr']*100:>6.0f}%{m['net']:>11,.0f}{m['maxdd']:>10,.0f}{rd:>8}")

    yb = by_year(trades)
    if yb:
        print("\nyear-by-year net$ (QQQ rule: no single year may carry it):")
        print("  " + "  ".join(f"{y}:{v:,.0f}" for y, v in yb.items()))

    if a.raw:
        rolls = roll_dates_from_raw(a.raw, a.tz)
        if rolls:
            def touches(t):
                return any(pd.Timestamp(t["day"]).date() <= r <= pd.Timestamp(t["exit_day"]).date()
                           for r in rolls)
            touch = [t for t in trades if touches(t)]
            clean = [t for t in trades if not touches(t)]
            net_t = sum(t["pnl"] for t in touch)
            frac = len(touch) / len(trades) if trades else 0.0
            share = (net_t / m["net"] * 100) if m["net"] else float("nan")
            print(f"\nroll diagnostic ({len(rolls)} rolls): {frac*100:.1f}% of trades touch a roll, "
                  f"net@roll ${net_t:,.0f} = {share:.0f}% of total net")
            mc = metrics(clean)
            pfc = f"{mc['pf']:.2f}" if np.isfinite(mc['pf']) else "inf"
            rdc = f"{mc['ret_dd']:.2f}" if np.isfinite(mc['ret_dd']) else "inf"
            print("  EX-ROLL (roll-touching trades removed — the honest edge):")
            print(f"  {mc['n']:>5}{pfc:>7}{mc['wr']*100:>6.0f}%{mc['net']:>11,.0f}"
                  f"{mc['maxdd']:>10,.0f}{rdc:>8}")
            print("  read: ex-roll PF still >1.4 → edge real, roll is garnish. "
                  "Ex-roll PF collapses → much of the 'edge' is roll artifact.")

    print("\nRead: PF>1 + year-by-year not one-year-carried + roll not artifact → "
          "power-hour edge transfers to this index → add SPY-HMM regime layer next. "
          "PF<1 / one year carries / roll-driven → no transfer, close.")


if __name__ == "__main__":
    main()
