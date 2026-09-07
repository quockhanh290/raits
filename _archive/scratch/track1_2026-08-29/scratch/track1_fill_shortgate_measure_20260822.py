"""scratch/track1_fill_shortgate_measure_20260822.py — Stage 2C. Offline. Scratch only.

Reads the 2x2 variant trade tables produced by `track1_fill_shortgate_regen_20260822.py`
and reports, against the shipped configuration:

  level 1  per SLEEVE, standalone, one contract, straight off the artifact's own per-trade
           P&L: trades, trades that changed, net, PF, MaxDD, Calmar
  level 2  the whole Track 1 BOOK, by re-running the committed combined replay with the
           variant tables swapped in under the caps, the family gate and the same-symbol
           suppression rules

Level 1 alone would be misleading. The caps are admission gates, so a sleeve that gains
trades in isolation can lose them in the book by crowding out another sleeve — the delta
that matters for a deploy decision is the one measured through the guard.

Calm and Stress are expected to be untouched by both axes: they are same-session sleeves
sourced from their own artifacts, not from the swing engine these axes patch. Expected is
not the same as verified, so it is checked rather than asserted in prose.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd  # noqa: E402

from global_index.deploy_sim import metrics  # noqa: E402
from scratch.track1_fill_shortgate_regen_20260822 import OUT_DIR, VARIANTS  # noqa: E402

R4 = ("MES", "MNQ", "MYM", "M2K")
BASE = "artifact_gate_on"
COMMITTED = "scratch/normal_promotion_trades_{}_20260821.json"
WINDOWS = ("floor", "vault2025", "vault2026")

_KEYS = ("day", "exit_day", "direction", "entry", "exit", "pnl")


def _key(t) -> tuple:
    return tuple(str(t.get(k)) for k in _KEYS)


def _daily(trades) -> pd.Series:
    """One contract, booked on the exit day — the same convention the artifact's own daily
    series uses, so the numbers stay comparable with what was published."""
    if not trades:
        return pd.Series(dtype=float)
    rows = [(pd.Timestamp(t.get("exit_day") or t["day"]), float(t["pnl"])) for t in trades]
    s = pd.Series([p for _, p in rows],
                  index=pd.DatetimeIndex([d.tz_localize(None) if d.tz is not None else d
                                          for d, _ in rows]).normalize())
    return s.groupby(level=0).sum().sort_index()


def sleeve_trades(payload: dict, sleeve: str) -> list:
    t = payload["trades"]
    insts = R4 if sleeve == "roska4_swing" else (payload["nkd_instrument"],)
    out = []
    for i in insts:
        out.extend(t.get(i, []))
    return out


def level1(window: str) -> dict:
    """Per-sleeve standalone metrics for every variant, plus the trade-level diff."""
    loaded = {}
    for name in VARIANTS:
        p = OUT_DIR / f"{window}__{name}.json"
        if p.exists():
            loaded[name] = json.loads(p.read_text(encoding="utf-8"))
    if BASE not in loaded:
        return {"window": window, "error": f"{BASE} missing — nothing to compare against"}

    out = {"window": window, "sleeves": {}}
    for sleeve in ("roska4_swing", "global_nkd"):
        base_t = sleeve_trades(loaded[BASE], sleeve)
        base_k = {_key(t) for t in base_t}
        base_m = metrics(_daily(base_t))
        rows = []
        for name, payload in loaded.items():
            tr = sleeve_trades(payload, sleeve)
            k = {_key(t) for t in tr}
            m = metrics(_daily(tr))
            rows.append({
                "variant": name,
                "fill_law": payload["fill_law"], "spy_short_gate": payload["spy_short_gate"],
                "trades": len(tr),
                "added": len(k - base_k), "removed": len(base_k - k),
                "changed": len(k ^ base_k),
                "net": m["pnl"], "pf": m["pf"], "calmar": m["calmar"], "maxdd": m["maxdd"],
                "d_net": m["pnl"] - base_m["pnl"],
                "d_pf": m["pf"] - base_m["pf"],
                "d_calmar": m["calmar"] - base_m["calmar"],
                "d_maxdd": m["maxdd"] - base_m["maxdd"],
            })
        out["sleeves"][sleeve] = rows
    return out


# ---------------------------------------------------------------------------
# level 2 — the book, through the guard
# ---------------------------------------------------------------------------
def _committed_shaped(payload: dict, window: str, tmp: Path) -> Path:
    """Write a variant table in the exact shape the committed artifact has.

    Both `load_normal` and `load_r4_and_nkd` read the `filtered` bucket, so that is the one
    swapped. `raw` and `filtered_prevbar` are carried over from the committed file untouched
    — nothing downstream in the Track 1 book reads them, and replacing them would change a
    second thing at the same time.
    """
    ref = json.loads(Path(COMMITTED.format(window)).read_text(encoding="utf-8"))
    ref["filtered"] = payload["trades"]
    out = tmp / f"{window}__{payload['variant']}__committed_shape.json"
    out.write_text(json.dumps(ref, indent=1), encoding="utf-8")
    return out


def level2(window: str, tmp: Path) -> dict:
    import scratch.calm_a_combined_replay_20260822 as calm_a_base
    import scratch.combined_repaired_replay_20260822 as comb
    import scratch.combined_stop_risk_audit_20260822 as audit
    import scratch.stress_switch_full_replay_20260822 as full

    rows = []
    orig = dict(full.NORMAL_PROMOTION_FILES)
    try:
        for name in VARIANTS:
            p = OUT_DIR / f"{window}__{name}.json"
            if not p.exists():
                continue
            payload = json.loads(p.read_text(encoding="utf-8"))
            full.NORMAL_PROMOTION_FILES[window] = _committed_shaped(payload, window, tmp)

            # `audit.load_all` memoises per window in `calm_a_base.DATA_CACHE`, so without
            # this every variant after the first silently replays the FIRST one's trades and
            # every delta comes out exactly zero. That is what happened on the first run.
            calm_a_base.DATA_CACHE.pop(window, None)

            # Wiring check, not a comment: the book must actually be holding this variant's
            # trades. A swap that fails to take is invisible in the output — it just prints
            # a clean table of zeros.
            r4_loaded, nkd_loaded, _pr, _ex, _st, _cn = audit.load_all(window)
            want_r4 = sum(len(payload["trades"].get(i, [])) for i in R4)
            want_nkd = len(payload["trades"].get(payload["nkd_instrument"], []))
            if len(r4_loaded) != want_r4 or len(nkd_loaded) != want_nkd:
                raise SystemExit(
                    f"{window}/{name}: the book loaded {len(r4_loaded)} R4 and "
                    f"{len(nkd_loaded)} NKD trades but the variant holds {want_r4}/"
                    f"{want_nkd} — the file swap did not take.")

            for pol in comb.POLICIES:
                daily, st = comb.replay_repaired(window, pol)
                m = metrics(daily)
                rows.append({
                    "variant": name, "policy": pol.name,
                    "fill_law": payload["fill_law"],
                    "spy_short_gate": payload["spy_short_gate"],
                    "net": m["pnl"], "pf": m["pf"], "calmar": m["calmar"],
                    "maxdd": m["maxdd"], "sharpe": m["sharpe"],
                    "taken": dict(st["taken"]), "rejected": dict(st["rejected"]),
                })
    finally:
        full.NORMAL_PROMOTION_FILES.clear()
        full.NORMAL_PROMOTION_FILES.update(orig)

    base = {r["policy"]: r for r in rows if r["variant"] == BASE}
    for r in rows:
        b = base.get(r["policy"])
        if b:
            r["d_net"] = r["net"] - b["net"]
            r["d_pf"] = r["pf"] - b["pf"]
            r["d_calmar"] = r["calmar"] - b["calmar"]
            r["d_maxdd"] = r["maxdd"] - b["maxdd"]
            # The claim being tested: neither axis touches the same-session sleeves.
            r["calm_stress_untouched"] = (
                r["taken"].get("roska4_calm") == b["taken"].get("roska4_calm")
                and r["taken"].get("roska4_stress") == b["taken"].get("roska4_stress"))
    return {"window": window, "rows": rows}


def _fmt(v, money=False):
    if v is None:
        return "-"
    if isinstance(v, float) and v != v:
        return "nan"
    return f"{v:>10,.0f}" if money else f"{v:>7.2f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=list(WINDOWS))
    ap.add_argument("--skip-book", action="store_true")
    ap.add_argument("--out", default="scratch/track1_fill_shortgate_measure_20260822.json")
    a = ap.parse_args()

    tmp = OUT_DIR / "committed_shape"
    tmp.mkdir(parents=True, exist_ok=True)
    result = {"level1": {}, "level2": {}}

    for w in a.which:
        l1 = level1(w)
        result["level1"][w] = l1
        if "error" in l1:
            print(f"\n=== {w} === {l1['error']}")
            continue
        print(f"\n=== {w} — sleeve standalone, 1 contract ===")
        for sleeve, rows in l1["sleeves"].items():
            print(f"  {sleeve}")
            print(f"    {'variant':22s} {'trades':>6} {'chg':>5} {'net':>10} "
                  f"{'d_net':>10} {'pf':>7} {'calmar':>7} {'maxdd':>10} {'d_maxdd':>10}")
            for r in rows:
                print(f"    {r['variant']:22s} {r['trades']:>6} {r['changed']:>5} "
                      f"{_fmt(r['net'], 1)} {_fmt(r['d_net'], 1)} {_fmt(r['pf'])} "
                      f"{_fmt(r['calmar'])} {_fmt(r['maxdd'], 1)} {_fmt(r['d_maxdd'], 1)}")

    if not a.skip_book:
        for w in a.which:
            if "error" in result["level1"].get(w, {}):
                continue
            l2 = level2(w, tmp)
            result["level2"][w] = l2
            print(f"\n=== {w} — Track 1 book, through the guard ===")
            print(f"    {'variant':22s} {'policy':28s} {'net':>10} {'d_net':>10} "
                  f"{'pf':>7} {'calmar':>7} {'maxdd':>10} {'calm/stress same'}")
            for r in l2["rows"]:
                print(f"    {r['variant']:22s} {r['policy'][:28]:28s} "
                      f"{_fmt(r['net'], 1)} {_fmt(r.get('d_net'), 1)} {_fmt(r['pf'])} "
                      f"{_fmt(r['calmar'])} {_fmt(r['maxdd'], 1)}   "
                      f"{r.get('calm_stress_untouched')}")

    Path(a.out).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(f"\n{a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
