"""scratch/stocks_stage0_causality_20260826.py — the no-lookahead proof. READ-ONLY.

A causality claim that cannot go red is not a proof. Every check here is a MUTATION: something
is corrupted, and the check states in advance which way the answer must move. A check that
passes because it corrupted nothing is a failure of the check, so each arm also asserts that
its sample is non-empty and that the corruption actually landed.

Four obligations, and what each one would look like if it were false
--------------------------------------------------------------------
P1  future bars cannot reach a signal.
    Multiply every bar STRICTLY AFTER the signal bar by 1.5 and rebuild everything the
    decision reads — the daily frame, the causal ATR, the context features, the engine's
    per-day cache. The admitted signal at that bar must be byte-identical. If it moves, some
    input is reading forward.

P1r the red arm for P1. Corrupt bars strictly BEFORE the signal bar instead. Across the
    sample, signals MUST move. If they do not, P1 proved nothing — it would mean the scan is
    insensitive to its own inputs and the green arm is vacuous.

P2  the full-day scan and the live-causal scan agree.
    Research scans 14:00-15:55 in one pass. A live slot at time T sees only 14:00..T. Truncate
    the window at the signal bar and rescan: the first admitted hit must be the same bar, the
    same direction, the same entry and the same stop. This is the same equivalence Track 1
    asserts for `detect_entry_for_slot`, re-run on equity bars.

P3  the regime label in force at 14:00 on D does not contain D.
    Scale SPY's close ON day D by ten and relabel. The label this route reads for D must not
    move (it is D-1's), and at least one label at a session AFTER D must move — otherwise the
    mutation did not land and the first half is vacuous.

P4  the SPY short gate is D-1.
    Same shape, on `short_days_from_csv`: D's own membership must not move; later days must.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from global_index import track1_normal_r4 as NR                      # noqa: E402
from global_index import track1_normal_filters as NF                 # noqa: E402
from scratch import stocks_stage0_data_20260826 as D                 # noqa: E402
from scratch import stocks_stage0_engine_20260826 as E               # noqa: E402
from scratch import stocks_stage0_regime_20260826 as R               # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "_stocks_stage0_causality.json"
WIN_START, WIN_END = "2019-01-02", "2022-12-30"


def _params(ema=50):
    return NR.NormalR4Params(ema_period=ema, stop_basis_atr_mult=2.0,
                             chandelier_atr_mult=2.5, max_hold_days=5, ratchet=False,
                             fill_law=NR.FILL_PRODUCTION)


def _scan_day(df, labels_obj, params, short_days, day, until=None):
    """The first admitted signal on `day`, using only `df`. Returns (bar_ts, entry, stop, dir).

    Built from the SAME production functions the backtest uses — `_cache_for`, `_strategy`,
    `make_signal_fn`, `_scan_window` — because a second implementation of the entry rule would
    prove something about itself and nothing about the rule under test.
    """
    daily = D.daily_from_5m(df)
    datr = D.daily_atr_causal(daily)
    cache = dict(NR._cache_for(df, params))
    cache["datr"] = datr
    b5 = cache["b5"].get(pd.Timestamp(day).normalize())
    if b5 is None or not len(b5):
        E.clear_engine_cache()
        return None
    regime = labels_obj.get(pd.Timestamp(day).normalize())
    if regime not in NR.ALLOWED_REGIMES:
        E.clear_engine_cache()
        return None
    try:
        da = float(datr.asof(pd.Timestamp(day).normalize()))
    except Exception:
        E.clear_engine_cache()
        return None
    if not np.isfinite(da) or da <= 0:
        E.clear_engine_cache()
        return None
    win = b5.between_time("14:00", "15:55")
    if until is not None:
        win = win[win.index <= pd.Timestamp(until)]
    if len(win) < 2:
        E.clear_engine_cache()
        return None
    strat = NR._strategy(params)
    sf = NR.make_signal_fn(strat, params, datr, short_days=short_days, context=None)
    hit = NR._scan_window(strat, b5, win, regime, sf, params.ema_period)
    E.clear_engine_cache()
    if hit is None:
        return None
    ts, sig = hit
    return (pd.Timestamp(ts), round(float(sig["entry_price"]), 6),
            round(float(sig["initial_stop"]), 6), str(sig["direction"]))


def _corrupt(df, ts, side, mult=1.5):
    d = df.copy()
    m = (d.index > ts) if side == "after" else (d.index < ts)
    for c in ("open", "high", "low", "close"):
        d.loc[m, c] = d.loc[m, c] * mult
    d.loc[m, "volume"] = d.loc[m, "volume"] * mult
    return d, int(m.sum())


def main() -> int:
    ap_syms = ["AAPL", "MSFT", "JPM", "XOM", "NVDA", "WMT"]
    n_per_symbol = 6
    params = _params()
    cal = pd.DatetimeIndex([d for d in D.calendar("SPY")
                            if pd.Timestamp(WIN_START) <= d <= pd.Timestamp(WIN_END)])
    lab = R.labels()
    labels_obj = R.LaggedLabels(lab["causal"], lag=1)
    short_days = NF.short_days_from_csv(str(D.SPY_CSV), params.spy_short_filter)

    rep: dict = {"p1_samples": [], "p1r_samples": [], "p2_samples": []}
    t0 = time.time()

    for sym in ap_syms:
        df = D.load_symbol(sym, cal)
        if df.empty:
            continue
        # Find real signal days on this symbol, cheaply, then sample across the window.
        daily = D.daily_from_5m(df)
        datr = D.daily_atr_causal(daily)
        cache = dict(NR._cache_for(df, params)); cache["datr"] = datr
        strat = NR._strategy(params)
        sf = NR.make_signal_fn(strat, params, datr, short_days=short_days, context=None)
        sigs = NR.scan_signals(strat, cache, labels_obj, params, sf)
        E.clear_engine_cache()
        days = sorted(sigs.keys())
        if not days:
            continue
        pick = [days[int(i)] for i in np.linspace(0, len(days) - 1, min(n_per_symbol,
                                                                       len(days)))]
        for day in pick:
            base = _scan_day(df, labels_obj, params, short_days, day)
            if base is None:
                continue
            bar_ts = base[0]

            # ---- P1: corrupt everything strictly AFTER the signal bar ----------------
            dfa, n_after = _corrupt(df, bar_ts, "after")
            got = _scan_day(dfa, labels_obj, params, short_days, day)
            rep["p1_samples"].append(dict(symbol=sym, day=str(day.date()),
                                          bar=str(bar_ts), bars_corrupted=n_after,
                                          unchanged=(got == base),
                                          base=[str(base[0]), base[1], base[2], base[3]],
                                          got=(None if got is None else
                                               [str(got[0]), got[1], got[2], got[3]])))

            # ---- P1r: the red arm — corrupt strictly BEFORE ---------------------------
            dfb, n_before = _corrupt(df, bar_ts, "before")
            gotb = _scan_day(dfb, labels_obj, params, short_days, day)
            rep["p1r_samples"].append(dict(symbol=sym, day=str(day.date()),
                                           bars_corrupted=n_before,
                                           changed=(gotb != base)))

            # ---- P2: full-day scan vs truncated-at-the-signal-bar scan -----------------
            trunc = _scan_day(df, labels_obj, params, short_days, day, until=bar_ts)
            rep["p2_samples"].append(dict(symbol=sym, day=str(day.date()),
                                          identical=(trunc == base)))

    # ---- P3: the regime label at D does not contain D ------------------------------
    spy = D.spy_daily_close()
    probe_day = pd.Timestamp("2021-06-15")
    from futures._validated_core import label_regimes
    base_lab = pd.Series(label_regimes(spy, "2018-12-31", 3, "2018-12-31"))
    base_lab.index = pd.DatetimeIndex(base_lab.index).normalize()
    spy_m = spy.copy()
    spy_m.loc[probe_day] = spy_m.loc[probe_day] * 10.0
    mut_lab = pd.Series(label_regimes(spy_m, "2018-12-31", 3, "2018-12-31"))
    mut_lab.index = pd.DatetimeIndex(mut_lab.index).normalize()
    lo = R.LaggedLabels(base_lab, lag=1)
    lm = R.LaggedLabels(mut_lab, lag=1)
    after = base_lab.index[(base_lab.index > probe_day)][:40]
    rep["p3"] = dict(
        probe_day=str(probe_day.date()),
        label_read_at_probe_day_unchanged=(lo.get(probe_day) == lm.get(probe_day)),
        label_at_probe_day_lag1=lo.get(probe_day),
        n_later_sessions_checked=int(len(after)),
        n_later_labels_moved=int(sum(1 for d in after
                                     if base_lab.get(d) != mut_lab.get(d))))

    # ---- P4: the SPY short gate is D-1 ----------------------------------------------
    import tempfile
    base_days = NF.short_days_from_csv(str(D.SPY_CSV), "below_sma50")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "spy_mut.csv"
        s = spy.copy()
        s.loc[probe_day] = s.loc[probe_day] * 10.0
        pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"),
                      "close": s.values}).to_csv(p, index=False)
        mut_days = NF.short_days_from_csv(str(p), "below_sma50")
    later = [d for d in spy.index if probe_day < d <= probe_day + pd.Timedelta(days=90)]
    rep["p4"] = dict(
        probe_day_membership_unchanged=((probe_day in base_days) == (probe_day in mut_days)),
        n_later_sessions_checked=int(len(later)),
        n_later_memberships_moved=int(sum(1 for d in later
                                          if (d in base_days) != (d in mut_days))))

    # ---- self-checks: each arm must be non-empty AND must have bitten ----------------
    p1 = rep["p1_samples"]; p1r = rep["p1r_samples"]; p2 = rep["p2_samples"]
    sc = {
        "SC1_p1_sample_nonempty": len(p1) >= 10,
        "SC2_p1_corruption_landed": all(x["bars_corrupted"] > 0 for x in p1),
        "SC3_p1_all_unchanged": all(x["unchanged"] for x in p1),
        "SC4_p1r_sample_nonempty": len(p1r) >= 10,
        "SC5_p1r_majority_changed": (sum(x["changed"] for x in p1r) / max(len(p1r), 1)) > 0.5,
        "SC6_p2_sample_nonempty": len(p2) >= 10,
        "SC7_p2_all_identical": all(x["identical"] for x in p2),
        "SC8_p3_probe_label_unchanged": rep["p3"]["label_read_at_probe_day_unchanged"],
        "SC9_p3_later_labels_moved": rep["p3"]["n_later_labels_moved"] > 0,
        "SC10_p4_probe_membership_unchanged": rep["p4"]["probe_day_membership_unchanged"],
        "SC11_p4_later_memberships_moved": rep["p4"]["n_later_memberships_moved"] > 0,
    }
    rep["self_check"] = sc
    rep["summary"] = dict(
        p1_n=len(p1), p1_unchanged=int(sum(x["unchanged"] for x in p1)),
        p1r_n=len(p1r), p1r_changed=int(sum(x["changed"] for x in p1r)),
        p2_n=len(p2), p2_identical=int(sum(x["identical"] for x in p2)),
        seconds=round(time.time() - t0, 1))
    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    print("=== STOCKS-0 causality proof ===")
    for k, v in sc.items():
        print(("[PASS] " if v else "[FAIL] ") + k + " = " + str(v))
    print()
    s = rep["summary"]
    print("P1  future bars corrupted, signal unchanged : {}/{}".format(s["p1_unchanged"],
                                                                       s["p1_n"]))
    print("P1r past bars corrupted, signal MOVED       : {}/{}   (red arm)".format(
        s["p1r_changed"], s["p1r_n"]))
    print("P2  truncated scan == full-day scan         : {}/{}".format(s["p2_identical"],
                                                                        s["p2_n"]))
    print("P3  SPY close on D scaled x10 -> label read at D unchanged={}, "
          "later labels moved={}/{}".format(rep["p3"]["label_read_at_probe_day_unchanged"],
                                            rep["p3"]["n_later_labels_moved"],
                                            rep["p3"]["n_later_sessions_checked"]))
    print("P4  short-gate membership at D unchanged={}, later moved={}/{}".format(
        rep["p4"]["probe_day_membership_unchanged"],
        rep["p4"]["n_later_memberships_moved"], rep["p4"]["n_later_sessions_checked"]))
    print("\nwrote", OUT, "({:.0f}s)".format(s["seconds"]))
    return 0 if all(sc.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
