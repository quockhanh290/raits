"""Regenerate Calm-NKD on the SAME basis as the current NKD sleeve. SCRATCH-ONLY.

The Calm-NKD challenger and the current NKD sleeve differ in FOUR ways, not one:

  1. price file      continuous            vs  the frozen file named in each artifact
  2. stop mechanism  2.5x 5-minute-ATR ratcheting chandelier, live from the session
                     boundary, vs a FIXED stop at entry -+ 2.0 x daily ATR armed at
                     14:00 Tokyo the next session
  3. ema             5                     vs  10
  4. regime gate     D-1 Calm only         vs  all allowed regimes at lag 1

Only (4) is the hypothesis under test. This script puts (1), (2) and (3) back onto
the current sleeve's basis so the Calm gate is the single variable.

ANCHOR GATE. Before any challenger number is read, the same harness is run with the
CURRENT sleeve's regime labels and must reproduce the MNKD trade list already sitting
in the promotion artifact - trade count, net, and every entry/exit price. If it cannot
reproduce a book somebody else already published, it is not on that basis and nothing
downstream is reported.

Also measured, because it decides how big the remaining search is:
  does `chandelier_atr_mult` do ANYTHING once the stop comes from stop_basis and the
  ratchet is off? If it does not, the 6-variant (ema x mult) sweep collapses to ema
  alone and three of the six variants are the same run.

  python scratch/calm_nkd_regen_same_basis_20260822.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from futures._validated_core import benchmark_daily, daily_atr_series, label_regimes
from global_index._core import load_parquet as gi_load
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels
from scratch.harness import ARM_LIVE, Cfg, patched_engine


def force_all_bars_gappable():
    """The artifacts were generated with this ON (normal_promotion_regen_audit_20260821.py:78).
    It marks EVERY bar gap-eligible, so a stop the market opened beyond fills at that bar's
    open rather than at the stop - the conservative fill law. Production's engine only does
    this when a real >15-minute time break precedes the bar. Without it the regenerated book
    is not the artifact's book, which is what the anchor gate caught."""
    import numpy as _np
    import futures._validated_core as VC
    orig = VC._swing_cache

    def patched(df, datr=None):
        c = orig(df, datr)
        if not c.get("_all_gap"):
            for day, (high, low, opn, isg) in list(c["hl"].items()):
                c["hl"][day] = (high, low, opn, _np.ones(len(isg), dtype=bool))
            c["_all_gap"] = True
        return c

    VC._swing_cache = patched
    return orig

OUT = Path("scratch/calm_nkd_regen_same_basis_20260822.json")
REPORT = Path("scratch/calm_nkd_regen_same_basis_20260822_report.md")
ARTIFACTS = {
    "floor": Path("scratch/normal_promotion_trades_floor_20260821.json"),
    "vault2025": Path("scratch/normal_promotion_trades_vault2025_20260821.json"),
    "vault2026": Path("scratch/normal_promotion_trades_vault2026_20260821.json"),
}
CUR_EMA, CUR_MULT = 10, 2.5          # deploy_sim defaults, never overridden in any window argv
STOP_BASIS = 2.0
EMAS = [5, 10, 15, 20]
MULTS = [2.0, 2.5, 3.0]


class D1CalmOnly:
    """Expose only D-1 Calm days, presented as 'Normal' so the swing signal fires.
    Same construction as the original probe, but wrapping RegimeLabels(lag_days=1)
    so the Calm gate rides on the SAME lag the current sleeve uses."""

    def __init__(self, spy: pd.Series):
        self.base = RegimeLabels(spy, lag_days=1)

    def get(self, day, default=None):
        return "Normal" if self.base.get(day, default=None) == "Calm" else default


def arg_of(argv, flag, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def window_inputs(which: str):
    raw = json.loads(ARTIFACTS[which].read_text(encoding="utf-8"))
    argv = raw["argv"]
    inst = raw["nkd_instrument"]
    c = gi_specs.SPECS[inst]
    df = gi_load(arg_of(argv, "--nkd-parquet"))
    df.index = df.index.tz_convert(c.session_tz)
    start, end = arg_of(argv, "--start"), arg_of(argv, "--end")
    if start:
        df = df[df.index >= pd.Timestamp(start).tz_localize(df.index.tz)]
    if end:
        df = df[df.index <= pd.Timestamp(end).tz_localize(df.index.tz)]
    spy = pd.Series(label_regimes(benchmark_daily(arg_of(argv, "--regime-csv")),
                                  "2018-01-01", 3, arg_of(argv, "--hmm-fit-end")))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    spy = spy.sort_index()
    slip = float(arg_of(argv, "--slippage-ticks", 2.0))
    from global_index._core import FuturesCost as GIFC
    cost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                slippage_ticks_per_side=slip)
    return raw, df, spy, cost, c, inst


def install_artifact_gates(spy_csv: str):
    """The artifact generator applies these GLOBALLY, so the NKD sleeve inherited them
    even though they read as Ro-4 concerns (normal_promotion_regen_audit_20260821.py:175-176):
      - allowed_regimes forced to ["Normal"]
      - SHORT only on days where SPY D-1 close is below its 50-day average
    The R4 context filter did NOT reach NKD (it is keyed on the R4 frames), which is why
    the artifact's raw and filtered NKD books are identical."""
    import raits.strategies.trend_follow as tf
    from scratch.directional_market_filter_probe import allowed_short_days, feature_frame
    short_days = allowed_short_days(feature_frame(spy_csv), "below_sma50")
    base = tf.TrendFollowStrategy.generate_signal

    def gated(self, *a, **kw):
        sig = base(self, *a, **kw)
        if not sig or sig.get("direction") != "SHORT":
            return sig
        ts = pd.Timestamp(a[1].name)
        day = (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
        return sig if day in short_days else None

    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
    tf.TrendFollowStrategy.generate_signal = gated


def run_engine(df, labels, cost, ema, mult):
    """Current-sleeve basis: fixed stop at entry -+ 2.0 x daily ATR, armed 14:00 next
    session in the frame's own timezone, no ratchet, gap-through fill on."""
    cfg = Cfg(fix_fill=False, arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              stop_basis=STOP_BASIS)
    _orig, fn = patched_engine(cfg, {"n": 0, "tot": 0.0})
    return fn(df, labels, cost, ema_period=ema, chandelier_atr_mult=mult, max_hold_days=5)


def trades_fingerprint(trades):
    return [(str(t["day"]), str(t["exit_day"]), t["direction"],
             round(float(t["entry"]), 2), round(float(t["exit"]), 2),
             round(float(t["pnl"]), 2), t["reason"]) for t in trades]


def stats(trades, atr, pv):
    if not trades:
        return dict(n=0, net=0.0)
    p = np.array([float(t["pnl"]) for t in trades])
    reasons = {}
    for t in trades:
        reasons[t["reason"]] = reasons.get(t["reason"], 0) + 1
    stop_ex = [t for t in trades if t["reason"] in ("CHANDELIER", "GAP")]
    dists, ratios, risks = [], [], []
    for t in trades:
        d0 = pd.Timestamp(t["day"])
        d0 = d0.tz_localize(None) if d0.tzinfo is not None else d0
        a = atr.asof(d0.normalize())
        if a is None or pd.isna(a) or float(a) <= 0:
            continue
        risks.append(STOP_BASIS * float(a) * pv)
        if t["reason"] == "CHANDELIER":
            dd = abs(float(t["entry"]) - float(t["exit"]))
            dists.append(dd)
            ratios.append(dd / float(a))
    tick_val = 5.0 * pv          # MNKD tick 5.0 index points
    return dict(
        n=len(trades), net=float(p.sum()),
        pf=float(p[p > 0].sum() / -p[p < 0].sum()) if (p < 0).any() else float("inf"),
        win_rate=float((p > 0).mean()),
        med_win=float(np.median(p[p > 0])) if (p > 0).any() else 0.0,
        med_loss=float(np.median(p[p < 0])) if (p < 0).any() else 0.0,
        max_loss=float(p.min()), reasons=reasons,
        stop_exit_rate=float(len(stop_ex) / len(trades)),
        med_stop_dist_pts=float(np.median(dists)) if dists else None,
        med_stop_x_datr=float(np.median(ratios)) if ratios else None,
        stop_x_datr_p10=float(np.percentile(ratios, 10)) if ratios else None,
        stop_x_datr_p90=float(np.percentile(ratios, 90)) if ratios else None,
        med_declared_risk=float(np.median(risks)) if risks else None,
        net_plus1tick=float(p.sum() - len(stop_ex) * tick_val),
        net_plus3tick=float(p.sum() - 3 * len(stop_ex) * tick_val),
    )


def main() -> int:
    force_all_bars_gappable()
    install_artifact_gates("spy_daily_live.csv")
    out = {}
    for which in ARTIFACTS:
        print(f"[run] {which}", flush=True)
        raw, df, spy, cost, c, inst = window_inputs(which)
        atr = daily_atr_series(df)
        pv = c.point_value

        # ---------------- anchor: reproduce the artifact's current-NKD book -------
        control = run_engine(df, RegimeLabels(spy, lag_days=1), cost, CUR_EMA, CUR_MULT)
        artifact = raw["filtered"][inst]
        got, want = trades_fingerprint(control), trades_fingerprint(artifact)
        anchor = dict(
            artifact_trades=len(want), regenerated_trades=len(got),
            exact_match=bool(got == want),
            artifact_net=round(sum(float(t["pnl"]) for t in artifact), 2),
            regenerated_net=round(sum(float(t["pnl"]) for t in control), 2),
            n_differing=int(sum(1 for a, b in zip(got, want) if a != b)),
            first_diff=[[list(a), list(b)] for a, b in zip(got, want) if a != b][:2],
        )
        print(f"  anchor: artifact {anchor['artifact_trades']} trades / "
              f"${anchor['artifact_net']:,.2f} | regen {anchor['regenerated_trades']} / "
              f"${anchor['regenerated_net']:,.2f} | exact={anchor['exact_match']}", flush=True)

        # ---------------- is chandelier_atr_mult inert on this basis? -------------
        calm_labels = D1CalmOnly(spy)
        mult_probe = {}
        base_fp = None
        for m in MULTS:
            t = run_engine(df, calm_labels, cost, CUR_EMA, m)
            fp = trades_fingerprint(t)
            if base_fp is None:
                base_fp = fp
            mult_probe[str(m)] = dict(n=len(t), net=round(sum(float(x["pnl"]) for x in t), 2),
                                      identical_to_mult2p0=bool(fp == base_fp))
        mult_inert = all(v["identical_to_mult2p0"] for v in mult_probe.values())
        print(f"  mult inert on this basis: {mult_inert}  {mult_probe}", flush=True)

        # ---------------- the ema line, on the repaired basis ---------------------
        sweep = {}
        for e in EMAS:
            t = run_engine(df, calm_labels, cost, e, CUR_MULT)
            sweep[str(e)] = stats(t, atr, pv)
            s = sweep[str(e)]
            print(f"  ema={e:>2} n={s['n']:>4} net=${s['net']:>9,.0f} pf={s.get('pf', 0):>5.2f} "
                  f"wr={100*s.get('win_rate', 0):>5.1f}% stopRate={100*s.get('stop_exit_rate', 0):>5.1f}% "
                  f"stopDist={s.get('med_stop_dist_pts')} x_dATR={s.get('med_stop_x_datr')}",
                  flush=True)

        # current sleeve for contrast, same basis, same file
        out[which] = dict(anchor=anchor, mult_probe=mult_probe, mult_inert=bool(mult_inert),
                          ema_sweep=sweep,
                          current_sleeve=stats(control, atr, pv))
    OUT.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT)
    bad = [w for w, d in out.items() if not d["anchor"]["exact_match"]]
    if bad:
        print("ANCHOR FAILED for:", bad, "- challenger numbers above are NOT on the current basis")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
