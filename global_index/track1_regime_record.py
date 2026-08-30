"""The regime label, recorded once so a page can read it. Stage 5ZZL.

Why this exists rather than a call from the dashboard
-----------------------------------------------------
`label_regimes` decodes an HMM over the whole benchmark series. **Measured on 2026-08-27 it
takes 8.54 seconds.** A dashboard endpoint that called it would hang the operator's page for
that long on the first poll after every SPY refresh, and on every cold backend. So it follows
the pattern the rest of this route already uses: a probe measures and writes down what it saw,
and the reader reads what the probe wrote. `track1_b1`, `track1_account_baseline` and
`regime_verify` are all shaped this way for the same reason.

What it does NOT do
-------------------
It does not decide anything, it does not compare against a threshold, and it does not say
whether the label is safe. It runs the same call the engine runs, against the same file the
engine reads, and writes the answer down with the inputs that produced it.

What the model publishes, corrected by Stage 5ZZP
------------------------------------------------
`label_regimes` hands back a series of strings, and Stage 5ZZL read that return type and
concluded the model published nothing underneath the label. Reading the ENGINE rather than its
return shows otherwise, and the difference matters: `not returned` is not `not computed`.

    predict_current  ->  self._model.predict(X)[-1]        a Viterbi decode
    predict_proba    ->  self._model.predict_proba(X)[-1]  a posterior per state

So there IS a score — the posterior probability of the labelled state — and it is recorded.

There is NO threshold, and that is a statement about the mechanism rather than about how far
this module can see. Viterbi picks the most likely path; nothing is compared against a
constant, so there is no cut to be near, and a display reading "distance to threshold" would
be describing a decision procedure the model does not use. What stands in its place is the
margin over the runner-up state, named as a margin and never as a threshold distance.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

SCHEMA = "track1_regime_label/1"
RECORD_DIR = "global_index/track1_runtime/regime_label"

#: The engine's own arguments, copied from the call the route makes. Kept here as named
#: constants so a record can carry them: a label without the fit window that produced it is a
#: label nobody can reproduce, which is the `FreezeRecord` mistake this project already made.
BENCHMARK_CSV = "spy_daily_live.csv"
START = "2018-01-01"
N_STATES = 3
FIT_END = "2024-12-31"

OK = "PASS"
UNREADABLE = "UNKNOWN"

#: How long a recorded label describes the world. The benchmark file is daily, so a label from
#: yesterday's close is still the current label until a new close lands — but one from last
#: week is describing a different market.
MAX_RECORD_AGE_HOURS = 48

#: Said out loud in every record, because absence invites invention.
NOT_EXPOSED = "not exposed by model"

#: Stage 5ZZP corrected the previous stage's claim. `label_regimes` returns strings, so 5ZZL
#: reported that the model published nothing underneath the label. Reading the engine rather
#: than its return type shows otherwise:
#:
#:     HMMEngine.predict_current  ->  self._model.predict(X)[-1]      a VITERBI decode
#:     HMMEngine.predict_proba    ->  self._model.predict_proba(X)[-1]  posterior per state
#:
#: So a real score exists — the posterior probability of the labelled state — and it comes
#: from the same fitted model on the same window. It is recorded here.
#:
#: A THRESHOLD does not exist, and that is a statement about the mechanism rather than about
#: this module's reach. Viterbi picks the most likely PATH; nothing is compared against a
#: constant, so there is no cut to be near. Anything that displayed "distance to threshold"
#: would be describing a decision procedure the model does not use.
#:
#: What can honestly stand in its place is the MARGIN to the runner-up state — how far ahead
#: the labelled state is of the next most likely one. That is a real number from the model and
#: it is named as a margin, never as a threshold distance.
NO_THRESHOLD = ("not published — the label comes from a Viterbi decode, which compares states "
                "against each other rather than against a cut, so there is no threshold to be "
                "near. The model compares state probabilities; it does not expose a simple "
                "flip threshold")
SCORE_NAME = "posterior probability of the labelled state"
MARGIN_NAME = "probability margin over the next most likely state"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


@dataclass(frozen=True)
class RegimeRecord:
    schema: str = SCHEMA
    status: str = UNREADABLE
    code: str = ""
    detail: str = ""
    checked_at: str = ""
    label: "str | None" = None
    label_date: "str | None" = None
    #: (date, label) for the tail, newest last. Two lengths because the page shows two things:
    #: a short strip of recent days and a longer context run.
    recent: list = field(default_factory=list)
    context: list = field(default_factory=list)
    #: The inputs that produced the label, so the record is reproducible.
    inputs: dict = field(default_factory=dict)
    #: Stage 5ZZP. The score is real and recorded; the threshold is genuinely absent and says
    #: why. Each is NAMED rather than omitted — an absent field invites the next reader to
    #: assume it was zero.
    score: "float | None" = None
    score_name: str = SCORE_NAME
    shift_threshold: "float | None" = None
    #: How far the labelled state leads the runner-up. NOT a distance to a threshold.
    margin: "float | None" = None
    margin_name: str = MARGIN_NAME
    runner_up: "str | None" = None
    #: Every state's posterior, so nobody has to trust a single number in isolation.
    state_probabilities: dict = field(default_factory=dict)
    #: Viterbi decides the label; the posterior is a separate view of the same bar. They agree
    #: on every recent day measured, but "usually agrees" is not "is the same thing", so when
    #: they disagree the record says so instead of quietly showing a confidence for a label
    #: the confidence did not choose.
    posterior_agrees_with_label: "bool | None" = None
    #: Stage 5ZZQ. Shannon entropy of the posterior, in bits. 0 means the model is certain;
    #: log2(n_states) means it cannot tell them apart. A margin says how far the leader is
    #: ahead of ONE rival; entropy says how spread the whole distribution is, and a day can
    #: have a healthy margin over second place while the tail is unusually alive.
    entropy_bits: "float | None" = None
    max_entropy_bits: "float | None" = None
    #: What the model actually looked at. Two columns, named at source, never guessed.
    features: list = field(default_factory=list)
    score_note: str = ""
    threshold_note: str = NO_THRESHOLD

    def as_dict(self) -> dict:
        return asdict(self)


def measure(root: str | Path = ".", *, recent: int = 5, context: int = 60) -> RegimeRecord:
    """Run the engine's own labeller and report what it said. Fails to UNKNOWN, never to Calm.

    Failing to a label would be the worst available default: `Calm` is the permissive regime,
    and a labeller that could not run must not read like one that answered "safe".
    """
    import pandas as pd

    try:
        from futures._validated_core import benchmark_daily, label_regimes
    except Exception as exc:                                      # noqa: BLE001
        return RegimeRecord(status=UNREADABLE, code="engine_unavailable",
                            detail=f"{type(exc).__name__}: {exc}", checked_at=_now())

    #: The two columns the model is actually fitted on, named from `raits.hmm.features` rather
    #: than from anywhere else. `build_feature_matrix` returns column 0 = daily log return and
    #: column 1 = annualised realised volatility over a five-day window, and there is no third.
    FEATURE_LABELS = (("log_return", "SPY 1-day log return", "pct"),
                      ("realised_vol", "Realised volatility, 5-day annualised", "vol"))

    #: Below this, no state is meaningfully nearest and `leans` reports `mixed`. Measured on
    #: 2026-08-27: the three state means for `log_return` sit within a thousandth of each other
    #: and the current value is inside one standard deviation of all three, while
    #: `realised_vol` separates them decisively. Reporting a lean for a feature that does not
    #: discriminate would be inventing attribution, which is the one thing this must not do.
    LEAN_MIN_SEPARATION = 0.5

    def _features(eng, bench) -> list:
        """Each feature's current value, where it sits recently, and which state it favours.

        The lean is deliberately modest: the distance from the value to each state's own mean,
        measured in that state's own standard deviations, and reported as `mixed` when the
        best and second-best are too close to separate. It is NOT an attribution of the label
        to a feature — a Gaussian HMM decodes a path over a joint distribution and does not
        decompose into per-feature contributions, so anything stronger would be invented.
        """
        try:
            import numpy as _np
            from raits.hmm.features import build_feature_matrix

            X = _np.asarray(build_feature_matrix(bench))
            model = eng._model
            means = _np.asarray(model.means_)
            covars = _np.asarray(model.covars_)
            tail = X[-60:]
            out = []
            for j, (name, label, kind) in enumerate(FEATURE_LABELS):
                if j >= X.shape[1]:
                    break
                cur = float(X[-1, j])
                col = tail[:, j]
                sd = float(col.std()) or 1.0
                dists = []
                for i in range(means.shape[0]):
                    ssd = float(_np.sqrt(covars[i][j][j])) if covars.ndim == 3 else \
                        float(_np.sqrt(covars[i][j]))
                    dists.append(abs(cur - float(means[i][j])) / (ssd or 1.0))
                ranked = sorted(range(len(dists)), key=lambda i: dists[i])
                separation = float(dists[ranked[1]] - dists[ranked[0]]) if len(dists) > 1 else 0.0
                leans = (eng.state_name(ranked[0]) if separation >= LEAN_MIN_SEPARATION
                         else "mixed")
                out.append({
                    "name": name, "label": label,
                    "value": round(cur, 8), "model_value": round(cur, 8),
                    "display_value": (f"{cur * 100:+.2f}%" if kind == "pct"
                                      else f"{cur * 100:.1f}% annualised"),
                    "percentile_60d": round(float((col < cur).mean() * 100), 1),
                    "z_score_60d": round(float((cur - col.mean()) / sd), 3),
                    "state_means": {eng.state_name(i): round(float(means[i][j]), 8)
                                    for i in range(means.shape[0])},
                    "sd_distance_to_state": {eng.state_name(i): round(dists[i], 3)
                                             for i in range(len(dists))},
                    "separation": round(separation, 3),
                    "leans": leans,
                    "source": "hmm_feature_matrix"})
            return out
        except Exception:                                         # noqa: BLE001
            return []

    def _confidence(bench) -> dict:
        """The posterior behind the current label, from the SAME model on the SAME window.

        Fitted here rather than reused from `label_regimes` because that function does not
        hand its engine back. It is the identical call with the identical arguments — the fit
        is deterministic on a fixed series — and it is a SECOND VIEW of the model, never a
        second implementation of the labelling. Nothing here decides a label.

        Fails soft to an empty dict: a missing confidence must not cost the label.
        """
        try:
            import numpy as _np
            from raits.hmm.engine import HMMEngine

            eng = HMMEngine(n_components=N_STATES)
            eng.fit(bench[bench.index <= pd.Timestamp(FIT_END)],
                    version_tag="track1_regime_record", save=False)
            probs = _np.asarray(eng.predict_proba(bench))
            viterbi = int(eng.predict_current(bench))
            order = _np.argsort(probs)[::-1]
            top, second = int(order[0]), int(order[1])
            nz = probs[probs > 0]
            entropy = float(-(nz * _np.log2(nz)).sum()) if len(nz) else None
            return {
                "score": round(float(probs[viterbi]), 6),
                "margin": round(float(probs[top] - probs[second]), 6),
                "runner_up": eng.state_name(second),
                "state_probabilities": {eng.state_name(i): round(float(probs[i]), 6)
                                        for i in range(len(probs))},
                "posterior_agrees_with_label": bool(viterbi == top),
                "entropy_bits": None if entropy is None else round(entropy, 6),
                "max_entropy_bits": round(float(_np.log2(len(probs))), 6),
                "features": _features(eng, bench),
            }
        except Exception:                                         # noqa: BLE001
            return {}

    csv = Path(root) / BENCHMARK_CSV
    try:
        bench = benchmark_daily(str(csv))
        labels = pd.Series(label_regimes(bench, START, N_STATES, FIT_END)).sort_index()
    except Exception as exc:                                      # noqa: BLE001
        return RegimeRecord(status=UNREADABLE, code="labelling_failed",
                            detail=f"{type(exc).__name__}: {exc}", checked_at=_now())

    if not len(labels):
        return RegimeRecord(status=UNREADABLE, code="no_labels",
                            detail="the labeller returned an empty series, which is not a "
                                   "regime — it is the absence of one",
                            checked_at=_now())

    def pairs(n: int) -> list:
        tail = labels.iloc[-n:]
        return [{"date": pd.Timestamp(d).date().isoformat(), "label": str(v)}
                for d, v in zip(tail.index, tail.values)]

    last_date = pd.Timestamp(labels.index[-1]).date().isoformat()
    conf = _confidence(bench)
    return RegimeRecord(
        **conf,
        score_note=("" if conf else
                    "the posterior could not be read; the label itself is unaffected"),
        status=OK, code="labelled",
        detail=f"{len(labels)} label(s) through {last_date}; current {labels.iloc[-1]}",
        checked_at=_now(),
        label=str(labels.iloc[-1]), label_date=last_date,
        recent=pairs(recent), context=pairs(context),
        inputs={"benchmark_csv": str(csv), "start": START, "n_states": N_STATES,
                "fit_end": FIT_END, "labels": int(len(labels))})


def path_for(root: str | Path = ".", day: str | None = None) -> Path:
    d = day or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d")
    return Path(root) / RECORD_DIR / f"regime_label_{d}.jsonl"


def record(rec: RegimeRecord, *, root: str | Path = ".", day: str | None = None) -> Path:
    p = path_for(root, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec.as_dict(), default=str) + "\n")
    return p


def latest(root: str | Path = ".", *, now: Any = None,
           max_age_hours: "int | None" = None) -> RegimeRecord:
    """The newest record, or UNKNOWN. A record too old to describe today is UNKNOWN too.

    `max_age_hours` is resolved at CALL time, not bound as a default: bound as a default it
    would freeze the module-load value and patching the constant would change nothing while
    appearing to — a trap this project has now been caught by twice.
    """
    cap = MAX_RECORD_AGE_HOURS if max_age_hours is None else max_age_hours
    files = sorted(Path(root, RECORD_DIR).glob("regime_label_*.jsonl")) \
        if Path(root, RECORD_DIR).is_dir() else []
    for f in reversed(files):
        try:
            rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()
                    if l.strip()]
        except Exception:                                         # noqa: BLE001
            continue
        if not rows:
            continue
        raw = rows[-1]
        raw.pop("schema", None)
        rec = RegimeRecord(schema=SCHEMA, **raw)
        age = _age_hours(rec.checked_at, now)
        if age is not None and age > cap:
            return RegimeRecord(status=UNREADABLE, code="record_stale",
                                detail=f"the newest regime label was recorded {age:.1f}h ago, "
                                       f"past the {cap}h allowance — a label that old is "
                                       f"describing a different market",
                                checked_at=rec.checked_at)
        return rec
    return RegimeRecord(status=UNREADABLE, code="no_record",
                        detail="no regime label has been recorded; a label that was never "
                               "measured is not a label that says Calm")


def _age_hours(checked_at: str, now: Any = None) -> "float | None":
    if not checked_at:
        return None
    try:
        when = _dt.datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    ref = now or _dt.datetime.now(_dt.timezone.utc)
    if isinstance(ref, str):
        ref = _dt.datetime.fromisoformat(ref.replace("Z", "+00:00"))
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=_dt.timezone.utc)
    return (ref - when).total_seconds() / 3600.0


def age_hours(rec: RegimeRecord, now: Any = None) -> "float | None":
    return _age_hours(rec.checked_at, now)


def operator_line(rec: RegimeRecord) -> str:
    if rec.status != OK or not rec.label:
        return f"Regime label {rec.status}: {rec.detail or rec.code}"
    age = _age_hours(rec.checked_at)
    return (f"Regime {rec.label} as of {rec.label_date}"
            + (f", read {age:.1f}h ago" if age is not None else ""))


def main(argv: "list | None" = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Record the current regime label. Reads the "
                                             "benchmark file and the engine's labeller; "
                                             "opens no connection and decides nothing.")
    ap.add_argument("--root", default=".")
    ap.add_argument("--record", action="store_true", help="write the record")
    a = ap.parse_args(argv)

    rec = measure(a.root)
    print(operator_line(rec))
    print(f"  status={rec.status} code={rec.code}")
    print(f"  {rec.detail}")
    print(f"  score={rec.score_note}; shift threshold={rec.threshold_note}")
    if a.record:
        print(f"recorded -> {record(rec, root=a.root)}")
    return 0 if rec.status == OK else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
