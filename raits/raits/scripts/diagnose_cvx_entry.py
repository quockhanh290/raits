"""
Verify CVX trade details in ORIG and ORIG's consecutive-loss streak at Jan 18.
Shows all CVX trades, all trades near Jan 18, and the streak entering each bar.
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

ORIG_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")

def main():
    with open(ORIG_CACHE, "rb") as f:
        trades = pickle.load(f)
    print(f"ORIG: {len(trades)} trades total")

    # --- All CVX trades ---
    cvx = [t for t in trades if t.ticker == "CVX"]
    print(f"\nAll CVX trades ({len(cvx)}):")
    print(f"  {'entry_time':<25} {'exit_time':<25} {'strategy':12} {'direction':8} {'pnl':>9}")
    for t in sorted(cvx, key=lambda t: t.entry_time):
        pnl = t.net_pnl if t.net_pnl is not None else float('nan')
        print(f"  {str(t.entry_time):<25} {str(t.exit_time):<25} {t.strategy:12} {t.direction:8} {pnl:>9.2f}")

    # --- All trades with entry_time on Jan 18 2019 ---
    jan18 = pd.Timestamp("2019-01-18").date()
    jan18_entries = [t for t in trades if pd.Timestamp(t.entry_time).date() == jan18]
    print(f"\nAll trades entering on Jan 18 2019 ({len(jan18_entries)}):")
    print(f"  {'entry_time':<25} {'ticker':6} {'strategy':12} {'direction':8} {'pnl':>9}")
    for t in sorted(jan18_entries, key=lambda t: t.entry_time):
        pnl = t.net_pnl if t.net_pnl is not None else float('nan')
        print(f"  {str(t.entry_time):<25} {t.ticker:6} {t.strategy:12} {t.direction:8} {pnl:>9.2f}")

    # --- All trades EXITING on Jan 18 ---
    jan18_exits = [t for t in trades if t.exit_time and pd.Timestamp(t.exit_time).date() == jan18]
    print(f"\nAll trades EXITING on Jan 18 2019 ({len(jan18_exits)}):")
    print(f"  {'exit_time':<25} {'ticker':6} {'strategy':12} {'pnl':>9}")
    for t in sorted(jan18_exits, key=lambda t: t.exit_time):
        pnl = t.net_pnl if t.net_pnl is not None else float('nan')
        print(f"  {str(t.exit_time):<25} {t.ticker:6} {t.strategy:12} {pnl:>9.2f}")

    # --- Streak replay for Jan 14-20 (show ALL trades to see full picture) ---
    closed = [t for t in trades if t.exit_time and t.net_pnl is not None]
    closed.sort(key=lambda t: (t.exit_time, t.entry_time))

    streak = 0
    show_from = pd.Timestamp("2019-01-14")
    show_to   = pd.Timestamp("2019-01-21")
    print(f"\nStreak replay (exit_time sorted), showing Jan 14-20:")
    print(f"  {'exit_time':<25} {'ticker':6} {'strategy':12} {'pnl':>9}  streak  CB")
    for t in closed:
        exit_dt = pd.Timestamp(t.exit_time)
        pnl = t.net_pnl
        if pnl > 0:
            streak = 0
        else:
            streak += 1
        cb = "*CB*" if streak >= 5 else ""
        if show_from <= exit_dt < show_to:
            print(f"  {str(exit_dt):<25} {t.ticker:6} {t.strategy:12} {pnl:>9.2f}  {streak:>6}  {cb}")

    print(f"\nFinal streak after Jan 14-20 window: {streak}")

if __name__ == "__main__":
    main()