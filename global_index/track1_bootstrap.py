"""global_index/track1_bootstrap.py — a Track 1 checkpoint the route can resume from.

Stage 3B, closing CHECKPOINT_bootstrap_under_track1_params. Offline: it reads candidates and
parquet frames, it writes two JSON files, and it connects to nothing.

Why the Stage 2B file could not be used
----------------------------------------
`scratch/replay_checkpoint.track1.bootstrap_20260822.json` was seeded under the LEGACY engine
identity, which was correct for what it did. Diffed field by field against
`track1_params`, the Normal sleeve differs on five settings that decide which trades exist at
all — ema 30 vs 50, chandelier vs fixed-entry stop, 2.5 vs 2.0, extreme-through-prior-bar vs
entry anchor, ratchet on vs off — plus the arm hour. `route_params.params_hash` covers every
one, so that file is refused with `params_mismatch`, and it should be. The test that proves
the refusal is kept rather than replaced.

What is bootstrapped, and why it is the BOOK
---------------------------------------------
Stage 2C established that the per-instrument checkpoint is not enough. The Track 1 book
carries strictly more across a day boundary, and each of these changes which trades are
ADMITTED rather than how they are reported:

    open positions with cluster and risk     the cap gate reads them
    equity                                   drives the breaker
    peak_equity                              kept ACROSS days; drawdown measures from it
    day_start_equity                         the -4% daily rule measures from it
    cur_day                                  decides when start_day() re-bases that rule
    booked                                   a double-settlement COUNTER, never an input

So two artefacts are written, not one:

    the BOOK      live_positions.track1.json shape — what a resume rebuilds
    the CHECKPOINT global_index/replay_checkpoint.track1.json — schema 2, route-scoped,
                   carrying the track1_params identity so a settings change is refused

The cut is an instant, always
------------------------------
Never a calendar day. `_day()` strips a timezone without converting it, so a Tokyo-dated
MNKD event can carry the next local date while occurring earlier than that afternoon's ET
events; a day-keyed cut is therefore not a prefix of the sequence. On the floor window it
left two events on 2022-01-10 in neither half and the resumed book skipped a Stress override.
`restore()` REFUSES a bootstrap with no `cut_instant` for exactly that reason.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd

from futures.circuit_breaker import CircuitBreaker
from global_index import route_checkpoint as rc
from global_index import route_params as rp
from global_index import track1_params as tp
from global_index.track1_signal_layer import (ACCOUNT, Track1Book, cut_instant_for,
                                              event_key, make_guard, restore,
                                              run_candidates)

BOOK_SCHEMA = 2


def snapshot_book(book: Track1Book, *, window: str | None = None) -> dict:
    """The carried state, in the shape `restore()` reads back.

    One implementation. Two snapshot writers with slightly different key sets is how a
    resume ends up missing the one field that decided a day of entries.
    """
    br = book.breaker
    return {
        "schema_version": BOOK_SCHEMA,
        "route": book.route,
        "window": window,
        "cut_instant": (str(book.cut_instant) if book.cut_instant is not None else None),
        "equity": round(float(book.equity), 10),
        "cur_day": str(book.cur_day.date()) if book.cur_day is not None else None,
        "peak_equity": (round(float(br.peak_equity), 10) if br is not None else None),
        "day_start_equity": (round(float(br._day_start_equity), 10)
                             if br is not None and br._day_start_equity is not None
                             else None),
        "positions": [
            {"trade_id": h.candidate.trade_id, "sleeve": h.position.cluster,
             "instrument": h.position.instrument, "direction": h.position.direction,
             "qty": int(h.position.contracts),
             "risk_dollars": round(float(h.position.risk_dollars), 10),
             "entry_time": str(h.candidate.entry_time),
             "exit_time": str(h.candidate.exit_time) if h.candidate.exit_time else None,
             "entry_price": h.candidate.entry_price,
             "stop_price": h.candidate.stop_price}
            for h in book.open_book
        ],
        "booked_counter": {k: v for k, v in book.booked.items() if v > 1},
        "counters": {k: v for k, v in book.counters.items() if v},
    }


def _fresh_book(**kw) -> Track1Book:
    return Track1Book(guard=make_guard(), breaker=CircuitBreaker(account=ACCOUNT), **kw)


def build(candidates: Iterable[Any], *, cut, window: str | None = None,
          early_exit_value=None) -> tuple[dict, list]:
    """Run to `cut` and return `(book_state, settlements_written)`.

    `cut` may be a bare date — "the last event still inside that local day" — or an explicit
    instant, which is the only way to place a cut INSIDE a trading day and therefore the only
    way to exercise anything the next `start_day()` resets.
    """
    cands = list(candidates)
    book = _fresh_book()
    settlements, _dec = run_candidates(cands, book=book, early_exit_value=early_exit_value,
                                       stop_after=cut)
    if book.cut_instant is None:
        book.cut_instant = cut_instant_for(cands, cut)
    return snapshot_book(book, window=window), settlements


def verify_resume(candidates: Iterable[Any], *, cut, early_exit_value=None) -> dict:
    """Full replay versus head + resumed tail. Returns a report; never raises on divergence.

    Compares the ORDERED settlement stream, because two books that traded entirely
    differently can carry the same total — the reason Stage 2C compares events rather than
    counting them.
    """
    cands = list(candidates)

    full_book = _fresh_book()
    full, _ = run_candidates(cands, book=full_book, early_exit_value=early_exit_value)

    state, head = build(cands, cut=cut, early_exit_value=early_exit_value)

    tail_book = _fresh_book()
    restore(tail_book, state, cands)
    tail, _ = run_candidates(cands, book=tail_book, early_exit_value=early_exit_value,
                             resume_from=state["cut_instant"])

    a = [event_key(s) for s in full]
    b = [event_key(s) for s in head] + [event_key(s) for s in tail]
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if first is None and len(a) != len(b):
        first = min(len(a), len(b))
    return {
        "cut_instant": state["cut_instant"],
        "events_full": len(a), "events_head": len(head), "events_tail": len(tail),
        "events_exact": a == b, "first_diff": first,
        "equity_full": round(float(full_book.equity), 6),
        "equity_resumed": round(float(tail_book.equity), 6),
        "equity_exact": round(float(full_book.equity), 6) == round(float(tail_book.equity), 6),
        "open_full": sorted(h.candidate.trade_id for h in full_book.open_book),
        "open_resumed": sorted(h.candidate.trade_id for h in tail_book.open_book),
        "book_state": state,
    }


def binding_cuts(candidates: Iterable[Any]) -> list:
    """Cuts at which a carried position's CLUSTER and RISK are actually consulted again.

    This exists because Stage 2C could not prove those two fields load-bearing and reported
    so honestly, and the reason turned out to be the cut rather than the fields. Measured
    here: a carried position's cluster and risk are read by exactly one thing — the cap gate,
    when a SAME-CLUSTER candidate arrives while that position is still open. Stage 2C placed
    its cuts to make the breaker's `peak_equity` bind (a few sessions before the deepest
    drawdown), and at those instants no same-cluster candidate followed before the carried
    position exited. The field was carried, restored, and never consulted.

    So "not proved load-bearing" was a statement about the cut, not about the field. With a
    cut from this list, both mutations diverge — verified at
    `2025-02-25 15:50:00-05:00` on vault2025 (risk) and `2026-02-06 14:30:00-05:00` on
    vault2026 (cluster).

    Returned as data so a test can PICK such a cut instead of hoping an arbitrary one binds,
    and so the condition is written down where the next reader will find it.
    """
    cands = list(candidates)
    out = []
    for c0 in cands:
        cut = pd.Timestamp(c0.entry_time)
        for sp in cands:
            if not (pd.Timestamp(sp.entry_time) <= cut < pd.Timestamp(sp.exit_time)):
                continue
            later = any(c.sleeve == sp.sleeve
                        and cut < pd.Timestamp(c.entry_time) < pd.Timestamp(sp.exit_time)
                        for c in cands)
            if later:
                out.append(cut)
                break
    return sorted(set(out))


# ---------------------------------------------------------------------------
# the route checkpoint
# ---------------------------------------------------------------------------
def checkpoint_entries(book_state: Mapping[str, Any], *, frames: Mapping[str, Any],
                       regime_csv: str, data_paths: Mapping[str, str],
                       fill_law: str,
                       last_day_by_inst: "Mapping[str, Any] | None" = None) -> dict:
    """Schema-2 entries for the cross-day sleeves, under the track1_params identity.

    Only the cross-day sleeves get an entry. `roska4_calm` and `roska4_stress` open and close
    inside one session, so there is no history for them to resume from — `empty_payload`
    still creates them, because present-but-empty says "accounted for" where absent would say
    "nobody thought about it". Their coverage lives in the window ledger.

    `last_day` comes from the cut instant, so the checkpoint and the book cannot disagree
    about where the run stopped.

    Stage 5ZK adds `last_day_by_inst`, and it overrides that per instrument for one measured
    reason: at a window close the parquet is NOT yet complete for the cut day. The daily
    append runs at 13:45 ET, so at 15:55 the store holds today only through 13:44 while
    yesterday runs to 23:59 — and the next append backfills today's afternoon, which sits
    below the cut a fingerprint through today would use. Measured on MES and MNKD: a
    fingerprint through the newest stored day does NOT survive the next append; one through
    the day before it does. A checkpoint whose `last_day` is the cut day is therefore refused
    by every later resume, and refused for a reason that looks like data corruption.

    Omitted (the default) the cut-derived day is used exactly as before, so the bootstrap path
    that has always passed complete history is byte-identical.

    `fill_law` is required and has no default. It is the law the RUN used, and it goes into the
    identity hash — so a checkpoint written from artifact-law rows is refused by a
    production-law run, and the other way round. That refusal is the point: the two laws
    produce different exits, and a resume that ignored the difference would seed a position the
    running engine would never have held.
    """
    cut = pd.Timestamp(book_state["cut_instant"])
    last_day = (cut.tz_localize(None) if cut.tz is not None else cut).normalize()

    held_by = {}
    for row in book_state.get("positions", []):
        held_by[(row["sleeve"], row["instrument"])] = row

    out: dict = {}
    for sleeve in rc.CHECKPOINTED_SLEEVES:
        insts = {}
        for inst in tp.SLEEVE_INSTRUMENTS.get(sleeve, ()):
            df = frames.get(inst)
            if df is None:
                continue
            cfg = tp.sleeve_config(sleeve, inst, regime_csv=regime_csv,
                                   data_path=data_paths.get(inst, ""),
                                   fill_law=fill_law)
            readable, phash = rp.identity(cfg)
            row = held_by.get((sleeve, inst))
            pos = None
            if row is not None:
                # The engine-shaped open position the resume seeds from. Direction, entry
                # and stop only: quantity and risk live in the BOOK, and recording them in
                # two places is two chances to disagree.
                pos = {"dir": row["direction"], "entry": row.get("entry_price"),
                       "stop": row.get("stop_price"),
                       "entry_day": str(pd.Timestamp(row["entry_time"]).date())}
            inst_day = (last_day_by_inst or {}).get(inst)
            inst_day = pd.Timestamp(inst_day).normalize() if inst_day is not None else last_day
            insts[inst] = rc.make_entry(df, inst_day, pos, route=tp.ROUTE, sleeve=sleeve,
                                        params=readable, params_hash=phash,
                                        data_source=tp.file_identity(
                                            data_paths.get(inst, "")))
        if insts:
            out[sleeve] = insts
    return out


def write(book_state: Mapping[str, Any], *, entries: Mapping[str, Any],
          book_path: str, checkpoint_path: str = rc.DEFAULT_PATH) -> dict:
    """Write both artefacts. The checkpoint goes through `save_route`, so the scoped merge
    and its `ScopeViolation` assertion apply — another route's keys cannot be touched."""
    bp = Path(book_path)
    bp.parent.mkdir(parents=True, exist_ok=True)
    tmp = bp.with_suffix(bp.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(book_state), indent=1, default=str), encoding="utf-8")
    tmp.replace(bp)
    payload = rc.save_route(entries, route=tp.ROUTE, path=checkpoint_path)
    return {"book_path": str(bp), "checkpoint_path": str(checkpoint_path),
            "sleeves_written": sorted(entries)}


def accepts(checkpoint_path: str, *, sleeve: str, inst: str, frame,
            regime_csv: str, data_path: str, fill_law: str):
    """`route_checkpoint.usable` for one instrument, under the Track 1 identity.

    Returns whatever `usable` returns — `Resumed` or a `Refusal` carrying a CODE. The code is
    the point: v1 returned a bare `None` for four distinct conditions and reconstructing
    which one fired meant diffing hashes out of log lines.
    """
    payload = rc.load(checkpoint_path)
    entry = rc.get_entry(payload, tp.ROUTE, sleeve, inst)
    _readable, phash = tp.sleeve_identity(sleeve, inst, regime_csv=regime_csv,
                                          data_path=data_path, fill_law=fill_law)
    return rc.usable(entry, frame, route=tp.ROUTE, params_hash=phash)
