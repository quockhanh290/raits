import pickle, sys
sys.path.insert(0,'..')
with open('data/cache/snapshots/results_20260621_063557.pkl','rb') as f: r=pickle.load(f)
strats={}
for w in r:
    for t in w.get('trades',[]):
        strats[t.strategy]=strats.get(t.strategy,0)+1
print("Strategies in snapshot:")
for s,n in sorted(strats.items()): print(f"  {s}: {n}t")
