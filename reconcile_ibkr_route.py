"""
reconcile_ibkr_route.py — standalone reconcile/test route
==========================================================
Fetch recent bars trực tiếp từ IBKR (specific Future, không dùng parquet,
không có splice offset), chạy SwingTFEngine.desired_basket(), apply
entry_day guard thủ công, in kết quả để so sánh với:

  - check_next_entry.py   (parquet-only, no offset)
  - --print-signals       (parquet + _concat_live + splice offset step-change)

Mục đích: isolate nguyên nhân discrepancy mà KHÔNG sửa bất kỳ file nào
trong hệ thống hiện tại.

Pagination: --total-days được chia thành nhiều chunks nhỏ (--chunk-days, mặc
định 20D) để tránh IBKR timeout khi request lớn (>30D gây cancel với 60s timeout).

Chạy từ d:\\raits (cùng CWD với run_live_day.py):
    python reconcile_ibkr_route.py [--port 4002] [--total-days 60] [--chunk-days 20]
"""
import argparse, datetime, logging, math, sys, time

sys.path.insert(0, ".")

import pandas as pd

from futures._validated_core import benchmark_daily, label_regimes
from futures.basket import BASKET, REGIME
from futures.swing_tf import SwingTFEngine, costs_for_basket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("reconcile_ibkr")

HMM_FIT_END = REGIME["hmm_fit_end"]   # "2024-12-31"
_EXCHANGE = {"MYM": "CBOT"}

FRONT_MONTH  = "20260918"   # Sep 2026 (current front month)
PREV_MONTH   = "20260619"   # Jun 2026 (expired, needed for stitching)

# Contract rollover for Jun→Sep 2026 cycle.
# CME/CBOT quarterly: expiry = 3rd Friday of contract month = June 19.
# IBKR ContFuture switches ~8 trading days before expiry = ~June 5.
# Use June 6 as the stitch boundary (first full day where Sep 2026 is front month).
_ROLLOVER_DATE = datetime.date(2026, 6, 6)
_ROLLOVER_OVERLAP_DAYS = 3   # fetch both contracts in a ±3-day overlap window


def _bars_to_df(ibi, bars):
    """Convert IB bars list → ET-naive DataFrame."""
    df = ibi.util.df(bars).set_index("date")
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert("America/New_York").tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].sort_index()


def _fetch_chunks(ib, ibi, contract, total_days, chunk_days,
                  end_anchor=None, label=""):
    """Fetch paginated 1-min bars for one contract, going back total_days from end_anchor.

    end_anchor: datetime or None (None = now).
    Returns concatenated DataFrame or empty DataFrame on failure.
    """
    anchor = end_anchor or datetime.datetime.now()
    n      = math.ceil(total_days / chunk_days)
    chunks = []
    for i in range(n):
        if i == 0 and end_anchor is None:
            end_str = ""
            end_lbl = "now"
        else:
            cutoff  = anchor - datetime.timedelta(days=i * chunk_days)
            end_str = cutoff.strftime("%Y%m%d %H:%M:%S")
            end_lbl = end_str
        log.info("    chunk %d/%d  endDateTime=%-20s  %dD", i + 1, n, end_lbl, chunk_days)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end_str,
            durationStr=f"{chunk_days} D",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=False,
            formatDate=1,
            timeout=120,
        )
        if not bars:
            log.warning("    chunk %d: no bars", i + 1)
        else:
            chunks.append(_bars_to_df(ibi, bars))
            log.info("    chunk %d: %d bars  %s → %s",
                     i + 1, len(chunks[-1]), chunks[-1].index[0], chunks[-1].index[-1])
        time.sleep(2)   # IBKR pacing: ≤60 req/10 min
    if not chunks:
        return pd.DataFrame()
    combined = pd.concat(chunks)
    return combined[~combined.index.duplicated(keep="first")].sort_index()


def fetch_ibkr_bars_paginated(port: int, total_days: int = 60, chunk_days: int = 10,
                               use_contfuture: bool = False,
                               stitch_contracts: bool = False) -> dict:
    """Fetch 1-min bars via paginated IBKR requests (chunk_days each, backwards from now).

    Three modes (in order of preference):
      use_contfuture=True  — IBKR ContFuture (auto back-adjusted, like parquet).
                             IDEAL but may timeout; try first.
      stitch_contracts=True — manual contract stitching across the Jun→Sep rollover.
                             fetch Jun2026 + Sep2026, compute offset at overlap,
                             splice into a consistent back-adjusted series.
                             Correct, always works, slightly more requests.
      default (both False) — Sep 2026 specific Future for entire window.
                             FAST but distorts EMA if window spans rollover.
    """
    try:
        import ib_insync as ibi
    except ImportError:
        sys.exit("ib_insync not installed")

    ib = ibi.IB()
    ib.connect("127.0.0.1", port, clientId=5)
    mode = "ContFuture" if use_contfuture else ("stitched" if stitch_contracts else "specific-Future")
    log.info("Connected (clientId=5). mode=%s  total=%dD  chunk=%dD", mode, total_days, chunk_days)

    dfs = {}
    try:
        for name in BASKET:
            exchange = _EXCHANGE.get(name, "CME")
            log.info("[%s] Fetching (%s)...", name, mode)

            if use_contfuture:
                # ContFuture: IBKR handles back-adjustment automatically.
                # IBKR error 10339: endDateTime must be "" for ContFuture — pagination
                # (which sets past endDateTimes) is not allowed. Single request only.
                contract = ibi.ContFuture(name, exchange=exchange)
                ib.qualifyContracts(contract)
                log.info("  [%s] ContFuture single request %dD (no pagination)...",
                         name, total_days)
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=f"{total_days} D",
                    barSizeSetting="1 min",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1,
                    timeout=300,   # ContFuture may be slower than specific Future
                )
                if not bars:
                    log.warning("  [%s] ContFuture: no bars (timeout or pacing)", name)
                    df = pd.DataFrame()
                else:
                    df = _bars_to_df(ibi, bars)
                    log.info("  [%s] ContFuture: %d bars  %s → %s",
                             name, len(df), df.index[0], df.index[-1])

            elif stitch_contracts:
                # Stitch Jun 2026 (pre-rollover) + Sep 2026 (post-rollover).
                today     = datetime.datetime.now()
                rollover  = datetime.datetime.combine(_ROLLOVER_DATE, datetime.time(0))
                cutoff    = today - datetime.timedelta(days=total_days)

                days_post = max(1, (today - rollover).days + _ROLLOVER_OVERLAP_DAYS)
                days_pre  = max(1, (rollover - cutoff).days + _ROLLOVER_OVERLAP_DAYS)

                # ── Sep 2026 (front month, post-rollover) ──────────────────
                sep_contract = ibi.Future(name, lastTradeDateOrContractMonth=FRONT_MONTH,
                                          exchange=exchange)
                ib.qualifyContracts(sep_contract)
                log.info("  [%s] Sep2026 (%d D post-rollover + overlap)...", name, days_post)
                sep_df = _fetch_chunks(ib, ibi, sep_contract, days_post, chunk_days, label=name)

                # ── Jun 2026 (prev month, pre-rollover) ────────────────────
                prev_contract = ibi.Future(name, lastTradeDateOrContractMonth=PREV_MONTH,
                                           exchange=exchange)
                ib.qualifyContracts(prev_contract)
                # endDateTime = rollover + overlap so we capture the overlap zone
                end_anchor = rollover + datetime.timedelta(days=_ROLLOVER_OVERLAP_DAYS + 1)
                log.info("  [%s] Jun2026 (%d D up to %s)...", name, days_pre,
                         end_anchor.strftime("%Y-%m-%d"))
                jun_df = _fetch_chunks(ib, ibi, prev_contract, days_pre, chunk_days,
                                       end_anchor=end_anchor, label=name)

                if sep_df.empty or jun_df.empty:
                    log.warning("  [%s] stitch FAILED — one leg empty; using sep only", name)
                    df = sep_df if not sep_df.empty else pd.DataFrame()
                else:
                    # Compute price offset in the overlap zone (where both contracts trade)
                    overlap_start = rollover - datetime.timedelta(days=_ROLLOVER_OVERLAP_DAYS)
                    overlap_end   = rollover + datetime.timedelta(days=_ROLLOVER_OVERLAP_DAYS)
                    sep_ol = sep_df[(sep_df.index >= overlap_start) & (sep_df.index <= overlap_end)]
                    jun_ol = jun_df[(jun_df.index >= overlap_start) & (jun_df.index <= overlap_end)]
                    common = sep_ol.index.intersection(jun_ol.index)
                    if len(common) >= 10:
                        offset = (sep_ol.loc[common, "close"].mean()
                                  - jun_ol.loc[common, "close"].mean())
                        log.info("  [%s] stitch offset = %.2f pts (%d common bars)",
                                 name, offset, len(common))
                    else:
                        # Fallback: use last Jun close vs first Sep close near rollover
                        offset = (sep_df[sep_df.index >= rollover]["close"].iloc[0]
                                  - jun_df[jun_df.index < rollover]["close"].iloc[-1])
                        log.warning("  [%s] few overlap bars (%d) — fallback offset=%.2f",
                                    name, len(common), offset)

                    # Apply offset to pre-rollover Jun bars, concat with Sep
                    pre = jun_df[jun_df.index < rollover].copy()
                    for col in ["open", "high", "low", "close"]:
                        if col in pre.columns:
                            pre[col] += offset
                    post = sep_df[sep_df.index >= rollover]
                    df   = pd.concat([pre, post]).sort_index()
                    df   = df[~df.index.duplicated(keep="last")]
                    log.info("  [%s] stitched: %d bars  %s → %s",
                             name, len(df), df.index[0], df.index[-1])

            else:
                # Default: Sep 2026 specific Future for entire window.
                # Fast, but distorts EMA if window spans the Jun→Sep rollover.
                contract = ibi.Future(name, lastTradeDateOrContractMonth=FRONT_MONTH,
                                      exchange=exchange)
                ib.qualifyContracts(contract)
                df = _fetch_chunks(ib, ibi, contract, total_days, chunk_days, label=name)

            if df is None or (hasattr(df, "empty") and df.empty):
                log.warning("[%s] no data — skipping", name)
            else:
                dfs[name] = df
                log.info("[%s] final: %d bars  %s → %s",
                         name, len(df), df.index[0], df.index[-1])

    finally:
        ib.disconnect()
        log.info("Disconnected.")

    return dfs


def main():
    ap = argparse.ArgumentParser(description="Reconcile route: IBKR-only, no parquet, no offset")
    ap.add_argument("--port",              type=int, default=4002)
    ap.add_argument("--total-days",        type=int, default=60,
                    help="Total history in calendar days (default: 60, enough for EMA30+ATR14)")
    ap.add_argument("--chunk-days",        type=int, default=10,
                    help="Days per IBKR request chunk (default: 10, avoids timeout)")
    ap.add_argument("--regime-csv",        default="spy_daily_live.csv")
    mode_g = ap.add_mutually_exclusive_group()
    mode_g.add_argument("--use-contfuture",    action="store_true",
                        help="Use ContFuture (IBKR auto back-adjusted). Ideal but may timeout.")
    mode_g.add_argument("--stitch-contracts",  action="store_true",
                        help="Manually stitch Jun2026+Sep2026 with offset at rollover (~June 6). "
                             "Correct for any window spanning the rollover. More requests.")
    a = ap.parse_args()

    today     = datetime.date.today().isoformat()
    today_ts  = pd.Timestamp(today).normalize()

    # ── Fetch bars from IBKR ─────────────────────────────────────────────────
    mode_label = ("ContFuture" if a.use_contfuture
                  else "stitched Jun+Sep" if a.stitch_contracts
                  else "Sep2026 specific Future")
    log.info("Fetching %d days of 1-min bars [%s, %d-D chunks]...",
             a.total_days, mode_label, a.chunk_days)
    dfs = fetch_ibkr_bars_paginated(a.port, a.total_days, a.chunk_days,
                                    use_contfuture=a.use_contfuture,
                                    stitch_contracts=a.stitch_contracts)
    if not dfs:
        sys.exit("No bars fetched — check IBKR Gateway connection.")

    # ── Regime labels (same as production) ────────────────────────────────────
    bench  = benchmark_daily(a.regime_csv)
    labels = label_regimes(bench, "2018-01-01", 3, HMM_FIT_END)
    spy_s  = pd.Series(labels).sort_index()
    regime = str(spy_s.asof(today_ts))

    # ── Compute desired_basket ─────────────────────────────────────────────────
    costs  = costs_for_basket(slippage_ticks=2.0)
    engine = SwingTFEngine()
    basket = engine.desired_basket(dfs, labels, costs)

    # ── Print results với entry_day guard (mirrors generate_today_signals) ────
    print()
    print("=" * 68)
    print(f"RECONCILE ROUTE — IBKR-only  [{mode_label}]")
    print(f"  today      : {today}")
    print(f"  regime     : {regime}")
    print(f"  total_days : {a.total_days}  chunk_days : {a.chunk_days}")
    print("=" * 68)
    any_entry = False
    for name, sig in basket.items():
        if sig is None:
            print(f"  {name:<5}: None")
            continue
        new_ed    = pd.Timestamp(sig["entry_day"]).normalize()
        guard_ok  = (new_ed == today_ts)
        guard_str = "entry_day PASS" if guard_ok else f"entry_day BLOCKED ({new_ed.date()} ≠ {today})"
        status    = f"dir={sig['direction']:<5} entry={sig['entry']:.2f} stop={sig['stop']:.2f}  [{guard_str}]"
        print(f"  {name:<5}: {status}")
        if guard_ok:
            any_entry = True

    print()
    if any_entry:
        print("=> Entries with guard PASS (what live system would do IF using this route):")
        for name, sig in basket.items():
            if sig and pd.Timestamp(sig["entry_day"]).normalize() == today_ts:
                print(f"   {name}: {sig['direction']}  entry={sig['entry']:.2f}  stop={sig['stop']:.2f}")
    else:
        print("=> No entries pass entry_day guard today.")

    print()
    print("Compare với:")
    print("  check_next_entry.py  — parquet-only (ContFuture+offset prices, no live bars)")
    print("  --print-signals      — parquet+_concat_live (splice offset step-change distorts EMA)")
    print("=" * 68)


if __name__ == "__main__":
    main()
