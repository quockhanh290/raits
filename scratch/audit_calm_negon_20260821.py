"""READ-ONLY independent audit of the Calm candidate on_neg_fade_mod001_010_x1555.
Reproduces every number quoted in the 2026-08-21 audit report. Writes nothing.
Run:  python scratch/audit_calm_negon_20260821.py
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path.cwd()))
from futures._validated_core import load_parquet, daily_atr_series
from futures.basket import BASKET, data_filename

P = "scratch/calm_neg_overnight_exit_sweep_mes_mnq_mym"
V, VR, V2 = ("on_neg_fade_mod001_010_x1555", "on_neg_fade_raw_x1555", "on_neg_fade_mod002_010_x1555")
WIN = {"is": "data/cache/futures/frozen_sim", "2025": "data/cache/futures/frozen_2025_sim",
       "2026": "data/cache/futures"}
COST = {"MES": 6.24, "MNQ": 3.24, "MYM": 3.24}     # commission 1.24 + 2 x 2 ticks x tick_value
rng = np.random.default_rng(20260821)

def load(tag, variant=V):
    d = pd.read_csv(f"{P}_{tag}.csv")
    for c in ("signal_time", "entry_time", "exit_time"):
        d[c] = pd.to_datetime(d[c], utc=True).dt.tz_convert("US/Eastern")
    return d[d.variant == variant].copy() if variant else d

def stat(g):
    p = g.pnl.astype(float); gw = p[p > 0].sum(); gl = -p[p < 0].sum()
    return len(g), float(p.sum()), (gw / gl if gl else math.inf)

def daybs(g, B=5000):
    daily = g.groupby("day")["pnl"].sum().values
    n = len(daily); obs = daily.sum()
    tot = daily[rng.integers(0, n, size=(B, n))].sum(axis=1)
    lo, hi = np.percentile(tot, [2.5, 97.5])
    cent = daily - daily.mean()
    null = cent[rng.integers(0, n, size=(B, n))].sum(axis=1)
    return n, obs, lo, hi, float((np.abs(null) >= abs(obs)).mean())

print("A1 headline reproduction from the saved trade logs")
for tag in WIN:
    n, pnl, pf = stat(load(tag)); print(f"   {tag:5s} n={n} net=${pnl:,.0f} pf={pf:.2f}")

print("\nA2 fill mechanics verified against the parquet bars")
for tag, dd in WIN.items():
    g = load(tag); Eb = Xb = Xc = oc = 0
    alt = 0.0
    for inst, sub in g.groupby("inst"):
        df = load_parquet(str(Path(dd) / data_filename(BASKET[inst]))); pv = BASKET[inst].point_value
        for _, r in sub.iterrows():
            eb, xb = df.loc[r.entry_time], df.loc[r.exit_time]
            Eb += abs(float(eb["open"]) - float(r.entry)) > 1e-9
            Xb += abs(float(xb["open"]) - float(r["exit"])) > 1e-9
            Xc += abs(float(xb["close"]) - float(r["exit"])) < 1e-9
            oc += abs(float(xb["open"]) - float(xb["close"])) > 1e-9
            alt += (float(xb["close"]) - float(r.entry)) * pv - COST[inst]
    print(f"   {tag:5s} entry!=open(entry bar):{Eb}/{len(g)}  exit!=open(exit bar):{Xb}/{len(g)}  "
          f"exit==close(exit bar):{Xc}/{len(g)} (bars with open!=close {oc}/{len(g)})  "
          f"net if CLOSE used=${alt:,.0f} vs ${g.pnl.sum():,.0f}")

print("\nA3 timestamps")
for tag in WIN:
    g = load(tag); et = g.entry_time.dt.strftime("%H:%M"); xt = g.exit_time.dt.strftime("%H:%M")
    print(f"   {tag:5s} signal==entry {int((g.signal_time==g.entry_time).sum())}/{len(g)}  "
          f"entry!=09:30 {int((et!='09:30').sum())}  exit!=15:55 {int((xt!='15:55').sum())}  "
          f"exit<=entry {int((g.exit_time<=g.entry_time).sum())}  "
          f"exit_date!=entry_date {int((g.exit_time.dt.date!=g.entry_time.dt.date).sum())}")

print("\nA4 entry-latency sensitivity (open of a later 1m bar)")
for tag, dd in WIN.items():
    g = load(tag); cache = {i: load_parquet(str(Path(dd)/data_filename(BASKET[i]))) for i in g.inst.unique()}
    out = []
    for lag in (1, 2, 5):
        t = sum((float(r["exit"]) - float(cache[r.inst].loc[r.entry_time+pd.Timedelta(minutes=lag), "open"]))
                * BASKET[r.inst].point_value - COST[r.inst] for _, r in g.iterrows())
        out.append(f"+{lag}m=${t:,.0f}({t-g.pnl.sum():+,.0f})")
    print(f"   {tag:5s} base=${g.pnl.sum():,.0f}  " + "  ".join(out))

print("\nA5 day-clustered bootstrap (5000 draws over trading days)")
for tag in WIN:
    for v in (V, VR):
        g = load(tag, v)
        if g.empty: continue
        n, obs, lo, hi, p = daybs(g)
        print(f"   {tag:5s} {v:<32} days={n:3d} net=${obs:8,.0f} CI95=[${lo:8,.0f},${hi:8,.0f}] p={p:.4f}")
o = pd.concat([load("2025"), load("2026")])
n, obs, lo, hi, p = daybs(o); print(f"   OOS pooled  {V:<32} days={n:3d} net=${obs:8,.0f} CI95=[${lo:8,.0f},${hi:8,.0f}] p={p:.4f}")
for inst, x in o.groupby("inst"):
    n, obs, lo, hi, p = daybs(x); print(f"      {inst} trades={len(x):3d} net=${obs:7,.0f} CI95=[${lo:7,.0f},${hi:7,.0f}] p={p:.4f}")

print("\nA6 overnight-return bucket stability (raw variant, shows what the band keeps/drops)")
for tag in WIN:
    r = load(tag, VR)
    b = pd.cut(r.overnight_ret.astype(float), [-9,-0.02,-0.01,-0.005,-0.002,-0.001,0.0],
               labels=["<-2%","-2..-1%","-1..-0.5%","-0.5..-0.2%","-0.2..-0.1%","-0.1..0%"])
    t = r.groupby(b, observed=False)["pnl"].agg(["count","sum"]); t["in_band"] = ["no","no","yes","yes","yes","no"]
    print(f"   -- {tag} --"); print(t.to_string(float_format=lambda x: f"{x:8.0f}"))

print("\nA7 symmetric trim: is the edge outlier-driven?")
for tag in WIN:
    s = load(tag).pnl.sort_values()
    print(f"   {tag:5s} n={len(s)} net=${s.sum():,.0f}  trim5/5=${s.iloc[5:-5].sum():,.0f}  "
          f"trim10/10=${s.iloc[10:-10].sum():,.0f}  median=${s.median():.2f}")

print("\nA8 same-day concurrency and the 1x-ATR admission proxy vs the 2.5% Calm cap ($1,250)")
for tag, dd in WIN.items():
    g = load(tag)
    print(f"   {tag:5s} days by concurrent instruments: {g.groupby('day')['inst'].nunique().value_counts().sort_index().to_dict()}")
    for inst, sub in g.groupby("inst"):
        atr = daily_atr_series(load_parquet(str(Path(dd)/data_filename(BASKET[inst]))))
        pv = BASKET[inst].point_value
        r = pd.Series([float(atr.asof(pd.Timestamp(t).tz_localize(None).normalize()))*pv for t in sub.entry_time])
        print(f"        {inst} risk$ med=${r.median():6.0f} max=${r.max():6.0f}  over $1,250: {int((r>1250).sum())}/{len(r)}")
