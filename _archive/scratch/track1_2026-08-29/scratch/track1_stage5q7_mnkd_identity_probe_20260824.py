"""Stage 5Q-7 — is the MNKD overlap disagreement a SYMBOL problem or a CLOCK problem?

READ-ONLY. Connects to IBKR to fetch bars and writes no parquet, ever. Default client id 95
so a measurement can never contend with the Track 1 data client (89), the Track 1 safety
client (90), legacy (1) or the daily updater (2).

The question
------------
`update_ibkr_daily._build_jobs` files MNKD's history under IBKR symbol **NKD** on purpose:
micro and full track one index and the full-size series is the longer one. The live path,
`IBKRBarProvider -> IBKRBroker.fetch_bars -> _RAITS_TO_IBKR`, resolves MNKD to **MNK**,
because that map exists to put the right ticker on an ORDER after the ten-times-size
incident of 2026-08-14.

If those two are the whole story, fetching NKD instead of MNK should make the overlap
disagreement collapse. If it does not, the cause is something else and this prints what.

There is a second candidate and it must not be assumed away. The docstring on
`_refuse_overlap_disagreement` records an earlier incident of **1,050** disagreeing Nikkei
bars caused by a thirteen-hour clock error, with price gaps of roughly 900 to 1,000 points.
The count measured in Stage 5Q-6 was 1,052. The two explanations are told apart by the SIZE
of the gap, not by the count, so the size is what this prints.

Both arms travel the same `on_frozen_clock` conversion, keyed on MNKD, so the clock is held
fixed and the symbol is the only thing that varies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index import track1_live_source as src  # noqa: E402
from global_index import specs as gi_specs  # noqa: E402
from global_index import run_live_day_track1 as R  # noqa: E402

PRICE_COLS = ("open", "high", "low", "close")
REPORT = Path(__file__).resolve().parent / "_track1_stage5q7_mnkd_identity.json"


def resolved_identity(inst: str) -> dict:
    """What each layer says this instrument is called. No connection needed."""
    from global_index.ibkr_broker import ibkr_symbol_and_exchange

    spec = gi_specs.SPECS.get(inst)
    sym, exch = ibkr_symbol_and_exchange(inst)
    return {
        "inst": inst,
        "spec_name": getattr(spec, "name", None),
        "spec_data_symbol": getattr(spec, "data_symbol", None),
        "spec_ibkr_symbol": getattr(spec, "ibkr_symbol", None),
        "spec_point_value": getattr(spec, "point_value", None),
        "broker_order_symbol": sym,
        "broker_exchange": exch,
        "session_tz": src.session_tz(inst),
    }


def compare(frozen, aligned) -> dict:
    """Overlap statistics between history and one live fetch, per price column."""
    shared = pd.DatetimeIndex(aligned.index).intersection(pd.DatetimeIndex(frozen.index))
    out = {"shared": int(len(shared)), "columns": {}, "worst_gap": 0.0,
           "first_disagreement": None, "disagreeing_bars": 0}
    if len(shared) == 0:
        return out
    any_bad = pd.Series(False, index=shared)
    for col in PRICE_COLS:
        if col not in aligned.columns or col not in frozen.columns:
            continue
        a = pd.to_numeric(aligned.loc[shared, col], errors="coerce")
        b = pd.to_numeric(frozen.loc[shared, col], errors="coerce")
        gap = (a - b).abs()
        bad = gap[gap > 1e-6]
        any_bad = any_bad | (gap > 1e-6)
        out["columns"][col] = {
            "disagreeing": int(len(bad)),
            "max_gap": float(gap.max()) if len(gap) else 0.0,
            "median_gap_where_bad": float(bad.median()) if len(bad) else 0.0,
        }
        out["worst_gap"] = max(out["worst_gap"], float(gap.max()) if len(gap) else 0.0)
        if len(bad) and out["first_disagreement"] is None:
            w = bad.index[0]
            out["first_disagreement"] = {
                "ts": str(w), "column": col,
                "history": float(b.loc[w]), "feed": float(a.loc[w]),
            }
    out["disagreeing_bars"] = int(any_bad.sum())
    # Level check: are the two series even quoting the same number? A symbol mix-up between
    # two contracts on ONE index shows as noise; a clock error shows as a large, persistent
    # offset. The median of the signed difference tells them apart.
    if "close" in aligned.columns and "close" in frozen.columns:
        d = pd.to_numeric(aligned.loc[shared, "close"], errors="coerce") - \
            pd.to_numeric(frozen.loc[shared, "close"], errors="coerce")
        out["signed_close_median"] = float(d.median())
        out["signed_close_p95_abs"] = float(d.abs().quantile(0.95))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client-id", type=int, default=95)
    ap.add_argument("--port", type=int, default=4002)
    ap.add_argument("--path", default=None, help="MNKD parquet; default from track1_runtime")
    a = ap.parse_args()

    path = a.path or R.default_data_paths()["MNKD"]
    print("MNKD parquet:", path)

    ident = {i: resolved_identity(i) for i in ("MNKD", "NKD")}
    print("\n=== identities, straight from the code ===")
    for i, d in ident.items():
        print(f"  {i:5s} data_symbol={d['spec_data_symbol']:<4} "
              f"order_symbol={d['broker_order_symbol']:<4} pv=${d['spec_point_value']:<5} "
              f"tz={d['session_tz']}")

    # SC1: the two arms must resolve to DIFFERENT broker symbols, or there is no experiment.
    if ident["MNKD"]["broker_order_symbol"] == ident["NKD"]["broker_order_symbol"]:
        print("\n[SC1 FAIL] both arms resolve to the same broker symbol - nothing to compare")
        return 2
    print(f"\n[SC1 PASS] the arms differ: MNKD -> {ident['MNKD']['broker_order_symbol']}, "
          f"NKD -> {ident['NKD']['broker_order_symbol']}")

    frozen = src.frozen_frame("MNKD", path)
    print(f"[frozen] {len(frozen)} bars, {frozen.index[0]} .. {frozen.index[-1]}, "
          f"tz={pd.DatetimeIndex(frozen.index).tz}")

    provider, broker = src.build_bar_provider("ibkr", port=a.port, client_id=a.client_id)
    through = pd.Timestamp.now(tz="America/New_York").tz_localize(None).floor("min")
    print(f"[fetch] through {through} (naive ET), read-only, client id {a.client_id}")

    results = {}
    try:
        for arm in ("MNKD", "NKD"):
            raw = provider.fetch_session_bars(arm, through=through)
            if raw is None or len(raw) == 0:
                results[arm] = {"error": "no_feed_bars"}
                print(f"  {arm}: NO BARS RETURNED")
                continue
            # The clock treatment is keyed on MNKD in BOTH arms on purpose: the frozen frame
            # is MNKD's, and holding the conversion fixed is what isolates the symbol.
            aligned = src.on_frozen_clock("MNKD", raw, frozen)
            stats = compare(frozen, aligned)
            stats["fetched_bars"] = int(len(raw))
            stats["fetch_span"] = [str(raw.index[0]), str(raw.index[-1])]
            stats["broker_symbol"] = ident[arm]["broker_order_symbol"]
            results[arm] = stats
            print(f"\n  === arm {arm} (IBKR {stats['broker_symbol']}) ===")
            print(f"    fetched {stats['fetched_bars']} bars "
                  f"{stats['fetch_span'][0]} .. {stats['fetch_span'][1]}")
            print(f"    shared with history: {stats['shared']}")
            print(f"    disagreeing bars   : {stats['disagreeing_bars']}")
            print(f"    worst price gap    : {stats['worst_gap']:.4f}")
            print(f"    signed close median: {stats.get('signed_close_median')}")
            print(f"    signed close p95abs: {stats.get('signed_close_p95_abs')}")
            if stats["first_disagreement"]:
                fd = stats["first_disagreement"]
                print(f"    first              : {fd['ts']} {fd['column']} "
                      f"history={fd['history']} feed={fd['feed']}")
            for c, cd in stats["columns"].items():
                print(f"      {c:6s} bad={cd['disagreeing']:5d}  max_gap={cd['max_gap']:.4f}  "
                      f"median_gap_where_bad={cd['median_gap_where_bad']:.4f}")
    finally:
        try:
            broker.disconnect()
        except Exception:
            pass

    # SC2: an empty overlap on BOTH arms means the fetch window never reached history and the
    # comparison proves nothing either way.
    if all(results.get(k, {}).get("shared", 0) == 0 for k in ("MNKD", "NKD")):
        print("\n[SC2 FAIL] neither arm overlapped history - this measured nothing")
        return 2
    print("\n[SC2 PASS] at least one arm overlapped history")

    verdict = "inconclusive"
    m, n = results.get("MNKD", {}), results.get("NKD", {})
    if m.get("shared") and n.get("shared"):
        if m.get("disagreeing_bars", 0) > 0 and n.get("disagreeing_bars", 0) == 0:
            verdict = "symbol_explains_it"
        elif m.get("disagreeing_bars", 0) > 0 and n.get("disagreeing_bars", 0) > 0:
            verdict = "not_only_the_symbol"
        elif m.get("disagreeing_bars", 0) == 0:
            verdict = "no_disagreement_on_either_arm"

    report = {"tool": "stage5q7_mnkd_identity_probe", "parquet": str(path),
              "through_naive_et": str(through), "client_id": a.client_id,
              "identities": ident, "arms": results, "verdict": verdict}
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nVERDICT: {verdict}")
    print(f"wrote {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
