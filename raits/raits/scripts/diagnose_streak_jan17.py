"""
Simulate the consecutive-loss streak through ALL trades (with carry-over across sessions)
to find the streak at END of Jan 17 in ORIG vs REFAC.

Uses:
  - ORIG: cached full-IS trades (verify_orig_trades_IS.pkl)
  - REFAC: cached Jan-25 trades (verify_refac_jan25_trades.pkl)
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

ORIG_CACHE  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")
REFAC_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_refac_jan25_trades.pkl")

JAN17 = pd.Timestamp("2019-01-17").date()
JAN18 = pd.Timestamp("2019-01-18").date()
CB_LIMIT = 5


def simulate_streak(trades, label, show_from=pd.Timestamp("2019-01-14")):
    """
    Replay all trades in exit-time order, carrying the streak across sessions.
    Print the streak state for each trade from show_from onward.
    Return streak value at end of Jan 17.
    """
    closed = [t for t in trades if t.exit_time and t.net_pnl is not None]
    closed.sort(key=lambda t: t.exit_time)

    streak = 0
    streak_eod_jan17 = None

    print(f"\n[{label}] Consecutive-loss streak replay from {show_from.date()}:")
    print(f"  {'exit_time':<25} {'ticker':6} {'strategy':12} {'pnl':>9}  streak  CB_fires")
    print("  " + "-"*75)

    for t in closed:
        exit_dt = pd.Timestamp(t.exit_time)
        pnl = t.net_pnl

        if pnl < 0:
            streak += 1
        else:
            streak = 0

        cb = "*CB*" if streak >= CB_LIMIT else ""

        if exit_dt >= show_from:
            print(f"  {str(exit_dt):<25} {t.ticker:6} {t.strategy:12} {pnl:>9.2f}  {streak:>6}  {cb}")

        if exit_dt.date() == JAN17:
            streak_eod_jan17 = streak

    return streak_eod_jan17


def main():
    print("Loading ORIG trades...")
    with open(ORIG_CACHE, "rb") as f:
        orig_trades = pickle.load(f)
    print(f"  {len(orig_trades)} total trades")

    print("\nLoading REFAC trades...")
    with open(REFAC_CACHE, "rb") as f:
        refac_trades = pickle.load(f)
    print(f"  {len(refac_trades)} total trades")

    streak_orig  = simulate_streak(orig_trades,  "ORIG")
    streak_refac = simulate_streak(refac_trades, "REFAC")

    print("\n" + "="*50)
    print(f"STREAK AT END OF JAN 17:")
    print(f"  ORIG  streak = {streak_orig}")
    print(f"  REFAC streak = {streak_refac}")
    print()
    if streak_orig is not None and streak_refac is not None:
        diff = streak_refac - streak_orig
        print(f"  Difference: REFAC - ORIG = {diff:+d}")
        if streak_refac >= CB_LIMIT - 1 and streak_orig < CB_LIMIT - 1:
            print(f"  -> REFAC enters Jan 18 with streak={streak_refac}")
            print(f"     MMM STOP_HIT at 09:30 pushes it to {streak_refac+1} -> CB fires")
            print(f"     ORIG enters Jan 18 with streak={streak_orig}")
            print(f"     MMM STOP_HIT at 09:30 pushes it to {streak_orig+1} -> no CB")
            print(f"  ROOT CAUSE CONFIRMED via consecutive-loss carry-over")


if __name__ == "__main__":
    main()