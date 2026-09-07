"""Stage 5ZZZ-H — regenerate the Normal/R4 promotion artifacts with a causal D-1 swing label.

ONE thing changes: the labels object handed to the swing basket's backtest. NKD keeps its own
`RegimeLabels(lag_days=1)` (it never goes through `SwingTFEngine.backtest_basket`), Stress and
Calm are untouched, and every other input - data dir, HMM fit end per window, costs, slippage,
contracts, caps, fill law - comes from the window's own recorded argv.

The regen writes to the SHARED baseline filenames, which the handoff doc warns about. So the
baselines are copied out first and restored in a `finally`, and their sha256 is checked
afterwards: if a baseline moved, this script says so rather than leaving a silently rewritten
history behind.

Usage:
    python scratch/track1_stage5zzzh_swing_d1_regen_20260829.py --which vault2026
    python scratch/track1_stage5zzzh_swing_d1_regen_20260829.py --which floor vault2025 vault2026
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

BASE = {w: Path(f"scratch/normal_promotion_trades_{w}_20260821.json")
        for w in ("floor", "vault2025", "vault2026")}
D1 = {w: Path(f"scratch/normal_promotion_trades_{w}_d1_20260829.json")
      for w in ("floor", "vault2025", "vault2026")}
SIDE = [Path("scratch/normal_promotion_regen_audit_20260821.txt"),
        Path("scratch/normal_promotion_regen_audit_20260821.json")]
BACKUP = Path("scratch/_5zzzh_baseline_backup")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "MISSING"


#: Stage 5ZZZ-M. The substitution the regeneration actually performs, stated here so a caller
#: can know what it will get instead of discovering it from a hash.
#:
#: `scratch/harness.py:315` reads:
#:
#:      if cfg.ema is not None and ema_period == 30:
#:          ema_period = cfg.ema
#:
#: and the regeneration builds `Cfg(..., ema=50, stop_basis=2.0)`. So a request for the Rổ 4
#: value 30 is rewritten to Track 1's own 50 - deliberately, because `NormalR4Params.ema_period`
#: IS 50 - while 10, 20 and 50 pass through untouched. Stage 5ZZZ-L spent a stage discovering
#: this from byte-identical artifacts; nothing recorded it.
HARNESS_CFG_EMA = 50
HARNESS_CFG_STOP_BASIS = 2.0
HARNESS_CFG_RATCHET = False


def effective_params(ema, mult, hold=5) -> dict:
    """What the engine will RUN, given what a caller asked for."""
    asked_ema = 30 if ema is None else int(ema)
    used_ema = HARNESS_CFG_EMA if asked_ema == 30 else asked_ema
    asked_mult = 2.5 if mult is None else float(mult)
    return {
        "asked_ema_period": asked_ema, "effective_ema_period": used_ema,
        "ema_was_substituted": used_ema != asked_ema,
        "asked_chandelier_atr_mult": asked_mult,
        # With ratchet=False and a stop_basis set, the day loop never recomputes the stop, so
        # the chandelier multiple only reaches the strategy config and changes no decision.
        # Documented in NormalR4Params' own docstring; measured here as identical artifacts for
        # mult 2.0 and 2.5 at the same ema.
        "chandelier_affects_decisions": False,
        "effective_stop_basis_atr_mult": HARNESS_CFG_STOP_BASIS,
        "ratchet": HARNESS_CFG_RATCHET,
        "max_hold_days": int(hold),
    }


def install_d1_swing_labels(ema: int | None = None, mult: float | None = None,
                            proxy_labels: dict | None = None):
    """Wrap the swing basket's labels in a one-day lag, and nothing else.

    The seam is `SwingTFEngine.backtest_basket`, which is the R4 basket's entry and ONLY that:
    NKD is run through `backtest_swing_tf` directly with its own already-lagged object, and
    Stress is disabled in this regen. Patched on the original class before the regen captures
    it, so the regen's own wrapper delegates straight into this.
    """
    import pandas as pd
    from futures import swing_tf as ST
    from global_index.regime import RegimeLabels

    original = ST.SwingTFEngine.backtest_basket
    orig_backtest = ST.SwingTFEngine.backtest
    seen = {"calls": 0, "engine_params": set()}

    # Stage 5ZZZ-L. The parameter override moved here, onto `SwingTFEngine.backtest` - the
    # method that actually READS the params and calls the engine.
    #
    # Setting them as attributes on the instance inside `backtest_basket` looked equivalent and
    # was not: the ema=50/mult=2.0 run produced artifacts BYTE-IDENTICAL to the default run,
    # which is impossible if the parameter had reached the engine. Caught because identical
    # hashes across a parameter change is not a result, it is a broken instrument. Forcing the
    # values at the call site removes the indirection entirely, and `seen["engine_params"]`
    # records what was actually passed so the run can prove it rather than assume it.
    def forced_backtest(self, df, labels, cost, **kw):
        # `backtest` takes no parameter kwargs - it READS them off `self` - so they are set
        # here, immediately before the read, and recorded so the run can prove what the engine
        # was handed instead of assuming it.
        if ema is not None:
            self.ema_period = int(ema)
        if mult is not None:
            self.chandelier_atr_mult = float(mult)
        seen["engine_params"].add((self.ema_period, self.chandelier_atr_mult,
                                   self.max_hold_days))
        return orig_backtest(self, df, labels, cost, **kw)

    def d1_backtest_basket(self, dfs, labels, costs, **kw):
        seen["calls"] += 1
        # Stage 5ZZZ-I. The retuned parameters, when the caller supplies them. Set on the
        # instance the regen just built rather than on the class, so nothing outside this run
        # sees them - and only for the swing basket, which is the only thing this seam reaches.
        if isinstance(labels, RegimeLabels):
            raise SystemExit("the swing basket was already handed a lagged object; "
                             "the premise of this run has changed - stop and re-read")
        # Stage 5ZZZ-J. The causal pre-14:00 proxy REPLACES the label map rather than lagging
        # it. `labels.get(D)` then returns the proxy's prediction for D, which was made from
        # information closed at 14:00 on D - so a same-day lookup that is nonetheless causal.
        # Days the proxy never predicted (its warm-up) are simply absent, and the sleeve
        # refuses on them, which is the honest consequence of partial coverage.
        if proxy_labels is not None:
            return original(self, dfs, dict(proxy_labels), costs, **kw)
        ser = pd.Series(labels)
        idx = pd.DatetimeIndex(ser.index)
        ser.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
        lagged = RegimeLabels(ser.sort_index(), lag_days=1)
        # Stage 5ZZZ-N. Proof of the regime basis, recorded from the object actually handed to
        # the engine rather than from a comment about it: its type, its lag, and one resolved
        # lookup showing the value comes from the PREVIOUS session.
        _probe_day = ser.index.max()
        seen.setdefault("regime_basis", set()).add(
            (type(lagged).__name__, int(lagged.lag),
             str(_probe_day.date()), str(ser.loc[_probe_day]),
             str(lagged.get(_probe_day))))
        return original(self, dfs, lagged, costs, **kw)

    ST.SwingTFEngine.backtest_basket = d1_backtest_basket
    if ema is not None or mult is not None:
        ST.SwingTFEngine.backtest = forced_backtest
    return (original, orig_backtest), seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["vault2026"])
    ap.add_argument("--ema", type=int, default=None, help="override the swing ema period")
    ap.add_argument("--mult", type=float, default=None, help="override the chandelier multiple")
    ap.add_argument("--suffix", default="d1", help="artifact suffix, e.g. d1 or d1r")
    ap.add_argument("--proxy-labels", default=None,
                    help="JSON {YYYY-MM-DD: label}; replaces the swing label map entirely")
    a = ap.parse_args()
    for w in D1:
        D1[w] = Path(f"scratch/normal_promotion_trades_{w}_{a.suffix}_20260829.json")

    BACKUP.mkdir(parents=True, exist_ok=True)
    before = {w: sha(BASE[w]) for w in BASE}
    for w, p in BASE.items():
        if p.exists():
            shutil.copy2(p, BACKUP / p.name)
    for p in SIDE:
        if p.exists():
            shutil.copy2(p, BACKUP / p.name)
    print("baseline artifacts backed up:")
    for w in sorted(before):
        print(f"    {before[w][:16]}  {BASE[w].name}")

    from futures import swing_tf as ST
    _proxy = None
    if a.proxy_labels:
        import pandas as _pd
        _raw = json.loads(Path(a.proxy_labels).read_text(encoding="utf-8"))
        _proxy = {_pd.Timestamp(k).normalize(): v for k, v in _raw.items()}
        print(f"proxy labels: {len(_proxy):,} sessions "
              f"{min(_raw)} .. {max(_raw)} (days outside this range get NO label)")
    original, seen = install_d1_swing_labels(ema=a.ema, mult=a.mult, proxy_labels=_proxy)
    if a.ema is not None or a.mult is not None:
        print(f"swing params overridden: ema={a.ema} mult={a.mult}")
    t0 = time.perf_counter()
    try:
        import scratch.normal_promotion_regen_audit_20260821 as regen

        old_argv = sys.argv
        sys.argv = ["regen", "--which"] + list(a.which)
        try:
            regen.main()
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
        finally:
            sys.argv = old_argv

        # the regen has just written D-1 tables over the baseline filenames; move them aside
        for w in a.which:
            if BASE[w].exists():
                shutil.copy2(BASE[w], D1[w])
                print(f"  D-1 artifact written: {D1[w]}  {sha(D1[w])[:16]}")
                # Stage 5ZZZ-L. A parameter override that changes nothing is not a result, it
                # is a broken instrument - and it happened: an ema=50/mult=2.0 run once
                # produced artifacts byte-identical to the default run. If a param was asked
                # for, the artifact MUST differ from the unoverridden D-1 one.
                # Stage 5ZZZ-M. A sidecar, not a change to the artifact: the promotion
                # artifacts are hash-pinned baselines and adding a key would break every
                # reproduction that depends on them. The sidecar records what the engine WILL
                # have run, so a reader never again has to infer it from a digest.
                eff = effective_params(a.ema, a.mult)
                side = D1[w].with_suffix(".params.json")
                side.write_text(json.dumps(
                    {"artifact": D1[w].name, "artifact_sha256": sha(D1[w]),
                     "window": w, "labels": "RegimeLabels(lag_days=1) causal D-1",
                     "proxy_labels": bool(a.proxy_labels), **eff}, indent=1),
                    encoding="utf-8")
                print(f"    effective: ema {eff['asked_ema_period']} -> "
                      f"{eff['effective_ema_period']}"
                      f"{'  (SUBSTITUTED)' if eff['ema_was_substituted'] else ''}"
                      f", chandelier affects decisions: "
                      f"{eff['chandelier_affects_decisions']}")

                # The guard, corrected. Stage 5ZZZ-L's version compared HASHES and fired on a
                # true equivalence: ema=50 and the default really do produce the same artifact,
                # because the default IS 50 after substitution. What must actually hold is that
                # two runs with different EFFECTIVE parameters produce different artifacts.
                ref = Path(f"scratch/normal_promotion_trades_{w}_d1_20260829.json")
                ref_side = ref.with_suffix(".params.json")
                if ref.exists() and ref_side.exists() and ref != D1[w]:
                    other = json.loads(ref_side.read_text(encoding="utf-8"))
                    same_effective = (other.get("effective_ema_period")
                                      == eff["effective_ema_period"])
                    same_bytes = sha(ref) == sha(D1[w])
                    if same_effective != same_bytes:
                        raise SystemExit(
                            f"{w}: effective ema "
                            f"{other.get('effective_ema_period')} vs "
                            f"{eff['effective_ema_period']} but artifacts "
                            f"{'match' if same_bytes else 'differ'} - the engine is not "
                            f"obeying the parameter it recorded")
    finally:
        ST.SwingTFEngine.backtest_basket = original[0]
        ST.SwingTFEngine.backtest = original[1]
        for rb in sorted(seen.get("regime_basis") or []):
            print(f"regime basis: {rb[0]}(lag_days={rb[1]}) - on {rb[2]} the same-day label is "
                  f"{rb[3]!r} and the object returned {rb[4]!r}")
        if seen.get("engine_params"):
            print(f"engine actually received (ema, mult, hold): "
                  f"{sorted(seen['engine_params'])}")
        for name in [p.name for p in BASE.values()] + [p.name for p in SIDE]:
            src = BACKUP / name
            if src.exists():
                shutil.copy2(src, Path("scratch") / name)
        after = {w: sha(BASE[w]) for w in BASE}
        bad = [w for w in BASE if before[w] != after[w]]
        print(f"\nswing basket calls intercepted: {seen['calls']}")
        print("baselines restored byte-identical:", "YES" if not bad else f"NO - {bad}")
        print(f"elapsed: {time.perf_counter() - t0:,.1f}s")
        if bad:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
