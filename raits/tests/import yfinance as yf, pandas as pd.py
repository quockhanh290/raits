"""
HMM visual + statistical validation
Run: python hmm_validate.py
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import yfinance as yf

from raits.hmm import HMMEngine, HMM_STATES, CALM, NORMAL, STRESS

# ── Load data and fit ─────────────────────────────────────────────────────────
spy = yf.download('SPY', start='2018-01-01', end='2025-01-01',
                  auto_adjust=True, progress=False)['Close'].dropna().squeeze()

engine = HMMEngine(n_iter=200, n_init=10)
engine.fit(spy, save=False)

states = engine.predict_sequence(spy)
state_series = pd.Series(states, index=spy.index[len(spy)-len(states):])
spy_aligned  = spy.loc[state_series.index]

# ── Plot 1: Price chart with regime background ────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 9),
                          gridspec_kw={'height_ratios': [3, 1]})

ax = axes[0]
colors = {CALM: '#d4edda', NORMAL: '#fff3cd', STRESS: '#f8d7da'}
labels = {CALM: 'Calm', NORMAL: 'Normal', STRESS: 'Stress'}

# Shade regime backgrounds
prev_state = None
start_date  = None
for date, state in state_series.items():
    if state != prev_state:
        if prev_state is not None:
            ax.axvspan(start_date, date, color=colors[prev_state], alpha=0.4)
        start_date = date
        prev_state = state
ax.axvspan(start_date, state_series.index[-1],
           color=colors[prev_state], alpha=0.4)

ax.plot(spy_aligned.index, spy_aligned.values, 'k-', linewidth=0.8)
ax.set_ylabel('SPY price ($)')
ax.set_title('SPY with HMM regime overlay  (green=Calm  yellow=Normal  red=Stress)')

patches = [mpatches.Patch(color=colors[i], alpha=0.6, label=labels[i])
           for i in range(3)]
ax.legend(handles=patches, loc='upper left')

# Mark known events
events = {
    'Volmageddon\nFeb 2018':  '2018-02-05',
    'COVID\nMar 2020':        '2020-03-16',
    '2022\nBear':             '2022-06-16',
}
for label, date in events.items():
    if date in spy_aligned.index.strftime('%Y-%m-%d'):
        idx = spy_aligned.index[spy_aligned.index.strftime('%Y-%m-%d') == date]
        if len(idx):
            ax.axvline(idx[0], color='navy', linewidth=0.8, linestyle='--', alpha=0.5)
            ax.text(idx[0], ax.get_ylim()[1]*0.95, label,
                    fontsize=7, color='navy', ha='center', va='top')

# ── Plot 2: Regime state over time ────────────────────────────────────────────
ax2 = axes[1]
state_colors = [colors[s] for s in state_series]
ax2.bar(state_series.index, np.ones(len(state_series)),
        color=state_colors, width=1.5, alpha=0.8)
ax2.set_ylabel('Regime')
ax2.set_yticks([])
ax2.set_xlabel('Date')

plt.tight_layout()
plt.savefig('hmm_regimes.png', dpi=150, bbox_inches='tight')
print("Chart saved: hmm_regimes.png")

# ── Statistical validation ────────────────────────────────────────────────────
log_returns = np.log(spy_aligned / spy_aligned.shift(1)).dropna()
state_aligned = state_series.loc[log_returns.index]

print("\n" + "=" * 62)
print("REGIME STATISTICS  (this is how you verify correctness)")
print("=" * 62)
print(f"\n{'Metric':<28} {'Calm':>10} {'Normal':>10} {'Stress':>10}")
print("─" * 62)

stats = {}
for idx in [CALM, NORMAL, STRESS]:
    mask   = state_aligned == idx
    rets   = log_returns[mask]
    stats[idx] = {
        'days':      mask.sum(),
        'pct':       mask.mean(),
        'mean_ret':  rets.mean() * 252,          # annualised
        'vol':       rets.std() * np.sqrt(252),  # annualised
        'sharpe':    (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0,
        'max_dd_day': rets.min(),
        'worst_5':   rets.nsmallest(5).mean(),
    }

def row(label, key, fmt):
    vals = [stats[i][key] for i in [CALM, NORMAL, STRESS]]
    print(f"  {label:<26}" + "".join(f"{fmt.format(v):>10}" for v in vals))

row("Trading days",       'days',      '{:.0f}')
row("% of all days",      'pct',       '{:.1%}')
row("Ann. return",        'mean_ret',  '{:.1%}')
row("Ann. volatility",    'vol',       '{:.1%}')
row("Sharpe ratio",       'sharpe',    '{:.2f}')
row("Worst single day",   'max_dd_day','{:.2%}')
row("Avg worst 5 days",   'worst_5',   '{:.2%}')

print()
print("What to look for:")
print("  Volatility must increase:  Calm < Normal < Stress")
calm_vol   = stats[CALM]['vol']
normal_vol = stats[NORMAL]['vol']
stress_vol = stats[STRESS]['vol']
vol_ordered = calm_vol < normal_vol < stress_vol
print(f"  Calm={calm_vol:.1%}  Normal={normal_vol:.1%}  Stress={stress_vol:.1%}"
      f"  →  {'CORRECT' if vol_ordered else 'WRONG — model has a problem'}")

print()
print("  Stress worst days must be much worse than Calm worst days")
ratio = stats[STRESS]['worst_5'] / stats[CALM]['worst_5']
print(f"  Stress avg worst 5 / Calm avg worst 5 = {ratio:.1f}x"
      f"  →  {'CORRECT (expect 3x+)' if ratio <= -2 else 'CHECK THIS'}")

print()
print("  Transition matrix (regime persistence):")
trans = engine.model.transmat_
for i in range(3):
    stay = trans[i, i]
    print(f"  P({HMM_STATES[i]:6s} → {HMM_STATES[i]:6s}) = {stay:.1%}"
          f"  {'GOOD (sticky)' if stay > 0.85 else 'LOW (too jumpy)'}")

print("=" * 62)