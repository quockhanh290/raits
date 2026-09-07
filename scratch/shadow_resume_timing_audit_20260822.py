"""Measured scheduler slot timing + shadow-resume outcome audit. SCRATCH-ONLY.

READ-ONLY. Parses scheduler_*.log and live_day_*.log that production already wrote.
Starts nothing, connects to nothing, writes only under scratch/.

What it answers, from measurement rather than assumption:
  - how long a slot actually takes, per slot family and per slot-of-day
  - how often the slot mutex actually fired, and on which slots
  - how often APScheduler misfired, and by how much
  - whether the shadow-resume comparison ever diverged
  - how much clearance the 15:55 slot really leaves before the 16:20 repair sweep
  - and only then: a static simulation of adding Track 1's windows, driven by the
    measured p90/p95/max rather than the "~5.5 min" figure in the source comment

  python scratch/shadow_resume_timing_audit_20260822.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path.cwd()
OUT_JSON = Path("scratch/shadow_resume_timing_audit_20260822.json")

TS = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
RE_RUNNING = re.compile(TS + r'.*Running job "(?P<name>[^"]+?)\s*\(trigger.*?scheduled at (?P<sched>[^)]+)\)')
RE_DONE = re.compile(TS + r'.*Job "(?P<name>[^"]+?)\s*\(trigger.*?executed successfully')
RE_MISSED = re.compile(TS + r'.*Run time of job "(?P<name>[^"]+?)\s*\(trigger.*?was missed by (?P<by>[0-9:.]+)')
RE_MUTEX = re.compile(TS + r'.*\[(?P<slot>[A-Z0-9_]+)\] SKIPPED — previous run_live_day still in flight')
RE_SKIP = re.compile(TS + r'.*\[(?P<slot>[A-Z0-9_]+)\] SKIPPED — (?P<why>[^.]{0,60})')
RE_STALL = re.compile(TS + r'.*\[HEARTBEAT\] STALLED (?P<secs>[0-9]+)s')

# A child is killed by the parent at this ceiling (run_scheduler.py:231
# _SLOT_TIMEOUT_SECS = 20*60), so a Running->executed gap longer than it CANNOT be one
# child run. Derived from the source rather than picked: the previous 3600 s cut was an
# arbitrary round number and it let a 2,174 s row through.
SLOT_TIMEOUT_SECS = 20 * 60

# job-name → (family, ET hh:mm) e.g. "Continuous run 14:10 ET"
RE_FAMILY = re.compile(r'^(?P<fam>.*?)\s*(?P<hh>\d{2}):(?P<mm>\d{2}) ET$')


def parse_scheduler_logs():
    runs, misses, mutex, skips, stalls = [], [], [], [], []
    open_by_name: dict[str, list] = defaultdict(list)
    files = sorted(ROOT.glob("scheduler_*.log"))
    for f in files:
        if f.stat().st_size == 0:
            continue
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = RE_RUNNING.search(line)
            if m:
                open_by_name[m.group("name")].append(
                    (pd.Timestamp(m.group(1)), m.group("sched"), f.name))
                continue
            m = RE_DONE.search(line)
            if m:
                stack = open_by_name.get(m.group("name"))
                if stack:
                    t0, sched, src = stack.pop(0)
                    t1 = pd.Timestamp(m.group(1))
                    runs.append(dict(log=src, job=m.group("name"), sched_et=sched,
                                     start=t0, end=t1,
                                     runtime_s=float((t1 - t0).total_seconds())))
                continue
            m = RE_MISSED.search(line)
            if m:
                misses.append(dict(log=f.name, ts=pd.Timestamp(m.group(1)),
                                   job=m.group("name"),
                                   missed_by_s=float(pd.Timedelta(m.group("by")).total_seconds())))
                continue
            m = RE_MUTEX.search(line)
            if m:
                mutex.append(dict(log=f.name, ts=pd.Timestamp(m.group(1)), slot=m.group("slot")))
                continue
            m = RE_STALL.search(line)
            if m:
                stalls.append(dict(log=f.name, ts=pd.Timestamp(m.group(1)),
                                   stalled_s=int(m.group("secs"))))
                continue
            m = RE_SKIP.search(line)
            if m:
                skips.append(dict(log=f.name, ts=pd.Timestamp(m.group(1)),
                                  slot=m.group("slot"), why=m.group("why").strip()))
    unclosed = {k: len(v) for k, v in open_by_name.items() if v}
    return (pd.DataFrame(runs), pd.DataFrame(misses), pd.DataFrame(mutex),
            pd.DataFrame(skips), [f.name for f in files], unclosed,
            pd.DataFrame(stalls))


def family_of(job: str):
    m = RE_FAMILY.match(job.strip())
    if not m:
        return job.strip(), None
    return m.group("fam").strip(), f"{m.group('hh')}:{m.group('mm')}"


def dist(v: np.ndarray) -> dict:
    if len(v) == 0:
        return dict(n=0)
    return dict(n=int(len(v)), median=float(np.median(v)),
                p75=float(np.percentile(v, 75)), p90=float(np.percentile(v, 90)),
                p95=float(np.percentile(v, 95)), max=float(np.max(v)),
                over_300s=int((v > 300).sum()), pct_over_300s=float((v > 300).mean()))


# ---------------------------------------------------------------------------
def shadow_outcomes():
    """Verdicts the shadow-resume comparison wrote into the day logs."""
    out = {"per_day": {}, "totals": defaultdict(int)}
    for f in sorted(ROOT.glob("live_day_*.log")):
        txt = f.read_text(encoding="utf-8", errors="replace")
        row = {
            "match": txt.count("DOI CHIEU KHOP"),
            "diverged": txt.count("DOI CHIEU LECH"),
            "no_checkpoint": txt.count("khong co checkpoint"),
            "checkpoint_not_advanced": txt.count("KHONG ghi tien checkpoint"),
        }
        if any(row.values()):
            out["per_day"][f.name] = row
            for k, v in row.items():
                out["totals"][k] += v
    out["totals"] = dict(out["totals"])
    return out


# ---------------------------------------------------------------------------
def clearance_1555_vs_1620(runs: pd.DataFrame):
    """Does the 15:55 slot finish before the 16:20 repair sweep starts?
    Both are machine-local timestamps from the same clock, so the gap is direct."""
    rows = []
    if runs.empty:
        return rows
    runs = runs.copy()
    runs["day"] = runs["start"].dt.normalize()
    for day, g in runs.groupby("day"):
        last = g[g["job"].str.contains("15:55 ET", regex=False)]
        rep = g[g["job"].str.contains("16:20 ET", regex=False)]
        if last.empty or rep.empty:
            continue
        end_1555 = last["end"].max()
        start_1620 = rep["start"].min()
        rows.append(dict(day=str(day.date()),
                         end_1555=str(end_1555), start_1620=str(start_1620),
                         clearance_s=float((start_1620 - end_1555).total_seconds()),
                         runtime_1555_s=float(last["runtime_s"].max())))
    return rows


# ---------------------------------------------------------------------------
def simulate(slot_times_min: list[int], runtime_sample: np.ndarray, seed_offset: int,
             label: str) -> dict:
    """Deterministic replay of the real mutex rule: a slot whose scheduled instant
    falls while a previous run is still going is SKIPPED, not queued
    (run_scheduler.py:235 _run_guarded → _live_day_body_inner never runs).

    No randomness: the measured runtimes are cycled in order, offset per scenario,
    so the same sample drives every scenario and the comparison is like-for-like.
    """
    if len(runtime_sample) == 0:
        return dict(label=label, n_slots=len(slot_times_min), error="no runtime sample")
    busy_until = -1.0
    ran, skipped, gaps = [], [], []
    last_ok = None
    k = seed_offset
    for t in slot_times_min:
        t_s = t * 60.0
        if t_s < busy_until:
            skipped.append(t)
            continue
        rt = float(runtime_sample[k % len(runtime_sample)])
        k += 1
        busy_until = t_s + rt
        ran.append(t)
        if last_ok is not None:
            gaps.append(t - last_ok)
        last_ok = t
    return dict(label=label, n_slots=len(slot_times_min), ran=len(ran),
                skipped=len(skipped), skip_pct=float(len(skipped) / len(slot_times_min)),
                max_gap_min=int(max(gaps)) if gaps else 0,
                median_gap_min=float(np.median(gaps)) if gaps else 0.0,
                skipped_slots=skipped[:40])


def main() -> int:
    runs, misses, mutex, skips, files, unclosed, stalls = parse_scheduler_logs()
    print(f"[parse] {len(files)} scheduler logs | {len(runs)} completed runs | "
          f"{len(misses)} misfires | {len(mutex)} mutex skips | {len(skips)} skips total",
          flush=True)

    # SC1: the parser must have found something, or nothing below means anything
    assert len(runs) > 0, "SC1 failed: no Running/executed pairs parsed"
    assert len(files) > 0, "SC1 failed: no scheduler logs found"

    fam = runs["job"].apply(family_of)
    runs["family"] = [a for a, _ in fam]
    runs["slot_et"] = [b for _, b in fam]
    runs["day"] = runs["start"].dt.normalize()

    out = {
        "inputs": {"scheduler_logs": files,
                   "n_completed_runs": int(len(runs)),
                   "days_covered": sorted({str(d.date()) for d in runs["day"]}),
                   "unclosed_running_lines": unclosed},
        "runtime_overall": dist(runs["runtime_s"].to_numpy()),
        "runtime_by_family": {f: dist(g["runtime_s"].to_numpy())
                              for f, g in runs.groupby("family")},
    }

    # ---- rows that are longer than the parent's own kill ceiling ------------
    # run_scheduler.py:231 sets _SLOT_TIMEOUT_SECS = 20*60 and _run kills the child at
    # it, so a Running->executed gap beyond that cannot be one child run. Each such row
    # is then classified by MECHANISM rather than lumped under one label:
    #   machine_sleep     — a [HEARTBEAT] STALLED line covers the gap. The wall clock
    #                       includes an OS suspend; the work itself may have been short.
    #   pairing_artifact  — no stall covers it: a "Running" whose "executed" was lost
    #                       across a scheduler restart, matched to a much later one.
    over = runs[runs["runtime_s"] > SLOT_TIMEOUT_SECS].copy()
    excluded = []
    for _, r in over.iterrows():
        covered = None
        if not stalls.empty:
            hit = stalls[(stalls["ts"] >= r["start"]) & (stalls["ts"] <= r["end"] + pd.Timedelta(minutes=2))]
            if len(hit):
                covered = int(hit["stalled_s"].max())
        # "a stall happened somewhere inside the gap" is not enough: a 24-hour gap
        # contains a stall almost by construction. The stall has to EXPLAIN the gap,
        # so require it to account for at least half of it.
        explains = covered is not None and covered >= 0.5 * r["runtime_s"]
        excluded.append(dict(job=r["job"], start=str(r["start"]), end=str(r["end"]),
                             runtime_s=r["runtime_s"], log=r["log"],
                             mechanism="machine_sleep" if explains else "pairing_artifact",
                             stalled_s=covered,
                             stall_explains_pct=(round(100 * covered / r["runtime_s"], 1)
                                                 if covered else None)))
    out["excluded_not_runtimes"] = dict(
        rule=f"runtime > _SLOT_TIMEOUT_SECS ({SLOT_TIMEOUT_SECS}s), the ceiling at which "
             f"run_scheduler._run kills the child",
        n=len(excluded), rows=excluded)
    runs = runs[runs["runtime_s"] <= SLOT_TIMEOUT_SECS].copy()
    out["runtime_by_family"] = {f: dist(g["runtime_s"].to_numpy())
                                for f, g in runs.groupby("family")}

    live_all = runs[runs["family"].isin(["Daily run", "Continuous run"])].copy()
    # A slot whose body was skipped (pre-flight failed / mutex held) still logs a
    # Running/executed pair, with ~0s between them. Those are not runtimes; leaving
    # them in drags the median toward zero. A real run connects to IB Gateway, which
    # the runner's own docstring measures at ~12s, so anything under 5s did no work.
    live = live_all[live_all["runtime_s"] >= 5.0]
    out["noop_runs_excluded"] = dict(
        n=int(len(live_all) - len(live)),
        by_day={str(d.date()): int(c) for d, c in
                live_all[live_all["runtime_s"] < 5.0]["day"].value_counts().items()},
        note="Running/executed pairs whose body returned immediately (pre-flight skip "
             "or mutex skip); excluded from every runtime figure below")
    out["runtime_live_day_slots"] = dist(live["runtime_s"].to_numpy())
    out["runtime_by_slot_et"] = {
        s: dist(g["runtime_s"].to_numpy())
        for s, g in live.groupby("slot_et")}
    out["runtime_by_day_live"] = {
        str(d.date()): dist(g["runtime_s"].to_numpy())
        for d, g in live.groupby("day")}

    out["mutex_skips"] = {
        "total": int(len(mutex)),
        "by_slot": (mutex["slot"].value_counts().to_dict() if not mutex.empty else {}),
        "by_day": ({str(pd.Timestamp(t).date()): int(c) for t, c in
                    mutex["ts"].dt.normalize().value_counts().items()}
                   if not mutex.empty else {}),
    }
    out["all_skip_reasons"] = (skips["why"].value_counts().to_dict()
                               if not skips.empty else {})
    # ---- misfires, classified ------------------------------------------------
    # An earlier version of this report said the misfires were "all on NKD night
    # slots". They are not: 9 of them are on other jobs, and one of those is a
    # TRADING job (the 09:31 max-hold close), which is not a maintenance concern.
    mf = misses.copy()
    if not mf.empty:
        mf["job_short"] = mf["job"].str.split("(").str[0].str.strip()
        mf["is_nkd_night"] = mf["job_short"].str.contains("NKD night", na=False)
        _TRADING = ("MAX_HOLD exit", "Daily run", "Continuous run", "NKD night run")
        mf["is_trading_job"] = mf["job_short"].str.startswith(_TRADING)
        # does a machine-sleep stall cover this misfire?
        cov = []
        for _, r in mf.iterrows():
            if stalls.empty:
                cov.append(None); continue
            hit = stalls[(stalls["ts"] >= r["ts"] - pd.Timedelta(minutes=5)) &
                         (stalls["ts"] <= r["ts"] + pd.Timedelta(minutes=5))]
            cov.append(int(hit["stalled_s"].max()) if len(hit) else None)
        mf["stall_covered_s"] = cov
    out["misfires"] = {
        "total": int(len(mf)),
        "worst_s": float(mf["missed_by_s"].max()) if not mf.empty else 0.0,
        "median_s": float(mf["missed_by_s"].median()) if not mf.empty else 0.0,
        "on_nkd_night": int(mf["is_nkd_night"].sum()) if not mf.empty else 0,
        "not_nkd_night": int((~mf["is_nkd_night"]).sum()) if not mf.empty else 0,
        "covered_by_machine_sleep": int(mf["stall_covered_s"].notna().sum()) if not mf.empty else 0,
        "trading_job_misfires": (mf[mf["is_trading_job"] & ~mf["is_nkd_night"]]
                                 [["ts", "job_short", "missed_by_s"]]
                                 .astype(str).to_dict("records") if not mf.empty else []),
        "non_nkd_detail": (mf[~mf["is_nkd_night"]][["ts", "job_short", "missed_by_s",
                                                    "stall_covered_s"]]
                           .astype(str).to_dict("records") if not mf.empty else []),
        "by_job": (mf["job_short"].value_counts().to_dict() if not mf.empty else {}),
    }
    out["machine_sleep_stalls"] = {
        "n": int(len(stalls)),
        "total_stalled_s": int(stalls["stalled_s"].sum()) if not stalls.empty else 0,
        "worst_s": int(stalls["stalled_s"].max()) if not stalls.empty else 0,
        "days": sorted({str(pd.Timestamp(x).date()) for x in stalls["ts"]}) if not stalls.empty else [],
    }
    # change-point: split the live-day sample at the date the operator's checkpoint
    # work landed, and report both regimes rather than one blended number
    live_sorted = live.sort_values("start")
    早 = live_sorted[live_sorted["day"] < pd.Timestamp("2026-08-11")]
    muon = live_sorted[live_sorted["day"] >= pd.Timestamp("2026-08-11")]
    out["regimes"] = {
        "before_2026_08_11": dist(早["runtime_s"].to_numpy()),
        "from_2026_08_11": dist(muon["runtime_s"].to_numpy()),
    }
    out["shadow"] = shadow_outcomes()
    out["clearance_1555_vs_1620"] = clearance_1555_vs_1620(runs)

    # ---- static simulation, driven by the MEASURED sample -------------------
    # NOT sorted: keep chronological order so consecutive slots draw consecutive
    # real runtimes and the within-day autocorrelation survives. Sorting and then
    # cycling would only ever consume the smallest values and make every scenario
    # look free.
    sample = muon.sort_values("start")["runtime_s"].to_numpy()
    sample_old = 早.sort_values("start")["runtime_s"].to_numpy()
    cur_pm = [845] + list(range(850, 956, 5))              # 14:05 .. 15:55 ET, minutes past midnight
    nkd_pm = list(range(70, 176, 5))                       # 01:10 .. 02:55
    t1_stress = list(range(635, 751, 5))                   # 10:35 .. 12:30
    t1_calm = [600]                                        # 10:00
    sims = []

    def sweep(slots, sample_arr, label):
        """Run the sim from every possible starting index in the sample and report the
        distribution, so no single arbitrary offset decides the answer."""
        if len(sample_arr) == 0:
            return dict(label=label, error="empty sample")
        runs_ = [simulate(slots, sample_arr, off, label) for off in range(len(sample_arr))]
        sk = np.array([r["skipped"] for r in runs_])
        gp = np.array([r["max_gap_min"] for r in runs_])
        worst = runs_[int(np.argmax(sk))]
        return dict(label=label, n_slots=len(slots), offsets_tried=len(runs_),
                    skipped_median=float(np.median(sk)), skipped_p90=float(np.percentile(sk, 90)),
                    skipped_max=int(sk.max()),
                    skip_pct_max=float(sk.max() / len(slots)),
                    max_gap_min_worst=int(gp.max()),
                    worst_case_skipped_slots=worst["skipped_slots"][:20])

    def worst_case(slots, rt_s, label):
        """Every slot takes the same fixed runtime — the honest upper bound."""
        return simulate(slots, np.array([rt_s]), 0, label)

    cur_now = sweep(cur_pm, sample, "CURRENT regime | current window only")
    both_now = sweep(sorted(cur_pm + t1_stress + t1_calm), sample,
                     "CURRENT regime | current + Track1 windows")
    t1_now = sweep(sorted(t1_stress + t1_calm), sample,
                   "CURRENT regime | Track1 window alone")
    all_now = sweep(sorted(cur_pm + nkd_pm + t1_stress + t1_calm), sample,
                    "CURRENT regime | all windows incl NKD night")
    both_old = sweep(sorted(cur_pm + t1_stress + t1_calm), sample_old,
                     "PRE-08-11 regime | current + Track1 windows")
    cur_old = sweep(cur_pm, sample_old, "PRE-08-11 regime | current window only")
    sims = [cur_now, t1_now, both_now, all_now, cur_old, both_old]

    p95_now = float(np.percentile(sample, 95)) if len(sample) else 0.0
    max_now = float(np.max(sample)) if len(sample) else 0.0
    p95_old = float(np.percentile(sample_old, 95)) if len(sample_old) else 0.0
    fixed = [
        worst_case(sorted(cur_pm + t1_stress + t1_calm), p95_now,
                   f"fixed p95 of current regime ({p95_now:.0f}s) | current + Track1"),
        worst_case(sorted(cur_pm + t1_stress + t1_calm), max_now,
                   f"fixed max of current regime ({max_now:.0f}s) | current + Track1"),
        worst_case(sorted(cur_pm + t1_stress + t1_calm), p95_old,
                   f"fixed p95 of PRE-08-11 regime ({p95_old:.0f}s) | current + Track1"),
        worst_case(sorted(cur_pm + t1_stress + t1_calm), 330.0,
                   "fixed 5.5 min (the figure written in run_scheduler.py) | current + Track1"),
    ]
    out["simulation"] = dict(
        note="slots are SKIPPED not queued, matching run_scheduler.py:235 _run_guarded; "
             "runtimes cycled from the measured live-day sample, no randomness",
        runtime_sample_n=int(len(sample)),
        runtime_sample_p90=float(np.percentile(sample, 90)) if len(sample) else None,
        runtime_sample_max=float(np.max(sample)) if len(sample) else None,
        scenarios=sims, fixed_runtime_bounds=fixed)

    OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT_JSON)

    d = out["runtime_live_day_slots"]
    print(f"[live-day slots] n={d['n']} median={d['median']:.0f}s p90={d['p90']:.0f}s "
          f"p95={d['p95']:.0f}s max={d['max']:.0f}s over5min={d['over_300s']} "
          f"({100*d['pct_over_300s']:.1f}%)", flush=True)
    print(f"[shadow] {out['shadow']['totals']}", flush=True)
    print(f"[mutex] {out['mutex_skips']['total']} skips", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
