#!/usr/bin/env python3
"""
trend_blindness_diagnostic.py -- IS only (2017-2022)

Hypothesis: RAITS loses money in bull-trending (low-vol) periods because the
current HMM only separates states by volatility and cannot distinguish
"choppy low-vol" from "trending low-vol".

This script is READ-ONLY. It imports NO engine or HMM code, loads NO 2023+ data,
and makes NO changes to the backtest system.

Method:
  1. Build a parallel TREND label from SPY daily data (two measures):
       a. SMA trend: |SMA50 - SMA200| / SMA200 vs 2% threshold
       b. Return autocorrelation: 20-day rolling lag-1 autocorr vs +/-0.10
  2. Build a parallel VOL regime from SPY 5-day realized vol (tercile proxy).
  3. Tag every IS trade with its entry-day vol + trend label.
  4. Build 2D [vol x trend] tables and answer the key question.
  5. Quantify the LOW-VOL + TRENDING-UP opportunity.
  6. Save a heatmap PNG.

Parameters (fixed, not tuned):
  SMA_FAST = 50, SMA_SLOW = 200, SMA_THRESHOLD = 2%
  AC_WINDOW = 20 days, AC_TREND = +0.10, AC_MR = -0.10
  VOL_WINDOW = 5 days (tercile over 2017-2022)

Usage:
  python trend_blindness_diagnostic.py [--trade-log PATH] [--spy-daily PATH] [--output-png PATH]
"""

import argparse
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants (fixed, not tuned -- do not modify to improve results)
# ---------------------------------------------------------------------------
IS_START = '2017-01-01'
IS_END   = '2022-12-31'

SMA_FAST      = 50    # days
SMA_SLOW      = 200   # days
SMA_THRESHOLD = 0.02  # 2% gap between SMA50 and SMA200

AC_WINDOW = 20    # days for rolling autocorrelation
AC_TREND  = 0.10  # above this -> TRENDING
AC_MR     = -0.10 # below this -> MEAN-REVERTING

VOL_WINDOW = 5  # days for realized vol

# ---------------------------------------------------------------------------
# Default paths  (resolved relative to this file's location)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT  = _SCRIPT_DIR.parents[2]   # d:\raits

# Use the 2007-2024 file so SMA200 is warmed up from the start of 2017
DEFAULT_SPY_DAILY  = _REPO_ROOT / 'raits' / 'data' / 'cache' / 'daily' / 'SPY_daily_2007_2024.parquet'
DEFAULT_TRADE_LOG  = _REPO_ROOT / 'raits' / 'configs' / 'wfo_trade_log.csv'
DEFAULT_OUTPUT_PNG = _REPO_ROOT / 'raits' / 'configs' / 'trend_blindness_heatmap.png'


# ===========================================================================
# Pure functions -- unit-testable, no I/O
# ===========================================================================

def compute_sma_trend(
    close: pd.Series,
    fast: int = SMA_FAST,
    slow: int = SMA_SLOW,
    threshold: float = SMA_THRESHOLD,
) -> pd.Series:
    """
    SMA-based trend label (daily, strictly backward-looking).

    Returns a Series aligned to `close` with values:
      'TRENDING-UP'   -- SMA_fast > SMA_slow by > threshold
      'TRENDING-DOWN' -- SMA_fast < SMA_slow by > threshold
      'CHOPPY'        -- gap within threshold
      NaN             -- insufficient history (< slow bars)

    Parameters are stated above; the defaults are FIXED (50/200, 2%) and must
    not be modified to improve downstream results.
    """
    sma_fast = close.rolling(fast, min_periods=fast).mean()
    sma_slow = close.rolling(slow, min_periods=slow).mean()
    gap = (sma_fast - sma_slow) / sma_slow

    out = pd.Series('CHOPPY', index=close.index, dtype=object)
    out[gap >  threshold] = 'TRENDING-UP'
    out[gap < -threshold] = 'TRENDING-DOWN'
    out[sma_slow.isna()]  = np.nan
    return out


def _rolling_autocorr_lag1(arr: np.ndarray) -> float:
    """Lag-1 Pearson autocorrelation of a 1-D numpy array."""
    x1, x2 = arr[:-1], arr[1:]
    s1, s2 = x1.std(), x2.std()
    if s1 == 0 or s2 == 0:
        return np.nan
    return float(np.corrcoef(x1, x2)[0, 1])


def compute_autocorr_trend(
    close: pd.Series,
    window: int = AC_WINDOW,
    trend_thresh: float = AC_TREND,
    mr_thresh: float = AC_MR,
) -> pd.Series:
    """
    Rolling lag-1 autocorrelation trend label (daily, strictly backward-looking).

    Computes daily log-returns, then a rolling lag-1 autocorrelation over
    `window` bars.

    Returns a Series aligned to `close` with values:
      'TRENDING'       -- autocorr > trend_thresh (+0.10)
      'MEAN-REVERTING' -- autocorr < mr_thresh    (-0.10)
      'NEUTRAL'        -- between the two thresholds
      NaN              -- insufficient history

    Parameters are fixed (20 days, +/-0.10) and must not be tuned.
    """
    log_ret = np.log(close / close.shift(1))
    autocorr = log_ret.rolling(window, min_periods=window).apply(
        _rolling_autocorr_lag1, raw=True
    )

    out = pd.Series('NEUTRAL', index=close.index, dtype=object)
    out[autocorr >  trend_thresh] = 'TRENDING'
    out[autocorr <  mr_thresh]    = 'MEAN-REVERTING'
    out[autocorr.isna()]          = np.nan
    return out


def compute_vol_regime(close: pd.Series, window: int = VOL_WINDOW) -> pd.Series:
    """
    5-day realised vol (annualised, std of log-returns x sqrt252), tercile-bucketed.

    Terciles are computed over the entire `close` series passed in -- caller
    should filter to the IS period before calling so thresholds are in-sample.

    Returns a Series aligned to `close` with values:
      'LOW'  -- bottom third
      'MED'  -- middle third
      'HIGH' -- top third
      NaN    -- insufficient history (< window bars)
    """
    log_ret     = np.log(close / close.shift(1))
    rvol        = log_ret.rolling(window, min_periods=window).std() * np.sqrt(252)

    valid       = rvol.dropna()
    q33         = valid.quantile(1 / 3)
    q67         = valid.quantile(2 / 3)

    out = pd.Series('MED', index=close.index, dtype=object)
    out[rvol <= q33]   = 'LOW'
    out[rvol >  q67]   = 'HIGH'
    out[rvol.isna()]   = np.nan
    return out


# ===========================================================================
# Analysis helpers
# ===========================================================================

def _cell_stats(cell: pd.DataFrame) -> dict:
    n = len(cell)
    if n == 0:
        return {'n_trades': 0, 'win_rate': float('nan'),
                'net_pnl': 0.0, 'profit_factor': float('nan')}
    wins = cell.loc[cell['net_pnl'] > 0, 'net_pnl'].sum()
    loss = cell.loc[cell['net_pnl'] < 0, 'net_pnl'].sum()
    return {
        'n_trades':     n,
        'win_rate':     (cell['net_pnl'] > 0).sum() / n,
        'net_pnl':      cell['net_pnl'].sum(),
        'profit_factor': (wins / abs(loss)) if loss != 0 else float('inf'),
    }


def build_2d_table(
    trades: pd.DataFrame,
    row_col: str,
    col_col: str,
    row_order: list = None,
    col_order: list = None,
) -> pd.DataFrame:
    """Build a 2-D performance table (n, win_rate, net_pnl, profit_factor)."""
    valid = trades.dropna(subset=[row_col, col_col])
    rows  = row_order or sorted(valid[row_col].unique())
    cols  = col_order or sorted(valid[col_col].unique())

    records = []
    for rv in rows:
        for cv in cols:
            cell  = valid[(valid[row_col] == rv) & (valid[col_col] == cv)]
            stats = _cell_stats(cell)
            stats['vol']   = rv
            stats['trend'] = cv
            records.append(stats)
    return pd.DataFrame(records)


def _fmt_pf(pf: float) -> str:
    if not np.isfinite(pf):
        return 'inf'
    return f'{pf:.2f}'


def print_2d_table(df: pd.DataFrame, title: str) -> None:
    """Pretty-print a 2-D [vol x trend] table."""
    rows = df['vol'].unique()
    cols = df['trend'].unique()
    W    = 38

    print(f'\n{"=" * 80}')
    print(f'  {title}')
    print(f'{"=" * 80}')
    print(f'{"":17}', end='')
    for c in cols:
        print(f'{c:^{W}}', end='')
    print()
    print(f'{"":17}' + '-' * (W * len(cols)))

    for r in rows:
        print(f'{r:<17}', end='')
        for c in cols:
            sub = df[(df['vol'] == r) & (df['trend'] == c)]
            if sub.empty or sub.iloc[0]['n_trades'] == 0:
                print(f'{"(no trades)":^{W}}', end='')
            else:
                s    = sub.iloc[0]
                cell = (f'n={int(s["n_trades"])}  wr={s["win_rate"]:.0%}  '
                        f'pnl=${s["net_pnl"]:+,.0f}  pf={_fmt_pf(s["profit_factor"])}')
                print(f'{cell:^{W}}', end='')
        print()


def _heatmap_on_ax(
    ax,
    table_df: pd.DataFrame,
    row_order: list,
    col_order: list,
    title: str,
) -> None:
    pivot = table_df.pivot(index='vol', columns='trend', values='net_pnl')
    pivot = pivot.reindex(index=row_order, columns=col_order)

    data = pivot.values.astype(float)
    vmax = max(abs(np.nanmax(data)), abs(np.nanmin(data)), 1.0)
    im   = ax.imshow(data, cmap='RdYlGn', vmin=-vmax, vmax=vmax, aspect='auto')

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns, fontsize=9, rotation=20, ha='right')
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index, fontsize=10)

    for i, r in enumerate(pivot.index):
        for j, c in enumerate(pivot.columns):
            val  = data[i, j]
            if np.isnan(val):
                continue
            n_row = table_df[(table_df['vol'] == r) & (table_df['trend'] == c)]['n_trades']
            n     = int(n_row.iloc[0]) if len(n_row) > 0 else 0
            ax.text(j, i, f'${val:+,.0f}\n(n={n})',
                    ha='center', va='center', fontsize=9,
                    color='black', fontweight='bold')

    plt.colorbar(im, ax=ax, label='Net P&L ($)')
    ax.set_xlabel('Trend Label', fontsize=10)
    ax.set_ylabel('Vol Regime', fontsize=10)
    ax.set_title(title, fontsize=11)


# ===========================================================================
# Main analysis
# ===========================================================================

def analyze(
    trade_log_path: Path,
    spy_daily_path: Path,
    output_png: Path,
) -> None:

    print('\n' + '=' * 80)
    print('  RAITS Trend-Blindness Diagnostic -- IN-SAMPLE ONLY (2017-2022)')
    print('=' * 80)
    print()
    print('CAVEATS:')
    print('  * Fixed, unoptimised trend rules -- concept test, not a tuned solution.')
    print('    SMA 50/200 @ 2% threshold | autocorr 20-day @ +/-0.10 threshold | vol 5-day tercile.')
    print('  * Vol-tercile proxy may differ from real HMM states; both reported.')
    print('  * In-sample only (2017-2022). 2023+ data sealed and never loaded.')
    print()

    # -----------------------------------------------------------------------
    # Load data
    # -----------------------------------------------------------------------
    trades = pd.read_csv(trade_log_path, parse_dates=['entry_time', 'exit_time'])
    trades = trades[
        (trades['entry_time'] >= IS_START) & (trades['entry_time'] <= IS_END)
    ].copy()
    print(f'Trade log : {len(trades)} IS trades from {trade_log_path.name}')

    spy_full = pd.read_parquet(spy_daily_path)
    spy_full.index = pd.to_datetime(spy_full.index)
    # compute labels on full history so SMA200 is warmed up; filter to IS after
    spy_full = spy_full[spy_full.index <= IS_END]
    spy_is   = spy_full[spy_full.index >= IS_START]
    print(f'SPY daily : {len(spy_full)} bars used for SMA warmup -> '
          f'{len(spy_is)} bars in IS window\n')

    # -----------------------------------------------------------------------
    # Build labels (on full history for SMA warmup, filter to IS for vol)
    # -----------------------------------------------------------------------
    close_full = spy_full['close']
    close_is   = spy_is['close']

    sma_trend_full    = compute_sma_trend(close_full)
    autocorr_full     = compute_autocorr_trend(close_full)
    # vol tercile computed only on IS so thresholds are in-sample
    vol_regime_is     = compute_vol_regime(close_is)

    sma_trend_is   = sma_trend_full.loc[IS_START:]
    autocorr_is    = autocorr_full.loc[IS_START:]

    # -----------------------------------------------------------------------
    # Tag trades
    # -----------------------------------------------------------------------
    trades['entry_date'] = trades['entry_time'].dt.normalize()

    def _map(label_series):
        return trades['entry_date'].map(label_series)

    trades['sma_trend']    = _map(sma_trend_is)
    trades['autocorr_trend'] = _map(autocorr_is)
    trades['vol_regime']   = _map(vol_regime_is)

    # Coverage report
    for col, name in [('sma_trend', 'SMA trend'), ('autocorr_trend', 'Autocorr trend'),
                      ('vol_regime', 'Vol regime')]:
        n_nan = trades[col].isna().sum()
        pct   = n_nan / len(trades) * 100
        if n_nan:
            print(f'  NOTE: {name} is NaN for {n_nan} trades ({pct:.1f}%) '
                  f'-- usually early 2017 warmup period.')

    has_hmm = 'hmm_state' in trades.columns and trades['hmm_state'].notna().any()
    if has_hmm:
        dist = trades['hmm_state'].value_counts().to_dict()
        print(f'  Real HMM state available: {dist}')
    print()

    # -----------------------------------------------------------------------
    # Ordering for tables
    # -----------------------------------------------------------------------
    vol_order  = ['LOW', 'MED', 'HIGH']
    sma_order  = ['TRENDING-UP', 'CHOPPY', 'TRENDING-DOWN']
    ac_order   = ['TRENDING', 'NEUTRAL', 'MEAN-REVERTING']
    hmm_order  = ['Calm', 'Normal', 'Stress']

    # -----------------------------------------------------------------------
    # Table A: Vol tercile x SMA trend
    # -----------------------------------------------------------------------
    table_a = build_2d_table(trades, 'vol_regime', 'sma_trend', vol_order, sma_order)
    print_2d_table(table_a, 'TABLE A: Vol Tercile (proxy) x SMA Trend  (SMA50/200, 2% threshold)')

    # -----------------------------------------------------------------------
    # Table B: Vol tercile x autocorr trend
    # -----------------------------------------------------------------------
    table_b = build_2d_table(trades, 'vol_regime', 'autocorr_trend', vol_order, ac_order)
    print_2d_table(table_b, 'TABLE B: Vol Tercile (proxy) x Autocorr Trend  (20-day, +/-0.10)')

    if has_hmm:
        # Table C: Real HMM x SMA trend
        table_c = build_2d_table(trades, 'hmm_state', 'sma_trend', hmm_order, sma_order)
        print_2d_table(table_c, 'TABLE C: Real HMM State x SMA Trend')

        # Table D: Real HMM x autocorr trend
        table_d = build_2d_table(trades, 'hmm_state', 'autocorr_trend', hmm_order, ac_order)
        print_2d_table(table_d, 'TABLE D: Real HMM State x Autocorr Trend')

    # -----------------------------------------------------------------------
    # KEY QUESTION
    # -----------------------------------------------------------------------
    print('\n' + '=' * 80)
    print('  KEY QUESTION: Does LOW-VOL+TRENDING-UP underperform LOW-VOL+CHOPPY?')
    print('=' * 80)

    def _print_kq(table_df, trending_val, choppy_val, section_name):
        lt = table_df[(table_df['vol'] == 'LOW') & (table_df['trend'] == trending_val)]
        lc = table_df[(table_df['vol'] == 'LOW') & (table_df['trend'] == choppy_val)]
        print(f'\n  [{section_name}]')
        for label, sub in [(trending_val, lt), (choppy_val, lc)]:
            if sub.empty or sub.iloc[0]['n_trades'] == 0:
                print(f'  LOW-VOL + {label:<18}: (no trades)')
            else:
                s = sub.iloc[0]
                print(f'  LOW-VOL + {label:<18}: '
                      f'n={int(s["n_trades"]):3d}  wr={s["win_rate"]:.0%}  '
                      f'net_pnl=${s["net_pnl"]:+,.0f}  pf={_fmt_pf(s["profit_factor"])}')
        if (not lt.empty and lt.iloc[0]['n_trades'] > 0 and
                not lc.empty and lc.iloc[0]['n_trades'] > 0):
            dpnl = lt.iloc[0]['net_pnl'] - lc.iloc[0]['net_pnl']
            dwr  = lt.iloc[0]['win_rate'] - lc.iloc[0]['win_rate']
            print(f'  -> Delta trending-choppy: net_pnl=${dpnl:+,.0f}  win_rate={dwr:+.1%}')
            if lt.iloc[0]['net_pnl'] < lc.iloc[0]['net_pnl']:
                print('  -> TRENDING-UP underperforms CHOPPY <- supports hypothesis')
            else:
                print('  -> TRENDING-UP does NOT underperform CHOPPY <- does not support hypothesis')

    _print_kq(table_a, 'TRENDING-UP', 'CHOPPY', 'Vol Tercile x SMA Trend')
    _print_kq(table_b, 'TRENDING', 'NEUTRAL', 'Vol Tercile x Autocorr Trend')

    if has_hmm:
        # Reuse tables C/D with col renamed to 'trend'
        # Table C already uses 'vol' for HMM state column
        lt_hmm = table_c[(table_c['vol'] == 'Calm') & (table_c['trend'] == 'TRENDING-UP')]
        lc_hmm = table_c[(table_c['vol'] == 'Calm') & (table_c['trend'] == 'CHOPPY')]
        print('\n  [Real HMM Calm x SMA Trend]')
        for label, sub in [('TRENDING-UP', lt_hmm), ('CHOPPY', lc_hmm)]:
            if sub.empty or sub.iloc[0]['n_trades'] == 0:
                print(f'  Calm + {label:<18}: (no trades)')
            else:
                s = sub.iloc[0]
                print(f'  Calm + {label:<18}: '
                      f'n={int(s["n_trades"]):3d}  wr={s["win_rate"]:.0%}  '
                      f'net_pnl=${s["net_pnl"]:+,.0f}  pf={_fmt_pf(s["profit_factor"])}')

    # -----------------------------------------------------------------------
    # STEP 3: QUANTIFY THE OPPORTUNITY
    # -----------------------------------------------------------------------
    print('\n' + '=' * 80)
    print('  LOW-VOL + TRENDING-UP BUCKET  (Vol tercile proxy, SMA trend)')
    print('=' * 80)

    total_pnl = trades['net_pnl'].sum()
    bucket    = trades[(trades['vol_regime'] == 'LOW') & (trades['sma_trend'] == 'TRENDING-UP')]
    bucket_pnl = bucket['net_pnl'].sum()
    excl_pnl  = total_pnl - bucket_pnl

    print(f'\n  Total IS net P&L  (all {len(trades)} trades):   ${total_pnl:+,.0f}')
    print(f'  LOW-VOL + TRENDING-UP bucket ({len(bucket)} trades): ${bucket_pnl:+,.0f}')
    print(f'  P&L if that bucket had been skipped:       ${excl_pnl:+,.0f}  '
          f'({"+" if excl_pnl > total_pnl else "-"}'
          f'${abs(excl_pnl - total_pnl):,.0f} vs current)')

    if len(bucket) > 0:
        print(f'\n  Per-strategy breakdown -- LOW-VOL + TRENDING-UP:')
        bk = bucket.groupby('strategy')['net_pnl'].agg(['count', 'sum', 'mean'])
        bk.columns = ['n', 'net_pnl', 'avg']
        bk = bk.sort_values('net_pnl')
        for strat, row in bk.iterrows():
            print(f'    {strat:<22}  n={int(row["n"]):3d}  '
                  f'net_pnl=${row["net_pnl"]:+,.0f}  avg=${row["avg"]:+,.0f}/trade')

    if has_hmm:
        hmm_bucket     = trades[(trades['hmm_state'] == 'Calm') & (trades['sma_trend'] == 'TRENDING-UP')]
        hmm_bucket_pnl = hmm_bucket['net_pnl'].sum()
        hmm_excl_pnl   = total_pnl - hmm_bucket_pnl
        print(f'\n  [Real HMM] Calm + TRENDING-UP ({len(hmm_bucket)} trades): '
              f'${hmm_bucket_pnl:+,.0f}')
        print(f'  [Real HMM] P&L if skipped: ${hmm_excl_pnl:+,.0f}')
        if len(hmm_bucket) > 0:
            print(f'\n  Per-strategy breakdown -- Calm + TRENDING-UP (real HMM):')
            bk2 = hmm_bucket.groupby('strategy')['net_pnl'].agg(['count', 'sum', 'mean'])
            bk2.columns = ['n', 'net_pnl', 'avg']
            bk2 = bk2.sort_values('net_pnl')
            for strat, row in bk2.iterrows():
                print(f'    {strat:<22}  n={int(row["n"]):3d}  '
                      f'net_pnl=${row["net_pnl"]:+,.0f}  avg=${row["avg"]:+,.0f}/trade')

    # -----------------------------------------------------------------------
    # VERDICT
    # -----------------------------------------------------------------------
    print('\n' + '=' * 80)
    print('  VERDICT')
    print('=' * 80)

    lt_row = table_a[(table_a['vol'] == 'LOW') & (table_a['trend'] == 'TRENDING-UP')]
    lc_row = table_a[(table_a['vol'] == 'LOW') & (table_a['trend'] == 'CHOPPY')]

    enough_data = (not lt_row.empty and lt_row.iloc[0]['n_trades'] >= 10 and
                   not lc_row.empty and lc_row.iloc[0]['n_trades'] >= 10)
    underperforms = (enough_data and
                     lt_row.iloc[0]['net_pnl'] < lc_row.iloc[0]['net_pnl'] and
                     lt_row.iloc[0]['win_rate'] < lc_row.iloc[0]['win_rate'])
    material = abs(bucket_pnl) > 1_000 and len(bucket) >= 10

    if underperforms and material:
        verdict_str = 'CONFIRMED -- trend-blindness is causing losses in low-vol+trending-up periods'
        action_str  = (f'adding a trend dimension is WORTH INVESTIGATING '
                       f'(${abs(bucket_pnl):,.0f} at stake, {len(bucket)} trades)')
    elif underperforms and not material:
        verdict_str = 'WEAK SIGNAL -- trending-up underperforms choppy but effect is small'
        action_str  = f'bucket too small (${bucket_pnl:+,.0f}, n={len(bucket)}) to justify HMM change'
    elif not enough_data:
        verdict_str = 'INCONCLUSIVE -- insufficient trades in one or both LOW-VOL cells'
        action_str  = 'cannot determine; collect more data or loosen label thresholds'
    else:
        verdict_str = 'NOT CONFIRMED -- LOW-VOL+TRENDING-UP does not clearly underperform CHOPPY'
        action_str  = 'trend-blindness is not the primary source of RAITS losses'

    print(f'\n  -> {verdict_str}')
    print(f'  -> {action_str}')
    print()

    # -----------------------------------------------------------------------
    # HEATMAP
    # -----------------------------------------------------------------------
    n_tables = 4 if has_hmm else 2
    fig, axes = plt.subplots(1 if n_tables == 2 else 2,
                              2,
                              figsize=(18, 6 * (1 if n_tables == 2 else 2)))
    if n_tables == 2:
        axes = [axes[0], axes[1]]  # flat list
    else:
        axes = axes.flatten().tolist()

    _heatmap_on_ax(axes[0], table_a, vol_order, sma_order,
                   'Net P&L: Vol Tercile x SMA Trend (50/200, 2%)')
    _heatmap_on_ax(axes[1], table_b, vol_order, ac_order,
                   'Net P&L: Vol Tercile x Autocorr Trend (20d, +/-0.10)')

    if has_hmm:
        _heatmap_on_ax(axes[2], table_c, hmm_order, sma_order,
                       'Net P&L: Real HMM State x SMA Trend')
        _heatmap_on_ax(axes[3], table_d, hmm_order, ac_order,
                       'Net P&L: Real HMM State x Autocorr Trend')

    plt.suptitle('RAITS Trend-Blindness Diagnostic -- IS 2017-2022',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_png, dpi=150)
    plt.close()
    print(f'Heatmap saved -> {output_png}')


# ===========================================================================
# Entry point
# ===========================================================================

def _parse_args():
    p = argparse.ArgumentParser(
        description='RAITS Trend-Blindness Diagnostic (IS 2017-2022 only, read-only)'
    )
    p.add_argument('--trade-log',  type=Path, default=DEFAULT_TRADE_LOG,
                   help=f'IS trade log CSV  (default: {DEFAULT_TRADE_LOG.name})')
    p.add_argument('--spy-daily',  type=Path, default=DEFAULT_SPY_DAILY,
                   help=f'SPY daily parquet (default: {DEFAULT_SPY_DAILY.name})')
    p.add_argument('--output-png', type=Path, default=DEFAULT_OUTPUT_PNG,
                   help=f'Output heatmap PNG (default: {DEFAULT_OUTPUT_PNG.name})')
    return p.parse_args()


def main():
    args = _parse_args()
    for p, name in [(args.trade_log, '--trade-log'), (args.spy_daily, '--spy-daily')]:
        if not p.exists():
            print(f'ERROR: {name} not found: {p}', file=sys.stderr)
            sys.exit(1)
    analyze(args.trade_log, args.spy_daily, args.output_png)


if __name__ == '__main__':
    main()
