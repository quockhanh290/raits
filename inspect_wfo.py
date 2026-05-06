import json

with open('configs/wfo_report.json') as f:
    r = json.load(f)

print('Per-window OOS results:')
print(f"{'Win':<4} {'Train':<25} {'Test':<25} {'Params':<20} {'Trades':<7} {'WinRt':<7} {'PF':<6} {'Calmar':<8} {'NetPnL':<10}")
for w in r['windows']:
    params = f"({w['best_orb_range']},{w['best_bb_std']},{w['best_ema_period']})"
    train = f"{w['train_start'][:10]} -> {w['train_end'][:10]}"
    test = f"{w['test_start'][:10]} -> {w['test_end'][:10]}"
    print(f"{w['window_idx']:<4} {train:<25} {test:<25} {params:<20} "
          f"{w['oos_total_trades']:<7} {w['oos_win_rate']:<7.1%} "
          f"{w['oos_profit_factor']:<6.2f} {w['oos_calmar']:<8.2f} "
          f"${w['oos_net_profit']:<9.2f}")

print()
print('Train vs OOS Calmar (degradation):')
for w in r['windows']:
    print(f"  Window {w['window_idx']}: train={w['train_calmar']:.2f}  "
          f"oos={w['oos_calmar']:.2f}  "
          f"degradation={w['train_calmar']-w['oos_calmar']:.2f}")
