"""
Compare which trades close between Jan 3-14 2019 in ORIG vs REFAC pickles,
and the streak each engine accumulates in that window.
Goal: find the 1-trade difference that makes ORIG consec=2 vs REFAC consec=3 entering XOM Jan 15.
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

ORIG_CACHE  = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")
REFAC_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_refac_jan25_trades.pkl")

WIN_START = pd.Timestamp("2019-01-01")
WIN_END   = pd.Timestamp("2019-01-15")  # exclusive
CB_LIMIT  = 5


def show_trades_in_window(trades, label):
    closed = [t for t in trades if t.exit_time and t.net_pnl is not None]
    closed.sort(key=lambda t: (t.exit_time, t.entry_time))

    # Find streak entering Jan 3 window (after SBUX CB reset on Nov 2, wins on Jan 3 reset to 0)
    # We need the streak JUST BEFORE Jan 3 by running from the start
    state = "ACTIVE"
    consec = 0
    current_day = None

    window_trades = []
    for t in closed:
        exit_dt   = pd.Timestamp(t.exit_time)
        trade_day = exit_dt.date()
        pnl       = t.net_pnl

        if trade_day != current_day:
            if state == "HALTED":
                state = "ACTIVE"
            current_day = trade_day

        # only collect in window
        if WIN_START <= exit_dt < WIN_END:
            window_trades.append((exit_dt, t.ticker, t.strategy, pnl, t.entry_time))

        if state == "HALTED":
            pass
        else:
            if pnl > 0:
                consec = 0
            else:
                consec += 1
                if consec >= CB_LIMIT:
                    state = "HALTED"

        if exit_dt >= WIN_END:
            break

    print(f"\n[{label}] Trades closing Jan 1–14 2019 (sorted by exit_time, entry_time):")
    print(f"  {'exit_time':<25} {'entry_time':<25} {'ticker':6} {'strategy':15} {'pnl':>9}")
    print("  " + "-"*90)
    for exit_dt, ticker, strat, pnl, entry_dt in window_trades:
        print(f"  {str(exit_dt):<25} {str(entry_dt):<25} {ticker:6} {strat:15} {pnl:>9.2f}")

    # Now replay just the window trades with proper stateful CB
    print(f"\n  Streak replay through this window:")
    state2 = "ACTIVE"
    consec2 = 0
    current_day2 = None
    # First: get streak entering Jan 1 window
    for t in closed:
        exit_dt = pd.Timestamp(t.exit_time)
        pnl = t.net_pnl
        if exit_dt >= WIN_START:
            break
        trade_day = exit_dt.date()
        if trade_day != current_day2:
            if state2 == "HALTED":
                state2 = "ACTIVE"
            current_day2 = trade_day
        if state2 == "HALTED":
            pass
        else:
            if pnl > 0:
                consec2 = 0
            else:
                consec2 += 1
                if consec2 >= CB_LIMIT:
                    state2 = "HALTED"

    print(f"  Streak entering Jan 1 window: consec={consec2}  state={state2}")
    prev_day = None
    for exit_dt, ticker, strat, pnl, entry_dt in window_trades:
        trade_day = exit_dt.date()
        if trade_day != prev_day:
            if state2 == "HALTED":
                state2 = "ACTIVE"
            prev_day = trade_day
        if state2 == "HALTED":
            result = "(HALTED-skipped)"
        else:
            if pnl > 0:
                consec2 = 0
                result = f"WIN  -> consec={consec2}"
            else:
                consec2 += 1
                result = f"LOSS -> consec={consec2}"
                if consec2 >= CB_LIMIT:
                    state2 = "HALTED"
                    result += " *CB*"
        print(f"    {str(exit_dt):<25} {ticker:6} {strat:15} {pnl:>9.2f}   {result}")
    print(f"  Streak AFTER window (entering XOM Jan 15): consec={consec2}  state={state2}")
    return window_trades


def main():
    with open(ORIG_CACHE, "rb") as f:
        orig_trades = pickle.load(f)
    with open(REFAC_CACHE, "rb") as f:
        refac_trades = pickle.load(f)

    print(f"ORIG: {len(orig_trades)} total trades")
    print(f"REFAC: {len(refac_trades)} total trades")

    orig_window = show_trades_in_window(orig_trades, "ORIG")
    refac_window = show_trades_in_window(refac_trades, "REFAC")

    # diff
    orig_keys  = {(str(e), k, s) for e, k, s, p, _ in orig_window}
    refac_keys = {(str(e), k, s) for e, k, s, p, _ in refac_window}
    only_orig  = orig_keys  - refac_keys
    only_refac = refac_keys - orig_keys
    print(f"\nTrades ONLY in ORIG window: {only_orig if only_orig else 'none'}")
    print(f"Trades ONLY in REFAC window: {only_refac if only_refac else 'none'}")


if __name__ == "__main__":
    main()
