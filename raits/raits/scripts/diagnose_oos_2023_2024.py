"""
scripts/diagnose_oos_2023_2024.py
----------------------------------
Run 2023-2024 on the CURRENT engine and check whether the original vault result
(+$7,404, Sharpe=0.88) still holds.

FRAMING:
  2023-2024 was SEEN (used for the "equity candidate" deployment decision) but NOT
  TUNED (no engine/strategy parameters were changed based on it).  It is therefore
  safe to re-run for diagnostic purposes.
  2025 remains FULLY CLEAN — do NOT touch it.

This script:
  1. Runs 2023-2024 with the current engine + locked params (orb=20/bb=1.5/ema=30)
  2. Compares to the original vault headline (+$7,404, Sharpe=0.88, PF=1.18)
  3. Decomposes by strategy (TF-driven vs PE_SHORT-concentrated vs no-edge trio)
  4. Computes R-multiple edge (GF_SHORT excluded — trailing-stop artifact)
  5. Jackknife: remove top k trades by net_pnl, re-check overall sign

DO NOT adjust engine or strategy parameters based on these results.
DO NOT touch 2025 data.

Usage (from d:\\raits\\raits):
    python raits/scripts/diagnose_oos_2023_2024.py
    python raits/scripts/diagnose_oos_2023_2024.py --rebuild-cache

Output: configs/oos_2023_2024_report.txt
"""

from __future__ import annotations

import sys
import os
import glob as _glob
import pickle
import time as _time
import warnings
warnings.filterwarnings("ignore")

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
from collections import defaultdict

from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Paths ─────────────────────────────────────────────────────────────────────
_RAITS_DIR   = os.path.join(_ROOT, "raits")
CACHE_5MIN   = os.path.join(_RAITS_DIR, "data", "cache", "data")
CACHE_DAILY  = os.path.join(_RAITS_DIR, "data", "cache", "daily")
PKL_5MIN     = os.path.join(_RAITS_DIR, "data", "cache", "window_debug_5min.pkl")
PKL_DAILY    = os.path.join(_RAITS_DIR, "data", "cache", "window_debug_daily.pkl")
REPORT_OUT   = os.path.join(_RAITS_DIR, "configs", "oos_2023_2024_report.txt")

UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1   = [
    "INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
    "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
    "CSCO", "GS", "CRM", "JPM",
]
PHASE2        = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
PE_EXPANSION  = [
    "PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY",
    "BAC", "WFC", "C",
    "WMT", "TGT", "HD", "LOW", "MCD", "NKE",
    "PG", "KO", "PEP",
    "CAT", "DE", "BA", "GE",
    "PYPL", "PANW", "NOW",
]
SECTOR_ETFS   = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS       = ["SPY", "QQQ", "IWM"] + SECTOR_ETFS + UNIVERSE + PHASE1 + PHASE2 + PE_EXPANSION

MR_UNIVERSE_STATIC = ["XLF", "XLE", "XLV", "XLU", "XLI",
                       "XLK", "XLP", "XLB", "XLY", "GLD", "QQQ", "IWM"]

# Locked OOS window (original vault params)
OOS_START = "2023-01-03"
OOS_END   = "2024-12-31"
WARMUP    = 252  # trading days of warmup before OOS window

# Original vault baseline (pre-CB-fix engine)
ORIG_VAULT_PNL    = 7_404.0
ORIG_VAULT_SHARPE = 0.88
ORIG_VAULT_PF     = 1.18

N_BOOT = 10_000
SEED   = 42


# ── Data loading ──────────────────────────────────────────────────────────────

def _cache_is_fresh(pkl: str, src_dir: str, pattern: str) -> bool:
    if not os.path.exists(pkl):
        return False
    pkl_mtime = os.path.getmtime(pkl)
    files = _glob.glob(os.path.join(src_dir, pattern))
    return bool(files) and all(os.path.getmtime(f) <= pkl_mtime for f in files)


def load_5min(rebuild: bool = False) -> dict:
    if not rebuild and _cache_is_fresh(PKL_5MIN, CACHE_5MIN, "*.parquet"):
        print("  Loading 5-min from pickle...", end=" ", flush=True)
        t0 = _time.time()
        with open(PKL_5MIN, "rb") as f:
            all_data = pickle.load(f)
        data = {t: df for t, df in all_data.items() if t in TICKERS}
        print(f"done ({_time.time()-t0:.1f}s) — {len(data)} tickers")
        return data

    print("  Building 5-min cache from parquets...")
    data = {}
    for ticker in TICKERS:
        files = _glob.glob(os.path.join(CACHE_5MIN, f"{ticker}_5min_*.parquet"))
        if not files:
            print(f"    {ticker}: no 5-min files — skipping")
            continue
        df = pd.concat([pd.read_parquet(f) for f in files])
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index().loc[~df.index.duplicated(keep="first")]
        df = df.between_time("09:30", "16:00")
        data[ticker] = df
    with open(PKL_5MIN, "wb") as f:
        pickle.dump(data, f)
    print(f"  Saved 5-min pickle ({len(data)} tickers)")
    return data


def load_daily(rebuild: bool = False) -> dict:
    if not rebuild and _cache_is_fresh(PKL_DAILY, CACHE_DAILY, "*.parquet"):
        print("  Loading daily from pickle...", end=" ", flush=True)
        t0 = _time.time()
        with open(PKL_DAILY, "rb") as f:
            data = pickle.load(f)
        print(f"done ({_time.time()-t0:.1f}s) — {len(data)} tickers")
        return data

    print("  Building daily cache from parquets...")
    data = {}
    for ticker in ["SPY"] + CANDIDATE_POOL:
        files = _glob.glob(os.path.join(CACHE_DAILY, f"{ticker}_daily_*.parquet"))
        if not files:
            continue
        df = pd.concat([pd.read_parquet(f) for f in files])
        df.index = pd.DatetimeIndex(df.index)
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_index().loc[~df.index.duplicated(keep="first")]
        data[ticker] = df
    with open(PKL_DAILY, "wb") as f:
        pickle.dump(data, f)
    print(f"  Saved daily pickle ({len(data)} tickers)")
    return data


def slice_window(full_data: dict, start: str, end: str) -> dict:
    spy = full_data.get("SPY", pd.DataFrame())
    spy_days = spy.index.normalize().unique().sort_values()
    warmup_idx = int(spy_days.searchsorted(pd.Timestamp(start).normalize()))
    warmup_idx = max(0, warmup_idx - WARMUP)
    warmup_start = pd.Timestamp(spy_days[warmup_idx])
    end_ts = pd.Timestamp(end) + pd.Timedelta("1D")

    result = {}
    for ticker, df in full_data.items():
        if ticker == "SPY":
            sliced = df[df.index <= end_ts]
        else:
            sliced = df[(df.index >= warmup_start) & (df.index <= end_ts)]
        if not sliced.empty:
            result[ticker] = sliced
    return result


# ── R-multiple ────────────────────────────────────────────────────────────────

def compute_r(entry_price: float, shares: int, stop: float, net_pnl: float):
    """R-multiple = net_pnl / initial_risk. Returns None for degenerate risk."""
    risk = shares * abs(entry_price - stop)
    return (net_pnl / risk) if risk >= 0.01 else None


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def iid_p(values: np.ndarray, n_boot: int, rng: np.random.Generator) -> float:
    if len(values) == 0:
        return 1.0
    if values.mean() <= 0:
        return 1.0
    boot_means = rng.choice(values, size=(n_boot, len(values)), replace=True).mean(axis=1)
    return float((boot_means <= 0).mean())


# ── Jackknife ─────────────────────────────────────────────────────────────────

def jackknife_top_k(values: np.ndarray, k_list=(1, 2, 3)) -> list[tuple[int, float, float]]:
    """Remove top-k by value, return (k, new_mean, new_total)."""
    results = []
    sorted_idx = np.argsort(values)[::-1]
    for k in k_list:
        mask = np.ones(len(values), dtype=bool)
        mask[sorted_idx[:k]] = False
        reduced = values[mask]
        results.append((k, float(reduced.mean()) if len(reduced) else 0.0,
                        float(reduced.sum()) if len(reduced) else 0.0))
    return results


# ── Main analysis ─────────────────────────────────────────────────────────────

def run_analysis(trades: list, metrics: dict, lines: list) -> None:
    SEP  = "=" * 80
    SEP2 = "-" * 80
    rng  = np.random.default_rng(SEED)

    # ── 1. Overall P&L ──────────────────────────────────────────────────────
    all_pnl = [t.net_pnl or 0.0 for t in trades]
    total   = sum(all_pnl)
    n       = len(trades)

    sharpe   = metrics.get("sharpe_ratio",  float("nan"))
    pf       = metrics.get("profit_factor", float("nan"))
    calmar   = metrics.get("calmar_ratio",  float("nan"))
    max_dd   = metrics.get("max_drawdown",  float("nan"))
    win_rate = metrics.get("win_rate",      float("nan"))

    delta_pnl    = total - ORIG_VAULT_PNL
    delta_sharpe = sharpe - ORIG_VAULT_SHARPE if not np.isnan(sharpe) else float("nan")

    lines += [
        SEP,
        "SECTION 1 — OVERALL P&L vs ORIGINAL VAULT",
        SEP2,
        f"  Original vault (pre-CB-fix):  ${ORIG_VAULT_PNL:+,.0f}  Sharpe={ORIG_VAULT_SHARPE}  PF={ORIG_VAULT_PF}",
        f"  Current engine (post-CB-fix): ${total:+,.0f}  Sharpe={sharpe:.2f}  PF={pf:.2f}  Calmar={calmar:.2f}",
        f"  Delta P&L:    ${delta_pnl:+,.0f}",
        f"  Delta Sharpe: {delta_sharpe:+.2f}" if not np.isnan(delta_sharpe) else "  Delta Sharpe: n/a",
        f"  Win Rate:     {win_rate*100:.1f}%  Max DD: {max_dd*100:.1f}%  Trades: {n}",
        "",
    ]

    # ── 2. Strategy decomposition ────────────────────────────────────────────
    by_strat = defaultdict(list)
    for t in trades:
        by_strat[t.strategy].append(t.net_pnl or 0.0)

    lines += ["SECTION 2 — STRATEGY DECOMPOSITION", SEP2]
    hdr = f"  {'Strategy':<14} {'N':>4} {'WR%':>6} {'Mean$/t':>9} {'Total':>10}  {'% of sys':>8}"
    lines.append(hdr)
    lines.append(f"  {'-'*60}")

    strat_order = ["TREND_FOLLOW", "PE_SHORT", "ORB", "STRESS_ORB", "STRESS_MID", "GF_SHORT"]
    for strat in strat_order:
        pnls = by_strat.get(strat, [])
        if not pnls:
            lines.append(f"  {strat:<14} {'0':>4}  —  (no trades)")
            continue
        ns = len(pnls)
        wr = sum(1 for p in pnls if p > 0) / ns * 100
        mn = sum(pnls) / ns
        tot = sum(pnls)
        pct = tot / total * 100 if total else float("nan")
        lines.append(f"  {strat:<14} {ns:>4} {wr:>5.1f}% {mn:>+9.2f} {tot:>+10,.0f}  {pct:>+7.1f}%")

    # Any unlisted strategies
    for strat, pnls in sorted(by_strat.items()):
        if strat not in strat_order:
            tot = sum(pnls)
            lines.append(f"  {strat:<14} {len(pnls):>4}  (extra strategy — not in standard set): ${tot:+,.0f}")

    lines.append("")

    # ── 3. TF-driven vs PE_SHORT-concentrated vs noise ───────────────────────
    tf_pnl   = sum(by_strat.get("TREND_FOLLOW", []))
    pe_pnl   = sum(by_strat.get("PE_SHORT",     []))
    noise_pnl= sum(by_strat.get("ORB", []) + by_strat.get("STRESS_ORB", []) + by_strat.get("STRESS_MID", []))
    gf_pnl   = sum(by_strat.get("GF_SHORT",     []))

    lines += [
        "SECTION 3 — EDGE CHARACTERIZATION",
        SEP2,
        f"  Confirmed backbone (TF):        ${tf_pnl:+,.0f}  ({tf_pnl/total*100:+.1f}% of total)",
        f"  Confirmed concentrated (PE):    ${pe_pnl:+,.0f}  ({pe_pnl/total*100:+.1f}% of total)",
        f"  No-edge trio (ORB+SORB+SMID):   ${noise_pnl:+,.0f}  ({noise_pnl/total*100:+.1f}% of total)",
        f"  Untrustworthy (GF_SHORT):       ${gf_pnl:+,.0f}  ({gf_pnl/total*100:+.1f}% of total)",
        "",
        "  Classification (from IS bootstrap audit):",
        "    TF          — CONFIRMED robust (R-p=0.009, block-R B20 confirmed)",
        "    PE_SHORT    — CONFIRMED concentrated (top-5 trades=75% CumR in IS, watch OOS)",
        "    GF_SHORT    — UNTRUSTWORTHY (trailing-stop R artifact; N=12 untestable)",
        "    ORB/SORB/SMID — NO EDGE on all IS tests",
        "",
    ]

    # TF dominance check
    tf_pct = tf_pnl / total * 100 if total else 0
    pe_pct = pe_pnl / total * 100 if total else 0
    if tf_pct > 50:
        lines.append(f"  -> TF-dominant ({tf_pct:.0f}% of P&L): robust edge driving result. Good.")
    elif pe_pct > 50:
        lines.append(f"  -> PE-dominant ({pe_pct:.0f}% of P&L): concentrated edge driving result. Fragile.")
    elif noise_pnl / total > 0.3 if total else False:
        lines.append(f"  -> Noise trio contributes {noise_pnl/total*100:.0f}% — no-edge strategies influencing result.")
    else:
        lines.append(f"  -> Mixed sourcing — see strategy table above.")
    lines.append("")

    # ── 4. R-multiple bootstrap (TF + PE_SHORT only, GF_SHORT excluded) ─────
    lines += ["SECTION 4 — R-MULTIPLE BOOTSTRAP (IS-comparable, GF_SHORT excluded)", SEP2]

    r_by_strat = {}
    for strat in ["TREND_FOLLOW", "PE_SHORT", "ORB", "STRESS_ORB", "STRESS_MID"]:
        r_vals = []
        for t in trades:
            if t.strategy != strat:
                continue
            r = compute_r(t.entry_price, t.shares, t.stop, t.net_pnl or 0.0)
            if r is not None:
                r_vals.append(r)
        r_by_strat[strat] = np.array(r_vals)

    r_hdr = f"  {'Strategy':<14} {'N':>4} {'MeanR':>8} {'StdR':>8} {'d_R':>7} {'R-p':>8} {'verdict'}"
    lines.append(r_hdr)
    lines.append(f"  {'-'*70}")

    IS_R_P = {  # from bootstrap_normalized.py / bootstrap_block_r.py
        "TREND_FOLLOW": 0.009,
        "PE_SHORT":     0.010,
        "ORB":          0.241,
        "STRESS_ORB":   0.366,
        "STRESS_MID":   0.380,
    }

    def r_verdict(p: float) -> str:
        if p < 0.05:  return "CONFIRMED"
        if p < 0.15:  return "BORDERLINE"
        return "NO EDGE"

    for strat in ["TREND_FOLLOW", "PE_SHORT", "ORB", "STRESS_ORB", "STRESS_MID"]:
        arr = r_by_strat[strat]
        if len(arr) < 2:
            lines.append(f"  {strat:<14} {len(arr):>4}  (too few trades for R-multiple)")
            continue
        mean_r = arr.mean()
        std_r  = arr.std(ddof=1)
        d_r    = mean_r / std_r if std_r > 1e-9 else float("nan")
        p_r    = iid_p(arr, N_BOOT, rng)
        vd     = r_verdict(p_r)
        is_p   = IS_R_P.get(strat, float("nan"))
        delta  = p_r - is_p if not np.isnan(is_p) else float("nan")
        delta_str = f"(IS {is_p:.3f} delta={delta:+.3f})" if not np.isnan(delta) else ""
        lines.append(
            f"  {strat:<14} {len(arr):>4} {mean_r:>+8.4f} {std_r:>8.4f} {d_r:>+7.3f} "
            f"{p_r:>8.3f} {vd:<10} {delta_str}"
        )
    lines += [
        "",
        "  GF_SHORT excluded: R-multiple invalid (trailing chandelier stop in CSV",
        "  stores FINAL stop position at exit, not initial risk stop). See BOOTSTRAP_AUDIT.md.",
        "",
    ]

    # ── 5. Jackknife ────────────────────────────────────────────────────────
    lines += ["SECTION 5 — JACKKNIFE: REMOVE TOP k TRADES BY NET PNL", SEP2]
    pnl_arr = np.array([t.net_pnl or 0.0 for t in trades])
    sorted_desc = sorted(enumerate(pnl_arr), key=lambda x: -x[1])

    lines.append(f"  Total 2023-2024: ${total:+,.0f}  N={n}")
    lines.append(f"  {'k':>3} {'removed_trade':>35} {'new_total':>12} {'still positive?'}")
    lines.append(f"  {'-'*65}")

    removed_pnl = 0.0
    for k_idx, (orig_idx, pnl_val) in enumerate(sorted_desc[:5], start=1):
        t = trades[orig_idx]
        removed_pnl += pnl_val
        new_total = total - removed_pnl
        label = f"{t.strategy}/{t.ticker} {str(t.entry_time)[:10]} ${pnl_val:+.0f}"
        sign  = "YES" if new_total > 0 else "NO *"
        lines.append(f"  {k_idx:>3} {label:<35} ${new_total:>+10,.0f}  {sign}")

    lines.append("")

    # ── 6. Equity candidate verdict ──────────────────────────────────────────
    lines += ["SECTION 6 — 'EQUITY CANDIDATE' VERDICT", SEP2]
    lines += [
        "  Original basis: +$7,404, Sharpe=0.88, PF=1.18 (pre-CB-fix engine)",
        f"  Current result: ${total:+,.0f}, Sharpe={sharpe:.2f}, PF={pf:.2f} (post-CB-fix)",
        "",
    ]

    if total > 0 and sharpe > 0.5:
        verdict = "HOLDS — positive P&L and Sharpe>0.5 on current engine."
    elif total > 0:
        verdict = "WEAKLY HOLDS — positive P&L but Sharpe below original threshold."
    else:
        verdict = "DOES NOT HOLD — negative P&L on current engine. Review CB-fix impact."

    lines.append(f"  VERDICT: {verdict}")
    lines.append("")
    lines += [
        "  CRITICAL CONSTRAINT: do NOT adjust engine/strategy based on this result.",
        "  2023-2024 is seen-but-not-tuned. Any parameter change triggered by this",
        "  result contaminate 2025 indirectly. Report only.",
        "",
    ]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild-cache", action="store_true",
                    help="Force reload parquets, bypass pkl cache")
    args = ap.parse_args()

    print("\n" + "=" * 80)
    print("  OOS 2023-2024 DIAGNOSTIC — current engine, report only, NO TUNING")
    print("=" * 80)

    # ── Data check ────────────────────────────────────────────────────────────
    print("\nChecking 5-min data coverage...")
    sample = _glob.glob(os.path.join(CACHE_5MIN, "AAPL_5min_*.parquet"))
    if not sample:
        print("  [BLOCK] No 5-min AAPL parquets found. Check data/cache/data/")
        sys.exit(1)
    # Check max date across ALL AAPL files — individual files are date-chunked
    max_date = max(
        pd.read_parquet(f, columns=[]).index.max()
        for f in sample
    )
    # Gate: require full-year coverage through Dec 2024 (not just any 2023 data)
    required = pd.Timestamp("2024-12-01")
    if max_date < required:
        print(f"\n  [BLOCK] Max 5-min date: {max_date} — need data through Dec 2024!")
        print("  Run first: python raits/scripts/fetch_oos_remaining.py  (~70 min)")
        sys.exit(1)
    print(f"  Max 5-min date: {max_date} — OK")

    # ── Load ─────────────────────────────────────────────────────────────────
    print("\nLoading data...")
    full_5min  = load_5min(args.rebuild_cache)
    daily_data = load_daily(args.rebuild_cache)

    print(f"\n  Tickers loaded (5-min): {len(full_5min)}")
    print(f"  Tickers loaded (daily): {len(daily_data)}")

    # ── Check OOS data present ────────────────────────────────────────────────
    spy = full_5min.get("SPY", pd.DataFrame())
    oos_bars = spy[spy.index >= pd.Timestamp(OOS_START)] if not spy.empty else pd.DataFrame()
    if oos_bars.empty:
        print(f"\n  [BLOCK] SPY has no bars >= {OOS_START}. Fetch 2023-2024 first.")
        sys.exit(1)
    print(f"\n  OOS window: {OOS_START} to {OOS_END}")
    print(f"  SPY OOS bars: {len(oos_bars):,} ({oos_bars.index.normalize().nunique()} days)")

    # ── Slice window ─────────────────────────────────────────────────────────
    window_data = slice_window(full_5min, OOS_START, OOS_END)
    print(f"  Window tickers: {len(window_data)}")

    # ── Engine config (match vault_test.py) ──────────────────────────────────
    cfg = BacktestConfig(
        start_date=OOS_START,
        end_date=OOS_END,
        universe=CANDIDATE_POOL,
        orb_universe=[],
        vwap_universe=MR_UNIVERSE_STATIC,
        orb_range_minutes=20,   # final_params.yaml (sealed)
        vwap_bb_std=1.5,        # final_params.yaml (sealed)
        ema_period=30,          # final_params.yaml (sealed)
        account_equity=50_000.0,
        enable_costs=True,
        enable_pdt_guard=False,   # matches vault_test.py
        log_level="WARNING",
        allow_swing_hold=True,
        max_hold_days=5,
        stress_size_fraction=0.5,
        use_scanner=True,
        scanner_top_n=15,
        use_mr_scanner=True,
        mr_scanner_top_n=8,
        use_orb_scanner=True,
        orb_scanner_top_n=10,
        use_fade_scanner=True,
        fade_scanner_top_n=10,
        max_risk_pct=0.015,
        max_position_pct=0.40,
        # kelly_fraction=0.75 is the default in BacktestConfig
    )

    # ── Run engine ────────────────────────────────────────────────────────────
    print("\nRunning engine on 2023-2024...")
    t0 = _time.time()
    engine = BacktestEngine(cfg)
    result = engine.run(window_data, daily_data=daily_data)
    trades = result.trade_log
    elapsed = _time.time() - t0
    print(f"  Done: {len(trades)} trades in {elapsed:.1f}s")

    # ── Report ────────────────────────────────────────────────────────────────
    lines = [
        "OOS 2023-2024 DIAGNOSTIC REPORT",
        f"Date:     2026-07-08",
        f"Engine:   BacktestEngine (post-CB-fix, commit 9113ddd branch)",
        f"Params:   orb=20 / bb=1.5 / ema=30 (sealed final_params.yaml)",
        f"Config:   account=$50k | Kelly=0.75 | max_risk=1.5% | max_pos=40% | PDT=off",
        f"Window:   {OOS_START} to {OOS_END} (same as original vault)",
        f"N_BOOT:   {N_BOOT} (seed={SEED})",
        "",
        "FRAMING:",
        "  2023-2024 = SEEN-BUT-NOT-TUNED (used for deployment decision, no params changed)",
        "  2025      = FULLY CLEAN (not touched, real arbiter)",
        "  This run: diagnostic only. DO NOT tune based on results.",
        "",
    ]

    run_analysis(trades, result.metrics, lines)

    report = "\n".join(lines)
    print("\n" + report)

    out = REPORT_OUT
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nSaved: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()