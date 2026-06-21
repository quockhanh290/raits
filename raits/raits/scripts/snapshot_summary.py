import pickle, os, glob

class _FU(pickle.Unpickler):
    def find_class(self, m, n):
        try: return super().find_class(m, n)
        except: return type(n, (), {})

SNAP_DIR = "data/cache/snapshots"
print(f"{'File':45} {'T':>4}  {'P&L':>9}  {'TF':>9}")
print("-"*70)
for f in sorted(glob.glob(f"{SNAP_DIR}/results_*.pkl")):
    with open(f, "rb") as fh:
        results = _FU(fh).load()
    trades = [t for w in results for t in w.get("trades", [])]
    total = sum(t.net_pnl for t in trades)
    tf = sum(t.net_pnl for t in trades if t.strategy == "TREND_FOLLOW")
    print(f"{os.path.basename(f):45} {len(trades):4}t  {total:+9,.0f}  {tf:+9,.0f}")
