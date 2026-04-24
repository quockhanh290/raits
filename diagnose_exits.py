"""
diagnose_exits.py
Analyze exit reasons and P&L distribution from WFO report.
"""
import json
from collections import defaultdict

with open('configs/wfo_report.json') as f:
    r = json.load(f)

m = r.get('stitched_metrics', {})

print("=== Key Metrics ===")
print(f"Avg win:  ${m.get('avg_win', 0):.2f}")
print(f"Avg loss: ${m.get('avg_loss', 0):.2f}")
print(f"Win/Loss ratio: {m.get('avg_win', 0) / max(m.get('avg_loss', 1), 0.01):.2f}x  (target: 2.0x for 2R)")
print(f"Win rate: {m.get('win_rate', 0):.1%}  (break-even at ~36% for 2R)")
print()

# Break-even analysis
win_rate = m.get('win_rate', 0)
avg_win  = m.get('avg_win', 0)
avg_loss = m.get('avg_loss', 0)
cost_per = m.get('total_costs', 0) / max(m.get('total_trades', 1), 1)

expected_per_trade = (win_rate * avg_win) - ((1 - win_rate) * avg_loss) - cost_per
print(f"=== Break-even Analysis ===")
print(f"Expected P&L per trade: ${expected_per_trade:.2f}")
print(f"  (win_rate × avg_win) - (loss_rate × avg_loss) - cost")
print(f"  ({win_rate:.1%} × ${avg_win:.2f}) - ({1-win_rate:.1%} × ${avg_loss:.2f}) - ${cost_per:.2f}")
print()

# What win rate is needed to break even?
# win_rate × avg_win = (1 - win_rate) × avg_loss + cost_per
# win_rate × (avg_win + avg_loss) = avg_loss + cost_per
be_win_rate = (avg_loss + cost_per) / (avg_win + avg_loss)
print(f"Break-even win rate needed: {be_win_rate:.1%}")
print(f"Current win rate:           {win_rate:.1%}")
print(f"Gap: {be_win_rate - win_rate:.1%} below break-even")
print()

# What avg_win is needed at current win rate?
# win_rate × avg_win = (1 - win_rate) × avg_loss + cost_per
needed_avg_win = ((1 - win_rate) * avg_loss + cost_per) / win_rate
print(f"=== What Needs to Change ===")
print(f"Current avg_win: ${avg_win:.2f}")
print(f"Needed avg_win at {win_rate:.1%} win rate: ${needed_avg_win:.2f}")
print(f"That's {needed_avg_win/avg_loss:.1f}R (current stop distance)")
print()
print(f"Current avg_loss: ${avg_loss:.2f}")
print(f"Needed avg_loss at {win_rate:.1%} win rate: ${avg_win * win_rate / (1 - win_rate) - cost_per:.2f}")
print()
print("=== Window Summary ===")
for i, w in enumerate(r.get('windows', [])):
    print(f"Window {i+1} ({w.get('test_start')} → {w.get('test_end')})")
    print(f"  OOS win rate: {w.get('oos_win_rate', 0):.1%}  trades: {w.get('oos_total_trades', 0)}")
    print(f"  Train Calmar: {w.get('train_calmar', 0):.2f}  OOS Calmar: {w.get('oos_calmar', 0):.2f}")
    print(f"  Best params: ORB={w.get('best_orb_range')} BB={w.get('best_bb_std')} EMA={w.get('best_ema_period')}")
