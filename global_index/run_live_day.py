"""
global_index/run_live_day.py
============================
PRODUCTION ENTRY POINT — IBKRBroker → FuturesRunner → run_day(today).

Verifies the full paper-trading wire end-to-end:
  1. IBKRBroker connects to IB Gateway (port 4002 paper)
  2. B3 reconcile: live_positions.json vs IBKR positions on startup
  3. Rollover check: _handle_rollover_if_needed(today)
  4. fetch_bars from IBKR for all 5 instruments
  5. signal_fn using pre-computed backtest timelines (same as smoke test)
  6. send_order() → IBKR for any entry/exit decisions
  7. dump_state() → live_positions.json after run_day completes

Signal note:
    signal_fn uses pre-computed backtest timelines (fit_C, 2024-12-31).
    Signals for dates AFTER the parquet data coverage are empty (no orders).
    To get live signals: update parquet files to today first (A5 step).
    --dry-run bypasses this by returning empty signals explicitly.

Usage:
    cd d:\\raits
    python -m global_index.run_live_day \\
        --data-dir data\\cache\\futures \\
        --nkd-parquet global_index/data/NKD_continuous_1m_8y.parquet \\
        --regime-csv spy_daily.csv \\
        [--port 4002] \\
        [--client-id 1] \\
        [--positions-path live_positions.json] \\
        [--lock-path runner.pid] \\
        [--dry-run]

    # Wire-only (no orders): add --dry-run
    # Paper trading default: IB Gateway port 4002
    # DO NOT use port 7496/7497 (live/paper TWS) without explicit intent
"""
from __future__ import annotations
import argparse, json, logging, sys, time
from pathlib import Path

# ── [1] CWD guard — must be d:\raits before anything else ──────────────────
_CWD = Path.cwd()
_has_gi  = (_CWD / "global_index").is_dir()
_has_fut = (_CWD / "futures").is_dir()
if not (_has_gi and _has_fut):
    sys.stderr.write(
        f"CWD guard FAIL: got {_CWD}\n"
        f"  Expected d:\\raits (global_index/ and futures/ must exist as subdirs).\n"
        f"  Fix: cd d:\\raits && python -m global_index.run_live_day ...\n"
    )
    sys.exit(1)

if str(_CWD) not in sys.path:
    sys.path.insert(0, str(_CWD))

# ── [2] UTF-8: reconfigure before any print with non-ASCII ─────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

# ── [3] Production imports ──────────────────────────────────────────────────
from futures.basket import BASKET, REGIME, RISK, SWING_TF_PARAM, data_filename
from futures.swing_tf import SwingTFEngine, costs_for_basket
from futures.stress_mid import StressMidEngine
from futures.circuit_breaker import CircuitBreaker
from futures._validated_core import load_parquet, benchmark_daily, label_regimes
from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from global_index.net_exposure_multi import MultiClusterGuard
from global_index.signal_layer import generate_today_signals
from global_index.ibkr_broker import IBKRBroker
from global_index.runner import FuturesRunner, _openpos_from_dict

# ── Production constants: from basket.py ────────────────────────────────────
ACCOUNT     = float(RISK["account"])    # $50,000
HMM_FIT_END = REGIME["hmm_fit_end"]    # "2024-12-31"
SLIPPAGE    = 2.0
NKD_INST    = "MNKD"
NKD_EMA     = 10
NKD_MULT_PARAM = SWING_TF_PARAM.get("chandelier_atr_mult", 2.5)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_live_day")


def main():
    ap = argparse.ArgumentParser(description="RAITS live paper trading — run_day(today)")
    ap.add_argument("--data-dir",        required=True,
                    help="Directory with parquet files for BASKET instruments")
    ap.add_argument("--nkd-parquet",     required=True,
                    help="NKD continuous 1m parquet file")
    ap.add_argument("--regime-csv",      required=True,
                    help="spy_daily.csv for HMM labels")
    ap.add_argument("--port",            type=int, default=4002,
                    help="IB Gateway port (default: 4002 paper)")
    ap.add_argument("--client-id",       type=int, default=1,
                    help="IBKR client ID (default: 1)")
    ap.add_argument("--positions-path",  default="live_positions.json",
                    help="JSON file for persistent position state (B1/B3)")
    ap.add_argument("--lock-path",       default="runner.pid",
                    help="PID lockfile (E1 duplicate-runner guard)")
    ap.add_argument("--dry-run",         action="store_true",
                    help="Connect + fetch bars but emit no orders (empty signal_fn)")
    ap.add_argument("--print-signals",   action="store_true",
                    help="Connect + fetch bars + compute real signals, print candidates, no orders")
    ap.add_argument("--live-state-path", default=None,
                    help="Path to write live_state_data.js for dashboard live mode "
                         "(e.g. global_index/live_state_data.js). Omit to skip dashboard update.")
    a = ap.parse_args()

    today = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    print("=" * 72)
    print("RAITS — live paper trading day")
    print(f"  CWD:            {_CWD}")
    print(f"  today:          {today.date()}")
    print(f"  port:           {a.port}  (paper=4002, live=4001)")
    print(f"  positions-path: {a.positions_path}")
    print(f"  dry-run:        {a.dry_run}")
    print("=" * 72)

    # ── Frozen integrity fast-check (size-only, <0.1s) ──────────────────────
    # WARNING when not OK (missing manifest, size mismatch) — never blocks paper.
    # "Silent pass" would conflate "unverified" with "verified OK" — avoid that.
    try:
        from global_index.verify_frozen import quick_check_manifest
        ok, issues = quick_check_manifest()
    except Exception as _e:
        ok, issues = False, [f"verify_frozen import failed: {_e}"]

    if not ok:
        print("!" * 72)
        print("  WARNING: frozen integrity check — UNVERIFIED (paper continues)")
        for iss in issues:
            print(f"  {iss}")
        print("  Size-only check; full verify: python -m global_index.verify_frozen verify")
        print("!" * 72)
        log.warning("[frozen] %d integrity issue(s) — see banner above", len(issues))
    else:
        log.info("[frozen] Primary frozen files intact (size check OK)")

    # ── Load bar data ────────────────────────────────────────────────────────
    log.info("[data] Loading parquet bar data...")
    dfs = {n: load_parquet(str(Path(a.data_dir) / data_filename(c)))
           for n, c in BASKET.items()}
    c_nkd = gi_specs.SPECS[NKD_INST]
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(c_nkd.session_tz)
    log.info("  Basket: %s | NKD: %d bars", list(dfs.keys()), len(ndf))

    # ── HMM fit_C labels ─────────────────────────────────────────────────────
    log.info("[hmm]  fit_C labels (hmm_fit_end=%s)...", HMM_FIT_END)
    bench        = benchmark_daily(a.regime_csv)
    swing_labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
    spy_s        = pd.Series(swing_labels)
    idx          = pd.DatetimeIndex(spy_s.index)
    spy_s.index  = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    nkd_labels   = RegimeLabels(spy_s.sort_index(), lag_days=1)
    sl_s         = spy_s.sort_index()

    def _regime(day_ts):
        d = pd.Timestamp(day_ts).normalize()
        if d.tzinfo is not None:
            d = d.tz_localize(None)
        try:
            v = sl_s.asof(d)
        except Exception:
            return None
        return str(v) if v is not None and not (isinstance(v, float) and pd.isna(v)) else None

    log.info("  %d SPY label days", len(swing_labels))

    # ── Costs + engines ──────────────────────────────────────────────────────
    # Option C: generate_today_signals() + concat(frozen_parquet + live_bars).
    # No full backtest pre-compute — desired_position() runs on concat per call.
    costs_2t     = costs_for_basket(slippage_ticks=SLIPPAGE)
    ncost_2t     = GIFC(point_value=c_nkd.point_value, tick=c_nkd.tick,
                        commission_rt=c_nkd.commission_rt, slippage_ticks_per_side=SLIPPAGE)
    swing_engine = SwingTFEngine()
    nkd_engine   = SwingTFEngine(ema_period=NKD_EMA,
                                  chandelier_atr_mult=NKD_MULT_PARAM,
                                  max_hold_days=5)
    stress_engine = StressMidEngine()   # passed to generate_today_signals; unused when stress_bars_1015={}

    # point values + contract map
    pv           = {n: c.point_value for n, c in BASKET.items()}
    pv[NKD_INST] = c_nkd.point_value
    N_CONTRACTS  = 1
    contracts_by = {n: N_CONTRACTS for n in list(BASKET) + [NKD_INST]}

    def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
        """Return df with tz-naive DatetimeIndex. load_parquet yields tz-aware US/Eastern;
        fetch_bars yields tz-naive ET. Strip tz so concat+sort_index() works without
        'Cannot compare tz-naive and tz-aware timestamps' TypeError."""
        if df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        return df

    def _concat_live(frozen_df, live_df):
        """Merge frozen parquet + live IBKR bars; live bars win on duplicate timestamps."""
        if live_df is None or live_df.empty:
            return _strip_tz(frozen_df)
        merged = pd.concat([_strip_tz(frozen_df), live_df])
        return merged[~merged.index.duplicated(keep="last")].sort_index()

    def _concat_nkd_live(frozen_nkd_df, live_nkd_et):
        """Merge frozen NKD parquet + IBKR NKD bars (both tz-naive ET after strip)."""
        if live_nkd_et is None or live_nkd_et.empty:
            return _strip_tz(frozen_nkd_df)
        merged = pd.concat([_strip_tz(frozen_nkd_df), live_nkd_et])
        return merged[~merged.index.duplicated(keep="last")].sort_index()

    # ── signal_fn — Option C ─────────────────────────────────────────────────
    # Calls generate_today_signals() with concat(frozen_parquet + live_IBKR_bars).
    # Swing/NKD: desired_position() on concat → fires at actual bar, not at 16:00.
    # STRESS_MID: stress_bars_1015={} → skipped here (needs separate 10:20 ET morning
    #   cron that passes bars through 10:15 — DEFERRED, implement as Phase C2).
    # Exit detection: desired_position() returning None → diff_desired_vs_held → exits.
    # --print-signals uses real signal_fn even when --dry-run is set.
    if a.dry_run and not a.print_signals:
        log.info("[sig]  --dry-run: signal_fn returns empty (no orders)")
        def signal_fn(day, _bars, held):
            return [], []
    else:
        def signal_fn(day, bars, held):
            day_ts = pd.Timestamp(day).normalize()

            # concat frozen parquet + live bars from IBKR (Mismatch A+B fix)
            concat_swing = {
                inst: _concat_live(dfs[inst], bars.get(inst))
                for inst in dfs
            }
            concat_nkd = _concat_nkd_live(ndf, bars.get(NKD_INST))

            return generate_today_signals(
                swing_engine=swing_engine,
                swing_dfs=concat_swing,
                swing_labels=swing_labels,
                swing_costs=costs_2t,
                nkd_engine=nkd_engine,
                nkd_df=concat_nkd,
                nkd_labels=nkd_labels,
                nkd_cost=ncost_2t,
                nkd_inst=NKD_INST,
                stress_engine=stress_engine,
                stress_bars_1015={},   # STRESS_MID deferred to Phase C2 morning cron
                today_regime=_regime(day_ts),
                held=held,
                point_values=pv,
                contracts_by_inst=contracts_by,
                today=day_ts,
            )

    # ── --print-signals: connect + fetch + compute signals, no orders ──────────
    if a.print_signals:
        log.info("[sig]  --print-signals: connect + fetch + compute, no orders")
        _ps_broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
        _ps_broker.connect()
        time.sleep(15)  # wait for IB Gateway farm connections to stabilize (2103/2104 flicker)
        try:
            # Fetch bars for all instruments.
            # _ps_through matches run_day _through (day+23:59) so signal_fn gets the same
            # live bars as the order path — IBKR caps at now, giving bars up to ~fetch time.
            # Bug history: originally through=today (midnight) — omitted when LIVE_RUNNER_AUDIT
            # changed signal_fn B→C (Option C needs live intraday bars; midnight cuts them all).
            _ps_insts   = list(contracts_by.keys())
            _ps_through = today + pd.Timedelta(hours=23, minutes=59)
            _ps_bars    = {i: _ps_broker.fetch_bars(i, through=_ps_through) for i in _ps_insts}

            # Load held positions from live_positions.json (if exists)
            _ps_held: list = []
            _ps_path = Path(a.positions_path)
            if _ps_path.exists():
                try:
                    with open(_ps_path, encoding="utf-8") as _f:
                        _raw = json.load(_f)
                    _pdata = _raw.get("positions", []) if isinstance(_raw, dict) else _raw
                    _ps_held = [_openpos_from_dict(d) for d in _pdata]
                except Exception as _e:
                    log.warning("print-signals: could not load positions: %s", _e)

            # Compute signals with real signal_fn
            _ps_entries, _ps_exits = signal_fn(today, _ps_bars, _ps_held)
            _ps_regime = _regime(today)

            # Bar coverage summary
            _bar_summary = "  ".join(
                f"{i}={'✓ ' + str(len(_ps_bars[i])) + 'b' if not _ps_bars[i].empty else '✗ EMPTY'}"
                for i in _ps_insts
            )

            print(f"\n{'='*68}")
            print(f"SIGNAL PREVIEW — {today.date()}")
            print(f"  regime:  {_ps_regime or 'unknown (stale labels?)'}")
            print(f"  held:    {len(_ps_held)} position(s)")
            print(f"  bars:    {_bar_summary}")
            print(f"  entries: {len(_ps_entries)}")
            print(f"  exits:   {len(_ps_exits)}")
            if _ps_entries:
                print()
                for c in _ps_entries:
                    _exp = f"  exp_pnl=${c.get('pnl_sized', 0):+.0f}" if c.get("pnl_sized") else ""
                    _exit = str(c.get("exit", "?").date()) if c.get("exit") else "?"
                    print(f"  ENTRY  {c.get('inst'):<5} {c.get('direction'):<5} "
                          f"×{c.get('contracts', 1)}  cluster={c.get('cluster')}"
                          f"  exit={_exit}{_exp}")
            if _ps_exits:
                print()
                for p in _ps_exits:
                    _ed = str(p.entry_day.date()) if p.entry_day else "?"
                    print(f"  EXIT   {p.inst:<5} {p.direction:<5} "
                          f"×{p.contracts}  cluster={p.cluster}  held_since={_ed}")
            if not _ps_entries and not _ps_exits:
                print("\n  (no signals for today)")
            print(f"{'='*68}\n")
        finally:
            _ps_broker.disconnect()
            log.info("[ibkr] Disconnected.")
        return

    # ── Connect IBKRBroker ───────────────────────────────────────────────────
    log.info("[ibkr] Connecting IBKRBroker → 127.0.0.1:%d clientId=%d ...",
             a.port, a.client_id)
    broker = IBKRBroker(host="127.0.0.1", port=a.port, client_id=a.client_id)
    broker.connect()
    log.info("       Connected.")

    # ── Wire runner ──────────────────────────────────────────────────────────
    runner = FuturesRunner(
        broker=broker,
        guard=MultiClusterGuard(account=ACCOUNT),
        contracts_by_inst=contracts_by,
        signal_fn=signal_fn,
        breaker=CircuitBreaker(account=ACCOUNT),
        positions_path=a.positions_path,
        lock_path=a.lock_path,
        live_state_path=a.live_state_path,
        regime_fn=_regime,
    )

    # ── run_day(today) ───────────────────────────────────────────────────────
    log.info("[run]  run_day(%s)...", today.date())
    try:
        decision = runner.run_day(today)
        log.info("[run]  run_day complete.")
        if decision is not None:
            log.info("       entries=%d  exits=%d",
                     len(getattr(decision, "entries", []) or []),
                     len(getattr(decision, "exits", []) or []))
    except Exception:
        log.exception("[run]  run_day raised — disconnecting before re-raise")
        raise
    finally:
        broker.disconnect()
        log.info("[ibkr] Disconnected.")

    print("\n" + "=" * 72)
    print("LIVE DAY COMPLETE")
    print(f"  today:         {today.date()}")
    print(f"  dry-run:       {a.dry_run}")
    print(f"  positions:     {a.positions_path}")
    print("=" * 72)


if __name__ == "__main__":
    main()
