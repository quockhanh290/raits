"""Find snapshot with specific total P&L."""
import pickle, glob, sys
sys.path.insert(0, '..')

files = sorted(glob.glob('data/cache/snapshots/results_*.pkl'))
print(f"{'File':<45} {'Total P&L':>12} {'Trades':>8} {'Strategies'}")
print('-'*90)
for f in files:
    try:
        with open(f,'rb') as fh: r = pickle.load(fh)
        total = 0; n = 0; strats = set()
        for w in r:
            for t in w.get('trades',[]):
                total += t.net_pnl or 0; n += 1; strats.add(t.strategy)
        strats_str = ','.join(sorted(strats))
        print(f"{f:<45} {total:>+12,.0f} {n:>8}  {strats_str}")
    except Exception as e:
        print(f"{f:<45}  ERROR: {e}")
