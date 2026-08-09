"""
global_index/replay_checkpoint.py — the open position at the end of a replayed day

run_live_day replays 2018-to-today for four instruments on every five-minute
slot, to answer which position should be open right now. The day loop carries
exactly one thing across days — that position — so a run can start from the
previous day's answer instead, given the daily ATR for the full history, which
costs 0.18s to recompute. See futures/_validated_core.backtest_swing_tf.

A checkpoint is therefore an optimisation and nothing more. Every entry carries
a fingerprint of the history it was computed from; if the parquet has changed
under it — the daily append rewriting a bar, a repair rebuilding a stretch — the
fingerprint stops matching and the caller falls back to replaying in full. A
stale checkpoint makes the run slow, never wrong.

The fingerprint covers history only up to the checkpointed day. Hashing the
whole frame would invalidate the entry every afternoon, since the point of the
daily update is to add bars after it.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_PATH = "global_index/replay_checkpoint.json"
SCHEMA = 1


def fingerprint(df: pd.DataFrame, through) -> str:
    """Identify the history up to and including `through`.

    Content-derived rather than a row count plus endpoints: a repair that
    rewrites bars in the middle leaves both of those untouched, and that is
    exactly the case a checkpoint must not survive. Measured at 0.54s on 2.8M
    rows, against the 83s replay it exists to skip.

    The tz is stripped before hashing, keeping the wall time. The same history
    reaches this function in two representations — tz-aware from load_parquet
    when the checkpoint is built, tz-naive from the live path, which strips the
    tz so parquet bars and IBKR bars can be concatenated. Hashing the index as
    it comes would make those two never match, and the checkpoint would be
    discarded on every live run while looking like it was working.
    """
    idx = df.index
    cut = pd.Timestamp(through).normalize() + pd.Timedelta(days=1)
    if idx.tz is not None:
        cut = cut.tz_localize(idx.tz)
    hist = df[idx < cut]
    if hist.empty:
        return ""
    if hist.index.tz is not None:
        hist = hist.copy()
        hist.index = hist.index.tz_localize(None)
    h = pd.util.hash_pandas_object(hist, index=True).sum()
    return f"{len(hist)}:{int(h) & 0xFFFFFFFFFFFFFFFF:016x}"


def _pos_to_json(pos):
    if pos is None:
        return None
    return {k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in pos.items()}


def _pos_from_json(d):
    if d is None:
        return None
    out = dict(d)
    for k in ("entry_day", "entry_time"):
        if out.get(k):
            out[k] = pd.Timestamp(out[k])
    return out


def load(path: str = DEFAULT_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except Exception as exc:                      # a corrupt file is a slow run
        log.warning("checkpoint unreadable (%s) — full replay", exc)
        return {}
    if raw.get("schema_version") != SCHEMA:
        log.warning("checkpoint schema %s != %s — full replay",
                    raw.get("schema_version"), SCHEMA)
        return {}
    return raw.get("instruments", {})


def save(entries: dict, path: str = DEFAULT_PATH) -> None:
    """Atomic: a run killed mid-write must not leave a half-parsed checkpoint."""
    p = Path(path)
    payload = {"schema_version": SCHEMA, "instruments": entries}
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1, default=str))
    tmp.replace(p)


def make_entry(df: pd.DataFrame, last_day, pos) -> dict:
    return {"last_day": str(pd.Timestamp(last_day).date()),
            "fingerprint": fingerprint(df, last_day),
            "pos": _pos_to_json(pos)}


def advance_day(raw: pd.DataFrame, run_day, last_day):
    """The newest day a checkpoint may be moved to, or None to leave it alone.

    Read off the PARQUET, never off the spliced frame the live path replays. The
    two disagree about where history ends, and that disagreement is the bug this
    exists to prevent: the spliced frame carries live IBKR bars, so it holds
    yesterday complete, while the parquet does not. Appends run once a day at
    13:45 ET, so the parquet's newest date always stops mid-day and the NEXT
    append fills in the rest of it — 13:46 to 23:59 ET of a date that may already
    be checkpointed.

    Advancing on the spliced frame therefore writes a fingerprint over a day the
    parquet only half holds, and tomorrow's append changes it. That is not
    hypothetical: on 2026-08-07 every slot rejected the checkpoint for all four
    Rổ 4 instruments, 554 rows short, and the session gathered no evidence at all.

    Stopping one day short of the parquet's own final session gives a day nothing
    will add to. It also keeps pos meaning what it claims: the position at the end
    of last_day, which a half-held day cannot produce. A day present only in live
    bars is not eligible — there is no history on disk to fingerprint it against.

    Sessions are read off `raw`'s own index, whatever clock it carries, and that is
    load-bearing — the frames do not share one. Rổ 4 arrives tz-aware ET, so a day
    closes at 00:00 ET, after the 13:45 ET append. MNKD arrives tz-aware Tokyo, so
    its day closes at 00:00 JST = 15:00 UTC, BEFORE that append; its history up to
    last_day was already fixed, and it was the one instrument whose checkpoint
    survived 2026-08-07. The general condition is that the cutoff must fall before
    the append boundary, and taking the parquet's second-to-last session on the
    parquet's own clock satisfies it for both clocks without special-casing either.
    """
    run_day = pd.Timestamp(run_day).normalize()
    psess = sorted(set(raw.index.normalize().tz_localize(None)))
    done = [d for d in psess[:-1] if d < run_day]
    if not done:
        return None
    if last_day is not None and done[-1] <= pd.Timestamp(last_day).normalize():
        return None
    return done[-1]


def usable(entry: dict, df: pd.DataFrame):
    """(last_day, pos) if this entry still describes df's history, else None.

    Returns the position as-is including None: a checkpoint recording that
    nothing was open is as valid as one recording a position, and treating it
    as a miss would replay in full on every flat day.
    """
    if not entry or "last_day" not in entry:
        return None
    try:
        last_day = pd.Timestamp(entry["last_day"]).normalize()
    except Exception:
        return None
    if fingerprint(df, last_day) != entry.get("fingerprint"):
        return None
    return last_day, _pos_from_json(entry.get("pos"))


def _bootstrap():
    """Build the first checkpoint by replaying in full, once, offline.

    Live can then only ever resume and step forward. Doing this cold start
    inside a trading slot would cost the very five minutes the checkpoint
    exists to avoid.

        python -m global_index.replay_checkpoint --bootstrap
    """
    import argparse

    from futures._validated_core import (load_parquet, benchmark_daily,
                                         label_regimes, backtest_swing_tf)
    from futures.basket import BASKET, REGIME, data_filename
    from futures.swing_tf import costs_for_basket, SWING_TF_PARAM

    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", action="store_true")
    ap.add_argument("--data-dir", default="data/cache/futures")
    ap.add_argument("--regime-csv", default="spy_daily_live.csv")
    ap.add_argument("--nkd-parquet",
                    default="global_index/data/NKD_continuous_1m_8y.parquet")
    ap.add_argument("--nkd-ema", type=int, default=10)
    ap.add_argument("--path", default=DEFAULT_PATH)
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    a = ap.parse_args()
    if not a.bootstrap:
        ap.error("nothing to do; pass --bootstrap")

    labels = label_regimes(benchmark_daily(a.regime_csv), "2018-01-01", 3,
                           REGIME["hmm_fit_end"])
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)
    kw = dict(ema_period=SWING_TF_PARAM["ema_period"],
              chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
              max_hold_days=SWING_TF_PARAM["max_hold_days"])
    entries = {}
    for inst, c in BASKET.items():
        df = load_parquet(str(Path(a.data_dir) / data_filename(c)))
        sess = sorted(set(df.index.normalize().tz_localize(None)))
        # The last COMPLETE session. Today is still being traded, so a
        # checkpoint taken there would describe a partial day.
        last = sess[-2]
        cut = (last + pd.Timedelta(days=1))
        if df.index.tz is not None:
            cut = cut.tz_localize(df.index.tz)
        _, pos = backtest_swing_tf(df[df.index < cut], labels, costs[inst],
                                   return_open=True, **kw)
        entries[inst] = make_entry(df, last, pos)
        held = "khong co vi the" if pos is None else \
            f"{pos['dir']} entry={pos['entry']:.2f} stop={pos['stop']:.2f}"
        print(f"  {inst:5s} last_day={last.date()}  {held}", flush=True)
        del df

    # MNKD: its own engine parameters, a Tokyo session clock and lagged SPY
    # labels. Left out, the live shadow would report "no checkpoint" for it on
    # every run — the instrument whose timezone handling has broken twice would
    # be the one never exercised.
    from global_index._core import load_parquet as gi_load, FuturesCost as GIFC
    from global_index import specs as gi_specs
    from global_index.regime import RegimeLabels

    cn = gi_specs.SPECS["MNKD"]
    spy = pd.Series(label_regimes(benchmark_daily(a.regime_csv), "2018-01-01", 3,
                                  REGIME["hmm_fit_end"]))
    idx = pd.DatetimeIndex(spy.index)
    spy.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    ndf = gi_load(a.nkd_parquet)
    ndf.index = ndf.index.tz_convert(cn.session_tz)
    nkw = dict(ema_period=a.nkd_ema, chandelier_atr_mult=SWING_TF_PARAM["chandelier_atr_mult"],
               max_hold_days=SWING_TF_PARAM["max_hold_days"])
    ncost = GIFC(point_value=cn.point_value, tick=cn.tick,
                 commission_rt=cn.commission_rt, slippage_ticks_per_side=a.slippage_ticks)
    nsess = sorted(set(ndf.index.normalize().tz_localize(None)))
    nlast = nsess[-2]
    ncut = nlast + pd.Timedelta(days=1)
    if ndf.index.tz is not None:
        ncut = ncut.tz_localize(ndf.index.tz)
    _, npos = backtest_swing_tf(ndf[ndf.index < ncut],
                                RegimeLabels(spy.sort_index(), lag_days=1),
                                ncost, return_open=True, **nkw)
    entries["MNKD"] = make_entry(ndf, nlast, npos)
    held = "khong co vi the" if npos is None else \
        f"{npos['dir']} entry={npos['entry']:.2f} stop={npos['stop']:.2f}"
    print(f"  {'MNKD':5s} last_day={nlast.date()}  {held}", flush=True)

    save(entries, a.path)
    print(f"\nda ghi {len(entries)} instrument -> {a.path}")


if __name__ == "__main__":
    _bootstrap()
