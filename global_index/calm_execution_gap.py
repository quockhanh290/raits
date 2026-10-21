"""global_index/calm_execution_gap.py — what the Calm paper fills cost against the backtest's prices.

READ-ONLY. Sends nothing, writes nothing, touches no book. It reads the Track 1 trade log and the
one-minute bars the system already holds, and prints how far each real fill landed from the price
the backtest transacts at:

    entry   the OPEN of the 10:00 bar        (the order is a market order sent at ~10:00:0x)
    exit    the OPEN of the 15:55 bar        (the clock-exit job starts at 15:54, see
                                              track1_slots.CALM_TIME_EXIT_LEAD_MINUTES)

Why it exists (2026-10-05). The exit was deliberately moved a minute early so its rewrite of the
positions file cannot race the 15:55 swing slot, and the entry price is planned from the closed
09:59 bar. Both are deviations from the backtest and both were estimated from one-minute bars on
381 historical setups (exit mid-15:54 vs the 15:55 open: mean +$0.05 per contract, sd $6.9; entry
16 s after the open: mean +$0.41, sd $5.6; together ~10% of the $4.71 round-trip cost the backtest
assumes). Estimated is not measured. This is the measurement, to be run after the first real fills.

Sign convention: POSITIVE = WORSE than the backtest price, for the position's direction (a LONG buy
above the 10:00 open, a LONG sell below the 15:55 open), in ticks and in dollars per contract.

Three outcomes per fill, never two. A fill is `measured`, or `unmeasured` with the reason — the
bar is not in the parquet yet (the 15:55 bar arrives with the NEXT 13:45 update), or the fill is not
on the bars' price scale. An unmeasured fill is never reported as a zero gap, and a run that finds
fills but measures none exits non-zero instead of printing a clean table.

Usage (from d:\\raits):
    python -m global_index.calm_execution_gap                 # every Calm fill in the trade log
    python -m global_index.calm_execution_gap --day 2026-10-06
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import pandas as pd

CLUSTER = "roska4_calm"
TRADE_LOG = "global_index/track1_runtime/trade_log.track1.jsonl"
DATA_DIR = "data/cache/futures"
#: fill-to-bar distance beyond this fraction of price means the two are not on one price scale.
#: The parquet store holds several scales (back-adjusted history vs the live feed); comparing
#: across them yields a huge "gap" that is an artefact, and an impossible value is evidence the
#: ruler is wrong, not that the fill was.
SCALE_LIMIT = 0.02
ET = "America/New_York"
ENTRY_AT, EXIT_AT = "10:00", "15:55"

DATA_SYMBOL = {"MES": "ES", "MNQ": "NQ"}


def _contract(inst: str):
    from futures.basket import BASKET
    return BASKET[inst]


def load_rows(trade_log: str | Path, cluster: str = CLUSTER) -> list:
    """Calm OPEN rows and TIME_EXIT CLOSE rows, in file order. Torn lines are counted, not hidden."""
    rows, torn = [], 0
    p = Path(trade_log)
    if not p.exists():
        return rows
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            torn += 1
            continue
        if not isinstance(r, dict) or str(r.get("cluster")) != cluster:
            continue
        kind = str(r.get("type")).upper()
        if kind == "OPEN" or (kind == "CLOSE" and str(r.get("exit_reason")).upper() == "TIME_EXIT"):
            rows.append(r)
    if torn:
        rows.append({"type": "TORN", "count": torn})
    return rows


def _naive_minutes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index).tz_convert(ET).tz_localize(None) \
        if getattr(out.index, "tz", None) is not None else pd.DatetimeIndex(out.index)
    return out


def minute_open(frame: pd.DataFrame, day: str, hhmm: str):
    """The OPEN of the bar stamped `hhmm` on `day`, or None when that bar is not there."""
    ts = pd.Timestamp(day) + pd.Timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:]))
    return float(frame.loc[ts, "open"]) if ts in frame.index else None


def _latency_seconds(row: dict, day: str, hhmm: str):
    """Seconds from the instant the order was meant to go to the moment the row was written."""
    try:
        written = pd.Timestamp(row["ts"])
        written = written.tz_convert(ET) if written.tzinfo is not None else written.tz_localize("UTC").tz_convert(ET)
        meant = pd.Timestamp(f"{day} {hhmm}", tz=ET)
        return float((written - meant).total_seconds())
    except Exception:                                           # noqa: BLE001
        return None


def measure(rows: list, frames: dict) -> list:
    """One dict per fill: `measured` with gaps, or `unmeasured` with the reason.

    `frames` maps an instrument to its one-minute bars on a naive-ET index (`_naive_minutes`).
    """
    out = []
    for r in rows:
        kind = str(r.get("type")).upper()
        if kind not in ("OPEN", "CLOSE"):
            continue
        inst = str(r.get("inst"))
        day = str(r.get("entry_day") if kind == "OPEN" else r.get("exit_day"))[:10]
        base = {"type": kind, "inst": inst, "day": day, "fill": r.get("fill_price")}
        hhmm = ENTRY_AT if kind == "OPEN" else EXIT_AT
        frame = frames.get(inst)
        fill = r.get("fill_price")
        if frame is None:
            out.append({**base, "status": "unmeasured", "reason": f"no bars loaded for {inst}"})
            continue
        ref = minute_open(frame, day, hhmm)
        if ref is None:
            out.append({**base, "status": "unmeasured",
                        "reason": f"the {hhmm} bar of {day} is not in the parquet yet"})
            continue
        try:
            fill = float(fill)
        except (TypeError, ValueError):
            out.append({**base, "status": "unmeasured", "reason": "the row carries no fill price"})
            continue
        if ref <= 0 or abs(fill - ref) / ref > SCALE_LIMIT:
            out.append({**base, "status": "unmeasured", "ref": ref,
                        "reason": f"fill {fill} and bar open {ref} are not on one price scale"})
            continue
        c = _contract(inst)
        direction = str(r.get("direction") or "LONG").upper()
        buys = (kind == "OPEN") == (direction == "LONG")        # LONG open / SHORT close buy
        pts = (fill - ref) if buys else (ref - fill)            # positive = worse than the backtest
        rec = {**base, "status": "measured", "ref": ref, "points": pts,
               "ticks": pts / c.tick, "usd": pts * c.point_value,
               "latency_s": _latency_seconds(r, day, hhmm)}
        if kind == "OPEN" and r.get("expected_entry") is not None:
            try:
                rec["planned_vs_open_ticks"] = (ref - float(r["expected_entry"])) / c.tick
            except (TypeError, ValueError):
                pass
        out.append(rec)
    return out


def summarize(measured: list) -> dict:
    """Per leg: n, and mean / sd / p90 of the gap and of the latency. Empty legs say so."""
    summary = {}
    for kind in ("OPEN", "CLOSE"):
        ms = [m for m in measured if m["type"] == kind and m["status"] == "measured"]
        un = [m for m in measured if m["type"] == kind and m["status"] != "measured"]
        s = {"n_measured": len(ms), "n_unmeasured": len(un)}
        if ms:
            usd = [m["usd"] for m in ms]
            tk = sorted(m["ticks"] for m in ms)
            lat = [m["latency_s"] for m in ms if m.get("latency_s") is not None]
            s.update(mean_usd=statistics.fmean(usd),
                     sd_usd=statistics.stdev(usd) if len(usd) > 1 else None,
                     mean_ticks=statistics.fmean(tk),
                     p90_ticks=tk[min(len(tk) - 1, int(0.9 * len(tk)))],
                     mean_latency_s=statistics.fmean(lat) if lat else None,
                     max_latency_s=max(lat) if lat else None)
        summary[kind] = s
    return summary


def _load_frames(data_dir: str, insts) -> dict:
    from futures._validated_core import load_parquet
    frames = {}
    for inst in sorted(insts):
        sym = DATA_SYMBOL.get(inst)
        p = Path(data_dir) / f"{sym}_continuous_1m_8y.parquet" if sym else None
        if p is not None and p.exists():
            frames[inst] = _naive_minutes(load_parquet(str(p)))
    return frames


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Calm fills vs the backtest's 10:00 / 15:55 opens (read-only)")
    ap.add_argument("--trade-log", default=TRADE_LOG)
    ap.add_argument("--data-dir", default=DATA_DIR)
    ap.add_argument("--day", default=None, help="only fills of this ET date (YYYY-MM-DD)")
    a = ap.parse_args(argv)

    rows = load_rows(a.trade_log)
    torn = [r for r in rows if r.get("type") == "TORN"]
    rows = [r for r in rows if r.get("type") != "TORN"]
    if a.day:
        rows = [r for r in rows
                if str(r.get("entry_day") if str(r.get("type")).upper() == "OPEN" else r.get("exit_day"))[:10] == a.day]
    print(f"trade log: {a.trade_log}  |  cluster {CLUSTER}  |  fills found: {len(rows)}"
          + (f"  |  {torn[0]['count']} torn line(s) skipped" if torn else ""))
    if not rows:
        print("No Calm fill in the trade log. Nothing measured — this is NOT a clean result.")
        return 3

    measured = measure(rows, _load_frames(a.data_dir, {str(r.get("inst")) for r in rows}))
    for m in measured:
        if m["status"] == "measured":
            lat = f"  {m['latency_s']:+.0f}s after" if m.get("latency_s") is not None else ""
            print(f"  {m['type']:<5} {m['inst']} {m['day']}  fill {m['fill']}  ref {m['ref']}  "
                  f"worse-by {m['ticks']:+.2f} ticks  ${m['usd']:+.2f}/contract{lat}")
        else:
            print(f"  {m['type']:<5} {m['inst']} {m['day']}  UNMEASURED — {m['reason']}")
    s = summarize(measured)
    print()
    for kind, label in (("OPEN", "ENTRY vs 10:00 open"), ("CLOSE", "EXIT  vs 15:55 open")):
        d = s[kind]
        if not d["n_measured"]:
            print(f"{label}: no fill measured ({d['n_unmeasured']} unmeasured)")
            continue
        sd = f"{d['sd_usd']:.2f}" if d["sd_usd"] is not None else "n/a (one fill)"
        lat = (f", latency mean {d['mean_latency_s']:.0f}s max {d['max_latency_s']:.0f}s"
               if d.get("mean_latency_s") is not None else "")
        print(f"{label}: n={d['n_measured']}  mean ${d['mean_usd']:+.2f}  sd {sd}  "
              f"mean {d['mean_ticks']:+.2f} ticks  p90 {d['p90_ticks']:+.2f}{lat}  "
              f"({d['n_unmeasured']} unmeasured)")
    print("\nBacktest assumes 2 ticks/side. Offline estimate (381 setups, bar level): exit mean "
          "+$0.05, entry mean +$0.41 per contract. Compare, do not tune: n is tiny at first.")
    return 0 if any(m["status"] == "measured" for m in measured) else 2


if __name__ == "__main__":
    sys.exit(main())
