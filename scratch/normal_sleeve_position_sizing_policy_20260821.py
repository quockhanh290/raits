"""
Normal sleeve position/cap policy probe - scratch/research only.

Purpose:
  - Find cap/admission settings that keep the corrected Normal sleeve under the
    account 15% breaker without depending on the permanent-latch artifact.
  - Use floor 2018-2024 for selection/read. 2025/2026 are sanity only.

No production code is changed. The script loads the corrected trade tables saved
by normal_sleeve_halt_probe_20260821.py and replays alternate cluster caps.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(Path.cwd()))

from scratch.normal_sleeve_risk_policy_probe_20260821 import (
    ACCOUNT,
    R4,
    build_book,
    build_meta,
    load_trade_json,
    metrics,
)


def guard_for(swing_gross: float, swing_net: float, nkd_cap: float):
    from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard

    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", swing_gross, swing_net),
        "roska4_stress": ClusterBudget("roska4_stress", 0.025, None),
        "global_nkd": ClusterBudget("global_nkd", nkd_cap, nkd_cap),
    }
    return MultiClusterGuard(clusters=clusters, account=ACCOUNT)


def replay(book: list[dict], *, swing_gross: float, swing_net: float, nkd_cap: float,
           breaker: float | None, release: str) -> dict:
    from global_index.net_exposure_multi import Position, entry_priority_key

    guard = guard_for(swing_gross, swing_net, nkd_cap)
    days = sorted({t["entry"] for t in book} | {t["exit"] for t in book})
    by_entry = {}
    for t in book:
        by_entry.setdefault(t["entry"], []).append(t)

    open_pos = []
    realized = {}
    equity = ACCOUNT
    peak = ACCOUNT
    taken = {c: 0 for c in guard.clusters}
    rejected = {c: 0 for c in guard.clusters}
    rejected_by_cluster = {c: 0 for c in guard.clusters}
    halted_days = 0
    blocked_trades = 0
    lost_trade_pnl = 0.0
    first_halt = None
    peak_rel_dd = 0.0
    peak_rel_day = None
    peak_at_worst = ACCOUNT

    for day in days:
        still = []
        for pos, t in open_pos:
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
            else:
                still.append((pos, t))
        open_pos = still

        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        if dd > peak_rel_dd:
            peak_rel_dd = float(dd)
            peak_rel_day = str(pd.Timestamp(day).date())
            peak_at_worst = float(peak)

        allow = True
        if breaker is not None and dd >= breaker:
            allow = False
            if first_halt is None:
                first_halt = dict(day=str(pd.Timestamp(day).date()), peak=float(peak),
                                  equity=float(equity), dd=float(dd))
            if release == "flat_reset" and not open_pos:
                peak = equity
                allow = True

        if not allow:
            halted_days += 1

        for t in sorted(by_entry.get(day, []), key=entry_priority_key):
            if not allow:
                blocked_trades += 1
                lost_trade_pnl += t["pnl_sized"]
                continue
            pos = Position(t["inst"], t["direction"], 1, t["risk_sized"], t["cluster"])
            ok, _ = guard.admits(pos, [p for p, _ in open_pos])
            if not ok:
                rejected[t["cluster"]] += 1
                rejected_by_cluster[t["cluster"]] += 1
                continue
            taken[t["cluster"]] += 1
            if t["exit"] == day:
                equity += t["pnl_sized"]
                realized[day] = realized.get(day, 0.0) + t["pnl_sized"]
                peak = max(peak, equity)
            else:
                open_pos.append((pos, t))

    daily = pd.Series(realized).sort_index()
    m = metrics(daily)
    yrs = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 1.0
    return dict(
        net=m["pnl"],
        pf=m["pf"],
        sharpe=m["sharpe"],
        calmar=m["calmar"],
        maxdd=m["maxdd"],
        maxdd_pct=m["maxdd"] / ACCOUNT,
        ret_yr=m["pnl"] / ACCOUNT / yrs,
        potential_trades=len(book),
        taken=sum(taken.values()),
        rejected=sum(rejected.values()),
        rejected_swing=rejected_by_cluster.get("roska4_swing", 0),
        rejected_nkd=rejected_by_cluster.get("global_nkd", 0),
        halted_days=halted_days,
        blocked_trades=blocked_trades,
        lost_trade_pnl=lost_trade_pnl,
        peak_rel_dd=peak_rel_dd,
        peak_rel_day=peak_rel_day,
        safety_margin_15=0.15 - peak_rel_dd,
        first_halt=first_halt,
        yearly={int(y): float(g.sum()) for y, g in daily.groupby(daily.index.year)} if len(daily) else {},
        swing_gross=swing_gross,
        swing_net=swing_net,
        nkd_cap=nkd_cap,
        breaker="off" if breaker is None else f"{breaker:.1%}",
        release=release,
    )


def books_for(which: str):
    raw = load_trade_json(which)
    meta = build_meta(raw)
    nkd = raw["nkd_instrument"]
    r4 = {k: raw["corrected"][k] for k in R4}
    both = dict(r4)
    both[nkd] = raw["corrected"][nkd]
    return {
        "R4 only": build_book(r4, meta),
        "R4 + NKD corrected": build_book(both, meta),
    }


def scenario_grid():
    strict_caps = [0.015, 0.020, 0.025, 0.030, 0.035, 0.040, 0.045, 0.050]
    nkd_caps = [0.020, 0.030, 0.040, 0.050, 0.060]
    scenarios = []
    # Current policy anchor: 5.0% gross / 4.4% net, NKD 6%.
    scenarios.append(("current_5g_44n_nkd6", 0.050, 0.044, 0.060))
    for c in strict_caps:
        scenarios.append((f"strict_{int(c * 1000):03d}", c, c, 0.060))
    for nc in nkd_caps:
        scenarios.append((f"strict_025_nkd{int(nc * 1000):03d}", 0.025, 0.025, nc))
        scenarios.append((f"strict_030_nkd{int(nc * 1000):03d}", 0.030, 0.030, nc))
    # Deduplicate while preserving order.
    out = []
    seen = set()
    for s in scenarios:
        key = s[1:]
        if key not in seen:
            out.append(s)
            seen.add(key)
    return out


def is_candidate(r: dict) -> bool:
    return (
        r["breaker"] == "15.0%"
        and r["release"] == "latch"
        and r["blocked_trades"] == 0
        and r["halted_days"] == 0
        and r["safety_margin_15"] >= 0.01
        and r["net"] > 0
        and r["pf"] >= 1.20
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scratch/normal_sleeve_position_sizing_policy_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_sleeve_position_sizing_policy_20260821.json")
    args = ap.parse_args()

    report = []
    results = {}

    def emit(s=""):
        print(s, flush=True)
        report.append(s)

    emit("=" * 118)
    emit("NORMAL SLEEVE - POSITION/CAP POLICY PROBE (scratch only)")
    emit("=" * 118)
    emit("Selection/read uses floor only. 2025/2026 are sanity only. Corrected trade tables loaded from scratch.")
    emit("Candidate flag: 15% latch, no halted/blocked trades, >=1.0pp safety to 15%, net>0, PF>=1.20.")
    emit("")

    all_books = {w: books_for(w) for w in ("floor", "vault2025", "vault2026")}
    grid = scenario_grid()

    for which in ("floor", "vault2025", "vault2026"):
        emit("#" * 118)
        emit("WINDOW: " + which)
        emit("#" * 118)
        results[which] = []
        rows = []
        for variant, book in all_books[which].items():
            for name, sg, sn, nc in grid:
                if variant == "R4 only" and "nkd" in name and name != "current_5g_44n_nkd6":
                    continue
                for breaker, release in ((0.15, "latch"), (None, "off"), (0.15, "flat_reset")):
                    r = replay(book, swing_gross=sg, swing_net=sn, nkd_cap=nc,
                               breaker=breaker, release=release)
                    r.update(variant=variant, scenario=name, candidate=is_candidate(r))
                    rows.append(r)
        results[which] = rows

        key_rows = [r for r in rows if r["release"] == "latch" and r["breaker"] == "15.0%"]
        key_rows.sort(key=lambda r: (r["candidate"], r["calmar"], r["net"]), reverse=True)
        emit("  15% LATCH GRID - top rows by candidate/calmar/net")
        emit("  {:<20} {:<22} {:>5} {:>5} {:>5} {:>10} {:>5} {:>7} {:>7} {:>8} {:>8} {:>6} {:>6} {:>7} {:>5}".format(
            "variant", "scenario", "sg", "sn", "nkdc", "net$", "PF", "Sharpe", "Calmar",
            "MaxDD%", "ret/yr", "taken", "rej", "block", "cand"))
        for r in key_rows[:36]:
            emit("  {variant:<20} {scenario:<22} {swing_gross:>5.1%} {swing_net:>5.1%} {nkd_cap:>5.1%} {net:>10,.0f} {pf:>5.2f} {sharpe:>7.2f} {calmar:>7.2f} {maxdd_pct:>8.1%} {ret_yr:>8.1%} {taken:>6} {rejected:>6} {blocked_trades:>7} {candidate!s:>5}".format(**r))
        emit("")

        cands = [r for r in key_rows if r["candidate"]]
        emit("  DEPLOY-CLEAN CANDIDATES UNDER THIS MECHANICAL GATE: {}".format(len(cands)))
        for r in cands[:12]:
            emit("    {variant:<20} {scenario:<22} net ${net:>8,.0f} PF {pf:.2f} Calmar {calmar:.2f} MaxDD {maxdd_pct:.1%} safety {safety_margin_15:.1%} taken {taken} rejected {rejected}".format(**r))
        emit("")

        if which == "floor":
            years = sorted({y for r in key_rows[:12] for y in r["yearly"]})
            emit("  YEARLY NET$ - top floor rows")
            emit("  {:<20} {:<22} {}".format("variant", "scenario", " ".join(f"{y:>9}" for y in years)))
            for r in key_rows[:12]:
                emit("  {:<20} {:<22} {}".format(
                    r["variant"], r["scenario"],
                    " ".join("{:>9,.0f}".format(r["yearly"].get(y, 0.0)) for y in years)))
            emit("")

    # Cross-window sanity for floor-selected candidates only.
    floor_cands = [
        r for r in results["floor"]
        if r["candidate"] and r["breaker"] == "15.0%" and r["release"] == "latch"
    ]
    floor_cands.sort(key=lambda r: (r["calmar"], r["net"]), reverse=True)
    selected = []
    seen = set()
    for r in floor_cands:
        key = (r["variant"], r["scenario"])
        if key not in seen:
            selected.append(key)
            seen.add(key)
        if len(selected) >= 8:
            break

    emit("#" * 118)
    emit("CROSS-WINDOW SANITY FOR FLOOR-SELECTED CANDIDATES")
    emit("#" * 118)
    emit("  {:<20} {:<22} {:<10} {:>10} {:>5} {:>7} {:>7} {:>8} {:>8} {:>7} {:>7}".format(
        "variant", "scenario", "window", "net$", "PF", "Sharpe", "Calmar",
        "MaxDD%", "ret/yr", "safety", "block"))
    for variant, scenario in selected:
        for which in ("floor", "vault2025", "vault2026"):
            rows = [
                r for r in results[which]
                if r["variant"] == variant and r["scenario"] == scenario
                and r["breaker"] == "15.0%" and r["release"] == "latch"
            ]
            if not rows:
                continue
            r = rows[0]
            emit("  {variant:<20} {scenario:<22} {window:<10} {net:>10,.0f} {pf:>5.2f} {sharpe:>7.2f} {calmar:>7.2f} {maxdd_pct:>8.1%} {ret_yr:>8.1%} {safety_margin_15:>7.1%} {blocked_trades:>7}".format(
                window=which, **r))
    emit("")

    verdict = "keep_digging"
    if selected:
        verdict = "candidate_exists_mechanical_floor_only"
    emit("VERDICT: " + verdict)
    emit("  Do not promote from this pass alone. The pass identifies mechanical cap policies that avoid")
    emit("  the 15% latch on floor; final promotion still requires choosing policy ex-ante, then re-running")
    emit("  production-equivalent anchors after the NKD fill law is fixed in the engine.")

    Path(args.out).write_text("\n".join(report) + "\n", encoding="utf-8")
    Path(args.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"\nwrote {args.out} and {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
