"""Does the Normal+Calm family cap actually hold the exposure it promises?

SCRATCH-ONLY.

The verification run recorded family exposure at admission instants and found a
peak NET of 4.89% under a 4.4% net cap. A cap that is 11% over its own ceiling is
either a broken cap or a cap that only binds at one kind of moment. This measures
family gross/net CONTINUOUSLY - at every event timestamp, not only at admissions -
and attributes every breach to the event that caused it.

Self-checks:
  SC1 the continuous peak must be >= the admission-time peak (a superset of moments)
  SC2 no family entry may be admitted into a state that already breaches its cap
  SC3 the observation series must be non-empty

  python scratch/combined_family_exposure_probe_20260822.py
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
from global_index.net_exposure_multi import Position, entry_priority_key
from scratch.normal_sleeve_fill_audit import ACCOUNT

OUT = Path("scratch/combined_family_exposure_probe_20260822.json")
FAMILY = ("roska4_swing", "roska4_calm")


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


def fam_state(open_pos):
    fam = [p for p, _ in open_pos if p.cluster in FAMILY]
    lo = sum(p.risk_dollars for p in fam if p.direction == "LONG")
    sh = sum(p.risk_dollars for p in fam if p.direction == "SHORT")
    return max(lo, sh) / ACCOUNT, abs(lo - sh) / ACCOUNT, len(fam)


def run(which: str, policy) -> dict:
    r4, current_nkd, prices, extra, stress, calm_nkd_df = audit.load_all(which)
    calm_a = rep.load_calm_a_atr15(which, extra["meta"])
    if not policy.include_calm_nkd_switch:
        calm_nkd_df = calm_nkd_df.iloc[0:0]
    guard = rep.make_guard()
    breaker = full.CircuitBreaker(account=ACCOUNT)
    open_pos, equity, cur_day = [], ACCOUNT, None
    obs, admit_obs, breaches = [], [], []

    entries = pd.concat([p for p in (r4, stress, current_nkd, calm_nkd_df, calm_a)
                         if not p.empty], ignore_index=True)
    by_time, times = {}, set()
    for _, row in entries.iterrows():
        tr = row.to_dict()
        et, xt = pd.Timestamp(tr["entry_time"]), pd.Timestamp(tr["exit_time"])
        by_time.setdefault(et, []).append(tr)
        times.add(et)
        times.add(xt)

    def record(ts, cause, detail=""):
        g, n, k = fam_state(open_pos)
        obs.append((str(ts), cause, g, n, k))
        cap_g = policy.family_gross if policy.family_gross is not None else 1.0
        cap_n = policy.family_net if policy.family_net is not None else 1.0
        if g > cap_g + 1e-12 or n > cap_n + 1e-12:
            breaches.append(dict(ts=str(ts), cause=cause, detail=detail,
                                 gross=g, net=n, n_family=k))
        return g, n

    for ts in sorted(times):
        day = naive(ts).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                equity += float(tr["pnl_sized"])
            else:
                still.append((pos, tr))
        if len(still) != len(open_pos):
            open_pos = still
            record(ts, "after_exit")
        else:
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
                    equity += calm_nkd.early_nkd_pnl(old, float(tr["entry"]) + rep.OFFSET[which])
                open_pos = survivors
                open_pos.append((proposed, tr))
                record(ts, "admit_calm_nkd")
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
                    open_pos.append((pos, tr))
                    g, n = record(ts, "admit_calm_a")
                    admit_obs.append((g, n))
                continue

            if cluster == "roska4_stress":
                survivors = [(p, t) for p, t in open_pos
                             if not (p.instrument == inst and p.cluster in FAMILY)]
                proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)),
                                    float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(proposed, [p for p, _ in survivors])
                if not ok:
                    continue
                closed = []
                for p, old in [(p, t) for p, t in open_pos
                               if p.instrument == inst and p.cluster in FAMILY]:
                    px = full.price_at_or_after(prices[inst], ts)
                    if px is None:
                        continue
                    equity += (calm_a_base.early_calm_pnl(old, px, 2.0) if p.cluster == "roska4_calm"
                               else full.early_pnl(old, px, full.costs_for_basket(slippage_ticks=2.0)))
                    closed.append(f"{p.cluster}/{p.direction}")
                open_pos = survivors
                open_pos.append((proposed, tr))
                record(ts, "stress_override",
                       f"closed={','.join(closed) if closed else 'none'} inst={inst}")
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
                    open_pos.append((pos, tr))
                    g, n = record(ts, "admit_normal")
                    admit_obs.append((g, n))
                continue

            pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(pos, open_positions)
            if ok:
                open_pos.append((pos, tr))
                record(ts, "admit_other")

    g = pd.Series([o[2] for o in obs])
    n = pd.Series([o[3] for o in obs])
    ag = pd.Series([a[0] for a in admit_obs]) if admit_obs else pd.Series(dtype=float)
    an = pd.Series([a[1] for a in admit_obs]) if admit_obs else pd.Series(dtype=float)
    by_cause = {}
    for b in breaches:
        by_cause[b["cause"]] = by_cause.get(b["cause"], 0) + 1
    return dict(
        policy=policy.name, n_obs=int(len(g)),
        continuous_gross_peak=float(g.max()), continuous_net_peak=float(n.max()),
        continuous_gross_p99=float(g.quantile(0.99)), continuous_net_p99=float(n.quantile(0.99)),
        family_admission_gross_peak=float(ag.max()) if len(ag) else 0.0,
        family_admission_net_peak=float(an.max()) if len(an) else 0.0,
        n_family_admissions=int(len(ag)),
        cap_gross=policy.family_gross, cap_net=policy.family_net,
        n_breaches=len(breaches), breaches_by_cause=by_cause,
        worst_breaches=sorted(breaches, key=lambda b: -max(b["gross"], b["net"]))[:6],
    )


def main() -> int:
    out = {}
    pols = [p for p in rep.POLICIES
            if p.name in ("repaired_mechanics_family_cap_5_44",
                          "repaired_mechanics_independent_caps")]
    for which in ("floor", "vault2025", "vault2026"):
        out[which] = {}
        for p in pols:
            r = run(which, p)
            out[which][p.name] = r
            assert r["n_obs"] > 0, "SC3 failed: empty observation series"
            if p.family_gross is not None:
                assert r["continuous_gross_peak"] >= r["family_admission_gross_peak"] - 1e-12, \
                    "SC1 failed: continuous peak below admission peak"
                assert r["family_admission_gross_peak"] <= p.family_gross + 1e-12, \
                    "SC2 failed: a family entry was admitted above its own gross cap"
                assert r["family_admission_net_peak"] <= p.family_net + 1e-12, \
                    "SC2 failed: a family entry was admitted above its own net cap"
            print("[ok] %-10s %-38s obs=%d contG=%.2f%% contN=%.2f%% admitG=%.2f%% admitN=%.2f%% breaches=%d %s"
                  % (which, p.name, r["n_obs"], 100 * r["continuous_gross_peak"],
                     100 * r["continuous_net_peak"], 100 * r["family_admission_gross_peak"],
                     100 * r["family_admission_net_peak"], r["n_breaches"],
                     r["breaches_by_cause"]), flush=True)
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
