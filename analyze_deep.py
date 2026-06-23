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
    'entry_price': t.entry_price,
    'exit_price':  t.exit_price,
    'shares':      t.shares,
    'net_pnl':     t.net_pnl,
    'exit_reason': t.exit_reason,
    'hmm_state':   getattr(t, 'hmm_state', '?'),
} for t in all_trades])

df['year']       = df['entry_time'].dt.year
df['hold_mins']  = (df['exit_time'] - df['entry_time']).dt.total_seconds() / 60
df['win']        = df['net_pnl'] > 0
df['is_swing']   = df['hold_mins'] > 400
df['date']       = df['entry_time'].dt.normalize()
total_pnl        = df.net_pnl.sum()

# ── 1. STOP-HIT by strategy ────────────────────────────────────────────────────
print('='*64)
print('1. STOP-HIT DEEP DIVE BY STRATEGY')
print('='*64)
stops = df[df['exit_reason'] == 'STOP_HIT']
print(f'  Total stops: {len(stops)}t  Total loss: ${stops.net_pnl.sum():+,.0f}  Avg: ${stops.net_pnl.mean():+.1f}')
print()
print(f'  {"Strategy":<15} {"Stops":>6} {"% of strat":>10} {"Avg loss$":>10} {"Total$":>9}')
print('  ' + '-'*55)
for strat, sg in df.groupby('strategy'):
    st = sg[sg['exit_reason'] == 'STOP_HIT']
    if len(st) == 0: continue
    pct = len(st) / len(sg) * 100
    print(f'  {strat:<15} {len(st):>6} {pct:>10.1f} {st["net_pnl"].mean():>+10.1f} {st["net_pnl"].sum():>+9.0f}')

print()
print('  STOP-HIT by year:')
print(f'  {"Year":<6} {"Stops":>6} {"Avg$":>8} {"Total$":>9}')
print('  ' + '-'*32)
for yr, g in stops.groupby('year'):
    print(f'  {yr:<6} {len(g):>6} {g["net_pnl"].mean():>+8.1f} {g["net_pnl"].sum():>+9.0f}')

print()
print('  WORST STOP tickers:')
tk_stops = stops.groupby('ticker')['net_pnl'].sum().sort_values().head(10)
for tk, v in tk_stops.items():
    cnt = len(stops[stops['ticker'] == tk])
    print(f'  {tk:<6} {cnt:>4}t  ${v:+,.0f}')

# ── 2. PE_SHORT intraday trade ─────────────────────────────────────────────────
print()
print('='*64)
print('2. PE_SHORT INTRADAY TRADE DETAIL')
print('='*64)
pe = df[df['strategy'] == 'PE_SHORT']
pe_intra = pe[~pe['is_swing']]
pe_swing = pe[pe['is_swing']]
print(f'  Total PE_SHORT: {len(pe)}t')
print(f'  Swing ({len(pe_swing)}t): ${pe_swing.net_pnl.sum():+,.0f}  WR={pe_swing["win"].mean()*100:.0f}%')
print(f'  Intraday ({len(pe_intra)}t): ${pe_intra.net_pnl.sum():+,.0f}')
if len(pe_intra):
    for _, row in pe_intra.iterrows():
        hold = row['hold_mins']
        print(f'  -> {row["ticker"]}  {row["entry_time"]}  hold={hold:.0f}min  ${row["net_pnl"]:+.0f}  exit={row["exit_reason"]}')

# ── 3. VWAP_MR by year and ticker ─────────────────────────────────────────────
print()
print('='*64)
print('3. VWAP_MR DEEP DIVE')
print('='*64)
vwap = df[df['strategy'] == 'VWAP_MR']
print(f'  Total: {len(vwap)}t  P&L: ${vwap.net_pnl.sum():+,.0f}  WR={vwap["win"].mean()*100:.1f}%')
print(f'  Slots consumed: {len(vwap)} (each trade uses a capital slot)')
print()
print('  By year:')
for yr, g in vwap.groupby('year'):
    print(f'  {yr}  {len(g):>4}t  WR={g["win"].mean()*100:.0f}%  ${g["net_pnl"].sum():+,.0f}')
print()
print('  By exit reason:')
for r, g in vwap.groupby('exit_reason'):
    print(f'  {r:<18} {len(g):>4}t  WR={g["win"].mean()*100:.0f}%  avg=${g["net_pnl"].mean():+.1f}  total=${g["net_pnl"].sum():+,.0f}')
print()
print('  Top 10 tickers by P&L:')
vt = vwap.groupby('ticker').agg(trades=('net_pnl','count'), pnl=('net_pnl','sum'), wr=('win','mean')).sort_values('pnl', ascending=False)
for tk, row in vt.head(10).iterrows():
    print(f'  {tk:<6} {row.trades:>4}t  WR={row.wr*100:.0f}%  ${row.pnl:+,.0f}')
print('  ...')
for tk, row in vt.tail(5).iterrows():
    print(f'  {tk:<6} {row.trades:>4}t  WR={row.wr*100:.0f}%  ${row.pnl:+,.0f}')

# ── 4. Single-trade days breakdown ─────────────────────────────────────────────
print()
print('='*64)
print('4. SINGLE-TRADE DAYS — WHAT FIRES?')
print('='*64)
tpd = df.groupby('date').size()
single_days = tpd[tpd == 1].index
st_df = df[df['date'].isin(single_days)]
print(f'  Single-trade days: {len(single_days)} ({len(single_days)/488*100:.1f}% of trading days)')
print(f'  Avg P&L: ${st_df.net_pnl.mean():+.1f}  Total: ${st_df.net_pnl.sum():+,.0f}')
print()
print('  By strategy:')
for strat, g in st_df.groupby('strategy'):
    print(f'  {strat:<15} {len(g):>4}t  WR={g["win"].mean()*100:.0f}%  avg=${g["net_pnl"].mean():+.1f}  total=${g["net_pnl"].sum():+,.0f}')

# ── 5. GAP_FILL + GF_SHORT deep dive ──────────────────────────────────────────
print()
print('='*64)
print('5. GAP_FILL + GF_SHORT DEEP DIVE')
print('='*64)
for strat in ['GAP_FILL', 'GF_SHORT']:
    g = df[df['strategy'] == strat]
    print(f'\n  {strat}: {len(g)}t  P&L=${g.net_pnl.sum():+,.0f}  WR={g["win"].mean()*100:.0f}%  avg=${g["net_pnl"].mean():+.1f}')
    print('  By year:')
    for yr, gy in g.groupby('year'):
        print(f'    {yr}  {len(gy):>4}t  WR={gy["win"].mean()*100:.0f}%  ${gy["net_pnl"].sum():+,.0f}')
    print('  By exit reason:')
    for r, gr in g.groupby('exit_reason'):
        print(f'    {r:<18} {len(gr):>4}t  avg=${gr["net_pnl"].mean():+.1f}  total=${gr["net_pnl"].sum():+,.0f}')

# ── 6. TREND_FOLLOW detailed ───────────────────────────────────────────────────
print()
print('='*64)
print('6. TREND_FOLLOW CONCENTRATION RISK')
print('='*64)
tf = df[df['strategy'] == 'TREND_FOLLOW']
print(f'  {len(tf)}t  P&L=${tf.net_pnl.sum():+,.0f}  WR={tf["win"].mean()*100:.1f}%  avg=${tf["net_pnl"].mean():+.1f}')
print()
print('  By year:')
for yr, g in tf.groupby('year'):
    print(f'  {yr}  {len(g):>4}t  WR={g["win"].mean()*100:.0f}%  avg=${g["net_pnl"].mean():+.1f}  ${g["net_pnl"].sum():+,.0f}')
print()
print('  By ticker (top 10):')
tft = tf.groupby('ticker').agg(trades=('net_pnl','count'), pnl=('net_pnl','sum'), wr=('win','mean')).sort_values('pnl', ascending=False)
for tk, row in tft.head(10).iterrows():
    print(f'  {tk:<6} {row.trades:>4}t  WR={row.wr*100:.0f}%  ${row.pnl:+,.0f}')
print('  Bottom 5:')
for tk, row in tft.tail(5).iterrows():
    print(f'  {tk:<6} {row.trades:>4}t  WR={row.wr*100:.0f}%  ${row.pnl:+,.0f}')
print()
print('  By regime:')
for r, g in tf.groupby('hmm_state'):
    print(f'  {r:<10} {len(g):>4}t  WR={g["win"].mean()*100:.0f}%  ${g["net_pnl"].sum():+,.0f}')
print()
print('  By exit reason:')
for r, g in tf.groupby('exit_reason'):
    print(f'  {r:<18} {len(g):>4}t  WR={g["win"].mean()*100:.0f}%  avg=${g["net_pnl"].mean():+.1f}  ${g["net_pnl"].sum():+,.0f}')

# ── 7. Sharpe / Sortino ────────────────────────────────────────────────────────
print()
print('='*64)
print('7. RISK-ADJUSTED METRICS')
print('='*64)
daily_pnl = df.groupby('date')['net_pnl'].sum().sort_index()
# Fill in zero for non-trading days (assume 252 trading days/yr)
mu  = daily_pnl.mean()
std = daily_pnl.std()
neg = daily_pnl[daily_pnl < 0]
semi_std = np.sqrt((neg**2).mean())

sharpe   = mu / std * np.sqrt(252)
sortino  = mu / semi_std * np.sqrt(252)
cagr     = total_pnl / 3 / 50000

print(f'  Avg P&L/day   : ${mu:+.2f}')
print(f'  Std/day       : ${std:.2f}')
print(f'  Semi-std/day  : ${semi_std:.2f} (downside only)')
print(f'  Sharpe (daily): {sharpe:.2f}')
print(f'  Sortino       : {sortino:.2f}')
print(f'  CAGR          : {cagr*100:.2f}%/yr')
print(f'  Calmar (CAGR/MaxDD): {cagr / abs(-1720/50000):.2f}')

# Per strategy Sharpe contribution
print()
print('  Sharpe contribution by strategy:')
for strat, sg in df.groupby('strategy'):
    sd = sg.groupby('date')['net_pnl'].sum()
    s_mu = sd.mean()
    s_std = sd.std() if len(sd) > 1 else 0
    s_sharpe = s_mu / s_std * np.sqrt(252) if s_std > 0 else 0
    print(f'  {strat:<15} days={len(sd):>4}  mu=${s_mu:+.1f}  sharpe={s_sharpe:.2f}')
