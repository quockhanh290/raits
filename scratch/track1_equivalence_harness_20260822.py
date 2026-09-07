"""Track 1 Stage 2A — offline resume-vs-full-replay equivalence harness. SCRATCH-ONLY.

Offline. Reads parquet and the day logs. Starts nothing, connects to nothing, writes only
under scratch/.

Two anchors, and they are NOT the same thing
--------------------------------------------
**A1 — log anchor (a reproduction of the RECORD).** Re-derive the published shadow counts
from `live_day_*.log`. This proves the harness is reading the same evidence the reports
were built on. It does not re-run any computation.

**A2 — parquet equivalence (NEW evidence).** Replay a window in full, then replay the same
window resumed from a checkpoint cut partway through, and require the open position and the
post-cut trade sequence to match exactly.

**A2 is not a reproduction of the shadow comparison, and cannot be.** `run_live_day.py:400`
says so in its own words: the shadow runs on frames spliced from live IBKR bars, and those
frames carry *"IBKR bars that are never persisted"* — *"which no offline check can
reproduce"*. So the literal Stage 2 instruction ("the harness must reproduce 91 matched /
0 diverged") is achievable only as a **count** (A1), never as a **recomputation**. A2 is the
comparison a resume-primary route actually needs, because its oracle will also run on
parquet.

A second correction the anchor needs
------------------------------------
The published figures are `91 matched / 0 diverged` **across all logged days** and
`85 matched / 0 diverged` over **2026-08-10 → 2026-08-21**. The Stage 2 brief attaches 91 to
the narrower window; measured, that window is 85. Both are asserted separately below so the
mix-up cannot be inherited again.

    python scratch/track1_equivalence_harness_20260822.py
    python scratch/track1_equivalence_harness_20260822.py --a2-instruments MES MNQ
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

OUT_JSON = Path("scratch/track1_equivalence_harness_20260822.json")

# Published figures this harness must re-derive before anything else is believed.
ANCHOR_ALL_DAYS = {"matched": 91, "diverged": 0, "skipped": 64}
ANCHOR_WINDOW = {"matched": 85, "diverged": 0, "skipped": 0}
ANCHOR_WINDOW_RANGE = ("0810", "0821")

RE_MATCH = re.compile(r"\[shadow\] (\w+): DOI CHIEU KHOP")
RE_DIVERGE = re.compile(r"\[shadow\] (\w+): DOI CHIEU LECH")
RE_SKIP = re.compile(r"\[shadow\] (\w+): khong co checkpoint")

#: Fields compared on the open position. `extreme` and `stop` carry the ratchet state the
#: engine threads across days; omitting them would let a resumed position agree on entry
#: and disagree on where it exits.
POS_FIELDS = ("dir", "entry", "entry_day", "entry_time", "stop", "extreme", "regime")

#: Fields compared on every trade that closed after the checkpoint cut.
TRADE_FIELDS = ("day", "exit_day", "regime", "direction", "entry", "exit", "points",
                "pnl", "hold_days", "reason", "entry_time", "exit_time")


# ---------------------------------------------------------------------------
# A1 — log anchor
# ---------------------------------------------------------------------------
def a1_log_anchor() -> dict:
    per_day, tot = {}, {"matched": 0, "diverged": 0, "skipped": 0}
    win = {"matched": 0, "diverged": 0, "skipped": 0}
    for f in sorted(Path(".").glob("live_day_*.log")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        row = {"matched": len(RE_MATCH.findall(txt)),
               "diverged": len(RE_DIVERGE.findall(txt)),
               "skipped": len(RE_SKIP.findall(txt))}
        if not any(row.values()):
            continue
        per_day[f.name] = row
        for k in tot:
            tot[k] += row[k]
        day = f.name.replace("live_day_", "").replace(".log", "")
        if ANCHOR_WINDOW_RANGE[0] <= day <= ANCHOR_WINDOW_RANGE[1]:
            for k in win:
                win[k] += row[k]
    return {"per_day": per_day, "all_days": tot, "window": win,
            "all_days_ok": tot == ANCHOR_ALL_DAYS,
            "window_ok": win == ANCHOR_WINDOW,
            "expected_all_days": ANCHOR_ALL_DAYS,
            "expected_window": ANCHOR_WINDOW,
            "note": "a reproduction of the RECORD, not of the computation; the shadow ran "
                    "on live-spliced frames that are never persisted "
                    "(run_live_day.py:400)"}


# ---------------------------------------------------------------------------
# A2 — parquet resume vs full replay
# ---------------------------------------------------------------------------
def _norm(v):
    """One canonical rendering, so two representations of the same value cannot read as a
    divergence. Timestamps in particular arrive tz-aware from one path and naive from the
    other, exactly as the checkpoint's own fingerprint docstring warns."""
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return str(v.tz_localize(None) if v.tzinfo is not None else v)
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def _pos_key(pos):
    return None if pos is None else tuple(_norm(pos.get(f)) for f in POS_FIELDS)


def _trade_key(t):
    return tuple(_norm(t.get(f)) for f in TRADE_FIELDS)


def compare(full_trades, full_pos, res_trades, res_pos, cut_day) -> dict:
    """Ordered-sequence comparison. Exact, no tolerance.

    Sequences, not sets: once a cap admits by priority, the same trades in a different
    order are a different book, and a set comparison would call them equal.
    """
    cut = pd.Timestamp(cut_day).normalize()

    def after_cut(ts):
        d = pd.Timestamp(ts)
        return (d.tz_localize(None) if d.tzinfo is not None else d).normalize() > cut

    exp = [t for t in full_trades if after_cut(t["exit_day"])]
    got = list(res_trades)
    exp_k = [_trade_key(t) for t in exp]
    got_k = [_trade_key(t) for t in got]

    first_diff = None
    for i in range(max(len(exp_k), len(got_k))):
        e = exp_k[i] if i < len(exp_k) else None
        g = got_k[i] if i < len(got_k) else None
        if e != g:
            first_diff = {"index": i,
                          "expected": dict(zip(TRADE_FIELDS, e)) if e else None,
                          "resumed": dict(zip(TRADE_FIELDS, g)) if g else None}
            break

    pe, pg = _pos_key(full_pos), _pos_key(res_pos)
    return {
        "trades_expected": len(exp_k), "trades_resumed": len(got_k),
        "trades_match": exp_k == got_k,
        "first_trade_diff": first_diff,
        "pos_match": pe == pg,
        "pos_expected": dict(zip(POS_FIELDS, pe)) if pe else None,
        "pos_resumed": dict(zip(POS_FIELDS, pg)) if pg else None,
        "match": exp_k == got_k and pe == pg,
    }


def a2_instrument(inst: str, data_dir: str, start: str, end: str, cut: str,
                  ema: int, mult: float, regime_csv: str, hmm_fit_end: str,
                  slippage: float) -> dict:
    """Full replay vs resume-from-cut for one instrument, parquet only."""
    from futures._validated_core import (backtest_swing_tf, benchmark_daily,
                                         daily_atr_series, label_regimes, load_parquet)
    from futures.basket import BASKET, data_filename
    from futures.swing_tf import costs_for_basket
    import global_index.route_checkpoint as rc

    df = load_parquet(str(Path(data_dir) / data_filename(BASKET[inst])))
    tz = df.index.tz
    lo = pd.Timestamp(start).tz_localize(tz) if tz is not None else pd.Timestamp(start)
    hi = pd.Timestamp(end).tz_localize(tz) if tz is not None else pd.Timestamp(end)
    df = df[(df.index >= lo) & (df.index <= hi)]
    if df.empty:
        return {"inst": inst, "error": "no bars in window"}

    labels = label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3, hmm_fit_end)
    cost = costs_for_basket(slippage_ticks=slippage)[inst]
    kw = dict(ema_period=ema, chandelier_atr_mult=mult, max_hold_days=5)
    datr = daily_atr_series(df)

    full_trades, full_pos = backtest_swing_tf(df, labels, cost, datr=datr,
                                              return_open=True, **kw)

    # Replay to the cut, take the position there, then resume. The frame handed to the
    # resume MUST start at or before the cut day: _swing_cache derives gap flags from each
    # bar's spacing to the one before it and forces the frame's first bar to "no gap", so a
    # frame cut exactly at the resume day turns a GAP exit into a CHANDELIER one. The cut
    # day rides along as a lead-in and resume_after_day keeps it out of the replay.
    cut_ts = pd.Timestamp(cut).normalize()
    head_hi = (cut_ts + pd.Timedelta(days=1))
    head = df[df.index < (head_hi.tz_localize(tz) if tz is not None else head_hi)]
    if head.empty:
        return {"inst": inst, "error": "cut day precedes the window"}
    _ht, head_pos = backtest_swing_tf(head, labels, cost, datr=datr,
                                      return_open=True, **kw)

    start_ts = cut_ts.tz_localize(tz) if tz is not None else cut_ts
    sub = df[df.index >= start_ts]
    res_trades, res_pos = backtest_swing_tf(sub, labels, cost, datr=datr,
                                            resume_pos=head_pos,
                                            resume_after_day=cut_ts,
                                            return_open=True, **kw)

    out = {"inst": inst, "cut": str(cut_ts.date()),
           "bars": int(len(df)), "full_trades": int(len(full_trades)),
           "checkpoint_pos": _pos_key(head_pos) is not None,
           "fingerprint": rc.fingerprint(df, cut_ts)}
    out.update(compare(full_trades, full_pos, res_trades, res_pos, cut_ts))
    return out


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--hmm-fit-end", default="2024-12-31")
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-08-19")
    ap.add_argument("--cut", default="2026-06-30")
    ap.add_argument("--ema", type=int, default=30)
    ap.add_argument("--mult", type=float, default=2.5)
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--a2-instruments", nargs="+", default=["MES", "MNQ", "MYM", "M2K"])
    ap.add_argument("--skip-a2", action="store_true")
    a = ap.parse_args()

    out = {"a1_log_anchor": a1_log_anchor()}
    a1 = out["a1_log_anchor"]
    print(f"[A1] all days  matched={a1['all_days']['matched']} "
          f"diverged={a1['all_days']['diverged']} skipped={a1['all_days']['skipped']} "
          f"-> {'OK' if a1['all_days_ok'] else 'MISMATCH'}", flush=True)
    print(f"[A1] 08-10..21 matched={a1['window']['matched']} "
          f"diverged={a1['window']['diverged']} skipped={a1['window']['skipped']} "
          f"-> {'OK' if a1['window_ok'] else 'MISMATCH'}", flush=True)

    if not (a1["all_days_ok"] and a1["window_ok"]):
        out["blocker"] = ("A1 log anchor not reproduced — the harness is not reading the "
                          "evidence the published figures came from. A2 not run.")
        OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
        print("BLOCKER:", out["blocker"])
        return 1

    if not a.skip_a2:
        rows = []
        for inst in a.a2_instruments:
            r = a2_instrument(inst, a.data_dir, a.start, a.end, a.cut, a.ema, a.mult,
                              a.regime_csv, a.hmm_fit_end, a.slippage_ticks)
            rows.append(r)
            if "error" in r:
                print(f"[A2] {inst:5s} ERROR {r['error']}", flush=True)
            else:
                print(f"[A2] {inst:5s} full={r['full_trades']:4d} "
                      f"after_cut={r['trades_expected']:3d} resumed={r['trades_resumed']:3d} "
                      f"trades={'OK ' if r['trades_match'] else 'DIFF'} "
                      f"pos={'OK ' if r['pos_match'] else 'DIFF'} "
                      f"-> {'MATCH' if r['match'] else 'DIVERGED'}", flush=True)
        out["a2_parquet_equivalence"] = {
            "config": {k: getattr(a, k) for k in
                       ("data_dir", "start", "end", "cut", "ema", "mult", "hmm_fit_end",
                        "slippage_ticks")},
            "rows": rows,
            "all_match": all(r.get("match") for r in rows),
            "note": "NOT a reproduction of the shadow comparison: the shadow ran on frames "
                    "spliced with live IBKR bars that are never persisted "
                    "(run_live_day.py:400). This is the parquet-only equivalence a "
                    "resume-primary oracle would use.",
        }
    OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
