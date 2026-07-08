"""
scripts/diagnose_removed_strategies.py
----------------------------------------
Re-enables FADE, GAP_FILL, VWAP_MR in the CONTINUOUS IS design (2017-2022,
Kelly=0.75, PDT on) and bootstraps each to test whether their removal on the
year-by-year design was a correct call or a real error.

HOW RE-ENABLEMENT WORKS:
  All three strategies' execution code is still in the engine.
  They are disabled only by the module-level _REGIME_STRATEGIES dict.
  This script patches that dict before instantiating BacktestEngine, so the
  rest of the engine is unchanged. FADE also requires use_fade_scanner=True
  to populate _effective_fade_universe (empty list otherwise).

ROBUSTNESS TESTS (for any strategy that flips toward has-edge):
  1. IID bootstrap (same method as bootstrap_strategy.py / bootstrap_continuous.py)
  2. Jackknife: remove top 1, 2, 3 winning trades — does verdict hold?
  3. Block bootstrap: ~20-day blocks to capture autocorrelation
     (IID bootstrap is optimistic; block bootstrap is the correct method)
  4. Cohen's d (mean/std): per-trade edge quality independent of N

VERDICT BUCKETS:
  "removal-correct"      : p high (>0.3), edge not present on continuous design
  "removal-was-error"    : low p (<0.05), survives jackknife, real Cohen's d,
                           survives block bootstrap — genuine edge
  "uncertain-needs-OOS"  : near threshold, fragile jackknife, or block vs IID conflict

Usage (from d:\\raits\\raits, ~25 min):
    python raits/scripts/diagnose_removed_strategies.py

Saves: configs/removed_strategies_report.txt
"""

from __future__ import annotations

import csv
import os
import pickle
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings("ignore")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import numpy as np
import pandas as pd

# ── Import engine BEFORE patching ────────────────────────────────────────────
from raits.backtest import engine as _engine_module
from raits.backtest.engine import BacktestEngine
from raits.backtest.data_types import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Patch _REGIME_STRATEGIES to re-enable FADE, GAP_FILL, VWAP_MR ────────────
_ORIGINAL_REGIME = dict(_engine_module._REGIME_STRATEGIES)
_engine_module._REGIME_STRATEGIES = {
    "Calm":   ["VWAP_MR", "FADE", "PE_SHORT"],
    "Normal": ["ORB", "TREND_FOLLOW", "FADE", "GAP_FILL", "GF_SHORT", "PE_SHORT"],
    "Stress": ["TREND_FOLLOW", "STRESS_ORB", "STRESS_MID", "PE_SHORT"],
    "Crisis": ["PE_SHORT"],
}
# ─────────────────────────────────────────────────────────────────────────────

# ── Universe / date range (matches verify_parallel_run.py / 605-trade baseline)
IS_START = "2017-01-03"
IS_END   = "2022-12-30"

UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1   = ["INTU", "COST", "VRTX", "AMAT", "REGN", "AVGO", "ADBE", "MS",
             "SBUX", "TXN", "XOM", "AMGN", "ORCL", "EBAY", "QCOM", "CVX",
             "CSCO", "GS", "CRM", "JPM"]
PHASE2   = ["MU", "HON", "MA", "NFLX", "INTC", "V", "GILD", "BIIB", "MMM"]
PE_EXP   = ["PFE", "MRK", "LLY", "ABBV", "JNJ", "BMY", "BAC", "WFC", "C",
             "WMT", "TGT", "HD", "LOW", "MCD", "NKE", "PG", "KO", "PEP",
             "CAT", "DE", "BA", "GE", "PYPL", "PANW", "NOW"]
SECTOR   = ["XLF", "XLE", "XLV", "XLU", "XLI", "XLK", "XLP", "XLB", "XLY", "GLD"]
TICKERS  = ["SPY", "QQQ", "IWM"] + SECTOR + UNIVERSE + PHASE1 + PHASE2 + PE_EXP

_CACHE = _ROOT / "raits" / "data" / "cache"
PICKLE_5MIN  = _CACHE / "window_debug_5min.pkl"
PICKLE_DAILY = _CACHE / "window_debug_daily.pkl"

_PARAMS_FILE = _ROOT / "raits" / "configs" / "final_params.yaml"

N_BOOT    = 10_000
SEED      = 42
BLOCK_SZ  = 20          # trading days per block for block bootstrap
N_BOOT_BK = 5_000       # block bootstrap (slower — use fewer iterations)

TARGET_STRATS = {"FADE", "GAP_FILL", "VWAP_MR"}

# YbY p-values from bootstrap_strategy.py (original wrong-design run)
_YBY_P = {"FADE": 0.754, "GAP_FILL": 0.687, "VWAP_MR": 0.613}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_params() -> dict:
    import yaml
    with open(_PARAMS_FILE) as f:
        return yaml.safe_load(f)


def _make_config(params: dict) -> BacktestConfig:
    return BacktestConfig(
        account_equity=50_000.0,
        start_date=IS_START,
        end_date=IS_END,
        universe=UNIVERSE + PHASE1 + PHASE2,
        orb_universe=list(CANDIDATE_POOL),
        vwap_universe=["SPY", "QQQ", "IWM"],
        orb_range_minutes=params["orb_range_minutes"],
        vwap_bb_std=params["vwap_bb_std"],
        ema_period=params["ema_period"],
        max_risk_pct=0.015,
        max_position_pct=0.40,
        kelly_fraction=0.75,
        enable_costs=True,
        enable_pdt_guard=True,
        hmm_retrain_weekly=True,
        allow_swing_hold=True,
        max_hold_days=5,
        stress_size_fraction=0.5,
        log_level="WARNING",
        # FADE needs the scanner to get a non-empty _effective_fade_universe
        use_fade_scanner=True,
        fade_scanner_top_n=10,
    )


def _load_market_data() -> Tuple[dict, dict]:
    print("  Loading 5-min data...", end=" ", flush=True)
    with open(PICKLE_5MIN, "rb") as f:
        raw5 = pickle.load(f)
    market_data = {t: df for t, df in raw5.items() if t in TICKERS}
    for t in list(market_data):
        df = market_data[t]
        market_data[t] = df[(df.index >= pd.Timestamp(IS_START)) &
                             (df.index <= pd.Timestamp(IS_END))]
    print(f"{len(market_data)} tickers")

    print("  Loading daily data...", end=" ", flush=True)
    with open(PICKLE_DAILY, "rb") as f:
        daily_data = pickle.load(f)
    print(f"{len(daily_data)} tickers")
    return market_data, daily_data


# ── Bootstrap methods ─────────────────────────────────────────────────────────

def iid_bootstrap_p(pnls: np.ndarray, n_boot: int, rng: np.random.Generator) -> float:
    if len(pnls) == 0:
        return 1.0
    boot = rng.choice(pnls, size=(n_boot, len(pnls)), replace=True).mean(axis=1)
    return float((boot <= 0).mean())


def block_bootstrap_p(pnls: np.ndarray, block_size: int, n_boot: int,
                       rng: np.random.Generator) -> float:
    """
    Circular block bootstrap.
    Randomly pick start indices, take overlapping blocks of `block_size`,
    concatenate until we reach N samples, compute mean, repeat.
    Preserves autocorrelation within blocks.
    """
    n = len(pnls)
    if n < 2:
        return 1.0
    # Wrap-around: extend array to handle circular blocks
    extended = np.concatenate([pnls, pnls[:block_size]])
    n_blocks = int(np.ceil(n / block_size))
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.integers(0, n, size=n_blocks)
        blocks = [extended[s:s + block_size] for s in starts]
        sample = np.concatenate(blocks)[:n]
        boot_means[i] = sample.mean()
    return float((boot_means <= 0).mean())


def jackknife_top_k(pnls: np.ndarray, k: int, n_boot: int,
                     rng: np.random.Generator) -> Tuple[float, List[float]]:
    if k >= len(pnls):
        return 1.0, []
    idx = np.argsort(pnls)[::-1]
    removed = pnls[idx[:k]].tolist()
    trimmed = np.delete(pnls, idx[:k])
    p = iid_bootstrap_p(trimmed, n_boot, rng)
    return p, removed


def _verdict(p: float) -> str:
    if p < 0.05:  return "CONFIRMED"
    if p < 0.15:  return "BORDERLINE"
    return "NO EDGE"


# ── Robustness analysis for a single strategy ─────────────────────────────────

def analyse_strategy(name: str, pnls: np.ndarray, rng: np.random.Generator) -> dict:
    n   = len(pnls)
    mu  = float(pnls.mean()) if n else 0.0
    sd  = float(pnls.std())  if n else 0.0
    cd  = mu / sd if sd > 0 else 0.0
    t   = mu / (sd / np.sqrt(n)) if (n > 0 and sd > 0) else 0.0
    wr  = float((pnls > 0).mean()) if n else 0.0

    p_iid   = iid_bootstrap_p(pnls, N_BOOT, rng)
    p_block = block_bootstrap_p(pnls, BLOCK_SZ, N_BOOT_BK, rng)

    jk = []
    for k in [1, 2, 3]:
        pk, removed = jackknife_top_k(pnls, k, max(1000, N_BOOT // 10), rng)
        jk.append((k, pk, removed))

    # Verdict bucket
    v_iid   = _verdict(p_iid)
    v_block = _verdict(p_block)

    if p_iid > 0.30:
        bucket = "removal-correct"
    elif p_iid < 0.05 and p_block < 0.10:
        # Check jackknife robustness
        p_jk1 = jk[0][1]
        if p_jk1 < 0.10:
            bucket = "removal-was-error"
        else:
            bucket = "uncertain-needs-OOS"
    elif p_iid < 0.10:
        p_jk1 = jk[0][1]
        if p_jk1 < 0.15:
            bucket = "uncertain-needs-OOS"
        else:
            bucket = "uncertain-needs-OOS"
    else:
        bucket = "uncertain-needs-OOS"

    return {
        "name": name, "n": n, "mu": mu, "sd": sd, "wr": wr,
        "t": t, "cohen_d": cd,
        "p_iid": p_iid, "p_block": p_block,
        "v_iid": v_iid, "v_block": v_block,
        "jackknife": jk,
        "pnls": pnls,
        "bucket": bucket,
    }


# ── Report builder ────────────────────────────────────────────────────────────

def build_report(results: List[dict], run_time_s: float) -> str:
    lines: List[str] = []
    W = 88

    def h(title: str) -> None:
        lines.append("")
        lines.append("=" * W)
        lines.append(f"  {title}")
        lines.append("=" * W)

    h("REMOVED STRATEGIES — Continuous IS design (Kelly=0.75, PDT on, 2017-2022)")
    lines.append(f"  Engine run time: {run_time_s:.0f}s")
    lines.append(f"  IID N_BOOT={N_BOOT}, Block N_BOOT={N_BOOT_BK} block_size={BLOCK_SZ} days")
    lines.append(f"  YbY p (wrong design): FADE={_YBY_P['FADE']}, GAP_FILL={_YBY_P['GAP_FILL']}, VWAP_MR={_YBY_P['VWAP_MR']}")
    lines.append("")
    lines.append("  Summary:")
    hdr = f"  {'Strategy':<12} {'N':>5}  {'WR%':>6} {'Avg$':>8} {'YbY p':>8} {'IID p':>8} {'Blk p':>8}  {'IID verdict':>12}  {'Blk verdict':>12}  BUCKET"
    lines.append(hdr)
    lines.append(f"  {'-'*len(hdr)}")
    for r in results:
        lines.append(
            f"  {r['name']:<12} {r['n']:>5}  {r['wr']*100:>5.1f}% {r['mu']:>8.2f} "
            f"{_YBY_P.get(r['name'], float('nan')):>8.3f} {r['p_iid']:>8.3f} {r['p_block']:>8.3f}  "
            f"{r['v_iid']:>12}  {r['v_block']:>12}  {r['bucket']}"
        )

    for r in results:
        h(f"{r['name']} -- Detail")
        lines.append(f"  N={r['n']}  WR={r['wr']*100:.1f}%  Mean=${r['mu']:.2f}  Std=${r['sd']:.2f}")
        lines.append(f"  t-stat={r['t']:.3f}  Cohen's d={r['cohen_d']:.4f}")
        lines.append(f"  IID p={r['p_iid']:.3f} ({r['v_iid']})   Block p={r['p_block']:.3f} ({r['v_block']})")
        lines.append(f"  YbY p={_YBY_P.get(r['name'], 'N/A')}")
        lines.append("")

        lines.append("  Jackknife (remove top k winning trades):")
        lines.append(f"  {'k':>4}  {'new N':>6}  {'IID p':>8}  {'verdict':>12}  top trades removed")
        lines.append(f"  {'-'*60}")
        for k, pk, removed in r["jackknife"]:
            top_str = ", ".join(f"${v:.0f}" for v in sorted(removed, reverse=True))
            lines.append(f"  {k:>4}  {r['n']-k:>6}  {pk:>8.3f}  {_verdict(pk):>12}  [{top_str}]")

        # Top trades
        if r["n"] > 0:
            pnls = r["pnls"]
            top_idx = np.argsort(pnls)[::-1][:5]
            lines.append(f"\n  Top 5 trades by P&L:")
            for i, idx in enumerate(top_idx):
                pct = pnls[idx] / pnls.sum() * 100 if pnls.sum() != 0 else 0.0
                lines.append(f"    #{i+1}: ${pnls[idx]:>8.2f}  ({pct:.1f}% of total P&L)")

        lines.append("")
        lines.append(f"  VERDICT: {r['bucket'].upper()}")
        # Explanation per bucket
        if r["bucket"] == "removal-correct":
            lines.append(
                f"  p={r['p_iid']:.3f} on continuous design — no edge. YbY verdict was correct.\n"
                f"  Strategy does not gain edge on the correct design. Removal stands."
            )
        elif r["bucket"] == "removal-was-error":
            lines.append(
                f"  p_iid={r['p_iid']:.3f} AND p_block={r['p_block']:.3f} both significant.\n"
                f"  Jackknife-1: p={r['jackknife'][0][1]:.3f} — verdict survives removal of top trade.\n"
                f"  Cohen's d={r['cohen_d']:.4f} indicates genuine per-trade edge.\n"
                f"  ** The removal decision was made on the wrong design and may be an error.\n"
                f"  ** However, do NOT auto-re-add. This requires deliberate re-evaluation."
            )
        else:
            lines.append(
                f"  IID p={r['p_iid']:.3f} but block p={r['p_block']:.3f} or jackknife fragile.\n"
                f"  Cannot distinguish edge from noise on this looked-at IS dataset.\n"
                f"  Do not re-add. OOS is the correct arbiter."
            )

    h("FINAL SUMMARY")
    lines.append("""
  FRAMEWORK REMINDER:
    - A ROBUST flip (low IID p AND low block p AND survives jackknife) = potential error.
      Valid to reconsider removal — but requires deliberate decision, not auto re-add.
    - A FRAGILE flip (IID p near 0.05, dies under jackknife or block) = noise on a
      dataset that has been heavily examined. Re-adding would be overfitting.
    - No flip (p stays high) = removal was correct on both designs.
    - "uncertain-needs-OOS" = the IS data cannot distinguish edge from noise.
      OOS is the only valid test.
""")

    for r in results:
        lines.append(f"  {r['name']:<12}: {r['bucket']:30}  (IID p={r['p_iid']:.3f}, block p={r['p_block']:.3f})")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 70)
    print("DIAGNOSE REMOVED STRATEGIES — Continuous IS")
    print("=" * 70)
    print(f"\nPatched _REGIME_STRATEGIES: {_engine_module._REGIME_STRATEGIES}")
    print("\nLoading market data...")
    market_data, daily_data = _load_market_data()
    params = _load_params()
    config = _make_config(params)

    print("\nRunning engine with FADE/GAP_FILL/VWAP_MR re-enabled (~25 min)...")
    t0 = time.time()
    engine = BacktestEngine(config)
    result = engine.run(market_data, daily_data)
    elapsed = time.time() - t0
    all_trades = result.trade_log

    print(f"\nEngine done: {len(all_trades)} total trades | ${sum(t.net_pnl or 0 for t in all_trades):,.2f} | {elapsed:.0f}s")

    # Extract per-strategy P&L for the 3 target strategies
    by_strat: Dict[str, List[float]] = {}
    for t in all_trades:
        s = getattr(t, "strategy", None)
        p = getattr(t, "net_pnl", None)
        if s and p is not None and s in TARGET_STRATS:
            by_strat.setdefault(s, []).append(float(p))

    # Report totals for context
    other_trades = [t for t in all_trades if getattr(t, "strategy", None) not in TARGET_STRATS]
    print(f"\nNon-target strategies: {len(other_trades)} trades")
    for s in TARGET_STRATS:
        pnls = by_strat.get(s, [])
        print(f"  {s}: {len(pnls)} trades | ${sum(pnls):,.2f}")

    # Check for empty strategies (may indicate config issue)
    for s in TARGET_STRATS:
        if s not in by_strat:
            print(f"  WARNING: {s} produced 0 trades — check scanner config or universe")

    print("\nRunning bootstrap + robustness tests...")
    rng = np.random.default_rng(SEED)
    results = []
    for s in sorted(TARGET_STRATS):
        pnls = np.array(by_strat.get(s, []))
        print(f"  {s} (N={len(pnls)})...", end=" ", flush=True)
        r = analyse_strategy(s, pnls, rng)
        results.append(r)
        print(f"IID p={r['p_iid']:.3f}, block p={r['p_block']:.3f} -> {r['bucket']}")

    report = build_report(results, elapsed)
    print("\n" + report)

    out_dir = Path("raits/configs") if Path("raits/configs").is_dir() else Path("configs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "removed_strategies_report.txt"
    out.write_text(report, encoding="utf-8")
    print(f"\nSaved: {out}", file=sys.stderr)

    # Restore original _REGIME_STRATEGIES (good practice)
    _engine_module._REGIME_STRATEGIES = _ORIGINAL_REGIME


if __name__ == "__main__":
    main()
