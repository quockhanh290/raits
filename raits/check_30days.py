"""
Trace 30 "extra" stress days: tại sao baseline engine ko có trades trên những ngày này?
Kiểm tra: ETF có valid OR range không? SPY có break OR low không?
"""
import pickle, sys, pandas as pd
sys.path.insert(0,'..')
from datetime import time as dtime

ONLY_NEW = [
    '2020-02-24','2020-04-29','2020-05-12','2020-09-08','2020-09-17',
    '2020-09-30','2020-10-15','2021-01-28','2021-01-29','2021-03-09',
    '2021-03-10','2021-12-01','2021-12-23','2022-02-10','2022-02-24',
    '2022-03-10','2022-03-14','2022-03-18','2022-03-28','2022-05-12',
    '2022-06-22','2022-06-27','2022-09-15','2022-09-19','2022-09-28',
    '2022-10-03','2022-10-13','2022-10-20','2022-11-08','2022-11-09',
]
target_days = [pd.Timestamp(d) for d in ONLY_NEW]

PKL_5MIN = r'd:\raits\raits\data\cache\window_debug_5min.pkl'
with open(PKL_5MIN,'rb') as f: data_5min = pickle.load(f)
for tk in data_5min: data_5min[tk].index = pd.to_datetime(data_5min[tk].index)

BASE_SNAP = 'data/cache/snapshots/results_20260620_163631.pkl'
with open(BASE_SNAP,'rb') as f: base = pickle.load(f)

# Trades từ baseline trên những ngày đó
base_trades = []
for w in base:
    for t in w.get('trades',[]):
        dt = pd.to_datetime(t.entry_time).normalize()
        if dt in set(target_days):
            base_trades.append(dict(day=dt, strategy=t.strategy, hmm=t.hmm_state, pnl=t.net_pnl))
base_df = pd.DataFrame(base_trades) if base_trades else pd.DataFrame()
print(f"Baseline trades on the 30 'extra' days: {len(base_df)}")
if len(base_df):
    print(base_df.groupby(['strategy','hmm']).size().to_string())

# Check SPY ETF behavior on those days
ETFs = ['SPY','QQQ','IWM']
OR_END = dtime(9, 35)
SIGNAL_END = dtime(10, 15)

def compute_atr(bars, period=14):
    if len(bars) < 2: return float(bars["close"].iloc[-1]) * 0.015
    hl=bars["high"]-bars["low"]
    hpc=(bars["high"]-bars["close"].shift(1)).abs()
    lpc=(bars["low"]-bars["close"].shift(1)).abs()
    return float(pd.concat([hl,hpc,lpc],axis=1).max(axis=1).tail(period).mean())

print(f"\n{'Day':<12} {'ETF OR valid?':<16} {'ETF broke OR?':<15} {'Baseline trades'}")
print('-'*65)
for day in target_days:
    etf_valid = []
    etf_broke = []
    for etf in ETFs:
        if etf not in data_5min: continue
        bars = data_5min[etf]
        day_bars = bars[bars.index.normalize() == day]
        if day_bars.empty: continue
        or_bars = day_bars[day_bars.index.time < OR_END]
        if or_bars.empty: continue
        or_high = float(or_bars["high"].max())
        or_low  = float(or_bars["low"].min())
        or_range = or_high - or_low
        atr = compute_atr(or_bars)
        valid = or_range > 0 and atr > 0 and 0.5*atr <= or_range <= 5*atr
        if valid: etf_valid.append(etf)
        # Check if any signal bar broke below OR low
        sig_bars = day_bars[(day_bars.index.time >= OR_END) & (day_bars.index.time <= SIGNAL_END)]
        broke = any(float(b["low"]) < or_low and float(b["close"]) < or_low
                    for _, b in sig_bars.iterrows())
        if valid and broke: etf_broke.append(etf)

    base_n = len(base_df[base_df['day']==day]) if len(base_df) else 0
    valid_str = ','.join(etf_valid) if etf_valid else 'NONE'
    broke_str = ','.join(etf_broke) if etf_broke else 'NONE'
    print(f"{str(day.date()):<12} {valid_str:<16} {broke_str:<15} {base_n}t")
