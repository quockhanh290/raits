from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.stress_open_search_20260821 as base
from global_index.deploy_sim import metrics


OUT = Path("scratch/stress_mnq_overlap_insurance_20260821_report.md")

NORMAL_FILES = {
    "floor": Path("scratch/normal_sleeve_trades_floor_20260821.json"),
    "vault2025": Path("scratch/normal_sleeve_trades_vault2025_20260821.json"),
    "vault2026": Path("scratch/normal_sleeve_trades_vault2026_20260821.json"),
}
CALM_FILES = {
    "floor": Path("scratch/calm_open_location_drift_delay_sensitivity_is.csv"),
    "vault2025": Path("scratch/calm_open_location_drift_delay_sensitivity_2025.csv"),
    "vault2026": Path("scratch/calm_open_location_drift_delay_sensitivity_2026.csv"),
}
CALM_VARIANT = "openloc_lower_third_long_e1000_x1555"


@dataclass(frozen=True)
class Candidate:
    name: str
    scale: int
    gap_min: int
    rr: float = 1.5


CANDIDATES = [
    Candidate("mnq_strict_10:30_b4_g2_rr15_x1555", 5, 2),
    Candidate("mnq_strict_10:30_b4_g3_rr15_x1555", 7, 3),
]


def make_rules() -> list[base.Rule]:
    base.SETUPS = ("10:30",)
    return [
        base.Rule(
            name=c.name,
            family="cont_short",
            direction="SHORT",
            instruments=("MNQ",),
            setup_time="10:30",
            entry_start="10:35",
            entry_end="12:30",
            exit_time="15:55",
            rr=c.rr,
            breadth_min=4,
            gapdown_min=c.gap_min,
            wide_min=0,
            avg_ret_max=None,
            avg_gap_max=-0.001,
        )
        for c in CANDIDATES
    ]


def load_normal(which: str) -> pd.DataFrame:
    path = NORMAL_FILES[which]
    if not path.exists():
        return pd.DataFrame()
    data = json.loads(path.read_text())
    bucket = data.get("corrected") or data.get("booked") or {}
    rows = []
    for inst, trades in bucket.items():
        for t in trades:
            rows.append({
                "source": "normal",
                "instrument": inst,
                "direction": t.get("direction", ""),
                "day": pd.Timestamp(t["day"]).normalize(),
                "entry_time": pd.Timestamp(t["entry_time"]),
                "exit_time": pd.Timestamp(t["exit_time"]),
                "pnl": float(t["pnl"]),
            })
    return pd.DataFrame(rows)


def load_calm(which: str) -> pd.DataFrame:
    path = CALM_FILES[which]
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df = df[df["variant"] == CALM_VARIANT].copy()
    if df.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "source": "calm",
        "instrument": df["inst"],
        "direction": df["direction"],
        "day": pd.to_datetime(df["day"]).dt.normalize(),
        "entry_time": df["entry_time"].map(pd.Timestamp),
        "exit_time": df["exit_time"].map(pd.Timestamp),
        "pnl": df["pnl"].astype(float),
    })


def load_stress(which: str, rules: list[base.Rule]) -> tuple[dict[str, pd.DataFrame], pd.DatetimeIndex]:
    dfs, costs, sessions = base.load_window(which)
    frames, ctx = base.build_day_cache(dfs)
    return {r.name: base.build_rule(frames, ctx, costs, r) for r in rules}, sessions


def dense_daily(trades: pd.DataFrame, sessions: pd.DatetimeIndex, scale: float = 1.0) -> pd.Series:
    s = pd.Series(0.0, index=sessions)
    if trades.empty:
        return s
    d = trades.groupby("day")["pnl"].sum() * scale
    d.index = pd.DatetimeIndex([pd.Timestamp(x).normalize() for x in d.index])
    return s.add(d, fill_value=0.0)


def summarize_daily(daily: pd.Series) -> dict:
    m = metrics(daily)
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    gp = float(daily[daily > 0].sum())
    gl = float(-daily[daily < 0].sum())
    return {
        "net": float(daily.sum()),
        "pf": gp / gl if gl else float("inf"),
        "sharpe": float(m.get("sharpe", 0.0)),
        "calmar": float(m.get("calmar", 0.0)),
        "maxdd": dd,
    }


def overlaps(stress: pd.DataFrame, other: pd.DataFrame) -> dict:
    if stress.empty or other.empty:
        return {"legs": 0, "days": 0, "opposite_legs": 0, "opposite_days": 0, "opposite_other_pnl": 0.0, "same_symbol_legs": 0}
    rows = []
    other_same = other[other["instrument"] == "MNQ"]
    for _, s in stress.iterrows():
        hit = other_same[
            (other_same["entry_time"] < s["exit_time"])
            & (other_same["exit_time"] > s["entry_time"])
        ]
        for _, o in hit.iterrows():
            rows.append({
                "day": s["day"],
                "other_source": o["source"],
                "other_dir": o["direction"],
                "other_pnl": o["pnl"],
                "opposite": o["direction"] != s["direction"],
            })
    if not rows:
        return {"legs": 0, "days": 0, "opposite_legs": 0, "opposite_days": 0, "opposite_other_pnl": 0.0, "same_symbol_legs": 0}
    df = pd.DataFrame(rows)
    opp = df[df["opposite"]]
    return {
        "legs": int(len(df)),
        "days": int(df["day"].nunique()),
        "opposite_legs": int(len(opp)),
        "opposite_days": int(opp["day"].nunique()) if not opp.empty else 0,
        "opposite_other_pnl": float(opp["other_pnl"].sum()) if not opp.empty else 0.0,
        "same_symbol_legs": int(len(df)),
    }


def fmt_money(x: float) -> str:
    return f"${x:,.0f}"


def fmt_num(x: float) -> str:
    return "inf" if x == float("inf") else f"{x:.2f}"


def table(rows: list[dict], cols: list[str]) -> str:
    out = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return "\n".join(out)


def insurance_rows(base_daily: pd.Series, stress_daily: pd.Series) -> list[dict]:
    rows = []
    for n in (5, 10, 20):
        worst = base_daily.nsmallest(min(n, len(base_daily)))
        sp = stress_daily.reindex(worst.index, fill_value=0.0)
        rows.append({
            "bucket": f"worst_{n}_base_days",
            "base_pnl": fmt_money(float(worst.sum())),
            "stress_pnl": fmt_money(float(sp.sum())),
            "stress_positive_days": int((sp > 0).sum()),
            "stress_trade_days": int((sp != 0).sum()),
        })
    neg = base_daily[base_daily < 0]
    sp = stress_daily.reindex(neg.index, fill_value=0.0)
    rows.append({
        "bucket": "all_negative_base_days",
        "base_pnl": fmt_money(float(neg.sum())),
        "stress_pnl": fmt_money(float(sp.sum())),
        "stress_positive_days": int((sp > 0).sum()),
        "stress_trade_days": int((sp != 0).sum()),
    })
    return rows


def run_window(which: str, rules: list[base.Rule]) -> str:
    stress_by_name, sessions = load_stress(which, rules)
    normal = load_normal(which)
    calm = load_calm(which)
    base_book = pd.concat([x for x in (normal, calm) if not x.empty], ignore_index=True) if (not normal.empty or not calm.empty) else pd.DataFrame()
    base_daily = dense_daily(base_book, sessions, 1.0)
    base_sum = summarize_daily(base_daily)
    lines = [f"## {which}", "", f"Base Normal+Calm: net {fmt_money(base_sum['net'])}, PF {fmt_num(base_sum['pf'])}, MaxDD {fmt_money(base_sum['maxdd'])}", ""]
    summary_rows = []
    for cand in CANDIDATES:
        stress = stress_by_name[cand.name].copy()
        stress["pnl"] = stress["pnl"].astype(float)
        stress_daily = dense_daily(stress, sessions, cand.scale)
        combined_daily = base_daily + stress_daily
        ss = summarize_daily(stress_daily)
        cs = summarize_daily(combined_daily)
        ov_normal = overlaps(stress, normal)
        ov_calm = overlaps(stress, calm)
        summary_rows.append({
            "candidate": cand.name,
            "scale": f"{cand.scale}x",
            "stress_net": fmt_money(ss["net"]),
            "stress_maxdd": fmt_money(ss["maxdd"]),
            "combined_net": fmt_money(cs["net"]),
            "combined_maxdd": fmt_money(cs["maxdd"]),
            "maxdd_delta": fmt_money(cs["maxdd"] - base_sum["maxdd"]),
            "normal_opp_days": ov_normal["opposite_days"],
            "normal_opp_legs": ov_normal["opposite_legs"],
            "calm_opp_days": ov_calm["opposite_days"],
            "calm_opp_legs": ov_calm["opposite_legs"],
        })
        lines += [
            f"### {cand.name} @ {cand.scale}x",
            "",
            table([summary_rows[-1]], ["candidate", "scale", "stress_net", "stress_maxdd", "combined_net", "combined_maxdd", "maxdd_delta", "normal_opp_days", "normal_opp_legs", "calm_opp_days", "calm_opp_legs"]),
            "",
            "Insurance buckets:",
            "",
            table(insurance_rows(base_daily, stress_daily), ["bucket", "base_pnl", "stress_pnl", "stress_positive_days", "stress_trade_days"]),
            "",
        ]
    lines = [f"## {which}", "", "Summary:", "", table(summary_rows, ["candidate", "scale", "stress_net", "stress_maxdd", "combined_net", "combined_maxdd", "maxdd_delta", "normal_opp_days", "normal_opp_legs", "calm_opp_days", "calm_opp_legs"]), ""] + lines[3:]
    return "\n".join(lines)


def main() -> int:
    rules = make_rules()
    parts = [
        "# Stress MNQ Strict Overlap / Insurance Probe - 2026-08-21",
        "",
        "Scratch-only. No production code modified.",
        "",
        "Purpose: test whether the MNQ-only strict Stress candidates are useful at intended synthetic scale after accounting for same-symbol overlap and payoff on bad Normal+Calm days.",
        "",
        "Candidates:",
        "",
        "- `mnq_strict_10:30_b4_g2_rr15_x1555` at 5x.",
        "- `mnq_strict_10:30_b4_g3_rr15_x1555` at 7x.",
        "",
        "Notes:",
        "",
        "- Stress uses no daily regime label.",
        "- 2026 remains sanity-only under the current Stress gate.",
        "- Overlap is same-symbol MNQ interval overlap; opposite means existing sleeve is LONG while Stress is SHORT.",
        "",
    ]
    for which in ("floor", "vault2025", "vault2026"):
        parts.append(run_window(which, rules))
        parts.append("")
    parts += [
        "## Verdict",
        "",
        "- A Stress candidate needs to improve bad-day payoff without creating unacceptable same-symbol netting conflicts.",
        "- If scaled MNQ-only improves tail days and has low overlap, it can remain a hedge candidate even with thin 1x PnL.",
        "- If overlap is frequent or combined MaxDD worsens, sizing does not rescue the sleeve.",
    ]
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
