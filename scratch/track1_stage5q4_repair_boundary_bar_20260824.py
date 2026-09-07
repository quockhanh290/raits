"""Stage 5Q-4 — a bounded, fail-closed repair for a partial boundary bar. DRY RUN BY DEFAULT.

    # measure only, writes nothing to the parquet
    python scratch/track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ

    # what an apply would need, and it is deliberately awkward
    python scratch/track1_stage5q4_repair_boundary_bar_20260824.py --inst MNQ \
        --apply --expect <sha256 printed by the dry run>

The defect this repairs
-----------------------
`update_ibkr_daily` appends `new_bars[new_bars.index > last_existing]` — STRICTLY newer. The
bar that was last in the file is never rewritten. If the 13:45 fetch caught that minute while
it was still open, the file keeps a snapshot of a partial minute for ever, and no later run
revisits it. Measured 2026-08-24: MNQ 2026-08-21 13:45 ET holds `low = 29400.25` while twelve
independent live fetches all report `low = 29395.75` — 4.5 points, and the feed's low is LOWER,
which is the only direction a partial bar's low can be wrong in.

Why this is not a script that just fixes it
-------------------------------------------
Writing to a shared parquet is one-way. This repo has already lost a baseline to an in-place
parquet update — `$52,936` became unreproducible, and the "frozen" copy taken afterwards was
built from the already-contaminated file. So every guard below exists:

    dry run by default      the only mode that runs without a second flag
    --expect <sha256>       an apply must name the file it thinks it is editing
    snapshot first          `<path>.pre5q4-<stamp>.bak`, written and re-read before any write
    bounded window          only bars inside the requested window may change
    bounded count           more than --max-bars differ -> REFUSED, because that is not a
                            boundary repair, it is a different problem wearing its clothes
    no new bars             a repair may replace a bar, never add or remove one
    verify after            the file is re-read and the diff re-computed; a repair that did
                            not land is reported as a failure, not assumed

It refuses rather than guesses at every one of those. A repair tool that proceeds when it is
unsure is worse than no repair tool, because the damage is silent and the original is gone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"d:\raits")

import pandas as pd

from global_index import run_live_day_track1 as R
from global_index import track1_live_source as src

REPORT_DIR = Path("scratch")
TOL = 1e-6


class RepairRefused(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compare(frozen: pd.DataFrame, live: pd.DataFrame, *, inst: str) -> list:
    """Bar-by-bar disagreement over the SHARED timestamps. Projection first, so the
    comparison is over the frozen schema and not over whatever the feed sent.

    Reuses `project_to_frozen_columns` rather than reimplementing it: a repair that compared
    on different columns from the ones the route joins on would be repairing a different
    question.
    """
    live, _dropped = src.project_to_frozen_columns(inst, live, frozen)
    shared = pd.DatetimeIndex(live.index).intersection(pd.DatetimeIndex(frozen.index))
    out = []
    for ts in shared:
        a, b = live.loc[ts], frozen.loc[ts]
        diffs = {c: {"parquet": float(b[c]), "feed": float(a[c]),
                     "delta": round(float(a[c]) - float(b[c]), 6)}
                 for c in frozen.columns
                 if abs(float(a[c]) - float(b[c])) > TOL}
        if diffs:
            out.append({"ts": str(ts), "columns": diffs})
    return out


def run(*, inst: str, path: str, provider, through, window_minutes: int,
        apply: bool = False, expect: str | None = None, max_bars: int = 5) -> dict:
    p = Path(path)
    if not p.exists():
        raise RepairRefused("no_parquet", f"{path} does not exist")

    before_hash = sha256(p)
    frozen = src.frozen_frame(inst, path)
    fidx = pd.DatetimeIndex(frozen.index)
    last_bar = fidx[-1]
    window_start = last_bar - pd.Timedelta(minutes=window_minutes)

    raw = provider.fetch_session_bars(inst, through=through)
    if raw is None or len(raw.index) == 0:
        raise RepairRefused("no_feed_bars", f"the provider returned nothing for {inst}")
    aligned = src.on_frozen_clock(inst, raw, frozen)

    diffs = compare(frozen, aligned, inst=inst)
    in_window = [d for d in diffs if window_start <= pd.Timestamp(d["ts"]) <= last_bar]
    outside = [d for d in diffs if d not in in_window]

    report = {
        "tool": "stage5q4_repair_boundary_bar", "inst": inst, "path": path,
        "ran_at_utc": datetime.utcnow().isoformat(timespec="seconds"),
        "parquet_sha256_before": before_hash,
        "parquet_rows": int(len(frozen)), "parquet_last_bar": str(last_bar),
        "window_minutes": window_minutes, "window_start": str(window_start),
        "feed_rows": int(len(raw.index)),
        "shared_disagreements_total": len(diffs),
        "in_window": in_window, "outside_window": outside,
        "applied": False, "dry_run": not apply,
    }

    # ── the refusals, all before anything is written ─────────────────────────
    if outside:
        raise RepairRefused(
            "disagreement_outside_the_window",
            f"{len(outside)} bar(s) disagree outside the last {window_minutes} minutes; the "
            f"first is {outside[0]['ts']}. That is not a boundary bar and this tool will not "
            f"touch it — a wider disagreement is a different problem and needs its own look.")
    if len(in_window) > max_bars:
        raise RepairRefused(
            "too_many_bars",
            f"{len(in_window)} bars disagree inside the window and --max-bars is {max_bars}. "
            f"A partial boundary bar is one bar; this many is a feed or a contract question.")
    if not in_window:
        report["verdict"] = "nothing_to_repair"
        return report

    report["verdict"] = "repairable" if apply else "repairable_dry_run"
    if not apply:
        return report

    # ── apply, and only now ──────────────────────────────────────────────────
    if expect is None or expect != before_hash:
        raise RepairRefused(
            "hash_guard",
            f"--apply needs --expect to match the file as it is now. Expected "
            f"{expect!r}, file is {before_hash!r}. This is what stops a repair measured "
            f"against one version of the file from landing on another.")

    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup = p.with_suffix(p.suffix + f".pre5q4-{stamp}.bak")
    if backup.exists():
        raise RepairRefused("backup_exists", f"{backup} already exists; refusing to overwrite")
    backup.write_bytes(p.read_bytes())
    if sha256(backup) != before_hash:
        raise RepairRefused("backup_mismatch",
                            "the snapshot does not match the original; nothing was written")
    report["backup"] = str(backup)

    fixed = frozen.copy()
    live, _ = src.project_to_frozen_columns(inst, aligned, frozen)
    for d in in_window:
        ts = pd.Timestamp(d["ts"])
        fixed.loc[ts, list(frozen.columns)] = live.loc[ts, list(frozen.columns)].values

    # A repair replaces bars. It may never add or remove one.
    if not pd.DatetimeIndex(fixed.index).equals(fidx):
        raise RepairRefused("index_changed",
                            "the repair changed the index; nothing was written")

    # Stage 5Q-6 — a latent corruption this tool would have caused, found by MEASURING the
    # real file instead of trusting the fixture.
    #
    # The parquets on disk carry a tz-NAIVE UTC index. `frozen_frame` converts it to a
    # tz-AWARE America/New_York index, because that is the clock the sleeves read on. Writing
    # that frame straight back would change the storage convention of an eight-year,
    # 3.3-million-row file that `_core.load_parquet`, `assert_utc_convention` and every
    # backtest depend on.
    #
    # The tests did not catch it because the fixture wrote a tz-AWARE UTC index, so the round
    # trip preserved awareness there and would not have on disk — a fixture that did not match
    # the file it stood in for.
    #
    # So the write is put back into the FILE'S OWN convention, read from the file rather than
    # assumed, and the columns must already match or the write is refused rather than reshaped.
    raw = pd.read_parquet(p)
    raw_tz = pd.DatetimeIndex(raw.index).tz
    if list(raw.columns) != list(fixed.columns):
        raise RepairRefused(
            "column_shape_changed",
            f"the file stores {list(raw.columns)} and this repair would write "
            f"{list(fixed.columns)}. Refused rather than reshaped.")
    out = fixed.copy()
    oi = pd.DatetimeIndex(out.index)
    out.index = (oi.tz_convert("UTC").tz_localize(None) if raw_tz is None
                 else oi.tz_convert(raw_tz))
    if str(pd.DatetimeIndex(out.index).tz) != str(raw_tz):
        raise RepairRefused("index_convention_changed",
                            f"could not restore the file's {raw_tz!r} index convention")
    out.to_parquet(p)

    # ── verify by re-reading, not by trusting the object in memory ───────────
    after = src.frozen_frame(inst, path)
    remaining = [d for d in compare(after, aligned, inst=inst)]
    if str(pd.DatetimeIndex(pd.read_parquet(p).index).tz) != str(raw_tz):
        raise RepairRefused(
            "index_convention_changed",
            f"the file came back with a different index convention than the {raw_tz!r} it "
            f"had. The original is at {backup}; restore it with a byte copy.")
    report["index_convention"] = str(raw_tz)
    report["parquet_sha256_after"] = sha256(p)
    report["remaining_disagreements"] = remaining
    report["applied"] = True
    report["verdict"] = "repaired" if not remaining else "repair_did_not_land"
    if remaining:
        raise RepairRefused(
            "verify_failed",
            f"{len(remaining)} disagreement(s) remain after the write. The original is at "
            f"{backup}; restore it with a byte copy.")
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Bounded, fail-closed repair of a partial boundary bar. DRY RUN unless "
                    "--apply AND --expect are both given.")
    ap.add_argument("--inst", required=True, choices=sorted(R.default_data_paths()))
    ap.add_argument("--path", default=None, help="override the parquet path")
    ap.add_argument("--window-minutes", type=int, default=120,
                    help="how far back from the parquet's LAST bar a disagreement may be "
                         "repaired. A disagreement outside it refuses the whole run.")
    ap.add_argument("--max-bars", type=int, default=5)
    ap.add_argument("--through", default=None, help="ET instant to fetch through")
    ap.add_argument("--apply", action="store_true",
                    help="write. Requires --expect. Snapshots first, verifies after.")
    ap.add_argument("--expect", default=None, help="sha256 the parquet must currently have")
    ap.add_argument("--bar-provider", default="ibkr", choices=["ibkr", "none"])
    ap.add_argument("--client-id", type=int, default=95,
                    help="IBKR client id for the READ-ONLY fetch. Default 95 so a measurement "
                         "run can never contend with the Track 1 data client (89), the Track 1 "
                         "safety client (90), legacy (1) or the daily updater (2). Two clients "
                         "on one id has already cost this system six entry slots.")
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    path = a.path or R.default_data_paths()[a.inst]
    through = pd.Timestamp(a.through) if a.through else pd.Timestamp.now(tz="America/New_York")

    provider, broker = src.build_bar_provider(a.bar_provider, client_id=a.client_id)
    try:
        report = run(inst=a.inst, path=path, provider=provider, through=through,
                     window_minutes=a.window_minutes, apply=a.apply, expect=a.expect,
                     max_bars=a.max_bars)
    except RepairRefused as exc:
        print(f"REFUSED - {exc.code}: {exc.detail}")
        return 2
    finally:
        if broker is not None and callable(getattr(broker, "disconnect", None)):
            try:
                broker.disconnect()
            except Exception as exc:              # noqa: BLE001
                print(f"  warning: disconnect failed: {exc}")

    print(json.dumps(report, indent=2, default=str))
    out = REPORT_DIR / f"_track1_stage5q4_repair_{a.inst}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out}")
    if not a.apply:
        print("\nDRY RUN - the parquet was not written. To apply, re-run with:")
        print(f"  --apply --expect {report['parquet_sha256_before']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
