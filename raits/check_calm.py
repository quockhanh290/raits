import sys, pickle
sys.path.insert(0, r'D:\raits')

with open(r'D:\raits\raits\data\cache\window_debug_results.pkl', 'rb') as f:
    results = pickle.load(f)

for r in results:
    if r['label'] not in ('2020','2021','2022'):
        continue
    orb = [t for t in r['trades'] if t.strategy == 'ORB']
    print(f"\n{'='*80}")
    print(f"  {r['label']} ORB — {len(orb)} trades")
    print(f"{'='*80}")
    print(f"  {'Date':<12} {'Ticker':<6} {'Dir':<5} {'Entry':>7} {'Stop':>7} {'Target':>7} {'Exit':>7} {'PnL':>8}  Reason")
    print(f"  {'-'*76}")
    for t in sorted(orb, key=lambda x: x.entry_time):
        print(f"  {str(t.entry_time)[:10]:<12} {t.ticker:<6} {t.direction:<5} "
              f"${t.entry_price:>6.2f} ${t.stop:>6.2f} ${t.target:>6.2f} "
              f"${t.exit_price:>6.2f} ${t.net_pnl:>+7.0f}  {t.exit_reason}")
