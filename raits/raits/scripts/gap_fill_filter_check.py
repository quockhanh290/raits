import sys, pickle, pandas as pd
sys.path.insert(0, r"d:\raits")
from datetime import time as dtime

with open(r"d:\raits\raits\data\cache\snapshots\results_scenario_g.pkl","rb") as f:
    results = pickle.load(f)
with open(r"d:\raits\raits\data\cache\window_debug_5min.pkl","rb") as f:
    data_5min = pickle.load(f)
for tk in data_5min:
    data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

prev_close_map = {}
for ticker in [tk for tk in data_5min if tk != "SPY"]:
    bars = data_5min[ticker].sort_index()
    bars["date"] = bars.index.normalize()
    dl = bars.groupby("date")["close"].last()
    ds = dl.index.tolist()
    for i in range(1, len(ds)):
        prev_close_map[(ticker, ds[i])] = float(dl.iloc[i-1])

rows = []
for w in results:
    yr = w.get("label","?")
    for t in w.get("trades",[]):
        d = vars(t).copy(); d["year"] = yr; rows.append(d)
df = pd.DataFrame(rows)
df["entry_time"] = pd.to_datetime(df["entry_time"])
tf_n = df[(df["strategy"]=="TREND_FOLLOW") & (df["hmm_state"]=="Normal")].copy()
tf_n["date"] = tf_n["entry_time"].dt.normalize()
normal_days = sorted(tf_n["date"].unique())

signals = []
for day in normal_days:
    for ticker in [tk for tk in data_5min if tk != "SPY"]:
        db = data_5min[ticker][data_5min[ticker].index.normalize()==day].sort_index()
        if len(db) < 8: continue
        pc = prev_close_map.get((ticker, day))
        if not pc or pc <= 0: continue
        fb = db[db.index.time >= dtime(9,30)]
        if fb.empty: continue
        sopen = float(fb.iloc[0]["open"])
        gp = (sopen - pc) / pc
        if not (-0.03 <= gp <= -0.015): continue   # gap DOWN 1.5-3%
        gap_size = sopen - pc
        pre = db[db.index.time <= dtime(10,30)]
        if pre.empty: continue
        px = float(pre.iloc[-1]["close"])
        ret = (sopen - px) / gap_size if gap_size != 0 else 0
        if not (0.50 <= ret <= 0.85): continue       # 50-85% retraced
        signals.append({"year": str(day.year), "ticker": ticker,
                        "gap_pct": round(abs(gp)*100,2), "retrace": round(ret,2)})

sim = pd.DataFrame(signals)
print(f"LONG + gap 1.5-3% + retrace 50-85%: {len(sim)} trades")
print(sim.groupby("year").size().to_string())
print(f"Avg gap: {sim['gap_pct'].mean():.2f}%  Avg retrace: {sim['retrace'].mean():.2f}")
print(sim.groupby("ticker").size().sort_values(ascending=False).head(10).to_string())
