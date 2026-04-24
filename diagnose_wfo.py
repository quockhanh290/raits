import json

with open('configs/wfo_report.json') as f:
    r = json.load(f)

m = r.get('stitched_metrics', {})
trades = m.get('total_trades', 1)
costs  = m.get('total_costs', 0)

print("=== Stitched Metrics ===")
print(f"Trades:         {trades}")
print(f"Total costs:    ${costs:.2f}")
print(f"Cost per trade: ${costs/max(trades,1):.2f}")
print(f"Win rate:       {m.get('win_rate',0):.1%}")
print(f"Total return:   {m.get('total_return',0):.2%}")
print(f"Calmar:         {m.get('calmar_ratio',0):.2f}")
print(f"Sharpe:         {m.get('sharpe_ratio',0):.2f}")
print(f"Max DD:         {m.get('max_drawdown',0):.1%}")

print("\n=== Windows ===")
for i, w in enumerate(r.get('windows', [])):
    params = w.get('best_params', {})
    print(f"Window {i+1}:")
    print(f"  OOS Calmar:  {w.get('oos_calmar', 0):.2f}")
    print(f"  OOS trades:  {w.get('oos_trades', 0)}")
    print(f"  OOS win rate:{w.get('oos_win_rate', 0):.1%}")
    print(f"  Best params: {params}")
    print(f"  Train Calmar:{w.get('train_calmar', 0):.2f}")

print("\n=== Config ===")
print(f"Vault boundary: {r.get('vault_boundary')}")
print(f"Windows run:    {len(r.get('windows', []))}")
print(f"WFO passes:     {r.get('wfo_passes')}")
