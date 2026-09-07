from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from futures.basket import BASKET, data_filename
from futures.circuit_breaker import CircuitBreaker
from futures.swing_tf import costs_for_basket
from global_index.deploy_sim import metrics
from global_index.net_exposure_multi import ClusterBudget, MultiClusterGuard, Position, entry_priority_key
from scratch.normal_promotion_variant_matrix_20260821 import load_frames, build_meta
from scratch.normal_sleeve_fill_audit import ACCOUNT, R4, _real_risk


OUT = Path("scratch/stress_switch_full_replay_20260822_report.md")
JSON_OUT = Path("scratch/stress_switch_full_replay_20260822.json")
NORMAL_PROMOTION_FILES = {
    "floor": Path("scratch/normal_promotion_trades_floor_20260821.json"),
    "vault2025": Path("scratch/normal_promotion_trades_vault2025_20260821.json"),
    "vault2026": Path("scratch/normal_promotion_trades_vault2026_20260821.json"),
}


@dataclass(frozen=True)
class Scenario:
    name: str
    instruments: tuple[str, ...]
    qty: int
    gap_min: int = 3
    rr: float = 1.5


SCENARIOS = [
    Scenario("mnq_only_g3_q7", ("MNQ",), 7),
    Scenario("r4_basket_g3_q1each", tuple(R4), 1),
    Scenario("r4_basket_g3_q2each", tuple(R4), 2),
]


def arg_from(argv: list[str], flag: str, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def make_rule(s: Scenario) -> base.Rule:
    return base.Rule(
        name=s.name,
        family="cont_short",
        direction="SHORT",
        instruments=s.instruments,
        setup_time="10:30",
        entry_start="10:35",
        entry_end="12:30",
        exit_time="15:55",
        rr=s.rr,
        breadth_min=4,
        gapdown_min=s.gap_min,
        wide_min=0,
        avg_ret_max=None,
        avg_gap_max=-0.001,
    )


def build_rule_with_levels(frames: dict, ctx: dict, costs: dict, rule: base.Rule) -> pd.DataFrame:
    days, feats = base.active_days(frames, ctx, rule)
    clusters = base.cluster_ids(days)
    rows = []
    for day in days:
        feat = feats[day]
        for inst in rule.instruments:
            c = ctx.get((day, inst, rule.setup_time))
            g = frames.get((day, inst))
            if c is None or g is None or not c["below"]:
                continue
            found = c["low_break"]
            if found is None:
                continue
            entry_ts, entry = found
            stop = c["pre_high"] * (1.0 + rule.stop_pad)
            dist = stop - entry
            target = entry - rule.rr * dist
            if dist <= 0 or dist / entry > rule.max_stop_pct:
                continue
            exited = base.exit_trade(g, rule.direction, entry_ts, stop, target, rule.exit_time)
            if exited is None:
                continue
            exit_px, reason, exit_ts = exited
            gross = entry - exit_px
            pnl = gross * BASKET[inst].point_value - costs[inst].round_turn_cost()
            rows.append({
                "trade_id": f"stress_{rule.name}_{inst}_{pd.Timestamp(day).date()}",
                "source": "stress_switch_candidate",
                "variant": rule.name,
                "cluster": "roska4_stress",
                "instrument": inst,
                "direction": rule.direction,
                "day": pd.Timestamp(day).normalize(),
                "entry_time": entry_ts,
                "signal_time": c["signal_time"],
                "known_time": c["known_time"],
                "exit_time": exit_ts,
                "entry": float(entry),
                "stop": float(stop),
                "target": float(target),
                "exit": float(exit_px),
                "pnl1": float(pnl),
                "risk1": float((stop - entry) * BASKET[inst].point_value),
                "exit_reason": reason,
                "event_cluster": clusters[day],
                "below_count": feat["below_count"],
                "gapdown_count": feat["gapdown_count"],
                "wide_count": feat["wide_count"],
                "signal_after_entry": int(c["known_time"] > entry_ts),
                "same_bar_exit": int(exit_ts == entry_ts),
            })
    return pd.DataFrame(rows)


def load_stress(which: str, scenario: Scenario) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    old_setups = base.SETUPS
    base.SETUPS = ("10:30",)
    try:
        dfs, costs, _ = base.load_window(which)
        frames, ctx = base.build_day_cache(dfs)
        raw = build_rule_with_levels(frames, ctx, costs, make_rule(scenario))
    finally:
        base.SETUPS = old_setups
    if raw.empty:
        return raw, dfs
    out = raw.copy()
    out["qty"] = scenario.qty
    out["pnl_sized"] = out["pnl1"].astype(float) * scenario.qty
    out["risk_sized"] = out["risk1"].astype(float) * scenario.qty
    return out, dfs


def load_normal(which: str) -> tuple[pd.DataFrame, dict]:
    raw = json.loads(NORMAL_PROMOTION_FILES[which].read_text(encoding="utf-8"))
    frames = load_frames(raw)
    meta = build_meta(raw, frames)
    rows = []
    for inst in R4:
        m = meta[inst]
        for i, t in enumerate(raw["filtered"].get(inst, [])):
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t["exit_day"]) if t.get("exit_day") else ed
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            rows.append({
                "trade_id": f"normal_filtered_{inst}_{i}",
                "source": "normal_r4_filtered",
                "cluster": "roska4_swing",
                "instrument": inst,
                "direction": t["direction"],
                "day": ed.normalize(),
                "entry_time": pd.Timestamp(t["entry_time"]),
                "exit_time": pd.Timestamp(t["exit_time"]),
                "entry": float(t["entry"]),
                "exit": float(t["exit"]),
                "pnl_sized": float(t["pnl"]),
                "risk_sized": _real_risk(m["atr"], m["mult"], m["pv"], ed, 1),
            })
    return pd.DataFrame(rows), meta


def price_at_or_after(df: pd.DataFrame, ts: pd.Timestamp) -> float | None:
    loc = df.index.searchsorted(ts)
    if loc >= len(df.index):
        return None
    return float(df.iloc[loc]["open"])


def early_pnl(pos: dict, exit_px: float, costs: dict) -> float:
    pv = BASKET[pos["instrument"]].point_value
    gross = (exit_px - pos["entry"]) if pos["direction"] == "LONG" else (pos["entry"] - exit_px)
    return gross * pv - costs[pos["instrument"]].round_turn_cost()


def sparse_metrics(daily: pd.Series) -> dict:
    m = metrics(daily)
    gp = float(daily[daily > 0].sum())
    gl = float(-daily[daily < 0].sum())
    win = float((daily > 0).mean()) if len(daily) else 0.0
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1) if len(daily) else 1.0
    return {
        "net": float(m["pnl"]),
        "pf": float(gp / gl) if gl > 1e-9 else math.inf,
        "sharpe": float(m["sharpe"]),
        "calmar": float(m["calmar"]),
        "maxdd": float(m["maxdd"]),
        "ret_pct": float(m["pnl"] / ACCOUNT),
        "ret_yr": float(m["pnl"] / ACCOUNT / span),
        "win_day": win,
    }


def make_guard(stress_cap: float) -> MultiClusterGuard:
    clusters = {
        "roska4_swing": ClusterBudget("roska4_swing", 0.050, 0.044),
        "roska4_stress": ClusterBudget("roska4_stress", stress_cap, None),
    }
    return MultiClusterGuard(clusters=clusters, account=ACCOUNT)


def replay_intraday(normal: pd.DataFrame, stress: pd.DataFrame, prices: dict[str, pd.DataFrame],
                    stress_cap: float) -> tuple[pd.Series, dict]:
    costs = costs_for_basket(slippage_ticks=2.0)
    guard = make_guard(stress_cap)
    breaker = CircuitBreaker(account=ACCOUNT)
    realized: dict[pd.Timestamp, float] = {}
    open_pos: list[tuple[Position, dict]] = []
    equity = ACCOUNT
    cur_day = None
    stats = {
        "taken": {"roska4_swing": 0, "roska4_stress": 0},
        "rejected": {"roska4_swing": 0, "roska4_stress": 0},
        "halted": 0,
        "closed_for_switch": 0,
        "switch_delta": 0.0,
        "suppressed_normal": 0,
        "suppressed_normal_pnl": 0.0,
        "stress_attempts": int(len(stress)),
        "first_halt_day": None,
    }

    entries = []
    for _, r in normal.iterrows():
        entries.append((pd.Timestamp(r["entry_time"]), "entry", r.to_dict()))
    for _, r in stress.iterrows():
        entries.append((pd.Timestamp(r["entry_time"]), "entry", r.to_dict()))
    exit_times = [(pd.Timestamp(r["exit_time"]), "exit_marker", None) for _, r in pd.concat([normal, stress]).iterrows()]
    timeline = sorted(set((x[0], x[1], id(x[2]) if x[2] is not None else 0) for x in entries + exit_times))
    by_time: dict[pd.Timestamp, list[dict]] = {}
    for ts, _, obj in entries:
        by_time.setdefault(ts, []).append(obj)
    times = sorted({x[0] for x in entries + exit_times})

    def realize(day_ts: pd.Timestamp, pnl: float):
        nonlocal equity
        day = pd.Timestamp(day_ts).tz_localize(None).normalize()
        equity += pnl
        realized[day] = realized.get(day, 0.0) + float(pnl)

    for ts in times:
        day = pd.Timestamp(ts).tz_localize(None).normalize()
        if cur_day is None or day != cur_day:
            breaker.start_day(equity)
            cur_day = day
        still = []
        for pos, tr in open_pos:
            if pd.Timestamp(tr["exit_time"]) <= ts:
                realize(ts, float(tr["pnl_sized"]))
            else:
                still.append((pos, tr))
        open_pos = still
        breaker.update(equity)
        status = breaker.status(equity)
        allow = status.get("allow_new_entries", True)
        if not allow and stats["first_halt_day"] is None:
            stats["first_halt_day"] = str(day.date())
        for tr in sorted(by_time.get(ts, []), key=entry_priority_key):
            if not allow:
                stats["halted"] += 1
                continue
            cluster = tr["cluster"]
            inst = tr["instrument"]
            if cluster == "roska4_swing":
                if any(p.instrument == inst and p.cluster == "roska4_stress" for p, _ in open_pos):
                    stats["suppressed_normal"] += 1
                    stats["suppressed_normal_pnl"] += float(tr["pnl_sized"])
                    continue
                pos = Position(inst, tr["direction"], 1, float(tr["risk_sized"]), cluster)
                ok, _ = guard.admits(pos, [p for p, _ in open_pos])
                if not ok:
                    stats["rejected"][cluster] += 1
                    continue
                stats["taken"][cluster] += 1
                open_pos.append((pos, tr))
                continue

            # Stress switch: close same-symbol swing positions only if Stress is admissible
            # after those closes. This prevents a rejected Stress from unnecessarily
            # damaging the base book.
            survivors = [(p, t) for p, t in open_pos if not (p.instrument == inst and p.cluster == "roska4_swing")]
            proposed = Position(inst, tr["direction"], int(tr.get("qty", 1)), float(tr["risk_sized"]), cluster)
            ok, _ = guard.admits(proposed, [p for p, _ in survivors])
            if not ok:
                stats["rejected"][cluster] += 1
                continue
            closing = [(p, t) for p, t in open_pos if p.instrument == inst and p.cluster == "roska4_swing"]
            for _, old in closing:
                px = price_at_or_after(prices[inst], ts)
                if px is None:
                    continue
                ep = early_pnl(old, px, costs)
                realize(ts, ep)
                stats["closed_for_switch"] += 1
                stats["switch_delta"] += ep - float(old["pnl_sized"])
            open_pos = survivors
            stats["taken"][cluster] += 1
            open_pos.append((proposed, tr))

    return pd.Series(realized).sort_index(), stats


def replay_base(normal: pd.DataFrame) -> tuple[pd.Series, dict]:
    empty_stress = pd.DataFrame(columns=normal.columns)
    return replay_intraday(normal, empty_stress, {}, 0.025)


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def fmt_float(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def run_window(which: str) -> tuple[str, dict]:
    normal, _ = load_normal(which)
    base_daily, base_st = replay_base(normal)
    base_m = sparse_metrics(base_daily)
    rows = []
    raw = {"base": base_m, "base_state": base_st, "scenarios": []}
    for sc in SCENARIOS:
        stress, prices = load_stress(which, sc)
        for cap in (0.025, 0.05, 0.075, 0.10):
            daily, st = replay_intraday(normal, stress, prices, cap)
            m = sparse_metrics(daily)
            stress_taken = st["taken"]["roska4_stress"]
            stress_rej = st["rejected"]["roska4_stress"]
            rows.append({
                "scenario": sc.name,
                "stress_cap": fmt_pct(cap),
                "stress_legs": int(len(stress)),
                "stress_taken": stress_taken,
                "stress_rej": stress_rej,
                "normal_taken": st["taken"]["roska4_swing"],
                "normal_rej": st["rejected"]["roska4_swing"],
                "closed": st["closed_for_switch"],
                "blocked_late_normal": st["suppressed_normal"],
                "net": fmt_money(m["net"]),
                "ret": fmt_pct(m["ret_pct"]),
                "pf": fmt_float(m["pf"]),
                "sharpe": fmt_float(m["sharpe"]),
                "calmar": fmt_float(m["calmar"]),
                "maxdd": fmt_money(m["maxdd"]),
                "dd_delta": fmt_money(m["maxdd"] - base_m["maxdd"]),
                "switch_delta": fmt_money(st["switch_delta"]),
                "removed_normal": fmt_money(st["suppressed_normal_pnl"]),
                "halts": st["halted"],
            })
            raw["scenarios"].append({
                "scenario": sc.name,
                "stress_cap": cap,
                "metrics": m,
                "state": st,
                "stress_legs": int(len(stress)),
            })
    section = [
        f"## {which}",
        "",
        f"Base Normal-R4 filtered replay: trades attempted {len(normal)}, taken {base_st['taken']['roska4_swing']}, "
        f"rejected {base_st['rejected']['roska4_swing']}, net {fmt_money(base_m['net'])}, "
        f"ret {fmt_pct(base_m['ret_pct'])}, PF {fmt_float(base_m['pf'])}, Sharpe {fmt_float(base_m['sharpe'])}, "
        f"Calmar {fmt_float(base_m['calmar'])}, MaxDD {fmt_money(base_m['maxdd'])}.",
        "",
        table(rows, [
            "scenario", "stress_cap", "stress_legs", "stress_taken", "stress_rej",
            "normal_taken", "normal_rej", "closed", "blocked_late_normal",
            "net", "ret", "pf", "sharpe", "calmar", "maxdd", "dd_delta",
            "switch_delta", "removed_normal", "halts",
        ]),
        "",
    ]
    return "\n".join(section), raw


def main() -> int:
    parts = [
        "# Stress Switch Full Cap/Breaker Replay - 2026-08-22",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Base book: `normal_promotion_trades_*_20260821.json`, bucket `filtered`, R4 only (MES/MNQ/MYM/M2K), NKD excluded.",
        "",
        "Switch semantics measured here:",
        "",
        "- if Stress is rejected by cap/breaker, existing Normal is left alone;",
        "- if Stress is admissible, same-symbol Normal is closed at Stress entry open and Stress enters;",
        "- if Normal later tries to enter a symbol while Stress is still open on that symbol, that Normal entry is suppressed;",
        "- replay is intraday for entry/exit/switch order, while cap math uses the existing `MultiClusterGuard` and account breaker.",
        "",
        "Caveat: this is still a scratch harness around captured Normal trades, not a production patch.",
        "",
    ]
    out = {}
    for which in ("floor", "vault2025", "vault2026"):
        section, raw = run_window(which)
        parts.append(section)
        out[which] = raw
    OUT.write_text("\n".join(parts), encoding="utf-8")
    JSON_OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    print(JSON_OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
