"""scratch/calm_mes_cap_monitor.py — two counterfactual ledgers for the Calm A sleeve.

Read-only. Rebuilds everything from what the 10:00 Calm slot already wrote, every run, so there
is no state to drift. Writes nothing.

  candidates global_index/track1_runtime/signals/track1_signals_<yyyymmdd>.jsonl
             (slot TRACK1_CALM_EXECUTE_1000: every leg the detector produced, taken or not)
  refusals   global_index/track1_runtime/shadow/explanations/live_<day>/roska4_calm/
             TRACK1_CALM_EXECUTE_1000/explanations_*.jsonl
  fills      global_index/track1_runtime/trade_log.track1.jsonl (OPEN rows, roska4_calm)
  bars       global_index/track1_runtime/session_bars/<INST>_<yyyymmdd>.parquet (tz-naive UTC)

Backtest rules for every hypothetical: entry at the leg's price (the paper fill when the leg was
traded, the slot's reference price otherwise), disaster stop as planned, exit at the OPEN of the
15:55 ET bar, cost = the backtest round turn at 2 ticks/side. Take-profit: bars strictly after
the 10:00 entry bar and strictly before 15:55; stop checked first inside a bar; fill at the TP,
or at the bar open if it gapped through.

Gates (decided 2026-10-20, before the ledgers were counted):

  1. FAMILY CAP. Legs refused by `reject_family_cap`. Once n >= 20:
     mean P&L >= $20 AND no leg lost more than 1R  ->  revisit the family cap.

  2. TAKE-PROFIT. Every Calm leg. A level is ELIGIBLE only if BOTH hold:
     a. backtest not worse: in EACH window (2018-24, 2025, 2026 to Aug-19) the level's Calm P&L
        is >= hold-to-15:55 (BACKTEST_DELTA below; re-derive with --backtest);
     b. live, once n >= 20 settled legs: the level's total beats hold-to-15:55.

    python scratch/calm_mes_cap_monitor.py               # ledgers + gates
    python scratch/calm_mes_cap_monitor.py --backtest    # also re-derive BACKTEST_DELTA (~5 min)
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from futures.basket import BASKET  # noqa: E402
import scratch.stress_switch_full_replay_20260822 as full  # noqa: E402

RT = ROOT / "global_index" / "track1_runtime"
CAP_N, CAP_MEAN, TP_N = 20, 20.0, 20
COSTS = full.costs_for_basket(slippage_ticks=2.0)
STOP_ATR = 1.5

#: name -> ("usd", dollars per contract) or ("atr", multiple of the daily ATR the stop uses)
TP_LEVELS = {"$300": ("usd", 300.0), "$400": ("usd", 400.0), "$500": ("usd", 500.0),
             "0.5ATR": ("atr", 0.5), "0.75ATR": ("atr", 0.75), "1.0ATR": ("atr", 1.0)}
WINDOWS = ("floor", "vault2025", "vault2026")

#: Calm P&L of each TP level MINUS hold-to-15:55, per backtest window, on the Track 1 route
#: replay (route caps, breaker, 2-tick slippage). Measured 2026-10-20 by `--backtest` on this
#: script's own TP rule; the run reproduced the stored route nets $64,902.91 / $13,236.11 /
#: $8,259.85 for hold-to-15:55 before any level was applied.
BACKTEST_DELTA = {
    "$300":    (740.00, -67.00, -503.50),
    "$400":    (233.50, 0.00, -103.50),
    "$500":    (0.00, 0.00, -192.50),
    "0.5ATR":  (-1056.19, 38.06, -131.70),
    "0.75ATR": (37.91, 6.65, 0.00),
    "1.0ATR":  (260.98, 0.00, 0.00),
}


# ── reading what the slot wrote ─────────────────────────────────────────────────────────────
def _jsonl(path: Path):
    if path.exists():
        for line in open(path, encoding="utf-8"):
            if line.strip():
                yield json.loads(line)


def legs() -> list:
    fills = {r["trade_id"]: r for r in _jsonl(RT / "trade_log.track1.jsonl")
             if r.get("type") == "OPEN" and r.get("cluster") == "roska4_calm"}
    refused = {}
    pat = str(RT / "shadow" / "explanations" / "live_*" / "roska4_calm" /
              "TRACK1_CALM_EXECUTE_1000" / "explanations_*.jsonl")
    for f in glob.glob(pat):
        for r in _jsonl(Path(f)):
            if r.get("status") == "rejected":
                refused[r.get("candidate_id")] = r.get("reason_code")
    out = []
    for f in sorted(glob.glob(str(RT / "signals" / "track1_signals_*.jsonl"))):
        for r in _jsonl(Path(f)):
            if r.get("slot_id") != "TRACK1_CALM_EXECUTE_1000":
                continue
            for c in r.get("candidates") or []:
                tid = c.get("trade_id") or ""
                ref, stop = float(c["entry"]), float(c["stop"])
                leg = {"day": str(r["session_date"]), "inst": c["instrument"], "trade_id": tid,
                       "ref": ref, "stop": stop, "risk": float(c["risk"]),
                       "atr": (ref - stop) / STOP_ATR}
                if tid in fills:
                    leg.update(kind="traded", entry=float(fills[tid]["fill_price"]))
                elif refused.get(tid) == "reject_family_cap":
                    leg.update(kind="cap_refused", entry=ref)
                elif tid in refused:
                    leg.update(kind=f"refused:{refused[tid]}", entry=ref)
                else:
                    leg.update(kind="shadow", entry=ref)
                out.append(leg)
    seen, uniq = set(), []
    for leg in out:                      # a re-run slot may write the same leg twice
        if leg["trade_id"] not in seen:
            seen.add(leg["trade_id"]); uniq.append(leg)
    return uniq


def bars_et(day: str, inst: str) -> "pd.DataFrame | None":
    f = RT / "session_bars" / f"{inst}_{day.replace('-', '')}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)
    df.index = pd.DatetimeIndex(df.index).tz_localize("UTC").tz_convert("America/New_York").tz_localize(None)
    return df


# ── one leg, one exit rule ──────────────────────────────────────────────────────────────────
def settle(leg: dict) -> dict:
    df = bars_et(leg["day"], leg["inst"])
    if df is None:
        return {**leg, "status": "no_bars"}
    d0 = pd.Timestamp(leg["day"])
    t_ref, t_in, t_out = (d0 + pd.Timedelta(h) for h in ("09:59:00", "10:00:00", "15:55:00"))
    # Self-check: the frame must reproduce the slot's own reference price, or it is not the
    # frame the slot read (wrong timezone, wrong file) and every number below would be wrong.
    if t_ref not in df.index or abs(float(df.loc[t_ref, "close"]) - leg["ref"]) > 1e-9:
        return {**leg, "status": "frame_mismatch"}
    if t_out not in df.index:
        return {**leg, "status": "pending_1555"}
    inst, entry, stop = leg["inst"], leg["entry"], leg["stop"]
    pv, cost = BASKET[inst].point_value, COSTS[inst].round_turn_cost()
    path = df[(df.index > t_in) & (df.index < t_out)]

    def run(tp: "float | None") -> float:
        for _, b in path.iterrows():
            if float(b["low"]) <= stop:
                px = float(b["open"]) if float(b["open"]) <= stop else stop
                return (px - entry) * pv - cost
            if tp is not None and float(b["high"]) >= tp:
                px = float(b["open"]) if float(b["open"]) >= tp else tp
                return (px - entry) * pv - cost
        if float(df.loc[t_out, "low"]) <= stop and float(df.loc[t_out, "open"]) <= stop:
            return (float(df.loc[t_out, "open"]) - entry) * pv - cost
        return (float(df.loc[t_out, "open"]) - entry) * pv - cost

    hold = run(None)
    res = {**leg, "status": "settled", "hold": round(hold, 2), "hold_r": round(hold / leg["risk"], 3),
           "max_unrealised": round((float(path["high"].max()) - entry) * pv, 2)}
    for name, (kind, v) in TP_LEVELS.items():
        tp = entry + (v / pv if kind == "usd" else v * leg["atr"])
        res[name] = round(run(tp), 2)
    return res


# ── backtest re-derivation (in-process patch of the replay's Calm exit; no file is written) ──
def backtest_delta() -> dict:
    import scratch.calm_a_disaster_stop_probe_20260822 as dis
    from futures.circuit_breaker import CircuitBreaker
    from global_index import track1_sleeves as sleeves
    from global_index.track1_signal_layer import (ACCOUNT, Track1Book, make_guard,
                                                  run_candidates)
    orig_build, orig_sim = dis.build_calm_trades, dis.simulate_exit
    st = {"level": None, "meta": None}

    def build(which, spec, meta, frames, slip_ticks=2.0):
        st["meta"] = meta
        return orig_build(which, spec, meta, frames, slip_ticks)

    def sim(row, stop, frames, slip_ticks=2.0):
        base = orig_sim(row, stop, frames, slip_ticks)
        if st["level"] is None:
            return base
        kind, v = TP_LEVELS[st["level"]]
        inst, entry = row["inst"], float(row["entry"])
        pv = BASKET[inst].point_value
        tp = entry + (v / pv if kind == "usd" else v * dis.atr_value(st["meta"], inst, pd.Timestamp(row["day"])))
        e0, x0 = pd.Timestamp(row["entry_time"]), pd.Timestamp(row["exit_time"])
        df = frames[inst]
        for ts, b in df[(df.index > e0) & (df.index < x0)].iterrows():
            if stop is not None and float(b["low"]) <= stop:
                return base
            if float(b["high"]) >= tp:
                px = float(b["open"]) if float(b["open"]) >= tp else tp
                cost = dis.calm_a_base.full.costs_for_basket(slippage_ticks=slip_ticks)[inst].round_turn_cost()
                return {**base, "exit": px, "exit_time": ts, "exit_reason": "tp",
                        "pnl_sized": (px - entry) * pv - cost}
        return base

    dis.build_calm_trades, dis.simulate_exit = build, sim
    try:
        def calm_net(window: str) -> float:
            mod = sys.modules.get("scratch.track1_replay_source_20260822")
            if mod is not None:
                mod._CACHE.pop(window, None)
            src = sleeves.load_source("replay")
            book = Track1Book(guard=make_guard(), breaker=CircuitBreaker(account=ACCOUNT),
                              enforce_windows=True)
            _, ds = run_candidates(src.candidates(window), book=book,
                                   early_exit_value=src.early_exit_valuer(window))
            return sum(d.candidate.pnl_sized for d in ds
                       if d.verdict == "take" and d.candidate.sleeve == "roska4_calm")
        out = {}
        for w in WINDOWS:
            st["level"] = None
            hold = calm_net(w)
            for name in TP_LEVELS:
                st["level"] = name
                out.setdefault(name, []).append(round(calm_net(w) - hold, 2))
        return {k: tuple(v) for k, v in out.items()}
    finally:
        dis.build_calm_trades, dis.simulate_exit = orig_build, orig_sim


# ── report ──────────────────────────────────────────────────────────────────────────────────
def main(argv: list) -> int:
    rows = [settle(leg) for leg in legs()]
    bad = [r for r in rows if r["status"] != "settled"]
    ok = [r for r in rows if r["status"] == "settled"]

    print("== 1. FAMILY CAP: legs refused by reject_family_cap (hold to 15:55)")
    cap = [r for r in rows if r["kind"] == "cap_refused"]
    for r in cap:
        tail = (f"{r['hold']:>9}{r['hold_r']:>8}{r['max_unrealised']:>10}" if r["status"] == "settled"
                else f"  {r['status']}")
        print(f"   {r['day']} {r['inst']:<4} entry {r['entry']:<9}{tail}")
    cs = [r for r in cap if r["status"] == "settled"]
    if cs:
        pnl = pd.Series([r["hold"] for r in cs]); worst = min(r["hold_r"] for r in cs)
        print(f"   settled {len(cs)}/{CAP_N} | total ${pnl.sum():,.2f} | mean ${pnl.mean():,.2f} | "
              f"win {(pnl > 0).mean():.0%} | worst {worst:+.2f}R")
        if len(cs) < CAP_N:
            print(f"   GATE 1: waiting ({CAP_N - len(cs)} more)")
        else:
            g = pnl.mean() >= CAP_MEAN and worst >= -1.0
            print(f"   GATE 1: {'PASS -> revisit the family cap' if g else 'FAIL -> keep 4.4%'}")

    print("\n== 2. TAKE-PROFIT: every Calm leg (P&L per level vs hold to 15:55)")
    names = list(TP_LEVELS)
    print(f"   {'day':<11}{'inst':<5}{'kind':<13}{'hold':>8}{'maxUnr':>8}" + "".join(f"{n:>9}" for n in names))
    for r in ok:
        print(f"   {r['day']:<11}{r['inst']:<5}{r['kind'][:12]:<13}{r['hold']:>8}{r['max_unrealised']:>8}"
              + "".join(f"{r[n]:>9}" for n in names))
    for r in bad:
        print(f"   {r['day']:<11}{r['inst']:<5}{r['kind'][:12]:<13}  {r['status']} (excluded)")
    hold_sum = sum(r["hold"] for r in ok)
    print(f"\n   settled legs {len(ok)}/{TP_N} | hold-to-15:55 total ${hold_sum:,.2f}")
    print(f"   {'level':<9}{'live vs hold':>14}{'bt 2018-24':>12}{'bt 2025':>10}{'bt 2026':>10}  eligible?")
    for n in names:
        live = sum(r[n] for r in ok) - hold_sum
        bt = BACKTEST_DELTA[n]
        a = all(x >= 0 for x in bt)
        if not a:
            verdict = "NO (backtest worse in a window)"
        elif len(ok) < TP_N:
            verdict = f"backtest ok; live waiting ({TP_N - len(ok)} more)"
        else:
            verdict = "YES" if live > 0 else "NO (live not better)"
        print(f"   {n:<9}{live:>14,.2f}{bt[0]:>12,.2f}{bt[1]:>10,.2f}{bt[2]:>10,.2f}  {verdict}")

    if "--backtest" in argv:
        print("\n== re-deriving BACKTEST_DELTA from the route replay ...")
        fresh = backtest_delta()
        for n in names:
            same = all(abs(a - b) < 0.01 for a, b in zip(fresh[n], BACKTEST_DELTA[n]))
            print(f"   {n:<9}{fresh[n]}  {'matches' if same else 'DIFFERS from the constant'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
