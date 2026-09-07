"""scratch/track1_bootstrap_checkpoint_20260822.py — Stage 2B. Offline. Scratch only.

Builds the FIRST Track 1 checkpoint (schema v2, route-keyed) by replaying from parquet
once, exactly as `global_index/replay_checkpoint._bootstrap()` does for legacy — same
loaders, same labels, same costs, same "last COMPLETE session" rule. Nothing here starts a
scheduler, opens a broker connection, or writes a production path.

Why it mirrors the legacy bootstrap line for line
-------------------------------------------------
A Track 1 checkpoint that disagrees with the legacy one about the SAME day and the SAME
parameters is not a new route, it is a bug. So this script does not re-derive the replay:
it calls the same `backtest_swing_tf` through the same entry points, and then ANCHORS the
result against the live legacy checkpoint on disk. If `last_day` or the open position
disagree for any instrument, it refuses to write.

The anchor is the whole point, so it is falsifiable
---------------------------------------------------
`--anchor-day` cuts every instrument at the day the legacy checkpoint recorded, not at
whatever today happens to be. Cutting at "the latest complete session" would compare two
different days and pass by construction — MNKD in particular runs a Tokyo clock and rolls
into a new session while the ET instruments have not, so on any given afternoon the two
files legitimately name different days.

Parameter identity
------------------
Every field in `route_params.ALL_FIELDS` is filled from a source that is named in
PROVENANCE below. The sentinel machinery stays: any field left `UNKNOWN` blocks the write,
because a default would hash cleanly and silently claim a setting nobody chose. As of
2026-08-22 nothing is blocked — the SPY short gate was audited into four sourced fields and
`fill_law` was settled by measuring both laws rather than by picking one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from global_index import route_checkpoint as rc
from global_index import route_params as rp

UNKNOWN = "UNKNOWN"
OUT_DEFAULT = "scratch/replay_checkpoint.track1.bootstrap_20260822.json"
LEGACY_PATH = "global_index/replay_checkpoint.json"

R4 = ("MES", "MNQ", "MYM", "M2K")
SLEEVE_OF = {i: "roska4_swing" for i in R4}
SLEEVE_OF["MNKD"] = "global_nkd"


# ---------------------------------------------------------------------------
# provenance — every value below is quoted from a file, never chosen here
# ---------------------------------------------------------------------------
PROVENANCE = {
    "ema_period": "futures/swing_tf.py SWING_TF_PARAM (R4=30); replay_checkpoint._bootstrap --nkd-ema default 10 (MNKD)",
    "max_hold_days": "futures/swing_tf.py SWING_TF_PARAM",
    "stop_basis": "futures/_validated_core.py:267 backtest_swing_tf, chandelier_atr_mult",
    "stop_multiple": "futures/swing_tf.py SWING_TF_PARAM chandelier_atr_mult",
    "stop_anchor": "futures/_validated_core.py:359-366 — stop in force at each bar open ratchets from pos['extreme'] through the PRIOR bar (run_prev)",
    "ratchet": "futures/_validated_core.py:301 'the loop ratchets pos[stop] and pos[extreme] in place'",
    "arm_hour": "global_index/runner.py:144 _ARM_BY_CLUSTER",
    "arm_timezone": "global_index/runner.py:144-145 _ARM_BY_CLUSTER (per cluster)",
    "r4_range_threshold": "scratch/normal_promotion_filter_lib_20260821.py:44 FLOOR_RANGE_P90",
    "r4_range_derivation_window": "same file, header: frozen on the floor window 2018-2024 by normal_sleeve_context_combo_probe_20260821.py",
    "r4_rel_volume_max": "scratch/normal_promotion_filter_lib_20260821.py:45 VOL_LE",
    "spy_short_filter": "scratch/normal_promotion_regen_audit_20260821.py:121,131 — applied in the generator that WROTE the promotion artifacts, ahead of the R4 context filter",
    "spy_short_lookback": "scratch/directional_market_filter_probe.py:26 — spy.rolling(50).mean().shift(1)",
    "spy_short_lag_days": "same line: close compared is spy.shift(1); proven causal by mutation 2026-08-22",
    "spy_short_source_identity": "spy_daily_live.csv + sha256, the file the generator was invoked with",
    "hmm_fit_end": "futures/basket.py REGIME['hmm_fit_end']",
    "regime_csv_identity": "computed here: spy_daily_live.csv + sha256 of its bytes",
    "label_lag_days": "replay_checkpoint._bootstrap: R4 uses label_regimes directly (0); MNKD uses RegimeLabels(..., lag_days=1)",
    "calm_gate_definition": "docs/futures/CALM_PCLOC_NOT_DEEP_GAP_AUDIT_2026-08-21.md title + line 333 + the >= -1.0% gap column",
    "cap_roska4_swing": "committed Track 1 candidate: Normal+Calm family 5.0% gross / 4.4% net",
    "cap_roska4_calm": "same family cap",
    "cap_roska4_stress": "committed Track 1 candidate: Stress-MNQ mnq_only_g3_q7 cap 10%",
    "cap_global_nkd": "committed Track 1 candidate: current NKD/MNKD qty 1 cap 6%",
    "cap_family_normal_calm": "committed Track 1 candidate: Normal+Calm 5.0% gross / 4.4% net",
    "slippage_ticks_per_side": "replay_checkpoint._bootstrap --slippage-ticks default 2.0; generate_replay_snapshots.py SLIPPAGE = 2.0",
    "commission_basis": "global_index/specs.py commission_rt / futures.swing_tf costs_for_basket",
    "data_source_identity": "computed here per instrument: parquet path + sha256 of file bytes",
    "fill_law": "measured on both laws 2026-08-22 across floor/vault2025/vault2026: the production law differs by $0 to +$6 at book level over seven years. Chosen because it is the one the live engine runs and the difference is immaterial",
}

#: Fields that could not be sourced, and the reason. Filling these with a plausible value
#: is the failure mode this table exists to prevent.
UNSOURCED: dict[str, str] = {}

#: Settled by measurement rather than by picking. `fill_law` was a genuine two-law conflict
#: until 2026-08-22, when both laws were regenerated through the generator that produced the
#: committed artifacts and compared at sleeve and book level on all three windows. The
#: production law — fill at the open only after a real break of more than 15 minutes — moved
#: the book by $0 to +$6 over seven years, and it is the MORE permissive of the two, so the
#: published Track 1 numbers were measured under the stricter one. It is chosen here because
#: it is what the live engine actually runs. Flipping it back is one constant.
DECIDED_BY_MEASUREMENT = {
    "fill_law": "scratch/track1_three_blockers_report_20260822.md section 2",
}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _common(regime_identity: str) -> dict:
    """Fields shared by every sleeve. Caps are shared on purpose: a cap is an admission
    gate on the whole book, so a sleeve that ignores one still depends on it."""
    return {
        "stop_basis": "chandelier_atr",
        "stop_multiple": 2.5,
        "stop_anchor": "extreme_through_prior_bar",
        "ratchet": True,
        "r4_range_threshold": 0.02652437134968455,
        "r4_range_derivation_window": "floor_2018_2024_p90",
        "r4_rel_volume_max": 2.0,
        # Audited 2026-08-22 and confirmed causal by mutation: corrupting SPY's close AT D
        # leaves the value at D unchanged and moves D+1, so the rule reads only sessions
        # strictly before the decision day.
        "spy_short_filter": "d1_spy_close_below_sma50_for_shorts_only",
        "spy_short_lookback": 50,
        "spy_short_lag_days": 1,
        # Same file as the regime labels today, but a separate axis on purpose: the HMM
        # labels and this gate could be pointed at different SPY histories tomorrow, and a
        # single field would hide that.
        "spy_short_source_identity": regime_identity,
        "hmm_fit_end": "2024-12-31",
        "regime_csv_identity": regime_identity,
        "calm_gate_definition":
            "pcloc_bottom_third_of_prior_rth_range AND prior_rth_down_close_below_open "
            "AND gap_from_prev_rth_close>=-0.01 LONG MES,MNQ entry=10:00 exit=15:55 lag1",
        "cap_roska4_swing": 0.05,
        "cap_roska4_calm": 0.05,
        "cap_roska4_stress": 0.10,
        "cap_global_nkd": 0.06,
        "cap_family_normal_calm": 0.05,
        "slippage_ticks_per_side": 2.0,
        "commission_basis": "round_turn_per_contract",
        "fill_law": "production_gap_after_15min_break",
    }


def sleeve_configs(regime_identity: str, source_identity: dict) -> dict:
    """One config per (sleeve, instrument). The two swing sleeves differ in three places —
    EMA, arming clock and label lag — and those three are exactly why they cannot share a
    params hash."""
    # Stage 5Q-9 — I-2. The identity gained four names on 2026-08-24: what an order is
    # routed to, what the contract is worth, its tick, and which of the two risk formulas
    # the cap gate is fed. Derived per instrument from the same contract table the route
    # reads, so this seed cannot disagree with the route about what it would have traded.
    #
    # `sizing_basis` is the ATR proxy for every row here because that is what this legacy
    # seed was produced under — `signal_layer` sized it as MULT x daily ATR.
    from global_index import track1_params as _tp

    def _traded(inst: str) -> dict:
        c = _tp._contract(inst)
        return {"tradable_symbol": c.ibkr, "point_value": float(c.point_value),
                "tick": float(c.tick), "sizing_basis": _tp.SIZING_ARTIFACT_ATR}

    out = {}
    for inst in R4:
        cfg = _common(regime_identity)
        cfg.update(ema_period=30, max_hold_days=5,
                   arm_hour=14, arm_timezone="America/New_York",
                   label_lag_days=0,
                   data_source_identity=source_identity[inst],
                   **_traded(inst))
        out[inst] = cfg
    cfg = _common(regime_identity)
    cfg.update(ema_period=10, max_hold_days=5,
               arm_hour=14, arm_timezone="Asia/Tokyo",
               label_lag_days=1,
               data_source_identity=source_identity["MNKD"],
               **_traded("MNKD"))
    out["MNKD"] = cfg
    return out


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------
def _cut_for(df: pd.DataFrame, day: pd.Timestamp) -> pd.Timestamp:
    cut = pd.Timestamp(day) + pd.Timedelta(days=1)
    return cut.tz_localize(df.index.tz) if df.index.tz is not None else cut


def replay_all(regime_csv: str, data_dir: str, nkd_parquet: str,
               slippage: float, anchor_day: "str | None") -> dict:
    """Return {inst: {df, last_day, pos, kw}} — the legacy bootstrap, per instrument."""
    from futures._validated_core import (backtest_swing_tf, benchmark_daily,
                                         label_regimes, load_parquet)
    from futures.basket import BASKET, REGIME, data_filename
    from futures.swing_tf import SWING_TF_PARAM, costs_for_basket

    labels = label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3,
                           REGIME["hmm_fit_end"])
    costs = costs_for_basket(slippage_ticks=slippage)
    kw = dict(ema_period=SWING_TF_PARAM["ema_period"],
              chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
              max_hold_days=SWING_TF_PARAM["max_hold_days"])

    out = {}
    for inst, c in BASKET.items():
        df = load_parquet(str(Path(data_dir) / data_filename(c)))
        sess = sorted(set(df.index.normalize().tz_localize(None)))
        last = pd.Timestamp(anchor_day) if anchor_day else sess[-2]
        if last not in sess:
            raise SystemExit(f"{inst}: {last.date()} is not a session in the parquet")
        _, pos = backtest_swing_tf(df[df.index < _cut_for(df, last)], labels,
                                   costs[inst], return_open=True, **kw)
        out[inst] = {"df": df, "last_day": last, "pos": pos, "kw": dict(kw),
                     "path": str(Path(data_dir) / data_filename(c))}

    # MNKD — its own clock, its own EMA, lagged labels. Same shape as legacy.
    from global_index import specs as gi_specs
    from global_index._core import FuturesCost as GIFC
    from global_index._core import load_parquet as gi_load
    from global_index.regime import RegimeLabels

    cn = gi_specs.SPECS["MNKD"]
    spy = pd.Series(label_regimes(benchmark_daily(regime_csv), "2018-01-01", 3,
                                  REGIME["hmm_fit_end"]))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    ndf = gi_load(nkd_parquet)
    ndf.index = ndf.index.tz_convert(cn.session_tz)
    nkw = dict(ema_period=10, chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
               max_hold_days=SWING_TF_PARAM["max_hold_days"])
    ncost = GIFC(point_value=cn.point_value, tick=cn.tick, commission_rt=cn.commission_rt,
                 slippage_ticks_per_side=slippage)
    nsess = sorted(set(ndf.index.normalize().tz_localize(None)))
    nlast = pd.Timestamp(anchor_day) if anchor_day else nsess[-2]
    if nlast not in nsess:
        raise SystemExit(f"MNKD: {nlast.date()} is not a session in the parquet")
    _, npos = backtest_swing_tf(ndf[ndf.index < _cut_for(ndf, nlast)],
                                RegimeLabels(spy.sort_index(), lag_days=1),
                                ncost, return_open=True, **nkw)
    out["MNKD"] = {"df": ndf, "last_day": nlast, "pos": npos, "kw": nkw,
                   "path": nkd_parquet}
    return out


# ---------------------------------------------------------------------------
# anchor
# ---------------------------------------------------------------------------
def _norm_pos(pos) -> "dict | None":
    if pos is None:
        return None
    keep = ("dir", "entry", "stop", "extreme", "entry_day", "entry_time", "regime")
    out = {}
    for k in keep:
        if k in pos:
            v = pos[k]
            out[k] = round(float(v), 6) if isinstance(v, (int, float)) else str(v)
    return out


def anchor_against_legacy(replayed: dict, legacy_path: str) -> dict:
    """Compare this bootstrap with the live legacy checkpoint, instrument by instrument.

    Only `last_day` and the open position are compared. The fingerprint deliberately is
    NOT: it pins the parquet's row count and content, which move every time bars are
    appended, so a fingerprint comparison would fail for a reason that has nothing to do
    with whether the replay agrees.
    """
    legacy = json.loads(Path(legacy_path).read_text(encoding="utf-8"))["instruments"]
    rows = []
    for inst, r in replayed.items():
        want = legacy.get(inst)
        if want is None:
            rows.append({"inst": inst, "ok": False, "why": "absent from legacy checkpoint"})
            continue
        same_day = str(pd.Timestamp(r["last_day"]).date()) == want["last_day"]
        mine, theirs = _norm_pos(r["pos"]), _norm_pos(want.get("pos"))
        same_pos = mine == theirs
        rows.append({"inst": inst, "ok": bool(same_day and same_pos),
                     "day_mine": str(pd.Timestamp(r["last_day"]).date()),
                     "day_legacy": want["last_day"],
                     "pos_mine": mine, "pos_legacy": theirs,
                     "why": "" if same_day and same_pos else
                            ("last_day differs" if not same_day else "position differs")})
    return {"rows": rows, "all_ok": all(r["ok"] for r in rows)}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--nkd-parquet",
                    default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    ap.add_argument("--anchor-day", default="2026-08-20",
                    help="cut every instrument here so the legacy comparison is same-day")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--legacy", default=LEGACY_PATH)
    a = ap.parse_args()

    out_path = Path(a.out)
    if "scratch" not in out_path.parts:
        print("REFUSED: this script writes scratch paths only.")
        return 2

    print("Track 1 bootstrap — offline, scratch only")
    print(f"  anchor day : {a.anchor_day}")
    print(f"  out        : {a.out}\n")

    if UNSOURCED:
        print("UNSOURCED / BLOCKER — fields with no defensible value:")
        for k, why in UNSOURCED.items():
            print(f"  [{UNKNOWN}] {k}")
            for line in _wrap(why):
                print(f"          {line}")
        print()

    replayed = replay_all(a.regime_csv, a.data_dir, a.nkd_parquet,
                          a.slippage_ticks, a.anchor_day)
    for inst in ("MES", "MNQ", "MYM", "M2K", "MNKD"):
        r = replayed[inst]
        held = "flat" if r["pos"] is None else \
            f"{r['pos']['dir']} entry={r['pos']['entry']:.2f} stop={r['pos']['stop']:.2f}"
        print(f"  {inst:5s} last_day={pd.Timestamp(r['last_day']).date()}  {held}")

    print("\nANCHOR vs legacy checkpoint")
    anc = anchor_against_legacy(replayed, a.legacy)
    for row in anc["rows"]:
        flag = "OK " if row["ok"] else "XX "
        print(f"  {flag}{row['inst']:5s} mine={row.get('day_mine')} "
              f"legacy={row.get('day_legacy')} {row['why']}")
    if not anc["all_ok"]:
        print("\nREFUSED to write: the bootstrap disagrees with the live checkpoint.")
        print("A Track 1 file that contradicts legacy on the same day and the same "
              "parameters is a bug, not a route.")
        return 1

    regime_identity = f"{a.regime_csv}:{_sha256(a.regime_csv)}"
    source_identity = {i: f"{Path(r['path']).name}:{_sha256(r['path'])}"
                       for i, r in replayed.items()}
    cfgs = sleeve_configs(regime_identity, source_identity)

    by_sleeve: dict = {"roska4_swing": {}, "global_nkd": {}}
    for inst, r in replayed.items():
        cfg = cfgs[inst]
        readable, phash = rp.identity(cfg)
        by_sleeve[SLEEVE_OF[inst]][inst] = rc.make_entry(
            r["df"], r["last_day"], r["pos"],
            route=rc.DEFAULT_ROUTE, sleeve=SLEEVE_OF[inst],
            params=readable, params_hash=phash,
            data_source=cfg["data_source_identity"])

    payload = rc.save_route(by_sleeve, route=rc.DEFAULT_ROUTE, path=str(out_path))
    sleeves = payload["routes"][rc.DEFAULT_ROUTE]["sleeves"]
    print(f"\nwrote {a.out}")
    for s in rc.SLEEVES:
        n = len(sleeves.get(s, {}).get("instruments", {}))
        note = "  (same-session sleeve, no carry — empty on purpose)" \
            if s in ("roska4_calm", "roska4_stress") else ""
        print(f"  {s:15s} {n} instrument(s){note}")

    print("\nSELF-CHECKS")
    ok = True
    for name, passed, detail in _self_checks(payload, replayed, cfgs, a):
        ok &= passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name} — {detail}")

    Path(str(out_path) + ".anchor.json").write_text(
        json.dumps({"anchor": anc, "unsourced": sorted(UNSOURCED)}, indent=2,
                   default=str), encoding="utf-8")
    return 0 if ok else 1


def _wrap(text: str, width: int = 84):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


def _self_checks(payload, replayed, cfgs, a):
    """Nine checks that can each go red. SC4 and SC7 are the ones that matter: a params
    hash that does not separate the two swing sleeves, or a sleeve list that quietly loses
    a sleeve, would both leave a file that looks correct."""
    sleeves = payload["routes"][rc.DEFAULT_ROUTE]["sleeves"]
    swing = sleeves["roska4_swing"]["instruments"]
    nkd = sleeves["global_nkd"]["instruments"]

    yield ("SC1 schema is v2", payload.get("schema_version") == rc.SCHEMA,
           f"schema_version={payload.get('schema_version')}")
    yield ("SC2 all four sleeves present", set(sleeves) == set(rc.SLEEVES),
           f"{sorted(sleeves)}")
    yield ("SC3 five instruments placed", len(swing) == 4 and len(nkd) == 1,
           f"swing={sorted(swing)} nkd={sorted(nkd)}")
    # Two separate properties, because one hash carries two things. Every instrument's
    # hash must be UNIQUE — otherwise the parquet a position was replayed from is not
    # really pinned. And with that per-file pin held constant, the four R4 sleeves must
    # collapse to one strategy identity while NKD stays apart on ema/clock/label lag.
    all_h = [e["params_hash"] for g in (swing, nkd) for e in g.values()]
    yield ("SC4a every instrument hash is unique (the data pin reaches the hash)",
           len(set(all_h)) == len(all_h), f"{len(set(all_h))} distinct of {len(all_h)}")
    fixed = "PINNED"
    strat = {i: rp.params_hash({**cfgs[i], "data_source_identity": fixed}) for i in cfgs}
    r4_set = {strat[i] for i in R4}
    yield ("SC4b R4 share one strategy identity, NKD differs",
           len(r4_set) == 1 and strat["MNKD"] not in r4_set,
           f"r4={sorted(r4_set)[0][:12]} nkd={strat['MNKD'][:12]}")
    yield ("SC5 same-session sleeves empty",
           not sleeves["roska4_calm"]["instruments"]
           and not sleeves["roska4_stress"]["instruments"],
           "calm and stress carry nothing across days")
    yield ("SC6 every entry carries a fingerprint and a data source",
           all(e.get("fingerprint") and e.get("data_source")
               for g in (swing, nkd) for e in g.values()),
           "no entry is missing either")
    yield ("SC7 every declared param field is filled",
           all(set(c) >= set(rp.ALL_FIELDS) for c in cfgs.values()),
           f"{len(rp.ALL_FIELDS)} fields required")
    n_unknown = sum(1 for c in cfgs.values() for v in c.values() if v == UNKNOWN)
    yield ("SC8 unsourced fields are declared, not defaulted",
           n_unknown == len(UNSOURCED) * len(cfgs),
           f"{n_unknown} sentinel values across {len(cfgs)} configs, "
           f"{len(UNSOURCED)} declared unsourced")
    yield ("SC9 last_day matches the requested anchor for every instrument",
           all(str(pd.Timestamp(r["last_day"]).date()) == a.anchor_day
               for r in replayed.values()),
           f"anchor={a.anchor_day}")


if __name__ == "__main__":
    raise SystemExit(main())
