"""
vmr_rr_sim.py — Retroactive sim: test different min_rr_ratio thresholds for VWAP_MR.
Uses cached PKL results — no engine re-run needed.

Usage:
    cd D:\raits\raits
    python raits\scripts\vmr_rr_sim.py
"""
import pickle, os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

PKL = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "window_debug_results.pkl")

class _FU(pickle.Unpickler):
    def find_class(self, m, n):
        try: return super().find_class(m, n)
        except: return type(n, (), {})

with open(PKL, "rb") as f:
    results = _FU(f).load()

vmr_trades = []
for w in results:
    for t in w.get("trades", []):
        if getattr(t, "strategy", None) == "VWAP_MR":
            vmr_trades.append(t)

print(f"VWAP_MR trades loaded: {len(vmr_trades)}")
print()

def sim_rr(trades, min_rr):
    kept, filtered = [], []
    for t in trades:
        ep  = getattr(t, "entry_price", None) or getattr(t, "entry", None)
        stp = getattr(t, "stop", None)
        tgt = getattr(t, "target", None)
        if ep is None or stp is None or tgt is None:
            kept.append(t)
            continue
        stop_dist   = abs(ep - stp)
        reward_dist = abs(ep - tgt)
        rr = reward_dist / stop_dist if stop_dist > 0 else 0
        if rr >= min_rr:
            kept.append(t)
        else:
            filtered.append(t)
    return kept, filtered

def stats(trades):
    if not trades:
        return 0, 0.0, 0.0
    wins = sum(1 for t in trades if (t.net_pnl or 0) > 0)
    total = sum(t.net_pnl or 0 for t in trades)
    return len(trades), wins / len(trades) * 100, total

print(f"{'min_rr':>8} {'Trades':>7} {'WR':>7} {'Total P&L':>12} {'Filtered':>9}")
print("-" * 50)

orig_n, orig_wr, orig_pnl = stats(vmr_trades)
print(f"{'orig':>8} {orig_n:>7} {orig_wr:>6.1f}% {orig_pnl:>+12,.2f}")

for min_rr in [1.5, 1.75, 2.0, 2.5, 3.0]:
    kept, filtered = sim_rr(vmr_trades, min_rr)
    n, wr, pnl = stats(kept)
    fn, _, fpnl = stats(filtered)
    print(f"{min_rr:>8.2f} {n:>7} {wr:>6.1f}% {pnl:>+12,.2f}   filtered={fn}t ({fpnl:+.0f})")

# Also show exit breakdown for each threshold
print()
print("Exit breakdown by min_rr:")
for min_rr in [1.5, 2.0, 2.5]:
    kept, _ = sim_rr(vmr_trades, min_rr)
    reasons = {}
    for t in kept:
        r = getattr(t, "exit_reason", "?")
        pnl = t.net_pnl or 0
        if r not in reasons:
            reasons[r] = {"n": 0, "wins": 0, "pnl": 0}
        reasons[r]["n"] += 1
        reasons[r]["pnl"] += pnl
        if pnl > 0:
            reasons[r]["wins"] += 1
    print(f"\n  min_rr={min_rr}  ({len(kept)} trades):")
    for r, v in sorted(reasons.items()):
        wr = v["wins"] / v["n"] * 100 if v["n"] else 0
        print(f"    {r:16} {v['n']:3}t  WR={wr:.0f}%  P&L={v['pnl']:+.0f}")
