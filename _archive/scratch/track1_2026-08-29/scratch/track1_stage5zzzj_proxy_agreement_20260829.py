"""Stage 5ZZZ-J — can a causal pre-14:00 feature set recover the same-day regime label?

The cheap decisive test, run before any backtest is built.

The proxy's whole purpose is to stand in for the SAME-DAY label at 14:05 without reading the
16:00 close. So the bar it must clear is not "is it informative" - it is "does it predict the
same-day label better than simply carrying yesterday's label forward". D-1 is already available,
already live-tradable, and already measured. A proxy that cannot beat D-1 at recovering the
same-day label has nothing to add, and no backtest is needed to say so.

Every feature here is closed by 14:00 ET. The 16:00 close is never read for session D; the
previous session's close is, which is known before D opens.
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
CUT = pd.Timestamp("14:00").time()
RTH_OPEN = pd.Timestamp("09:30").time()
RTH_CLOSE = pd.Timestamp("16:00").time()
HMM_TRAIN_END = "2018-01-01"
FLOOR_HMM_FIT_END = "2022-12-31"
FLOOR_END = "2024-12-31"


def load_spy_intraday() -> pd.DataFrame:
    """Every SPY 5-minute bar on disk, de-duplicated, ET, RTH only."""
    frames = []
    for p in sorted(Path(".").rglob("SPY_5min*.parquet")):
        try:
            df = pd.read_parquet(p)
        except Exception:                                          # noqa: BLE001
            continue
        if not isinstance(df.index, pd.DatetimeIndex) or not len(df):
            continue
        idx = df.index
        df = df.copy()
        df.index = (idx.tz_convert(ET) if idx.tz is not None
                    else idx.tz_localize(ET, ambiguous="NaT", nonexistent="NaT"))
        frames.append(df[~df.index.isna()])
    if not frames:
        raise SystemExit("no SPY intraday data at all")
    all_df = pd.concat(frames).sort_index()
    all_df = all_df[~all_df.index.duplicated(keep="last")]
    cols = {c.lower(): c for c in all_df.columns}
    keep = {k: cols[k] for k in ("open", "high", "low", "close", "volume") if k in cols}
    all_df = all_df[list(keep.values())].rename(columns={v: k for k, v in keep.items()})
    rth = all_df[(all_df.index.time >= RTH_OPEN) & (all_df.index.time < RTH_CLOSE)]
    return rth


def causal_features(rth: pd.DataFrame) -> pd.DataFrame:
    """One row per session, built ONLY from bars closed by 14:00 plus prior sessions."""
    day = rth.index.normalize()
    prev_close = rth.groupby(day)["close"].last().shift(1)          # session D-1's 16:00 close
    upto = rth[rth.index.time <= CUT]
    g = upto.groupby(upto.index.normalize())

    op = g["open"].first()
    px = g["close"].last()
    hi = g["high"].max()
    lo = g["low"].min()

    def bar_rets(x):
        c = x["close"].to_numpy(dtype=float)
        return np.diff(np.log(c)) if len(c) > 2 else np.array([0.0])

    rv = g.apply(lambda x: float(np.std(bar_rets(x)) * np.sqrt(78 * 252)))

    f = pd.DataFrame({
        "prev_close": prev_close.reindex(px.index),
        "open": op, "px1400": px, "hi": hi, "lo": lo, "rvol_1400": rv,
    }).dropna(subset=["prev_close"])

    f["gap"] = f["open"] / f["prev_close"] - 1.0
    f["ret_to_1400"] = f["px1400"] / f["prev_close"] - 1.0
    f["ret_open_to_1400"] = f["px1400"] / f["open"] - 1.0
    f["range_to_1400"] = (f["hi"] - f["lo"]) / f["prev_close"]
    # strictly-prior context: 5-session realised vol of the 14:00 series, shifted
    f["rvol_5d_prior"] = f["rvol_1400"].rolling(5).mean().shift(1)
    f["absret_5d_prior"] = f["ret_to_1400"].abs().rolling(5).mean().shift(1)
    return f[["gap", "ret_to_1400", "ret_open_to_1400", "range_to_1400",
              "rvol_1400", "rvol_5d_prior", "absret_5d_prior"]].dropna()


def daily_labels() -> pd.Series:
    from futures._validated_core import benchmark_daily, label_regimes

    bench = benchmark_daily("spy_daily_live.csv")
    bench = bench[bench.index <= pd.Timestamp(FLOOR_END)]
    raw = label_regimes(bench, HMM_TRAIN_END, 3, FLOOR_HMM_FIT_END)
    s = pd.Series(raw)
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return s.sort_index()


def main() -> int:
    print("loading SPY intraday ...", flush=True)
    rth = load_spy_intraday()
    print(f"  {len(rth):,} RTH 5-minute bars, "
          f"{rth.index.normalize().nunique():,} sessions, "
          f"{rth.index.min().date()} .. {rth.index.max().date()}")

    X = causal_features(rth)
    X.index = pd.DatetimeIndex(X.index).tz_localize(None).normalize()
    y = daily_labels()
    common = X.index.intersection(y.index)
    X, y = X.loc[common], y.loc[common]
    print(f"  usable sessions with BOTH features and a label: {len(common):,}"
          f"  {common.min().date()} .. {common.max().date()}")
    assert len(common) > 500, "too few aligned sessions for this to mean anything"

    # ── baseline 1: carry yesterday's label forward (this is D-1, already live-tradable) ────
    d1 = y.shift(1)
    ok = d1.notna()
    acc_d1 = float((d1[ok] == y[ok]).mean())

    # ── baseline 2: always predict the most common label (the floor any model must clear) ───
    major = y.value_counts().idxmax()
    acc_major = float((y == major).mean())

    # ── the proxy: walk-forward multinomial logistic regression on causal features ─────────
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    preds = pd.Series(index=y.index, dtype=object)
    days = list(y.index)
    step = 126                      # refit every half year, train on everything before
    first = 378                     # ~18 months before the first prediction
    for start in range(first, len(days), step):
        tr = slice(0, start)
        te = slice(start, min(start + step, len(days)))
        xt, yt = X.iloc[tr], y.iloc[tr]
        if yt.nunique() < 2:
            continue
        sc = StandardScaler().fit(xt)
        m = LogisticRegression(max_iter=2000, multi_class="multinomial")
        m.fit(sc.transform(xt), yt)
        preds.iloc[te] = m.predict(sc.transform(X.iloc[te]))
    have = preds.notna()
    acc_proxy = float((preds[have] == y[have]).mean())

    # and the same comparison restricted to the days the proxy actually covered
    acc_d1_same = float((d1[have & ok] == y[have & ok]).mean())

    print("\n=== recovering the SAME-DAY label ===")
    print(f"  sessions scored                    {int(have.sum()):,}")
    print(f"  always-majority ({major})           {acc_major:6.1%}")
    print(f"  carry yesterday forward (D-1)      {acc_d1_same:6.1%}   <- the bar to beat")
    print(f"  causal pre-14:00 proxy             {acc_proxy:6.1%}")
    print(f"  proxy minus D-1                    {acc_proxy - acc_d1_same:+6.1%}")

    print("\n=== confusion, proxy (rows) vs same-day label (cols) ===")
    cm = pd.crosstab(preds[have], y[have])
    print(cm.to_string())

    print("\n=== where D-1 is WRONG, does the proxy fix it? ===")
    wrong = have & ok & (d1 != y)
    fixed = float((preds[wrong] == y[wrong]).mean()) if wrong.sum() else float("nan")
    print(f"  sessions where D-1 disagrees with the same-day label: {int(wrong.sum()):,} "
          f"({wrong.sum() / have.sum():.1%})")
    print(f"  of those, the proxy gets right:                        {fixed:.1%}")
    broke = have & ok & (d1 == y)
    kept = float((preds[broke] == y[broke]).mean()) if broke.sum() else float("nan")
    print(f"  sessions where D-1 is already right:                  {int(broke.sum()):,}")
    print(f"  of those, the proxy keeps right:                       {kept:.1%}")

    out = {
        "spy_intraday": {
            "rth_bars": int(len(rth)),
            "sessions": int(rth.index.normalize().nunique()),
            "first": str(rth.index.min().date()), "last": str(rth.index.max().date()),
        },
        "aligned_sessions": int(len(common)),
        "accuracy_same_day_label": {
            "always_majority": round(acc_major, 4), "majority_label": str(major),
            "carry_d1_forward": round(acc_d1_same, 4),
            "causal_pre1400_proxy": round(acc_proxy, 4),
            "proxy_minus_d1": round(acc_proxy - acc_d1_same, 4),
            "scored_sessions": int(have.sum()),
        },
        "d1_wrong_sessions": int(wrong.sum()),
        "proxy_fixes_d1_errors": None if np.isnan(fixed) else round(fixed, 4),
        "proxy_keeps_d1_correct": None if np.isnan(kept) else round(kept, 4),
        "confusion_proxy_vs_sameday": {str(i): {str(c): int(cm.loc[i, c]) for c in cm.columns}
                                       for i in cm.index},
    }
    Path("scratch/track1_stage5zzzj_proxy_agreement_20260829.json").write_text(
        json.dumps(out, indent=1), encoding="utf-8")
    print("\nwrote scratch/track1_stage5zzzj_proxy_agreement_20260829.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
