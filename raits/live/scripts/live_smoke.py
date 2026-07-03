"""
live_smoke.py  —  Step 3/4: Market-hours LivePolygonFeed observation script.

Runs LivePolygonFeed in live mode for a configurable duration (default 30 min),
logging every bar and BarContext. No orders are placed.

Usage
-----
    POLYGON_API_KEY=xxx python raits/live/scripts/live_smoke.py [--minutes N]

Exit 0 = observation completed without errors.
Exit 1 = setup error (missing API key, import failure, etc.).

Pass/Fail checklist for a real market-hours run
------------------------------------------------
Run this script starting no earlier than 09:30 ET on a regular trading day.
After the run, verify:

  [PASS/FAIL] At least 13 BarContexts yielded (one per 5-min slot 09:30–15:55)
              within the first 65 minutes of market open.
  [PASS/FAIL] SPY bar arrives within 30s of each expected cadence slot.
  [PASS/FAIL] No "malformed WS bar" warnings in the log.
  [PASS/FAIL] No "WS error" / reconnect messages (stable session).
  [PASS/FAIL] hmm_state is one of: Calm / Normal / Stress / Crisis.
  [PASS/FAIL] bar_ts timestamps are sequential and in ET (no UTC leakage).
  [PASS/FAIL] day_stocks contains at least one non-SPY ticker by 09:45.
  [PASS/FAIL] orb_vix_ok and spy_or_high are non-None by 09:45.
  [PASS/FAIL] Script exits cleanly on Ctrl-C / duration timeout.
  [PASS/FAIL] No Python exceptions or tracebacks in stdout/stderr.

What this does NOT test
-----------------------
  - Order routing (IBKRBroker) — requires a live IBKR connection.
  - Paper trades from PaperTrader — exercise that path via verify_live_path.py.
  - HMM regime transitions — needs at least ~3 weeks of daily SPY data pre-loaded.
"""
from __future__ import annotations

import argparse
import datetime
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("live_smoke")


def main() -> int:
    parser = argparse.ArgumentParser(description="LivePolygonFeed market-hours observation")
    parser.add_argument("--minutes", type=float, default=30.0,
                        help="Observation window in minutes (default 30)")
    parser.add_argument("--ws-feed", default=None,
                        help="WebSocket feed domain (default: socket.massive.com)")
    parser.add_argument("--rest-base", default=None,
                        help="REST API base URL (default: https://api.massive.com)")
    args = parser.parse_args()

    api_key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not api_key:
        logger.error("POLYGON_API_KEY not set.  export POLYGON_API_KEY=your_key")
        return 1

    try:
        from raits.backtest.data_types import BacktestConfig
        from raits.live.context_feed import LivePolygonFeed
        from raits.live.trading_calendar import (
            et_now_time, is_early_close, is_trading_day, market_close_time,
        )
    except ImportError as exc:
        logger.error("Import failed — run from project root with raits installed: %s", exc)
        return 1

    # ── Calendar pre-flight ───────────────────────────────────────────────────
    today = datetime.date.today()
    if not is_trading_day(today):
        logger.warning(
            "Today (%s) is not a NYSE trading day (holiday or weekend). "
            "No bars will be received — exiting.",
            today,
        )
        return 0

    close_time = market_close_time(today)
    now_et = et_now_time()
    if now_et >= close_time:
        if is_early_close(today):
            logger.warning(
                "Half-day: NYSE closed at 13:00 ET on %s (current ET time %s). "
                "No bars will be received — exiting.",
                today, now_et.strftime("%H:%M"),
            )
        else:
            logger.warning(
                "NYSE closed at 16:00 ET on %s (current ET time %s). "
                "No bars will be received — exiting.",
                today, now_et.strftime("%H:%M"),
            )
        return 0

    if is_early_close(today):
        logger.info("HALF-DAY: NYSE closes at 13:00 ET today (%s).", today)

    # Minimal config: SPY + QQQ baseline universe; no scanners; default WFO params.
    config = BacktestConfig(
        start_date="2020-01-01",  # not used in live mode
        end_date="2020-01-01",
        universe=["SPY", "QQQ", "AAPL", "MSFT", "AMZN", "TSLA",
                  "NVDA", "META", "GOOGL", "JPM"],
        account_equity=50_000.0,
    )

    feed = LivePolygonFeed(
        config=config,
        api_key=api_key,
        backfill_on_reconnect=True,
        ws_feed=args.ws_feed,
        rest_base=args.rest_base,
    )

    deadline = time.monotonic() + args.minutes * 60.0
    ctx_count = 0
    bar_latencies: list[float] = []
    anomalies: list[str] = []
    prev_ts = None

    logger.info("Starting %g-minute observation window — press Ctrl-C to stop early.",
                args.minutes)
    logger.info("Universe: %s", config.universe)

    try:
        for ctx in feed:
            now = time.monotonic()
            if now >= deadline:
                logger.info("Observation window elapsed — stopping.")
                break

            # Stop cleanly when market closes mid-observation (e.g. half-day)
            if et_now_time() >= close_time:
                logger.info(
                    "Market closed at %s ET — ending observation.",
                    close_time.strftime("%H:%M"),
                )
                break

            ctx_count += 1
            wall_s = time.time()

            # Latency: wall-clock minus bar close time (approximate — bar ts is
            # start of 5-min slot; actual close is ts + 5 min).
            bar_close_epoch = (ctx.bar_ts + __import__("pandas").Timedelta(minutes=5)).timestamp()
            latency_s = max(0.0, wall_s - bar_close_epoch)
            bar_latencies.append(latency_s)

            # Sequence check
            if prev_ts is not None and ctx.bar_ts <= prev_ts:
                anomalies.append(
                    f"non-monotonic bar_ts: {prev_ts} → {ctx.bar_ts}"
                )
            prev_ts = ctx.bar_ts

            # Regime sanity
            if ctx.hmm_state not in ("Calm", "Normal", "Stress", "Crisis"):
                anomalies.append(f"unexpected hmm_state={ctx.hmm_state!r} at {ctx.bar_ts}")

            logger.info(
                "[ctx #%d] bar_ts=%s  hmm=%s  vol=%.2f  "
                "day_stocks=%d tickers  latency=%.1fs  "
                "orb_vix_ok=%s  spy_or_high=%s",
                ctx_count,
                ctx.bar_ts,
                ctx.hmm_state,
                ctx.cur_vol,
                len(ctx.day_stocks),
                latency_s,
                ctx.orb_vix_ok,
                f"{ctx.spy_or_high:.2f}" if ctx.spy_or_high else "None",
            )

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        anomalies.append(f"exception: {exc}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("LIVE SMOKE SUMMARY")
    print("=" * 60)
    if ctx_count == 0:
        final_et = et_now_time()
        if final_et >= close_time:
            reason = (
                f"half-day — NYSE closed at {close_time.strftime('%H:%M')} ET"
                if is_early_close(today) else
                f"NYSE closed at {close_time.strftime('%H:%M')} ET"
            )
        elif not is_trading_day(today):
            reason = "not a trading day (holiday or weekend)"
        else:
            reason = "no bars received — possible feed issue or delayed-plan lag"
        print(f"  BarContexts emitted : 0  ({reason})")
    else:
        print(f"  BarContexts emitted : {ctx_count}")
    if bar_latencies:
        avg_lat = sum(bar_latencies) / len(bar_latencies)
        max_lat = max(bar_latencies)
        print(f"  Bar latency (avg)   : {avg_lat:.1f}s")
        print(f"  Bar latency (max)   : {max_lat:.1f}s")
        cadence_ok = sum(1 for l in bar_latencies if l <= 60) / len(bar_latencies)
        print(f"  Within 60s cadence  : {cadence_ok:.0%}")
    print(f"  Anomalies           : {len(anomalies)}")
    for a in anomalies:
        print(f"    - {a}")
    print()
    print("Pass/fail checklist (fill in manually after inspecting log above):")
    print("  [ ] >= 13 BarContexts per 65 min of market open")
    print("  [ ] SPY bar latency <= 30s for each slot")
    print("  [ ] No 'malformed WS bar' warnings")
    print("  [ ] No 'WS error' / reconnect messages")
    print("  [ ] hmm_state in {Calm, Normal, Stress, Crisis}")
    print("  [ ] bar_ts timestamps sequential and in ET")
    print("  [ ] day_stocks has non-SPY ticker by 09:45")
    print("  [ ] orb_vix_ok + spy_or_high set by 09:45")
    print("  [ ] Clean exit on Ctrl-C / timeout")
    print("  [ ] No exceptions / tracebacks")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
