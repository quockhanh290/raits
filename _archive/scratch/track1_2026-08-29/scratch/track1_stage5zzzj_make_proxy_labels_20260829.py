"""Stage 5ZZZ-J — write the causal pre-14:00 proxy's predicted labels to disk.

Walk-forward: refit every 126 sessions on everything strictly before, predict the next block.
No session's label is ever predicted by a model that saw it. The features close at 14:00 ET and
the 16:00 close of the session being predicted is never read.

Coverage is partial by construction - the first ~18 months are warm-up and get no prediction -
and that is carried through to the backtest rather than papered over.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd

import scratch.track1_stage5zzzj_proxy_agreement_20260829 as A


def main() -> int:
    rth = A.load_spy_intraday()
    X = A.causal_features(rth)
    X.index = pd.DatetimeIndex(X.index).tz_localize(None).normalize()
    y = A.daily_labels()
    common = X.index.intersection(y.index)
    X, y = X.loc[common], y.loc[common]

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
        m = LogisticRegression(max_iter=2000)
        m.fit(sc.transform(xt), yt)
        preds.iloc[te] = m.predict(sc.transform(X.iloc[te]))

    have = preds.dropna()
    out = {str(k.date()): str(v) for k, v in have.items()}
    dest = Path("scratch/track1_stage5zzzj_proxy_labels_20260829.json")
    dest.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print(f"wrote {len(out):,} predicted labels  {min(out)} .. {max(out)}")
    print(f"  distribution: {have.value_counts().to_dict()}")
    print(f"  actual same-day distribution over the same days: "
          f"{y.loc[have.index].value_counts().to_dict()}")
    print(f"  sessions with NO prediction (warm-up): {len(y) - len(have):,}")
    print("wrote", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
