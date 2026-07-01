import pickle, pandas as pd, numpy as np

SNAP = r'd:\raits\raits\data\cache\snapshots\results_20260623_070518.pkl'
with open(SNAP,'rb') as f: results = pickle.load(f)

all_trades = []
for w in results:
    all_trades.extend(w['trades'])

df = pd.DataFrame([{
    'strategy':    t.strategy,
    'ticker':      t.ticker,
    'direction':   t.direction,
    'entry_time':  pd.Timestamp(t.entry_time),
    'exit_time':   pd.Timestamp(t.exit_time),
    'net_pnl':     t.net_pnl,
    'exit_reason': t.exit_reason,
    'hmm_state':   getattr(t, 'hmm_state', '?'),
} for t in all_trades])

df['year']        = df['entry_time'].dt.year
df['dow']         = df['entry_time'].dt.dayofweek       # 0=Mon
df['dow_name']    = df['entry_time'].dt.day_name().str[:3]
df['entry_hour']  = df['entry_time'].dt.hour
df['entry_min']   = df['entry_time'].dt.minute
df['entry_hhmm']  = df['entry_hour'] * 60 + df['entry_min']
df['hold_mins']   = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60
df['win']         = df['net_pnl'] > 0
df['is_swing']    = df['hold_mins'] > 400
df['date']        = df['entry_time'].dt.normalize()
total_pnl         = df.net_pnl.sum()

# ── 1. Entry time buckets (ET) ─────────────────────────────────────────────────
print('='*62)
print('1. ENTRY TIME OF DAY (ET)')
print('='*62)

bins = [
    ('09:30-09:35',  9*60+30,  9*60+35),
    ('09:35-09:45',  9*60+35,  9*60+45),
    ('09:45-10:15',  9*60+45, 10*60+15),
    ('10:15-11:00', 10*60+15, 11*60+0),
    ('11:00-12:00', 11*60+0,  12*60+0),
    ('12:00-14:00', 12*60+0,  14*60+0),
    ('14:00-15:00', 14*60+0,  15*60+0),
    ('15:00-16:00', 15*60+0,  16*60+0),
]

print(f'  {"Window":<16} {"Trades":>6} {"WR%":>6} {"Avg$":>8} {"Total$":>9} {"Share%":>7}')
print('  ' + '-'*57)
for label, lo, hi in bins:
    g = df[(df['entry_hhmm'] >= lo) & (df['entry_hhmm'] < hi)]
    if len(g) == 0: continue
    wr  = g['win'].mean() * 100
    avg = g['net_pnl'].mean()
    tot = g['net_pnl'].sum()
    pct = tot / total_pnl * 100
    print(f'  {label:<16} {len(g):>6} {wr:>6.1f} {avg:>+8.1f} {tot:>+9.0f} {pct:>6.1f}%')

# ── 2. Entry time × strategy ──────────────────────────────────────────────────
print()
print('='*62)
print('2. ENTRY TIME × STRATEGY')
print('='*62)

strategies = df['strategy'].unique()
for strat in sorted(strategies):
    sg = df[df['strategy'] == strat]
    print(f'\n  {strat}  ({len(sg)}t  ${sg.net_pnl.sum():+,.0f})')
    print(f'  {"Window":<16} {"Trades":>6} {"WR%":>6} {"Avg$":>8} {"Total$":>9}')
    for label, lo, hi in bins:
        g = sg[(sg['entry_hhmm'] >= lo) & (sg['entry_hhmm'] < hi)]
        if len(g) == 0: continue
        wr  = g['win'].mean() * 100
        avg = g['net_pnl'].mean()
        tot = g['net_pnl'].sum()
        print(f'  {label:<16} {len(g):>6} {wr:>6.1f} {avg:>+8.1f} {tot:>+9.0f}')

# ── 3. Hold duration buckets ──────────────────────────────────────────────────
print()
print('='*62)
print('3. HOLD DURATION BUCKETS')
print('='*62)

dur_bins = [
    ('<15 min',    0,   15),
    ('15-30 min',  15,  30),
    ('30-60 min',  30,  60),
    ('1-2 hr',     60, 120),
    ('2-4 hr',    120, 240),
    ('4-7 hr',    240, 420),
    ('>7 hr (swing)', 420, 99999),
]

print(f'  {"Duration":<16} {"Trades":>6} {"WR%":>6} {"Avg$":>8} {"Total$":>9} {"Share%":>7}')
print('  ' + '-'*57)
for label, lo, hi in dur_bins:
    g = df[(df['hold_mins'] >= lo) & (df['hold_mins'] < hi)]
    if len(g) == 0: continue
    wr  = g['win'].mean() * 100
    avg = g['net_pnl'].mean()
    tot = g['net_pnl'].sum()
    pct = tot / total_pnl * 100
    print(f'  {label:<16} {len(g):>6} {wr:>6.1f} {avg:>+8.1f} {tot:>+9.0f} {pct:>6.1f}%')

# ── 4. Trades per day ─────────────────────────────────────────────────────────
print()
print('='*62)
print('4. TRADES PER DAY DISTRIBUTION')
print('='*62)

trades_per_day = df.groupby('date').size()
pnl_per_day    = df.groupby('date')['net_pnl'].sum()

print(f'  Trading days: {len(trades_per_day)}')
print(f'  Avg trades/day: {trades_per_day.mean():.1f}  |  median: {trades_per_day.median():.0f}')
print(f'  Max trades/day: {trades_per_day.max()}  |  min: {trades_per_day.min()}')
print()
print(f'  {"#Trades/day":<14} {"Days":>5} {"% of days":>9} {"Avg PnL$":>10}')
print('  ' + '-'*42)
for n in sorted(trades_per_day.unique()):
    days_with_n = trades_per_day[trades_per_day == n].index
    avg_pnl = pnl_per_day.loc[days_with_n].mean()
    days_count = len(days_with_n)
    pct = days_count / len(trades_per_day) * 100
    if days_count < 2 and n > 8: continue
    print(f'  {n:<14} {days_count:>5} {pct:>9.1f} {avg_pnl:>+10.1f}')

# ── 5. Day of week ────────────────────────────────────────────────────────────
print()
print('='*62)
print('5. DAY OF WEEK')
print('='*62)

print(f'  {"Day":<5} {"Trades":>6} {"WR%":>6} {"Avg$":>8} {"Total$":>9}')
print('  ' + '-'*38)
day_order = ['Mon','Tue','Wed','Thu','Fri']
for day_name in day_order:
    g = df[df['dow_name'] == day_name]
    if len(g) == 0: continue
    wr  = g['win'].mean() * 100
    avg = g['net_pnl'].mean()
    tot = g['net_pnl'].sum()
    print(f'  {day_name:<5} {len(g):>6} {wr:>6.1f} {avg:>+8.1f} {tot:>+9.0f}')

# ── 6. Win/loss by trade size bucket ──────────────────────────────────────────
print()
print('='*62)
print('6. P&L MAGNITUDE DISTRIBUTION (all trades)')
print('='*62)

pnl_bins = [
    ('< -$200',     -9999, -200),
    ('-$200 to -$100', -200, -100),
    ('-$100 to -$50',  -100, -50),
    ('-$50  to   $0',   -50,   0),
    ('  $0  to +$50',     0,  50),
    ('+$50  to +$100',   50, 100),
    ('+$100 to +$200',  100, 200),
    ('> +$200',         200, 9999),
]

print(f'  {"P&L bucket":<22} {"Count":>6} {"% of trades":>12} {"Sum$":>9}')
print('  ' + '-'*52)
for label, lo, hi in pnl_bins:
    g = df[(df['net_pnl'] >= lo) & (df['net_pnl'] < hi)]
    pct = len(g) / len(df) * 100
    print(f'  {label:<22} {len(g):>6} {pct:>12.1f} {g["net_pnl"].sum():>+9.0f}')

# ── 7. Strategy vs hold time (intraday vs swing) ──────────────────────────────
print()
print('='*62)
print('7. STRATEGY × HOLD TYPE')
print('='*62)

print(f'  {"Strategy":<15} {"Intra-t":>7} {"Intra-$":>9} {"Swing-t":>7} {"Swing-$":>9}')
print('  ' + '-'*52)
for strat in sorted(strategies):
    sg   = df[df['strategy'] == strat]
    intr = sg[~sg['is_swing']]
    swng = sg[sg['is_swing']]
    print(f'  {strat:<15} {len(intr):>7} {intr["net_pnl"].sum():>+9.0f} {len(swng):>7} {swng["net_pnl"].sum():>+9.0f}')
