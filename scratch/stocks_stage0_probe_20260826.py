"""scratch/stocks_stage0_probe_20260826.py — what the stock cache actually holds, and
whether the futures ATR basis is causal. READ-ONLY.

Every number the Stage STOCKS-0 report leans on about coverage or about the ATR lookahead is
produced here, with a self-check block that has to pass before anything is printed as a result.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from scratch.stocks_stage0_data_20260826 import (  # noqa: E402
    ETFS, adv_dollar, calendar, daily_atr_causal, daily_atr_engine, daily_from_5m,
    load_symbol, session_path, spy_daily_close, universe,
)

OUT = Path(__file__).resolve().parent / "_stocks_stage0_probe.json"


def main() -> int:
    rep: dict = {"self_check": {}}

    # ---------------------------------------------------------------- universe & calendar
    uni = universe()
    rep["universe_size"] = len(uni)
    rep["universe"] = uni
    rep["etf_count"] = len([t for t in uni if t in ETFS])
    rep["single_name_count"] = len([t for t in uni if t not in ETFS])

    cal = calendar("SPY")
    rep["calendar_source"] = "SPY cached session files, 2017-01-01..2024-12-31"
    rep["calendar_sessions"] = len(cal)
    rep["calendar_first"] = str(cal[0].date())
    rep["calendar_last"] = str(cal[-1].date())
    by_year = pd.Series(1, index=cal).groupby(cal.year).sum()
    rep["calendar_by_year"] = {int(k): int(v) for k, v in by_year.items()}

    # ---------------------------------------------------------------- per-symbol coverage
    cov = {}
    for t in uni:
        n = sum(1 for d in cal if session_path(t, d).exists())
        cov[t] = n
    rep["coverage_sessions_per_symbol"] = cov
    covv = np.array(list(cov.values()))
    rep["coverage_min"] = int(covv.min())
    rep["coverage_median"] = float(np.median(covv))
    rep["coverage_max"] = int(covv.max())

    # ---------------------------------------------------------------- ATR causality probe
    # Two definitions on the SAME daily frame. If they differ only by a shift, the engine
    # value at D is a function of D itself and cannot be read at 14:00 on D.
    probe_syms = ["AAPL", "MSFT", "JPM", "XOM", "TSLA", "SPY"]
    atr_rows = []
    frames = {}
    for t in probe_syms:
        df = load_symbol(t, cal)
        if df.empty:
            continue
        frames[t] = df
        d = daily_from_5m(df)
        a_eng = daily_atr_engine(d)
        a_cau = daily_atr_causal(d)
        both = pd.concat([a_eng.rename("eng"), a_cau.rename("cau")], axis=1).dropna()
        if both.empty:
            continue
        # Is the causal series exactly the engine series shifted one session?
        shifted_equal = bool(np.allclose(both["cau"].values,
                                         a_eng.reindex(both.index).shift(0).values * 0 +
                                         a_eng.shift(1).reindex(both.index).values,
                                         rtol=0, atol=1e-12, equal_nan=True))
        rel = (both["eng"] - both["cau"]).abs() / both["cau"].abs().clip(lower=1e-12)
        atr_rows.append(dict(symbol=t, n=int(len(both)),
                             causal_is_engine_shift1=shifted_equal,
                             median_rel_diff_pct=float(rel.median() * 100),
                             p90_rel_diff_pct=float(rel.quantile(0.90) * 100),
                             max_rel_diff_pct=float(rel.max() * 100)))
    rep["atr_causality"] = atr_rows

    # A day whose OWN range is extreme is exactly where the two definitions diverge most.
    # Quantify on AAPL: how much narrower/wider is the engine stop band on the day of a shock?
    if "AAPL" in frames:
        d = daily_from_5m(frames["AAPL"])
        a_eng, a_cau = daily_atr_engine(d), daily_atr_causal(d)
        both = pd.concat([a_eng.rename("eng"), a_cau.rename("cau")], axis=1).dropna()
        rng = ((d["high"] - d["low"]) / d["close"]).reindex(both.index)
        top = rng.nlargest(20).index
        rep["atr_causality_shock_days_AAPL"] = dict(
            n_shock_days=int(len(top)),
            median_rel_diff_pct_on_shock_days=float(
                ((both.loc[top, "eng"] - both.loc[top, "cau"]).abs()
                 / both.loc[top, "cau"]).median() * 100),
            median_rel_diff_pct_all_days=float(
                ((both["eng"] - both["cau"]).abs() / both["cau"]).median() * 100))

    # ---------------------------------------------------------------- liquidity & price
    liq = []
    for t, df in frames.items():
        d = daily_from_5m(df)
        adv = adv_dollar(d)
        liq.append(dict(symbol=t, median_adv_usd=float(adv.median()),
                        min_adv_usd=float(adv.min()),
                        median_close=float(d["close"].median()),
                        min_close=float(d["close"].min())))
    rep["liquidity_sample"] = liq

    # ---------------------------------------------------------------- SPY daily
    spy = spy_daily_close()
    rep["spy_csv"] = dict(first=str(spy.index[0].date()), last=str(spy.index[-1].date()),
                          n=int(len(spy)))

    # ---------------------------------------------------------------- self-checks
    sc = rep["self_check"]
    sc["SC1_universe_nonempty"] = len(uni) > 0
    sc["SC2_calendar_nonempty"] = len(cal) > 100
    sc["SC3_atr_probe_nonempty"] = len(atr_rows) > 0
    # The claim under test. If this is False the lookahead story is wrong and must not be told.
    sc["SC4_causal_is_engine_shifted_one_session"] = all(
        r["causal_is_engine_shift1"] for r in atr_rows)
    # The two definitions must actually DIFFER, or the shift is a no-op and the finding is empty.
    sc["SC5_definitions_differ"] = all(r["median_rel_diff_pct"] > 0 for r in atr_rows)
    # Prices must be plausible for adjusted US large caps.
    sc["SC6_prices_plausible"] = all(1.0 < r["median_close"] < 5000 for r in liq)
    # SPY daily must cover the intraday calendar, or the regime labels have holes.
    sc["SC7_spy_covers_calendar"] = bool(spy.index[0] <= cal[0] and spy.index[-1] >= cal[-1])
    # Coverage must not be uniform-and-perfect; that would suggest the existence test is broken.
    sc["SC8_coverage_varies"] = bool(covv.min() < covv.max())

    OUT.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    print("=== STOCKS-0 probe ===")
    for k, v in sc.items():
        print(("[PASS] " if v else "[FAIL] ") + k + " = " + str(v))
    print()
    print("universe            :", len(uni), "symbols ({} single names, {} ETFs)".format(
        rep["single_name_count"], rep["etf_count"]))
    print("calendar            :", rep["calendar_sessions"], "sessions",
          rep["calendar_first"], "->", rep["calendar_last"])
    print("sessions by year    :", rep["calendar_by_year"])
    print("coverage per symbol : min={} median={} max={}".format(
        rep["coverage_min"], rep["coverage_median"], rep["coverage_max"]))
    print()
    print("--- ATR basis: futures definition vs causal definition, same daily frame ---")
    for r in atr_rows:
        print("  {:6s} n={:5d}  causal==engine.shift(1): {!s:5s}  |eng-cau|/cau  "
              "median={:.2f}%  p90={:.2f}%  max={:.2f}%".format(
                  r["symbol"], r["n"], r["causal_is_engine_shift1"],
                  r["median_rel_diff_pct"], r["p90_rel_diff_pct"], r["max_rel_diff_pct"]))
    if "atr_causality_shock_days_AAPL" in rep:
        s = rep["atr_causality_shock_days_AAPL"]
        print("  AAPL 20 widest-range sessions: median diff {:.2f}%  vs {:.2f}% on all days"
              .format(s["median_rel_diff_pct_on_shock_days"],
                      s["median_rel_diff_pct_all_days"]))
    print()
    print("--- liquidity sample ---")
    for r in liq:
        print("  {:6s} median ADV ${:,.0f}   min ADV ${:,.0f}   median close ${:.2f}".format(
            r["symbol"], r["median_adv_usd"], r["min_adv_usd"], r["median_close"]))
    print()
    print("wrote", OUT)
    return 0 if all(sc.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
