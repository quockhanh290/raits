"""
diagnose_first_divergence.py
----------------------------
Find the FIRST bar where BacktestEngine and RefactoredBacktestEngine diverge.

Strategy:
  1. Run both engines on IS 2017 (or read cache).
  2. Build per-bar entry/exit event maps from trade logs.
  3. Walk every SPY bar in time order; stop at first mismatch.
  4. Show: bar_ts, what each engine did, open positions before that bar,
     full field detail for the divergent trade.

No engine modification.  Read-only analysis.

Usage:
    cd d:\\raits\\raits
    python raits/scripts/diagnose_first_divergence.py
    python raits/scripts/diagnose_first_divergence.py --no-cache
    python raits/scripts/diagnose_first_divergence.py --year 2018
"""

import sys, os, pickle, warnings, time, argparse, hashlib
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
warnings.filterwarnings("ignore")

import yaml, pandas as pd
from collections import defaultdict


def _code_hash() -> str:
    """SHA-256 of the two files whose changes should bust the results cache."""
    h = hashlib.sha256()
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    for rel in (
        "raits/backtest/engine_refactored.py",
        "raits/decision/decision_unit.py",
    ):
        path = os.path.join(root, rel)
        if os.path.exists(path):
            h.update(open(path, "rb").read())
    return h.hexdigest()[:16]

from raits.backtest.engine            import BacktestEngine
from raits.backtest.engine_refactored import RefactoredBacktestEngine
from raits.backtest.data_types        import BacktestConfig
from raits.strategies.universe_scanner import CANDIDATE_POOL

# ── Universe (must match diagnose_parallel_run.py exactly) ───────────────────
UNIVERSE = ["TSLA", "NVDA", "AAPL", "META", "AMZN", "MSFT", "AMD", "GOOGL"]
PHASE1   = ["INTU","COST","VRTX","AMAT","REGN","AVGO","ADBE","MS",
             "SBUX","TXN","XOM","AMGN","ORCL","EBAY","QCOM","CVX",
             "CSCO","GS","CRM","JPM"]
PHASE2   = ["MU","HON","MA","NFLX","INTC","V","GILD","BIIB","MMM"]
PE_EXP   = ["PFE","MRK","LLY","ABBV","JNJ","BMY",
             "BAC","WFC","C","WMT","TGT","HD","LOW","MCD","NKE",
             "PG","KO","PEP","CAT","DE","BA","GE","PYPL","PANW","NOW"]
SECT_ETF = ["XLF","XLE","XLV","XLU","XLI","XLK","XLP","XLB","XLY","GLD"]
ALL_UNI  = UNIVERSE + PHASE1 + PHASE2
TICKERS  = ["SPY","QQQ","IWM"] + SECT_ETF + UNIVERSE + PHASE1 + PHASE2 + PE_EXP

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PICKLE_5MIN  = os.path.join(_SCRIPTS_DIR, "..", "..", "data", "cache", "window_debug_5min.pkl")
PICKLE_DAILY = os.path.join(_SCRIPTS_DIR, "..", "..", "data", "cache", "window_debug_daily.pkl")
CACHE_DIR    = os.path.join(_SCRIPTS_DIR, "..", "..", "data", "cache")
PARAMS_PATH  = os.path.join(_SCRIPTS_DIR, "..", "..", "configs", "final_params.yaml")


def load_params():
    with open(PARAMS_PATH) as f:
        return yaml.safe_load(f)


def make_config(params, year):
    return BacktestConfig(
        account_equity=50_000.0,
        start_date=f"{year}-01-01",
        end_date=f"{year}-12-31",
        universe=ALL_UNI,
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
    )


def run_engine(engine_cls, market_data, daily_data, config, label):
    t0 = time.time()
    engine = engine_cls(config)
    result = engine.run(market_data, daily_data)
    elapsed = time.time() - t0
    trades = result.trade_log
    print(f"  {label}: {len(trades)} trades  ({elapsed:.1f}s)", flush=True)
    return trades


# ── Event-timeline helpers ────────────────────────────────────────────────────

def build_maps(trades):
    """Return (entry_map, exit_map): bar_ts -> list[trade]."""
    entry_map = defaultdict(list)
    exit_map  = defaultdict(list)
    for t in trades:
        entry_map[pd.Timestamp(t.entry_time)].append(t)
        if t.exit_time is not None:
            exit_map[pd.Timestamp(t.exit_time)].append(t)
    return entry_map, exit_map


def event_key(t):
    """Canonical key for comparing trade events (ignore timestamps and prices)."""
    return (t.ticker, t.strategy, t.direction)


def open_before(trades, bar_ts):
    """Trades open at START of bar_ts: entered strictly before, not yet exited."""
    return [
        t for t in trades
        if pd.Timestamp(t.entry_time) < bar_ts
        and (t.exit_time is None or pd.Timestamp(t.exit_time) >= bar_ts)
    ]


# ── Core divergence finder ────────────────────────────────────────────────────

def find_first_divergence(orig_trades, refac_trades, all_bar_ts):
    orig_em,  orig_xm  = build_maps(orig_trades)
    refac_em, refac_xm = build_maps(refac_trades)

    for bar_ts in all_bar_ts:
        oe = {event_key(t) for t in orig_em[bar_ts]}
        re = {event_key(t) for t in refac_em[bar_ts]}
        ox = {event_key(t) for t in orig_xm[bar_ts]}
        rx = {event_key(t) for t in refac_xm[bar_ts]}

        if oe != re or ox != rx:
            return dict(
                bar_ts       = bar_ts,
                orig_entries = oe,
                refac_entries= re,
                orig_exits   = ox,
                refac_exits  = rx,
                orig_entry_trades  = orig_em[bar_ts],
                refac_entry_trades = refac_em[bar_ts],
                orig_exit_trades   = orig_xm[bar_ts],
                refac_exit_trades  = refac_xm[bar_ts],
            )
    return None


# ── Report helpers ────────────────────────────────────────────────────────────

def show_trade(label, t):
    target = getattr(t, "target", None)
    hmm    = getattr(t, "hmm_state", "?")
    print(f"    {label}: {t.ticker:<8} {t.strategy:<14} {t.direction:<6}"
          f" entry=${t.entry_price:.4f}  stop=${t.stop:.4f}"
          f"  target={target!r}  shares={t.shares}  hmm={hmm}")


def print_divergence_report(div, orig_trades, refac_trades):
    bar_ts = div["bar_ts"]
    print(f"\n{'='*72}")
    print(f"  FIRST DIVERGENCE:  {bar_ts}")
    print(f"{'='*72}")

    in_orig_only  = div["orig_entries"]  - div["refac_entries"]
    in_refac_only = div["refac_entries"] - div["orig_entries"]

    if in_orig_only or in_refac_only:
        print("\n  ENTRY DIFFERENCE:")
        for k in sorted(in_orig_only):
            print(f"    MISSING from refac:  {k}")
        for k in sorted(in_refac_only):
            print(f"    EXTRA  in   refac:   {k}")

    exit_orig_only  = div["orig_exits"]  - div["refac_exits"]
    exit_refac_only = div["refac_exits"] - div["orig_exits"]

    if exit_orig_only or exit_refac_only:
        print("\n  EXIT DIFFERENCE:")
        for k in sorted(exit_orig_only):
            print(f"    MISSING exit in refac:  {k}")
        for k in sorted(exit_refac_only):
            print(f"    EXTRA  exit in refac:   {k}")

    # ── Open positions before this bar ───────────────────────────────────────
    o_before = open_before(orig_trades, bar_ts)
    r_before = open_before(refac_trades, bar_ts)
    o_keys   = {event_key(t) for t in o_before}
    r_keys   = {event_key(t) for t in r_before}
    all_keys = sorted(o_keys | r_keys)

    print(f"\n  OPEN POSITIONS BEFORE {bar_ts}  (orig={len(o_before)}  refac={len(r_before)}):")
    if o_keys == r_keys:
        print("    [identical in both engines]")
        for k in all_keys:
            print(f"    OK {k[0]:<10} {k[1]:<16} {k[2]}")
    else:
        print(f"    {'Ticker':<10} {'Strategy':<16} {'Dir':<6}  Orig  Refac")
        for k in all_keys:
            in_o = "Y" if k in o_keys else "N"
            in_r = "Y" if k in r_keys else "N"
            flag = "  <- DIFF" if (k in o_keys) != (k in r_keys) else ""
            print(f"    {k[0]:<10} {k[1]:<16} {k[2]:<6}  {in_o}     {in_r}{flag}")

    # ── Capacity summary ──────────────────────────────────────────────────────
    tf_orig  = sum(1 for t in o_before if t.strategy == "TREND_FOLLOW")
    tf_refac = sum(1 for t in r_before if t.strategy == "TREND_FOLLOW")
    print(f"\n  TF capacity before bar:  orig={tf_orig}  refac={tf_refac}")

    # ── Full detail for the divergent trade(s) ────────────────────────────────
    print(f"\n  ALL ENTRIES AT {bar_ts}:")
    if not div["orig_entry_trades"] and not div["refac_entry_trades"]:
        print("    (none)")
    for t in div["orig_entry_trades"]:
        k = event_key(t)
        tag = "[MISSING in refac]" if k in in_orig_only else "[MATCH]"
        show_trade(f"ORIG  {tag}", t)
    for t in div["refac_entry_trades"]:
        k = event_key(t)
        tag = "[EXTRA in refac]" if k in in_refac_only else "[MATCH]"
        show_trade(f"REFAC {tag}", t)

    print(f"\n  ALL EXITS AT {bar_ts}:")
    if not div["orig_exit_trades"] and not div["refac_exit_trades"]:
        print("    (none)")
    for t in div["orig_exit_trades"]:
        k = event_key(t)
        tag = "[MISSING in refac]" if k in exit_orig_only else "[MATCH]"
        print(f"    ORIG  {tag}: {t.ticker} {t.strategy} {t.direction}  reason={t.exit_reason}  exit_px=${t.exit_price:.4f}")
    for t in div["refac_exit_trades"]:
        k = event_key(t)
        tag = "[EXTRA in refac]" if k in exit_refac_only else "[MATCH]"
        print(f"    REFAC {tag}: {t.ticker} {t.strategy} {t.direction}  reason={t.exit_reason}  exit_px=${t.exit_price:.4f}")

    # ── Context: trades within 3 calendar days before divergence ────────────
    cutoff = bar_ts - pd.Timedelta(days=3)
    print(f"\n  RECENT TRADES (last 3 days before divergence, both engines):")
    recent_o = [t for t in orig_trades
                if cutoff <= pd.Timestamp(t.entry_time) < bar_ts]
    recent_r = [t for t in refac_trades
                if cutoff <= pd.Timestamp(t.entry_time) < bar_ts]
    o_keys_recent = {(t.ticker, t.strategy, t.direction, str(t.entry_time)) for t in recent_o}
    r_keys_recent = {(t.ticker, t.strategy, t.direction, str(t.entry_time)) for t in recent_r}
    both_recent = sorted(o_keys_recent | r_keys_recent, key=lambda x: x[3])
    for k in both_recent:
        in_o = "O" if k in o_keys_recent else " "
        in_r = "R" if k in r_keys_recent else " "
        flag = " <-" if (k in o_keys_recent) != (k in r_keys_recent) else ""
        print(f"    [{in_o}{in_r}]  {k[3]}  {k[0]:<8} {k[1]:<14} {k[2]}{flag}")


COMPARED_FIELDS = [
    "ticker", "strategy", "direction",
    "entry_time", "entry_price", "shares",
    "exit_time", "exit_price", "exit_reason",
    "stop", "target", "hmm_state",
    "gross_pnl", "net_pnl",
]


def _field_compare(orig_trades, refac_trades):
    print(f"\n{'='*72}")
    print("FIELD-BY-FIELD COMPARISON")
    print(f"{'='*72}")

    if len(orig_trades) != len(refac_trades):
        print(f"  COUNT MISMATCH: orig={len(orig_trades)} refac={len(refac_trades)}")
        return

    mismatches = []
    for i, (a, b) in enumerate(zip(orig_trades, refac_trades)):
        for field in COMPARED_FIELDS:
            va = getattr(a, field, None)
            vb = getattr(b, field, None)
            if isinstance(va, float) and isinstance(vb, float):
                ok = abs(va - vb) < 0.01
            else:
                ok = (va == vb)
            if not ok:
                mismatches.append({
                    "i": i, "ticker": getattr(a, "ticker", "?"),
                    "strategy": getattr(a, "strategy", "?"),
                    "entry_time": str(getattr(a, "entry_time", "?")),
                    "field": field, "orig": va, "refac": vb,
                })

    n = len(orig_trades)
    bad_trades = len({m["i"] for m in mismatches})
    if not mismatches:
        print(f"\n  OK {n}/{n} trades match 100% on all fields.")
    else:
        print(f"\n  {n - bad_trades}/{n} trades fully clean  |  {bad_trades} trades have mismatches")
        print(f"  Total field mismatches: {len(mismatches)}\n")
        for m in mismatches:
            print(f"  trade[{m['i']:>3}]  {m['ticker']:<8} {m['strategy']:<14} "
                  f"@ {m['entry_time']}   "
                  f"{m['field']}: orig={m['orig']!r}  refac={m['refac']!r}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--year",     type=int, default=2017)
    args = parser.parse_args()

    cache_path = os.path.join(CACHE_DIR, f"first_div_{args.year}.pkl")
    current_hash = _code_hash()

    # Invalidate cache if --no-cache flag OR source files changed since last run
    def _cache_valid():
        if not os.path.exists(cache_path):
            return False
        try:
            with open(cache_path, "rb") as f:
                data = pickle.load(f)
            saved_hash = data[3] if len(data) == 4 else None
            if saved_hash != current_hash:
                print(f"Cache hash mismatch ({saved_hash} vs {current_hash}) — re-running.")
                return False
            return True
        except Exception:
            return False

    if args.no_cache and os.path.exists(cache_path):
        os.remove(cache_path)
        print(f"Removed cache: {cache_path}")

    print("=" * 72)
    print(f"RAITS First-Divergence Diagnostic  (year={args.year})  hash={current_hash}")
    print("=" * 72)

    # ── Run or load ───────────────────────────────────────────────────────────
    if _cache_valid():
        print(f"Loading from cache: {cache_path}")
        with open(cache_path, "rb") as f:
            orig_trades, refac_trades, market_data_year, _ = pickle.load(f)
    else:
        print("Loading 5-min data...", end=" ", flush=True)
        with open(PICKLE_5MIN, "rb") as f:
            all_data = pickle.load(f)
        market_data_full = {t: df for t, df in all_data.items() if t in TICKERS}
        print(f"{len(market_data_full)} tickers")

        daily_data = None
        if os.path.exists(PICKLE_DAILY):
            with open(PICKLE_DAILY, "rb") as f:
                daily_data = pickle.load(f)

        start = pd.Timestamp(f"{args.year}-01-01")
        end   = pd.Timestamp(f"{args.year}-12-31 23:59:59")
        market_data_year = {
            t: df[(df.index >= start) & (df.index <= end)]
            for t, df in market_data_full.items()
        }

        params = load_params()
        config = make_config(params, args.year)

        print("\nRunning BacktestEngine (original)...", flush=True)
        orig_trades = run_engine(BacktestEngine, market_data_year, daily_data, config, "Orig")

        print("\nRunning RefactoredBacktestEngine...", flush=True)
        refac_trades = run_engine(RefactoredBacktestEngine, market_data_year, daily_data, config, "Refac")

        with open(cache_path, "wb") as f:
            pickle.dump((orig_trades, refac_trades, market_data_year, current_hash), f)
        print(f"Cached to: {cache_path}  hash={current_hash}")

    print(f"\nOrig={len(orig_trades)} trades   Refac={len(refac_trades)} trades"
          f"  (delta={len(refac_trades)-len(orig_trades):+d})")

    # ── Build timeline ────────────────────────────────────────────────────────
    spy_data = market_data_year.get("SPY", pd.DataFrame())
    all_bar_ts = sorted(spy_data.index)
    print(f"Timeline: {len(all_bar_ts)} bars in {args.year}")

    # ── Find first divergence ─────────────────────────────────────────────────
    print("Scanning for first entry/exit divergence...", flush=True)
    div = find_first_divergence(orig_trades, refac_trades, all_bar_ts)

    if div is None:
        print("\nOK NO ENTRY/EXIT DIVERGENCE at any bar.")
        _field_compare(orig_trades, refac_trades)
        return

    print_divergence_report(div, orig_trades, refac_trades)

    print(f"\n{'-'*72}")
    print("NEXT: run both engines on just the divergence day with detailed")
    print("per-candidate traces to identify the differing input.")


if __name__ == "__main__":
    main()
