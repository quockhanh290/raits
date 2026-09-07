"""Stage 5ZZZ-K — can ES intraday, closed at 14:00 ET, recover the same-day SPY-HMM label?

A label-recovery test. No trading, no backtest, no promotion.

The bar is not "is it informative". It is "does it beat carrying yesterday's label forward",
because D-1 is already available, already causal, and already measured at 91.6% in Stage 5ZZZ-J.
A proxy that cannot beat persistence has nothing to add and no backtest is needed to say so.

Timezone: the ES parquet index is NAIVE UTC. Measured, not assumed - localising UTC puts 80.3%
of volume inside 09:30-16:00 ET with the peak in the closing hour; localising ET puts 42.6% there
and the peak overnight. This repo has already paid for two loaders disagreeing about a clock.

Walk-forward: refit every 126 sessions on everything strictly before. Labels follow the route's
own convention - the floor window is labelled by the HMM fit through 2022-12-31, and 2025/2026 by
the fit through 2024-12-31 - so no later fit leaks backwards into an earlier window.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd

ET = "America/New_York"
ES_PATH = "data/cache/futures/ES_continuous_1m_8y.parquet"
RTH_OPEN = pd.Timestamp("09:30").time()
RTH_CLOSE = pd.Timestamp("16:00").time()
CUT = pd.Timestamp("14:00").time()
OVERNIGHT_START = pd.Timestamp("18:00").time()

HMM_TRAIN_END = "2018-01-01"
WINDOWS = [("floor", "2018-01-01", "2024-12-31", "2022-12-31"),
           ("vault2025", "2025-01-01", "2025-12-31", "2024-12-31"),
           ("vault2026", "2026-01-01", "2026-08-19", "2024-12-31")]


def load_es() -> pd.DataFrame:
    df = pd.read_parquet(ES_PATH)
    idx = df.index
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df = df.copy()
    df.index = idx.tz_convert(ET)
    return df.sort_index()


def features(es: pd.DataFrame) -> pd.DataFrame:
    """One row per RTH session, from bars closed by 14:00 ET plus strictly-prior sessions."""
    rth = es[(es.index.time >= RTH_OPEN) & (es.index.time < RTH_CLOSE)]
    day = rth.index.normalize()
    prev_close = rth.groupby(day)["close"].last().shift(1)

    upto = rth[rth.index.time <= CUT]
    g = upto.groupby(upto.index.normalize())
    op, px = g["open"].first(), g["close"].last()
    hi, lo = g["high"].max(), g["low"].min()
    vol = g["volume"].sum()

    def rv(x):
        c = x["close"].to_numpy(dtype=float)
        if len(c) < 3:
            return 0.0
        r = np.diff(np.log(c))
        return float(np.std(r) * np.sqrt(390 * 252))

    rvol = g.apply(rv)

    # ES-only: the overnight session, 18:00 the evening before through the 09:30 open.
    # SPY cannot see this at all, and it is closed before the RTH open.
    on = es[(es.index.time >= OVERNIGHT_START) | (es.index.time < RTH_OPEN)]
    # The session an overnight bar BELONGS to: bars before 09:30 belong to that date, bars from
    # 18:00 onward belong to the NEXT date. Grouped on a tz-aware ET key, because grouping on
    # `.values` strips the tz and every later reindex against a tz-aware index then yields NaN,
    # which the final dropna turns into an empty frame. The first run of this probe reported
    # zero usable sessions for exactly that reason - a result too empty to be a finding.
    on_key = on.index.normalize().where(
        pd.Index(on.index.time) < RTH_OPEN, on.index.normalize() + pd.Timedelta(days=1))
    on_hi = on.groupby(on_key)["high"].max()
    on_lo = on.groupby(on_key)["low"].min()

    f = pd.DataFrame({"prev_close": prev_close.reindex(px.index), "open": op, "px": px,
                      "hi": hi, "lo": lo, "vol": vol, "rvol_1400": rvol}).dropna(
        subset=["prev_close"])
    f["on_hi"] = on_hi.reindex(f.index)
    f["on_lo"] = on_lo.reindex(f.index)
    assert f["on_hi"].notna().sum() > 0.5 * len(f), (
        "the overnight join produced almost nothing; the session keys do not line up")

    f["gap"] = f["open"] / f["prev_close"] - 1.0
    f["ret_to_1400"] = f["px"] / f["prev_close"] - 1.0
    f["ret_open_to_1400"] = f["px"] / f["open"] - 1.0
    f["range_to_1400"] = (f["hi"] - f["lo"]) / f["prev_close"]
    f["overnight_range"] = (f["on_hi"] - f["on_lo"]) / f["prev_close"]
    f["vol_ratio"] = f["vol"] / f["vol"].rolling(20).median().shift(1)
    f["rvol_5d_prior"] = f["rvol_1400"].rolling(5).mean().shift(1)
    f["absret_5d_prior"] = f["ret_to_1400"].abs().rolling(5).mean().shift(1)

    cols = ["gap", "ret_to_1400", "ret_open_to_1400", "range_to_1400", "overnight_range",
            "rvol_1400", "vol_ratio", "rvol_5d_prior", "absret_5d_prior"]
    out = f[cols].replace([np.inf, -np.inf], np.nan).dropna()
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).normalize()
    return out


def labels_for(fit_end: str, upto: str) -> pd.Series:
    from futures._validated_core import benchmark_daily, label_regimes

    bench = benchmark_daily("spy_daily_live.csv")
    bench = bench[bench.index <= pd.Timestamp(upto)]
    s = pd.Series(label_regimes(bench, HMM_TRAIN_END, 3, fit_end))
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return s.sort_index()


def composite_labels() -> pd.Series:
    """The route's own convention: each window labelled by the fit its argv names."""
    floor = labels_for("2022-12-31", "2024-12-31")
    late = labels_for("2024-12-31", "2026-08-19")
    parts = []
    for name, lo, hi, _fit in WINDOWS:
        src = floor if name == "floor" else late
        m = (src.index >= pd.Timestamp(lo)) & (src.index <= pd.Timestamp(hi))
        parts.append(src[m])
    return pd.concat(parts).sort_index()


def per_state(pred: pd.Series, truth: pd.Series) -> dict:
    out = {}
    for st in sorted(set(truth) | set(pred.dropna())):
        tp = int(((pred == st) & (truth == st)).sum())
        fp = int(((pred == st) & (truth != st)).sum())
        fn = int(((pred != st) & (truth == st)).sum())
        out[str(st)] = {
            "support": int((truth == st).sum()),
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
        }
    return out


def main() -> int:
    print("loading ES ...", flush=True)
    es = load_es()
    print(f"  {len(es):,} bars  {es.index.min()} .. {es.index.max()}  (ET)")

    X = features(es)
    y = composite_labels()
    common = X.index.intersection(y.index)
    X, y = X.loc[common], y.loc[common]
    assert len(common) > 1000, (
        f"only {len(common)} sessions have both features and a label; that is a tooling "
        f"failure, not a data finding - stop and read the join")
    print(f"  sessions with features AND a label: {len(common):,}  "
          f"{common.min().date()} .. {common.max().date()}")

    # ── coverage, per window, before anything is modelled ──────────────────────────────────
    cov = {}
    for name, lo, hi, fit in WINDOWS:
        m = (common >= pd.Timestamp(lo)) & (common <= pd.Timestamp(hi))
        n = int(m.sum())
        span = (min(pd.Timestamp(hi), common.max()) - pd.Timestamp(lo)).days / 365.25
        exp = max(int(252 * span), 1)
        cov[name] = {"sessions_with_1400_bar": n, "expected": exp,
                     "share": round(n / exp, 4), "hmm_fit_end": fit,
                     "first": str(common[m].min().date()) if n else None,
                     "last": str(common[m].max().date()) if n else None}
        print(f"  {name:10s} usable={n:>5}  expected~{exp:>5}  {n / exp:6.1%}  fit_end={fit}")

    # ── walk-forward proxy ─────────────────────────────────────────────────────────────────
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    preds = pd.Series(index=y.index, dtype=object)
    days = list(y.index)
    for start in range(378, len(days), 126):
        tr, te = slice(0, start), slice(start, min(start + 126, len(days)))
        xt, yt = X.iloc[tr], y.iloc[tr]
        if yt.nunique() < 2:
            continue
        sc = StandardScaler().fit(xt)
        m = LogisticRegression(max_iter=3000)
        m.fit(sc.transform(xt), yt)
        preds.iloc[te] = m.predict(sc.transform(X.iloc[te]))

    d1 = y.shift(1)
    res = {"coverage": cov, "windows": {}}

    for name, lo, hi in [("ALL", "2018-01-01", "2026-08-19")] + \
            [(n, a, b) for n, a, b, _ in WINDOWS]:
        m = (y.index >= pd.Timestamp(lo)) & (y.index <= pd.Timestamp(hi)) & preds.notna() & d1.notna()
        if not m.sum():
            print(f"\n{name}: no scored sessions")
            res["windows"][name] = {"scored": 0}
            continue
        yt, pt, dt = y[m], preds[m], d1[m]
        a_d1 = float((dt == yt).mean())
        a_px = float((pt == yt).mean())
        wrong = dt != yt
        fixed = float((pt[wrong] == yt[wrong]).mean()) if wrong.sum() else float("nan")
        right = dt == yt
        kept = float((pt[right] == yt[right]).mean()) if right.sum() else float("nan")
        gained = int((pt[wrong] == yt[wrong]).sum())
        lost = int((pt[right] != yt[right]).sum())

        print(f"\n=== {name}  ({int(m.sum()):,} scored sessions) ===")
        print(f"  D-1 persistence      {a_d1:7.1%}   <- the bar")
        print(f"  ES pre-14:00 proxy   {a_px:7.1%}")
        print(f"  difference           {a_px - a_d1:+7.1%}")
        print(f"  D-1 wrong {int(wrong.sum()):>4}, proxy fixes {gained:>4} ({fixed:.1%})")
        print(f"  D-1 right {int(right.sum()):>4}, proxy breaks {lost:>4} "
              f"({1 - kept:.1%})   net {gained - lost:+d}")
        ps = per_state(pt, yt)
        for st, v in ps.items():
            print(f"    {st:7s} support={v['support']:>4}  precision={v['precision']}  "
                  f"recall={v['recall']}")

        # what D-1 achieves per state, for the Normal comparison the brief asks for
        ps_d1 = per_state(dt, yt)
        res["windows"][name] = {
            "scored": int(m.sum()),
            "agreement_d1": round(a_d1, 4), "agreement_proxy": round(a_px, 4),
            "difference": round(a_px - a_d1, 4),
            "d1_wrong": int(wrong.sum()), "proxy_fixed": gained,
            "d1_right": int(right.sum()), "proxy_broke": lost,
            "net_sessions": gained - lost,
            "per_state_proxy": ps, "per_state_d1": ps_d1,
            "confusion": {str(i): {str(c): int(v) for c, v in row.items()}
                          for i, row in pd.crosstab(pt, yt).iterrows()},
        }

    Path("scratch/track1_stage5zzzk_es_proxy_label_recovery_20260829.json").write_text(
        json.dumps(res, indent=1), encoding="utf-8")
    print("\nwrote scratch/track1_stage5zzzk_es_proxy_label_recovery_20260829.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
