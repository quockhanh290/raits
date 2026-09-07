"""scratch/stocks_stage0_regime_20260826.py — SPY-HMM labels for the stock route. READ-ONLY.

Builds and caches two label sets, and the reason there are two is the whole point.

`futures/basket.py` calls `label_regimes(daily, train_end="2018-01-01", n_components=3,
hmm_fit_end="2024-12-31")`. The fit therefore ends in **2024** while the labels it produces
start in **2018**. For the futures route that is a declared, separately gated decision — the
HMM is frozen once on a diverse span and treated as a fixed component. For a stock-route
backtest whose whole question is "is there any edge here", a regime model fitted on data
through 2024 labelling sessions in 2019 is a lookahead, and quoting a P&L built on it without
saying so would be dishonest.

So:

    causal      fit ends 2018-12-31, labels every session strictly after it.
                Nothing that decides a label was measured after the label's own date.
    production  the exact futures call. Kept so the two can be compared instead of
                one being asserted to matter.

If the two label sets disagree on few sessions, the regime question is not load-bearing and
the report says so with a number. If they disagree on many, the causal one is the answer and
the production one is the sensitivity.

Lag
---
`track1_params` declares `label_lag_days=0` for `roska4_swing`: the backtest reads day D's own
label for a 14:00 entry on day D, and that label is a function of SPY's 16:00 close on D. The
stock route reads **lag 1** — the label of the most recent session strictly before D — because
that is the newest label that exists at the decision instant. `lag0` is built too, purely as a
sensitivity row, and is never the headline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CACHE = Path(__file__).resolve().parent / "_stocks_stage0_regime_labels.csv"

CONFIGS = {
    # name        train_end      hmm_fit_end     causal for 2019-2022?
    "causal": dict(train_end="2018-12-31", hmm_fit_end="2018-12-31", causal=True),
    "production": dict(train_end="2018-01-01", hmm_fit_end="2024-12-31", causal=False),
}
N_COMPONENTS = 3


def _build(name: str) -> pd.Series:
    from futures._validated_core import benchmark_daily, label_regimes
    cfg = CONFIGS[name]
    daily = benchmark_daily(str(ROOT / "spy_daily_live.csv"))
    daily = daily[~daily.index.duplicated(keep="last")]
    t0 = time.time()
    raw = label_regimes(daily, cfg["train_end"], N_COMPONENTS, cfg["hmm_fit_end"])
    s = pd.Series(raw)
    s.index = pd.DatetimeIndex(s.index).normalize()
    s = s.sort_index()
    print("  {:11s} {:5d} labelled sessions {} -> {}  ({:.0f}s)".format(
        name, len(s), s.index[0].date(), s.index[-1].date(), time.time() - t0))
    return s


def labels(force: bool = False) -> pd.DataFrame:
    """`DataFrame(index=session, columns=['causal','production'])`, cached on disk.

    Cached because an expanding-window HMM relabel is minutes of work that produces the same
    answer every time, and because a number that gets rebuilt on every run is a number nobody
    can point at afterwards.
    """
    if CACHE.exists() and not force:
        d = pd.read_csv(CACHE, parse_dates=["date"]).set_index("date")
        d.index = pd.DatetimeIndex(d.index).normalize()
        return d
    print("building SPY-HMM labels (not cached yet):")
    out = pd.concat({k: _build(k) for k in CONFIGS}, axis=1)
    out.index.name = "date"
    out.to_csv(CACHE)
    return out


class LaggedLabels:
    """`get(day)` -> the regime label in force at 14:00 ET on `day`.

    lag=1 returns the label of the most recent session STRICTLY BEFORE `day`; lag=0 returns
    `day`'s own. `asof` rather than a fixed calendar offset, so a Monday reads Friday and a
    session after a holiday reads the session before it rather than a day that does not exist.

    Returns None outside the labelled span. None is not "Calm": the sleeve trades one regime,
    and a missing label has to mean "cannot decide", never "decided against".
    """

    def __init__(self, series: pd.Series, lag: int = 1):
        self.s = series.dropna().sort_index()
        self.lag = int(lag)

    def get(self, day, default=None):
        d = pd.Timestamp(day)
        if d.tzinfo is not None:
            d = d.tz_localize(None)
        d = d.normalize()
        if self.lag == 0:
            v = self.s.get(d, None)
            return default if v is None else str(v)
        prior = self.s.index[self.s.index < d]
        if not len(prior):
            return default
        return str(self.s.loc[prior[-1]])


def main() -> int:
    d = labels(force="--force" in sys.argv)
    print()
    print("labelled span:", d.index[0].date(), "->", d.index[-1].date(), " n =", len(d))
    both = d.dropna()
    agree = (both["causal"] == both["production"]).mean()
    print("sessions where both label sets exist :", len(both))
    print("agreement causal vs production       : {:.2f}%".format(agree * 100))
    print()
    for col in ("causal", "production"):
        vc = d[col].value_counts(dropna=True)
        tot = int(vc.sum())
        print(col, "distribution ({} sessions):".format(tot),
              {k: "{} ({:.1f}%)".format(int(v), 100 * v / tot) for k, v in vc.items()})
    print()
    win = d.loc["2019-01-01":"2022-12-30"]
    print("--- trading window 2019-01-01..2022-12-30 ---")
    for col in ("causal", "production"):
        w = win[col].dropna()
        yr = w.groupby(w.index.year).apply(lambda x: int((x == "Normal").sum()))
        print("  {:11s} Normal sessions per year: {}".format(col, dict(yr)))
    print()
    print("cache:", CACHE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
