"""Independent verification of the repaired combined replay. SCRATCH-ONLY.

The repaired replay reports its own `double_booked = 0`. A counter a script keeps
about itself is not evidence, so this rebuilds the same control flow with separate
instrumentation and asks four questions the repaired script does not ask itself:

  Q1  does every position that ever entered the book settle EXACTLY once?
      (catches both double settlement and the silent-drop path where a forced
       close finds no price and the position disappears with no cashflow)
  Q2  is there any instant where two positions on the same contract are held?
  Q3  how high did combined Normal+Calm gross exposure actually go with the
      family cap switched off?  — this is what sizes whether the family cap was
      needed at all, rather than assuming it was
  Q4  does the forced-close price lookup ever come back empty?

GATE: the mirror must reproduce the repaired script's net and worst drawdown to
the cent for the same window and policy. If it does not, none of Q1-Q4 is being
measured on the same book and nothing below is reported.

  python scratch/combined_repaired_verify_20260822.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.calm_a_combined_replay_20260822 as calm_a_base
import scratch.calm_nkd_switch_vs_current_20260822 as calm_nkd
import scratch.combined_repaired_replay_20260822 as rep
import scratch.combined_stop_risk_audit_20260822 as audit
import scratch.stress_switch_full_replay_20260822 as full
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT

OUT = Path("scratch/combined_repaired_verify_20260822.json")
FAMILY = ("roska4_swing", "roska4_calm")


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


def mirror(which: str, policy) -> dict:
    """Same control flow as rep.replay_repaired, separate instrumentation."""
    r4, current_nkd, prices, extra, stress, calm_nkd_df = audit.load_all(which)
    calm_a = rep.load_calm_a_atr15(which, extra["meta"])
    if not policy.include_calm_nkd_switch:
        calm_nkd_df = calm_nkd_df.iloc[0:0]
    guard = rep.make_guard()
    breaker = full.CircuitBreaker(account=ACCOUNT)
    open_pos, realized, equity, cur_day = [], {}, ACCOUNT, None

    entered, settled = {}, {}          # trade_id -> count
    overlaps, ledger = [], []
    missing_price = 0
    fam_peak = 0.0
    fam_series = []

    entries = pd.concat([p for p in (r4, stress, current_nkd, calm_nkd_df, calm_a)
                         if not p.empty], ignore_index=True)
    by_time, times = {}, set()
    for _, row in entries.iterrows():
        tr = row.to_dict()
        et, xt = pd.Timestamp(tr["entry_time"]), pd.Timestamp(tr["exit_time"])
        by_time.setdefault(et, []).append(tr)
        times.add(et)
        times.add(xt)

    def book(ts, tr, pnl, kind):
        nonlocal equity
        equity += float(pnl)
        d = naive(ts).normalize()
        realized[d] = realized.get(d, 0.0) + float(pnl)
        tid = tr.get("trade_id", "?")
        settled[tid] = settled.get(tid, 0) + 1
        ledger.append((str(ts), tid, kind, float(pnl)))

    def admit(ts, pos, tr):
        nonlocal fam_peak
        for p, t in open_pos:
            if p.instrument == tr["instrument"]:
                overlaps.append(dict(ts=str(ts), inst=p.instrument,
                                     held=f"{t['source']}/{p.cluster}/{t['direction']}",
                                     new=f"{tr['source']}/{pos.cluster}/{tr['direction']}"))
        open_pos.append((pos, tr))
        entered[tr.get("trade_id", "?")] = entered.get(tr.get("trade_id", "?"), 0) + 1
        fam = [p for p, _ in open_pos if p.cluster in FAMILY]
        lo = sum(p.risk_dollars for p in fam if p.direction == "LONG")
        sh = sum(p.risk_dollars for p in fam if p.direction == "SHORT")
        g = max(lo, sh) / ACCOUNT
        n = abs(lo - sh) / ACCOUNT
        fam_series.append((g, n))
        fam_peak = max(fam_peak, g)

    for ts in sorted(times):
        day = naive(ts).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                book(ts, tr, float(tr["pnl_sized"]), "exit")
            else:
                still.append((pos, tr))
        open_pos = still
        breaker.update(equity)
        allow = breaker.status(equity).get("allow_new_entries", True)

        for tr in sorted(by_time.get(ts, []), key=entry_priority_key):
            if not allow:
                continue
            src, inst, cluster = tr["source"], tr["instrument"], tr["cluster"]
            open_positions = [p for p, _ in open_pos]

            if src == "normal_nkd_filtered_bucket" and any(t["source"] == "calm_nkd" for _, t in open_pos):
                continue

            if src == "calm_nkd":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket")]
                proposed = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    continue
                for _, old in [(p, t) for p, t in open_pos
                               if p.instrument == "MNKD" and t["source"] == "normal_nkd_filtered_bucket"]:
                    ep = calm_nkd.early_nkd_pnl(old, float(tr["entry"]) + rep.OFFSET[which])
                    book(ts, old, ep, "forced_close_by_calm_nkd")
                open_pos = survivors
                admit(ts, proposed, tr)
                continue

            if src == "calm_a_pcloc_not_deep":
                if any(p.instrument == inst and p.cluster in ("roska4_swing", "roska4_stress")
                       for p, _ in open_pos):
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, open_positions)
                if ok and not rep.family_admits(pos, open_positions, policy):
                    ok = False
                if ok:
                    admit(ts, pos, tr)
                continue

            if cluster == "roska4_stress":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == inst and p.cluster in FAMILY)]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)),
                                    float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    continue
                for p, old in [(p, t) for p, t in open_pos
                               if p.instrument == inst and p.cluster in FAMILY]:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        missing_price += 1
                        continue
                    ep = (calm_a_base.early_calm_pnl(old, px, 2.0) if p.cluster == "roska4_calm"
                          else full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0)))
                    book(ts, old, ep, "forced_close_by_stress")
                open_pos = survivors
                admit(ts, proposed, tr)
                continue

            if cluster == "roska4_swing":
                if any(p.instrument == inst and p.cluster in ("roska4_stress", "roska4_calm")
                       for p, _ in open_pos):
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, open_positions)
                if ok and not rep.family_admits(pos, open_positions, policy):
                    ok = False
                if ok:
                    admit(ts, pos, tr)
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(pos, open_positions)
            if ok:
                admit(ts, pos, tr)

    daily = pd.Series(realized).sort_index()
    never = [t for t in entered if t not in settled]
    twice = {t: c for t, c in settled.items() if c > 1}
    ghost = [t for t in settled if t not in entered]
    fam_g = pd.Series([g for g, _ in fam_series]) if fam_series else pd.Series(dtype=float)
    fam_n = pd.Series([n for _, n in fam_series]) if fam_series else pd.Series(dtype=float)
    return dict(daily=daily, ledger=ledger, overlaps=overlaps,
                n_entered=len(entered), n_settled=len(settled),
                never_settled=never, settled_twice=twice, ghost_settlements=ghost,
                missing_price=missing_price,
                family_gross_peak=float(fam_peak),
                family_gross_p50=float(fam_g.quantile(0.50)) if len(fam_g) else 0.0,
                family_gross_p90=float(fam_g.quantile(0.90)) if len(fam_g) else 0.0,
                family_gross_p99=float(fam_g.quantile(0.99)) if len(fam_g) else 0.0,
                family_net_peak=float(fam_n.max()) if len(fam_n) else 0.0,
                n_family_obs=int(len(fam_g)),
                n_family_over_5pct=int((fam_g > 0.050).sum()) if len(fam_g) else 0,
                n_family_over_7p5pct=int((fam_g > 0.075).sum()) if len(fam_g) else 0)


def main() -> int:
    out = {}
    for which in ("floor", "vault2025", "vault2026"):
        out[which] = {}
        for policy in rep.POLICIES:
            official_daily, official_st = rep.replay_repaired(which, policy)
            om = metrics(official_daily)
            m = mirror(which, policy)
            mm = metrics(m["daily"])
            gate = (round(om["pnl"], 2) == round(mm["pnl"], 2)
                    and round(om["maxdd"], 2) == round(mm["maxdd"], 2))
            row = dict(
                gate_matches_repaired_script=bool(gate),
                official_net=round(float(om["pnl"]), 2), mirror_net=round(float(mm["pnl"]), 2),
                official_maxdd=round(float(om["maxdd"]), 2), mirror_maxdd=round(float(mm["maxdd"]), 2),
                ledger_sum=round(sum(x[3] for x in m["ledger"]), 2),
                positions_entered=m["n_entered"], positions_settled=m["n_settled"],
                never_settled=len(m["never_settled"]), settled_twice=len(m["settled_twice"]),
                ghost_settlements=len(m["ghost_settlements"]),
                same_symbol_overlaps=len(m["overlaps"]),
                overlap_sample=m["overlaps"][:5],
                forced_close_missing_price=m["missing_price"],
                script_double_booked=official_st["double_booked"],
                family_gross_peak=m["family_gross_peak"],
                family_gross_p50=m["family_gross_p50"],
                family_gross_p90=m["family_gross_p90"],
                family_gross_p99=m["family_gross_p99"],
                family_net_peak=m["family_net_peak"],
                n_family_obs=m["n_family_obs"],
                n_family_over_5pct=m["n_family_over_5pct"],
                n_family_over_7p5pct=m["n_family_over_7p5pct"],
            )
            out[which][policy.name] = row
            flag = "OK " if gate else "GATE-FAIL"
            print(f"[{flag}] {which:10s} {policy.name:40s} net {mm['pnl']:>10,.0f} "
                  f"entered={row['positions_entered']} settled={row['positions_settled']} "
                  f"twice={row['settled_twice']} never={row['never_settled']} "
                  f"overlaps={row['same_symbol_overlaps']}", flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    bad = [f"{w}/{p}" for w, d in out.items() for p, r in d.items()
           if not r["gate_matches_repaired_script"]]
    if bad:
        print("GATE FAILED for:", bad)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
