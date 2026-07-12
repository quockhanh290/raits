"""
global_index/connect_test_paper.py — GIAI ĐOẠN 1: IB Gateway connection + data test
=====================================================================================
Mục đích: verify IBKRBroker hoạt động đúng với paper account trước khi paper trade.

Requires:
  - IB Gateway (hoặc TWS) đang chạy, đã đăng nhập vào PAPER account
  - Port mặc định: 7497 (paper). Live = 7496 — KHÔNG dùng live cho test này.
  - pip install ib_insync (nếu chưa có)

Run từ d:\\raits:
    python global_index\\connect_test_paper.py
    python global_index\\connect_test_paper.py --inst MNQ --port 7497 --client-id 11

Exit 0 = tất cả checks PASS.
Exit 1 = có check FAIL.

Checks:
  CON.1  connect to IB Gateway (port 7497)
  CON.2  account equity > 0 (NetLiquidation)
  CON.3  fetch positions list (no crash)

  DATA.1 fetch_bars returns non-empty DataFrame
  DATA.2 columns lowercase (C6 spec)
  DATA.3 index sorted ascending (C3 spec)
  DATA.4 index is datetime64 (not string, not object)

  P2.1   bar timestamps in ET market hours range (09:00–16:30)
  P2.2   NO UTC shift artifact: no bars before 04:00 (which would indicate UTC→ET bug)
  P2.3   index is tz-naive (runner expects ET naive, not tz-aware)

Note: DATA.* and P2.* require market hours data to be available. Run during or shortly
after market hours, or use bar_duration="5 D" to fetch recent history.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

PASS_STR = "PASS"
FAIL_STR = "FAIL"
SKIP_STR = "SKIP"
results: list[tuple[str, str, str]] = []  # (name, status, detail)


def check(name: str, cond: bool, detail: str = "") -> bool:
    status = PASS_STR if cond else FAIL_STR
    results.append((name, status, detail))
    mark = "  PASS" if cond else "  FAIL"
    print(f"{mark}  {name}" + (f"  [{detail}]" if detail else ""))
    return cond


def skip(name: str, reason: str) -> None:
    results.append((name, SKIP_STR, reason))
    print(f"  SKIP  {name}  [{reason}]")


def main() -> int:
    parser = argparse.ArgumentParser(description="IBKRBroker paper account connection test")
    parser.add_argument("--inst", default="MES", help="Futures instrument symbol (default: MES)")
    parser.add_argument("--port", type=int, default=7497, help="IB Gateway port (default: 7497 paper)")
    parser.add_argument("--host", default="127.0.0.1", help="IB Gateway host")
    parser.add_argument("--client-id", type=int, default=11, help="Client ID (default: 11)")
    parser.add_argument("--bar-duration", default="2 D", help="Bar fetch duration (default: '2 D')")
    parser.add_argument("--test-orders", action="store_true",
                        help="GIAI ĐOẠN 2: place a real OPEN+CLOSE paper order to test send_order() "
                             "(opt-in — places actual paper trades)")
    parser.add_argument("--test-edge-cases", action="store_true",
                        help="A3+P3+A2: timeout/cancel, order crossing, partial fill attempt "
                             "(opt-in — places and cancels paper orders)")
    args = parser.parse_args()

    print("=" * 60)
    print(f"IBKRBroker Paper Account Connection Test")
    print(f"  host={args.host}  port={args.port}  clientId={args.client_id}")
    print(f"  instrument={args.inst}  bar_duration={args.bar_duration!r}")
    print("=" * 60)
    print()

    # ── Check ib_insync availability ──────────────────────────────────────────
    try:
        import ib_insync  # type: ignore  # noqa: F401
        print(f"  ib_insync version: {ib_insync.__version__}")
    except ImportError:
        print("ERROR: ib_insync not installed.")
        print("  Install: pip install ib_insync")
        return 1
    print()

    # ── Import IBKRBroker ─────────────────────────────────────────────────────
    try:
        from global_index.ibkr_broker import IBKRBroker, IBKRConnectionError
    except ImportError as exc:
        print(f"ERROR: cannot import IBKRBroker: {exc}")
        return 1

    broker = IBKRBroker(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        bar_duration=args.bar_duration,
    )

    # ── CON: Connection checks ────────────────────────────────────────────────
    print("── CON: Connection ──────────────────────────────────────")

    try:
        broker.connect()
        check("CON.1 connect to IB Gateway", True, f"port={args.port}")
    except Exception as exc:
        check("CON.1 connect to IB Gateway", False, str(exc))
        print()
        print("Cannot connect — verify IB Gateway is running on paper account.")
        print(f"  Expected: 127.0.0.1:{args.port} (paper)")
        print("  In IB Gateway: File → Settings → API → Enable ActiveX and Socket Clients")
        print(f"  Also check: API Settings → Socket port = {args.port}")
        return 1

    try:
        equity = broker.get_equity()
        check("CON.2 account equity > 0", equity > 0, f"NetLiquidation=${equity:,.2f}")
    except Exception as exc:
        check("CON.2 account equity > 0", False, str(exc))

    try:
        positions = broker.get_positions()
        check("CON.3 get_positions no crash", True,
              f"n_positions={len(positions)}"
              + (f"  {[(p.inst, p.direction, p.contracts) for p in positions]}" if positions else ""))
        if positions:
            from global_index.broker import BrokerPosition
            check("CON.3b positions are BrokerPosition",
                  all(isinstance(p, BrokerPosition) for p in positions),
                  f"types={[type(p).__name__ for p in positions]}")
    except NotImplementedError:
        skip("CON.3 get_positions", "NotImplementedError — GIAI ĐOẠN 3 not yet implemented")
    except Exception as exc:
        check("CON.3 get_positions no crash", False, str(exc))

    print()

    # ── DATA + P2: Market data + timezone checks ──────────────────────────────
    print("── DATA + P2: Market data fetch + timezone ──────────────")

    through = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None) + pd.Timedelta(hours=16)  # today 16:00 ET
    df = pd.DataFrame()
    data_ok = False

    try:
        df = broker.fetch_bars(args.inst, through=through)
        data_ok = not df.empty
        check("DATA.1 fetch_bars non-empty", data_ok,
              f"rows={len(df)} cols={list(df.columns)[:5]}")
    except Exception as exc:
        check("DATA.1 fetch_bars non-empty", False, str(exc))

    if data_ok:
        check("DATA.2 columns lowercase (C6)",
              all(c == c.lower() for c in df.columns),
              f"columns={list(df.columns)}")

        check("DATA.3 index sorted ascending (C3)",
              df.index.is_monotonic_increasing,
              f"first={df.index[0]}  last={df.index[-1]}")

        is_datetime = pd.api.types.is_datetime64_any_dtype(df.index)
        check("DATA.4 index is datetime64",
              is_datetime,
              f"dtype={df.index.dtype}")

        if is_datetime:
            # P2.1: CME Globex session opens 18:00 ET (6 PM) daily.
            # First bar should be in 17:00–19:00 ET window (allow DST / reconnect jitter).
            # UTC shift bug would put it at ~12:00–14:00 ET (5–6h earlier).
            first_hour = df.index[0].hour
            check("P2.1 session open near 18:00 ET (CME Globex start, no UTC shift)",
                  17 <= first_hour <= 19,
                  f"first_bar={df.index[0]}  hour={first_hour} (expect 17-19; UTC shift→12-14)")

            # P2.2: CME futures trade ~23h/day (18:00→17:00 ET). Overnight bars (00:00-04:00)
            # are normal. UTC shift check: if first bar < 14:00 on Sunday → shift artifact.
            # Re-check: bar count per day should be ~1380 (23h × 60min), not ~480 (8h RTH).
            days = df.index.normalize().unique()
            if len(days) >= 2:
                # Pick a full inner day (not first/last which may be partial)
                mid_day_bars = sum(1 for ts in df.index if ts.normalize() == days[1])
                check("P2.2 bar count per day consistent with 23h CME session (>800/day)",
                      mid_day_bars > 800,
                      f"day={days[1].date()} bars={mid_day_bars} (expect ~1380 for 23h)")
            else:
                skip("P2.2", "need ≥2 days of data to check bar count")

            # P2.3: tz-naive (runner expects ET naive, not tz-aware)
            is_tz_naive = df.index.tz is None
            check("P2.3 index is tz-naive (ET naive, not tz-aware)",
                  is_tz_naive,
                  f"tz={df.index.tz}")

            # Print sample rows for visual inspection
            print()
            print("  Sample bars (first 3, last 3):")
            sample = pd.concat([df.head(3), df.tail(3)])
            for ts, row in sample.iterrows():
                print(f"    {ts}  open={row.get('open', 'n/a'):.2f}  close={row.get('close', 'n/a'):.2f}")
        else:
            for name in ["P2.1", "P2.2", "P2.3"]:
                skip(name, "skipped — DATA.4 failed (non-datetime index)")
    else:
        for name in ["DATA.2", "DATA.3", "DATA.4", "P2.1", "P2.2", "P2.3"]:
            skip(name, "skipped — DATA.1 failed (empty DataFrame)")

        print()
        print("  Possible reasons for empty bars:")
        print(f"  1. {args.inst} not in paper account permissions")
        print("  2. Outside market data subscription hours — try a recent trading day")
        print("  3. Gateway not permissioned for this exchange (CME)")

    # ── ORDER: GIAI ĐOẠN 2 send_order() test (opt-in via --test-orders) ─────────
    if args.test_orders:
        print()
        print("── ORDER: send_order() OPEN+CLOSE (GIAI ĐOẠN 2) ────────")
        print("  WARNING: placing real paper orders on account", end=" ")

        from global_index.broker import Order
        from global_index.signal_layer import CLUSTER_SWING

        ref_day = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
        open_order = Order(
            inst=args.inst, action="OPEN", direction="LONG",
            contracts=1, cluster=CLUSTER_SWING,
            ref_day=ref_day,
        )

        # A1: entry fill
        open_fill = None
        try:
            t0 = time.time()
            open_fill = broker.send_order(open_order)
            t_open = time.time() - t0
            check("A1.1 OPEN fill received (no exception)", True,
                  f"status={open_fill.status} elapsed={t_open:.1f}s")
            check("A1.2 OPEN status == FILLED", open_fill.status == "FILLED",
                  f"status={open_fill.status} error={open_fill.error_msg}")
            check("A1.3 OPEN avg_price > 0", open_fill.avg_price > 0,
                  f"avg_price={open_fill.avg_price:.4f}")
            if data_ok and open_fill.avg_price > 0:
                last_close = float(df["close"].iloc[-1])
                pct_dev = abs(open_fill.avg_price - last_close) / last_close * 100
                check("A1.4 fill price within 2% of last bar close",
                      pct_dev < 2.0,
                      f"fill={open_fill.avg_price:.2f}  last_close={last_close:.2f}  dev={pct_dev:.2f}%")
            # A4: timing
            check("A4.1 entry fill time < 30s (A4 design assumption)",
                  t_open < 30.0,
                  f"elapsed={t_open:.2f}s (design assumption: ~5s)")
        except Exception as exc:
            check("A1.1 OPEN fill received (no exception)", False, str(exc))

        # A1: exit fill (only if OPEN succeeded)
        if open_fill is not None and open_fill.status == "FILLED":
            close_order = Order(
                inst=args.inst, action="CLOSE", direction="LONG",
                contracts=1, cluster=CLUSTER_SWING,
                ref_day=ref_day,
            )
            try:
                t0 = time.time()
                close_fill = broker.send_order(close_order)
                t_close = time.time() - t0
                check("A1.5 CLOSE fill received (no exception)", True,
                      f"status={close_fill.status} elapsed={t_close:.1f}s")
                check("A1.6 CLOSE status == FILLED", close_fill.status == "FILLED",
                      f"status={close_fill.status} error={close_fill.error_msg}")
                check("A4.2 exit fill time < 30s (A4 design assumption)",
                      t_close < 30.0,
                      f"elapsed={t_close:.2f}s (design assumption: ~5s)")
                if open_fill.avg_price > 0 and close_fill.avg_price > 0:
                    slippage_ticks = abs(close_fill.avg_price - open_fill.avg_price) / 0.25
                    print(f"  NOTE  round-trip: open={open_fill.avg_price:.2f}"
                          f"  close={close_fill.avg_price:.2f}"
                          f"  slippage≈{slippage_ticks:.1f} ticks")
            except Exception as exc:
                check("A1.5 CLOSE fill received (no exception)", False, str(exc))
        else:
            for name in ["A1.5", "A1.6", "A4.2"]:
                skip(name, "skipped — OPEN did not fill")

    # ── EDGE CASES: A3 timeout + P3 crossing + A2 partial fill (opt-in) ─────
    if args.test_edge_cases:
        print()
        print("── EDGE CASES: A3 timeout / P3 crossing / A2 partial ────")
        from global_index.broker import Order
        from global_index.signal_layer import CLUSTER_SWING
        ref_day = pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)

        # ── A3: entry timeout → CANCELLED ────────────────────────────────────
        # Set limit price guaranteed to miss (buy at $1 = never fills on MES ~$7500).
        # Reduce timeout to 5s so test doesn't block for 30s.
        print()
        print("  A3: timeout test (limit@$1, 5s timeout) ...")
        broker._test_entry_lmt_price = 1.0
        broker._test_entry_timeout   = 5
        a3_order = Order(inst=args.inst, action="OPEN", direction="LONG",
                         contracts=1, cluster=CLUSTER_SWING, ref_day=ref_day)
        # Snapshot position count before A3 (may have pre-existing positions from other tests)
        a3_baseline = [p for p in broker.get_positions() if p.inst == args.inst]
        try:
            t0 = time.time()
            a3_fill = broker.send_order(a3_order)
            t_a3 = time.time() - t0
            check("A3.1 timeout returns CANCELLED (not exception)",
                  a3_fill.status == "CANCELLED",
                  f"status={a3_fill.status} elapsed={t_a3:.1f}s")
            check("A3.2 error_msg mentions timeout",
                  "timeout" in (a3_fill.error_msg or "").lower(),
                  f"error_msg={a3_fill.error_msg!r}")
            check("A3.3 elapsed ≥ 5s (timeout fired, not fast fill)",
                  t_a3 >= 4.5,
                  f"elapsed={t_a3:.2f}s (expect ≥5s)")
            # Compare delta — cancelled order must not add a new position
            a3_pos = [p for p in broker.get_positions() if p.inst == args.inst]
            check("A3.4 no new position added by cancelled order (delta == 0)",
                  len(a3_pos) == len(a3_baseline),
                  f"before={len(a3_baseline)} after={len(a3_pos)} (expect same)")
        except Exception as exc:
            check("A3.1 timeout returns CANCELLED (not exception)", False, str(exc))
        finally:
            broker._test_entry_lmt_price = None
            broker._test_entry_timeout   = None

        # ── P3: order crossing — LONG then SHORT same instrument ──────────────
        # IBKR futures net positions: LONG ×1 then SHORT ×1 → net 0 (flat).
        # Verify: no error/exception, IBKR does not reject crossing futures orders.
        # Our runner prevents this via ClusterBudget; this test characterises IBKR's behaviour.
        print()
        print("  P3: crossing test (LONG ×1 then SHORT ×1 → expect flat) ...")
        p3_long_fill = p3_short_fill = None
        try:
            p3_long = Order(inst=args.inst, action="OPEN", direction="LONG",
                            contracts=1, cluster=CLUSTER_SWING, ref_day=ref_day)
            p3_long_fill = broker.send_order(p3_long)
            check("P3.1 LONG OPEN filled", p3_long_fill.status == "FILLED",
                  f"status={p3_long_fill.status}")

            if p3_long_fill.status == "FILLED":
                p3_short = Order(inst=args.inst, action="OPEN", direction="SHORT",
                                 contracts=1, cluster=CLUSTER_SWING, ref_day=ref_day)
                p3_short_fill = broker.send_order(p3_short)
                check("P3.2 opposing SHORT accepted by IBKR (no exception/rejection)",
                      p3_short_fill.status == "FILLED",
                      f"status={p3_short_fill.status} error={p3_short_fill.error_msg}")

                p3_pos = broker.get_positions()
                p3_inst_pos = [p for p in p3_pos if p.inst == args.inst]
                net = sum(p.contracts * (1 if p.direction == "LONG" else -1)
                          for p in p3_inst_pos)
                print(f"  NOTE  P3: IBKR net position after LONG+SHORT = {net} "
                      f"(0=netted flat, ±1=kept separate)")
                check("P3.3 IBKR nets to flat or keeps both (no crash)",
                      True, f"net={net}  positions={len(p3_inst_pos)}")

                # Cleanup: close any remaining position
                for p in p3_inst_pos:
                    cl = Order(inst=p.inst, action="CLOSE", direction=p.direction,
                               contracts=p.contracts, cluster=CLUSTER_SWING, ref_day=ref_day)
                    cf = broker.send_order(cl)
                    print(f"  NOTE  P3 cleanup: CLOSE {p.direction} {p.inst} ×{p.contracts}"
                          f" → {cf.status}")
        except Exception as exc:
            check("P3.1 LONG OPEN filled", False, str(exc))

        # ── A2: partial fill attempt ──────────────────────────────────────────
        # Partial fills on market orders in liquid futures (MES) are extremely rare on paper.
        # We attempt a 50-lot order; IBKR paper usually fills 100% instantly.
        # A PARTIAL result here would be notable; FILLED is the expected outcome.
        print()
        print("  A2: partial fill attempt (50 lots market — expect FILLED, PARTIAL notable) ...")
        try:
            a2_order = Order(inst=args.inst, action="OPEN", direction="LONG",
                             contracts=50, cluster=CLUSTER_SWING, ref_day=ref_day)
            t0 = time.time()
            a2_fill = broker.send_order(a2_order)
            t_a2 = time.time() - t0
            check("A2.1 large order accepted (FILLED or PARTIAL)",
                  a2_fill.status in ("FILLED", "PARTIAL"),
                  f"status={a2_fill.status} filled_qty={a2_fill.filled_qty} elapsed={t_a2:.1f}s")
            if a2_fill.status == "PARTIAL":
                print(f"  NOTE  A2: PARTIAL fill observed: {a2_fill.filled_qty}/50 @ {a2_fill.avg_price:.2f}")
            else:
                print(f"  NOTE  A2: full FILLED (paper simulates instant fill) — {a2_fill.avg_price:.2f}")

            # Always close whatever was filled
            if a2_fill.status in ("FILLED", "PARTIAL"):
                qty = a2_fill.filled_qty if a2_fill.status == "PARTIAL" else 50
                if qty > 0:
                    a2_cl = Order(inst=args.inst, action="CLOSE", direction="LONG",
                                  contracts=qty, cluster=CLUSTER_SWING, ref_day=ref_day)
                    a2_cf = broker.send_order(a2_cl)
                    print(f"  NOTE  A2 cleanup: CLOSE ×{qty} → {a2_cf.status}")
        except Exception as exc:
            check("A2.1 large order accepted", False, str(exc))

    # ── Disconnect ────────────────────────────────────────────────────────────
    broker.disconnect()
    print()

    # ── Summary ──────────────────────────────────────────────────────────────
    print("=" * 60)
    passed = sum(1 for _, s, _ in results if s == PASS_STR)
    failed = sum(1 for _, s, _ in results if s == FAIL_STR)
    skipped = sum(1 for _, s, _ in results if s == SKIP_STR)
    total_run = passed + failed
    print(f"RESULT: {passed}/{total_run} PASS  {failed} FAIL  {skipped} SKIP")
    if failed == 0:
        print("ALL PASS" if skipped == 0 else "ALL PASS (some skipped)")
    else:
        print("FAIL — see above")
    print("=" * 60)

    if failed > 0:
        print()
        print("Next steps:")
        if any(n == "CON.2" and s == FAIL_STR for n, s, _ in results):
            print("  CON.2: verify paper account has positive equity (check TWS account summary)")
        if any(n.startswith("P2") and s == FAIL_STR for n, s, _ in results):
            print("  P2: timezone bug in _fetch_raw() — check formatDate=1 parse logic")
        if any(n == "DATA.1" and s == FAIL_STR for n, s, _ in results):
            print("  DATA.1: check market data subscription for", args.inst, "on CME")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
