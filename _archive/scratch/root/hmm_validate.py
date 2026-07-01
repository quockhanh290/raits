"""
HMM visual + statistical validation
Run: python hmm_validate.py
"""

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import yfinance as yf

from raits.hmm import HMMEngine, HMM_STATES, CALM, NORMAL, STRESS

# ── Load data and fit ─────────────────────────────────────────────────────────
print("Downloading SPY (2018–2025)...")
spy = yf.download('SPY', start='2018-01-01', end='2025-01-01',
                  auto_adjust=True, progress=False)['Close'].dropna().squeeze()

print(f"Fitting HMM on {len(spy)} days (n_init=10, ~30–60 seconds)...")
engine = HMMEngine(n_iter=200, n_init=10)
engine.fit(spy, save=False)

states       = engine.predict_sequence(spy)
state_series = pd.Series(states, index=spy.index[len(spy) - len(states):])
spy_aligned  = spy.loc[state_series.index]

# ── Plot 1: Price chart with regime background ────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(14, 9),
                         gridspec_kw={'height_ratios': [3, 1]})

ax = axes[0]
colors = {CALM: '#d4edda', NORMAL: '#fff3cd', STRESS: '#f8d7da'}
labels = {CALM: 'Calm', NORMAL: 'Normal', STRESS: 'Stress'}

prev_state = None
start_date = None
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

events = {
    'Volmageddon\nFeb 2018': '2018-02-05',
    'COVID\nMar 2020':       '2020-03-16',
    '2022\nBear':            '2022-06-16',
}
for label, date in events.items():
    matches = spy_aligned.index[spy_aligned.index.strftime('%Y-%m-%d') == date]
    if len(matches):
        ax.axvline(matches[0], color='navy', linewidth=0.8,
                   linestyle='--', alpha=0.5)
        ax.text(matches[0], ax.get_ylim()[1] * 0.95, label,
                fontsize=7, color='navy', ha='center', va='top')

# ── Plot 2: Regime strip ──────────────────────────────────────────────────────
ax2 = axes[1]
ax2.bar(state_series.index, np.ones(len(state_series)),
        color=[colors[s] for s in state_series], width=1.5, alpha=0.8)
ax2.set_ylabel('Regime')
ax2.set_yticks([])
ax2.set_xlabel('Date')

plt.tight_layout()
plt.savefig('hmm_regimes.png', dpi=150, bbox_inches='tight')
print("Chart saved: hmm_regimes.png")
plt.close()

# ── Statistical validation ────────────────────────────────────────────────────
log_returns   = np.log(spy_aligned / spy_aligned.shift(1)).dropna()
state_aligned = state_series.loc[log_returns.index]

print("\n" + "=" * 62)
print("REGIME STATISTICS  (this is how you verify correctness)")
print("=" * 62)
print(f"\n{'Metric':<28} {'Calm':>10} {'Normal':>10} {'Stress':>10}")
print("─" * 62)

stats = {}
for idx in [CALM, NORMAL, STRESS]:
    mask = state_aligned == idx
    rets = log_returns[mask]
    stats[idx] = {
        'days':     mask.sum(),
        'pct':      mask.mean(),
        'mean_ret': rets.mean() * 252,
        'vol':      rets.std() * np.sqrt(252),
        'sharpe':   (rets.mean() / rets.std() * np.sqrt(252))
                    if rets.std() > 0 else 0,
        'worst_day': rets.min(),
        'worst_5':   rets.nsmallest(5).mean(),
    }

def row(label, key, fmt):
    vals = [stats[i][key] for i in [CALM, NORMAL, STRESS]]
    print(f"  {label:<26}" + "".join(f"{fmt.format(v):>10}" for v in vals))

row("Trading days",     'days',     '{:.0f}')
row("% of all days",    'pct',      '{:.1%}')
row("Ann. return",      'mean_ret', '{:.1%}')
row("Ann. volatility",  'vol',      '{:.1%}')
row("Sharpe ratio",     'sharpe',   '{:.2f}')
row("Worst single day", 'worst_day','{:.2%}')
row("Avg worst 5 days", 'worst_5',  '{:.2%}')

# ── Check 1: Volatility ordering ──────────────────────────────────────────────
print()
print("Check 1 — Volatility must increase:  Calm < Normal < Stress")
cv, nv, sv = stats[CALM]['vol'], stats[NORMAL]['vol'], stats[STRESS]['vol']
vol_ok = cv < nv < sv
print(f"  Calm={cv:.1%}  Normal={nv:.1%}  Stress={sv:.1%}"
      f"  →  {'PASS' if vol_ok else 'FAIL — model has a problem'}")

# ── Check 2: Stress tail much worse than Calm ─────────────────────────────────
print()
print("Check 2 — Stress worst days must be much worse than Calm (expect 3x+)")
# Both worst_5 values are negative; dividing two negatives gives a positive ratio.
# e.g. Stress avg worst 5 = -8% / Calm avg worst 5 = -1.4%  →  ratio = 5.7x
calm_w5   = stats[CALM]['worst_5']
stress_w5 = stats[STRESS]['worst_5']
if calm_w5 != 0:
    ratio = stress_w5 / calm_w5          # positive number (neg / neg)
    tail_ok = ratio >= 3.0
    print(f"  Stress avg worst 5 / Calm avg worst 5 = {ratio:.1f}x"
          f"  →  {'PASS' if tail_ok else 'FAIL — regimes not well separated'}")
else:
    print("  Cannot compute ratio (Calm worst_5 = 0)")
    tail_ok = False

# ── Check 3: Transition matrix persistence ────────────────────────────────────
print()
print("Check 3 — Regimes must be sticky (diagonal > 85%)")
trans      = engine.model.transmat_
persist_ok = True
for i in range(3):
    stay = trans[i, i]
    ok   = stay > 0.85
    if not ok:
        persist_ok = False
    print(f"  P({HMM_STATES[i]:6s} → {HMM_STATES[i]:6s}) = {stay:.1%}"
          f"  →  {'PASS' if ok else 'FAIL — too jumpy'}")

# ── Summary ───────────────────────────────────────────────────────────────────
from raits.hmm.state_sorting import validate_state_order
ordered  = validate_state_order(engine.model)
all_ok   = vol_ok and tail_ok and persist_ok and ordered

print()
print("=" * 62)
print("SUMMARY")
print("=" * 62)
print(f"  Volatility ordered (Calm<Normal<Stress) : {'PASS' if vol_ok     else 'FAIL'}")
print(f"  Stress tail 3x+ worse than Calm         : {'PASS' if tail_ok    else 'FAIL'}")
print(f"  Regimes sticky (diag > 85%)             : {'PASS' if persist_ok else 'FAIL'}")
print(f"  State variance ordering valid           : {'PASS' if ordered    else 'FAIL'}")
print()
if all_ok:
    print("  OVERALL: PASS — HMM validated, ready for Weeks 6-8")
else:
    print("  OVERALL: ISSUES FOUND — paste output for diagnosis")
print("=" * 62)
