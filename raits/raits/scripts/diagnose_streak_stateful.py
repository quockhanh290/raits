"""
Stateful streak simulation that properly tracks BreakerState (ACTIVE/HALTED).
When _state == HALTED, record_trade_result returns early without modifying _consecutive_losses.
reset_for_new_session() sets _state = ACTIVE but preserves _consecutive_losses.

This corrects the earlier bug where wins after a CB firing would incorrectly reset the streak.

Processes trades sorted by (exit_time, entry_time) — same order as engine.
"""
import sys, os, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
import pandas as pd

ORIG_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "cache", "verify_orig_trades_IS.pkl")
CB_LIMIT = 5
JAN18 = pd.Timestamp("2019-01-18").date()


def simulate_stateful(trades, label):
    """
    Properly model the BreakerState machine:
      - ACTIVE:  record_trade_result updates _consecutive_losses
      - HALTED:  record_trade_result returns early (no modification)
      - reset_for_new_session: _state -> ACTIVE, _consecutive_losses preserved
    Also prints every CB firing event.
    """
    closed = [t for t in trades if t.exit_time and t.net_pnl is not None]
    # Sort by (exit_time, entry_time) - same priority as engine loop ordering
    closed.sort(key=lambda t: (t.exit_time, t.entry_time))

    state = "ACTIVE"          # BreakerState
    consecutive = 0           # _consecutive_losses
    current_day = None

    print(f"\n[{label}] Stateful streak simulation:")
    print(f"  {'exit_time':<25} {'ticker':6} {'strategy':12} {'pnl':>9}  consec  state    CB_fires")
    print("  " + "-"*85)

    show_from = pd.Timestamp("2019-01-01")
    show_to   = pd.Timestamp("2019-01-25")

    for t in closed:
        exit_dt  = pd.Timestamp(t.exit_time)
        trade_day = exit_dt.date()
        pnl = t.net_pnl

        # reset_for_new_session at start of each new day
        if trade_day != current_day:
            # Every new day resets _state=ACTIVE, preserves consecutive_losses
            if state == "HALTED":
                state = "ACTIVE"
                # consecutive_losses preserved
            current_day = trade_day

        # record_trade_result logic
        cb_fired = ""
        if state == "HALTED":
            # Returns _already_halted() immediately — NO modification
            pass
        else:
            # state == ACTIVE
            if pnl > 0:
                consecutive = 0
            else:
                consecutive += 1
                if consecutive >= CB_LIMIT:
                    state = "HALTED"
                    cb_fired = "*CB*"

        in_window = (show_from <= exit_dt < show_to)
        if in_window or cb_fired:
            marker = "  " if not cb_fired else ">>"
            print(f"{marker}  {str(exit_dt):<25} {t.ticker:6} {t.strategy:12} {pnl:>9.2f}  {consecutive:>6}  {state:<8} {cb_fired}")

    return consecutive, state


def main():
    print("Loading ORIG trades...")
    with open(ORIG_CACHE, "rb") as f:
        orig_trades = pickle.load(f)
    print(f"  {len(orig_trades)} total trades")

    consec, state = simulate_stateful(orig_trades, "ORIG")
    print(f"\nFinal: consecutive_losses={consec}  state={state}")

    # Now specifically show what streak ORIG has at each Jan 18 bar
    # (i.e., at the start of Jan 18, after Jan 17's reset_for_new_session)
    print()
    print("Hypothesis: check consecutive_losses entering Jan 18 in stateful simulation")
    closed = [t for t in orig_trades if t.exit_time and t.net_pnl is not None]
    closed.sort(key=lambda t: (t.exit_time, t.entry_time))

    state = "ACTIVE"
    consecutive = 0
    current_day = None
    consec_at_jan18_start = None

    for t in closed:
        exit_dt = pd.Timestamp(t.exit_time)
        trade_day = exit_dt.date()
        pnl = t.net_pnl

        if trade_day != current_day:
            if state == "HALTED":
                state = "ACTIVE"
            current_day = trade_day
            if trade_day == JAN18:
                consec_at_jan18_start = consecutive
                print(f"  Jan 18 starts: consecutive_losses={consec_at_jan18_start}  state={state}")

        if state == "HALTED":
            pass
        else:
            if pnl > 0:
                consecutive = 0
            else:
                consecutive += 1
                if consecutive >= CB_LIMIT:
                    state = "HALTED"

    if consec_at_jan18_start is not None:
        print(f"\n  -> After MMM (-230.37): would be {consec_at_jan18_start + 1}")
        if consec_at_jan18_start + 1 >= CB_LIMIT:
            print("  -> CB fires at 09:30 Jan 18 -> bar loop breaks at 09:35")
            print("  -> CVX cannot enter at 14:00 in ORIG (but it does!)")
        else:
            print("  -> CB does NOT fire -> ORIG can reach 14:00 -> CVX enters")
            print("  -> ROOT CAUSE CONFIRMED: stateful simulation shows different streak than naive sim")
    else:
        print("  (no trades on Jan 18)")


if __name__ == "__main__":
    main()