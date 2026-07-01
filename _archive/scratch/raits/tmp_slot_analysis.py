import sys, pickle
sys.path.insert(0, r'd:\raits'); sys.path.insert(0, r'd:\raits\raits')
import pandas as pd, numpy as np

with open(r'data/cache/snapshots/results_20260624_075432.pkl','rb') as f: d6 = pickle.load(f)
with open(r'data/cache/snapshots/results_20260623_175340.pkl','rb') as f: d5 = pickle.load(f)

trades = []
for data, yrs in [(d6,[2017,2018,2019,2020,2021,2022]),(d5,[2023,2024])]:
    for w in data:
        for t in w['trades']:
            if t.exit_time is None or t.entry_time.year not in yrs: continue
            trades.append({
                'year': t.entry_time.year, 'strategy': t.strategy, 'ticker': t.ticker,
                'entry_time': pd.Timestamp(t.entry_time), 'exit_time': pd.Timestamp(t.exit_time),
                'net_pnl': t.net_pnl,
            })

df = pd.DataFrame(trades).drop_duplicates(subset=['strategy','ticker','entry_time'])
MAX_TOTAL = 8

tf_rows = df[df.strategy == 'TREND_FOLLOW'].sort_values('entry_time')
non_tf  = df[df.strategy != 'TREND_FOLLOW']

total_open_at_tf = []
fade_open_at_tf  = []

for _, tf in tf_rows.iterrows():
    et = tf['entry_time']
    open_now = non_tf[(non_tf.entry_time < et) & (non_tf.exit_time > et)]
    total_open_at_tf.append(len(open_now))
    fade_open_at_tf.append((open_now.strategy == 'FADE').sum())

arr   = np.array(total_open_at_tf)
arr_f = np.array(fade_open_at_tf)
blocked = (arr >= MAX_TOTAL).sum()

print('=== Slot competition at TF entry ===')
print('TF entries: %d  |  Blocked by MAX_TOTAL=8: %d (%.1f%%)' % (len(arr), blocked, blocked/len(arr)*100))
print()
print('Other open positions when TF enters:')
for v in sorted(set(arr)):
    cnt = (arr == v).sum()
    bar = '#' * (cnt // 5)
    print('  %d other open: %3d  %s' % (v, cnt, bar))
print()
print('FADE positions open when TF enters:')
for v in sorted(set(arr_f)):
    cnt = (arr_f == v).sum()
    bar = '#' * (cnt // 5)
    print('  %d FADE open: %3d  %s' % (v, cnt, bar))

tf_pnl = df[df.strategy=='TREND_FOLLOW']['net_pnl']
print()
print('=== TF sizing context ===')
avg_net = tf_pnl.mean()
trades_yr = len(tf_pnl) / 8.0
ann_pnl = tf_pnl.sum() / 8.0
ann_ret = ann_pnl / 50000 * 100
print('TF avg net/trade: $%.2f' % avg_net)
print('TF trades/year (8yr avg): %.1f' % trades_yr)
print('TF annualized P&L: $%.0f/yr = %.2f%% on $50k' % (ann_pnl, ann_ret))
print()

# Total system return
total_pnl_8yr = df['net_pnl'].sum()
print('=== System-level return ===')
print('Total P&L 8yr: $%.0f' % total_pnl_8yr)
print('Annualized: $%.0f/yr = %.2f%% on $50k' % (total_pnl_8yr/8, total_pnl_8yr/8/50000*100))
print('Total return 8yr: %.1f%%' % (total_pnl_8yr/50000*100))
print()

# If FADE removed - slot availability for TF
print('=== If FADE removed: slot freed for TF ===')
non_fade_non_tf = df[~df.strategy.isin(['TREND_FOLLOW','FADE'])]
freed_arr = []
for _, tf in tf_rows.iterrows():
    et = tf['entry_time']
    open_now = non_fade_non_tf[(non_fade_non_tf.entry_time < et) & (non_fade_non_tf.exit_time > et)]
    freed_arr.append(len(open_now))
freed_arr = np.array(freed_arr)
newly_freed = ((arr >= MAX_TOTAL) & (freed_arr < MAX_TOTAL)).sum()
print('TF entries currently blocked, unblocked if FADE removed: %d' % newly_freed)
print()

# Risk sizing: what does 1% risk actually deploy?
print('=== Position sizing impact ===')
print('Account: $50,000')
print('Risk per trade: 1% = $500, Kelly 0.5 -> effective $250 max loss')
print('Max position: 20% = $10,000')
print()
print('To reach 15%% annual return on $50k = $7,500/yr:')
per_yr_needed = 7500
trades_needed = per_yr_needed / avg_net if avg_net > 0 else 9999
print('  Need %.0f TF-equivalent trades/yr at current avg $%.2f/trade' % (trades_needed, avg_net))
print('  Current TF: %.0f trades/yr -> shortfall %.0fx' % (trades_yr, trades_needed/trades_yr))
print()
print('OR increase risk/sizing:')
scale = 7500 / ann_pnl if ann_pnl > 0 else 9999
print('  Need %.1fx current sizing to hit $7,500/yr TF alone' % scale)
all_good_pnl = df[df.strategy.isin(['TREND_FOLLOW','ORB','PE_SHORT','STRESS_ORB'])]['net_pnl'].sum() / 8
print('  Core 4 strategies annual (TF+ORB+PE_SHORT+STRESS_ORB): $%.0f = %.1f%% on $50k' % (all_good_pnl, all_good_pnl/50000*100))
scale2 = 7500 / all_good_pnl if all_good_pnl > 0 else 9999
print('  Need %.1fx sizing on core-4 to hit $7,500/yr' % scale2)
