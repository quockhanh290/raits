"""Stage 5M-1 — the live route runs the production fill law, and says so.

Read-only: no scheduler, no broker, no order, no live state file. Every checkpoint and every
explanation written here goes under `tmp_path`.

The decision being enforced
---------------------------
The three-blockers report of 2026-08-22 adopted `production_gap_after_15min_break` as the
Track 1 identity. It measured both laws by monkeypatching the one generator that produced the
committed artifacts, and found the book-level difference across floor, vault2025 and vault2026
to be $0 to +$6 — in the SAFE direction, since the production law is the more permissive one
and the published numbers were measured under the more conservative.

The implementation did not follow. `NormalR4Params.fill_law` defaulted to the ARTIFACT law,
and five places took that default:

    four in the route  — the string recorded in the identity hash
    one in the engine  — `track1_sleeves.LiveSleeveSource.detect`, which decides which bars
                         are gap-eligible and therefore WHICH TRADES EXIST

That fifth one is why this suite has a static scan in it. It contains no `fill_law` token, so
the search that found the four identity callsites walked straight past it.

Why an immaterial delta still matters
-------------------------------------
$0 to +$6 over seven years is not worth a re-rating. But the fill law is hashed into
`params_hash`, and a checkpoint is accepted or refused on that hash. A route whose identity
names a law it did not run would accept state computed under the other one. That is the exact
defect Stage 4B removed when the law was a hard-coded literal; a default nobody passed is the
same defect wearing a different hat.
"""
from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from global_index import track1_normal_r4 as NR      # noqa: E402
from global_index import track1_params as tp         # noqa: E402
from global_index import track1_sleeves as sleeves   # noqa: E402

PRODUCTION = "production_gap_after_15min_break"
ARTIFACT = "artifact_all_bars_gappable"
GI = Path(r"d:\raits\global_index")


# ── 1. the policy, as constants ─────────────────────────────────────────────────────────

def test_the_route_names_the_production_law_and_only_once():
    assert tp.LIVE_FILL_LAW == tp.FILL_PRODUCTION == PRODUCTION


def test_the_two_modules_still_agree_about_the_law_strings():
    """The names are defined twice, in the params module and in the engine. They must be the
    same strings or an identity and the engine that produced it describe different runs."""
    assert tp.FILL_PRODUCTION == NR.FILL_PRODUCTION == PRODUCTION
    assert tp.FILL_ARTIFACT == NR.FILL_ARTIFACT == ARTIFACT
    assert set(tp.FILL_LAWS) == set(NR.FILL_LAWS)


def test_the_engine_default_is_the_live_law():
    """A default is what gets taken. This one used to be the artifact law, which is how the
    engine came to run one law while the route believed another."""
    assert NR.NormalR4Params().fill_law == tp.LIVE_FILL_LAW == PRODUCTION


def test_the_artifact_law_is_reachable_only_by_asking_for_it():
    assert NR.NormalR4Params(fill_law=ARTIFACT).fill_law == ARTIFACT
    with pytest.raises(ValueError):
        NR.NormalR4Params(fill_law="whatever_is_convenient")


def test_the_two_laws_are_not_cosmetic_they_change_the_engine():
    """Guards against 'both laws' becoming two labels for the same computation.

    The artifact law forces every bar gap-eligible; the production law passes the source's own
    flags through. If these ever produced the same cache, every other test here would be
    asserting about a string with no consequence behind it.
    """
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2026-08-20 09:30", periods=120, freq="1min", tz="America/New_York")
    df = pd.DataFrame({"open": np.linspace(100, 101, 120), "high": np.linspace(100, 101, 120),
                       "low": np.linspace(100, 101, 120), "close": np.linspace(100, 101, 120),
                       "volume": np.ones(120)}, index=idx)
    art = NR._cache_for(df, NR.NormalR4Params(fill_law=ARTIFACT))
    prod = NR._cache_for(df, NR.NormalR4Params(fill_law=PRODUCTION))
    assert art["hl"] and prod["hl"], "the cache produced no sessions — nothing was compared"
    for day, (_h, _l, _o, isg) in art["hl"].items():
        assert isg.all(), f"the artifact law left a bar non-gappable on {day}"
    # The production side passes the source's own flags through rather than rewriting them.
    # Compared by VALUE: `_swing_cache` memoises on `id(df)`, so object identity here would be
    # testing the memo, not the law.
    from futures._validated_core import _swing_cache, daily_atr_series
    src = _swing_cache(df, daily_atr_series(df))
    differs = False
    for day in prod["hl"]:
        assert np.array_equal(prod["hl"][day][3], src["hl"][day][3]), day
        differs = differs or not np.array_equal(prod["hl"][day][3], art["hl"][day][3])
    assert differs, ("both laws produced the same gap flags on this frame, so nothing here "
                     "distinguishes them — pick a frame where they diverge")


# ── 2. nothing on the live path reaches the artifact law implicitly ─────────────────────

def _production_modules():
    mods = sorted(p for p in GI.glob("*.py") if not p.name.startswith("test_"))
    assert mods, "no production modules found — the scan would pass on nothing"
    return mods


def test_no_production_module_reads_the_engine_default_for_the_routes_law():
    """`NormalR4Params().fill_law` is banned in `global_index/`.

    Not style. It makes the ROUTE's recorded identity a side effect of an ENGINE default —
    correct today only because Stage 5M-1 also moved that default, and silently wrong again the
    day someone moves it back for a reproduction run. The route's law has one name,
    `track1_params.LIVE_FILL_LAW`, and that is what the route reads.
    """
    offenders = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "fill_law"
                    and isinstance(node.value, ast.Call)
                    and getattr(node.value.func, "attr", getattr(node.value.func, "id", ""))
                    == "NormalR4Params"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def test_every_engine_params_built_in_production_states_its_fill_law():
    """The callsite the other scan could never have found.

    `LiveSleeveSource.detect` built `NormalR4Params(ema_period=...)` and took the artifact law
    into the engine — the law that decides which trades exist, not merely what a hash says. It
    carries no `fill_law` token, so a text search for the law walks past it. This asks the
    opposite question: does every construction NAME the law?
    """
    offenders = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name != "NormalR4Params":
                continue
            if not any(k.arg == "fill_law" for k in node.keywords):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def test_the_scan_would_notice_an_offender():
    """Both scans above pass by finding nothing, which is the shape of a check that has
    quietly stopped looking. Hand the same rules a module that does the wrong thing."""
    bad = ("from global_index.track1_normal_r4 import NormalR4Params\n"
           "law = NormalR4Params().fill_law\n"
           "p = NormalR4Params(ema_period=10)\n")
    tree = ast.parse(bad)
    reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Attribute) and n.attr == "fill_law"
             and isinstance(n.value, ast.Call)]
    builds = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and getattr(n.func, "id", "") == "NormalR4Params"
              and not any(k.arg == "fill_law" for k in n.keywords)]
    assert len(reads) == 1 and len(builds) == 2   # the bare read is itself a bare build


# ── 3. the identity the route actually records ──────────────────────────────────────────

IDENT_KW = dict(regime_csv="spy_daily_live.csv",
                data_path="data/cache/futures/ES_continuous_1m_8y.parquet")


def test_sleeve_identity_still_refuses_to_default_the_law():
    """Stage 4B removed the default on purpose. If it comes back, every caller that forgets
    silently gets whatever it is."""
    with pytest.raises(TypeError):
        tp.sleeve_identity("roska4_swing", "MES", **IDENT_KW)


def test_the_live_identity_is_the_production_identity():
    live = tp.sleeve_identity("roska4_swing", "MES", fill_law=tp.LIVE_FILL_LAW, **IDENT_KW)
    prod = tp.sleeve_identity("roska4_swing", "MES", fill_law=PRODUCTION, **IDENT_KW)
    art = tp.sleeve_identity("roska4_swing", "MES", fill_law=ARTIFACT, **IDENT_KW)
    assert live == prod
    assert live != art, "the two laws hash the same — the law is not reaching the identity"
    assert PRODUCTION in live[0] and ARTIFACT not in live[0]


def test_the_checkpoint_report_defaults_to_the_production_identity(tmp_path):
    """`checkpoint_report(fill_law=None)` is what the route calls. It must resolve to the
    live law, and it must still honour an explicit one."""
    import global_index.run_live_day_track1 as entry
    empty = tmp_path / "cp.json"
    empty.write_text(json.dumps({"schema_version": 2, "route": tp.ROUTE, "sleeves": {}}),
                     encoding="utf-8")
    paths = {"MES": "data/cache/futures/ES_continuous_1m_8y.parquet"}
    rows = entry.checkpoint_report(regime_csv="spy_daily_live.csv", data_paths=paths,
                                   path=str(empty))
    assert rows, "the report produced no rows — nothing was checked"
    mine = {r["params_hash"] for r in rows if r.get("inst") == "MES"}
    want = {tp.sleeve_identity(s, "MES", regime_csv="spy_daily_live.csv",
                               data_path=paths["MES"], fill_law=PRODUCTION)[1]
            for s in ("roska4_swing",)}
    assert mine & want, (mine, want)
    art_rows = entry.checkpoint_report(regime_csv="spy_daily_live.csv", data_paths=paths,
                                       path=str(empty), fill_law=ARTIFACT)
    assert {r["params_hash"] for r in art_rows} != {r["params_hash"] for r in rows}


# ── 4. a checkpoint written under one law is refused by the other, both ways ────────────

def _checkpoint(tmp_path, law):
    """A one-instrument checkpoint written under `law`, entirely inside tmp_path."""
    import numpy as np
    import pandas as pd
    from global_index import track1_bootstrap as boot
    d = tmp_path / law[:8]
    d.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2026-08-20 09:30", periods=60, freq="1min", tz="America/New_York")
    frame = pd.DataFrame({"open": np.ones(60), "high": np.ones(60), "low": np.ones(60),
                          "close": np.ones(60), "volume": np.ones(60)}, index=idx)
    pq = d / "MES.parquet"
    frame.tz_localize(None, level=0) if False else None
    frame.to_parquet(pq)
    paths = {"MES": str(pq)}
    state = {"schema_version": 2, "route": tp.ROUTE, "window": "live",
             "cut_instant": "2026-08-20T15:55:00", "equity": 0.0, "cur_day": "2026-08-20",
             "peak_equity": 0.0, "day_start_equity": 0.0, "positions": [],
             "booked_counter": {}, "counters": {}}
    entries = boot.checkpoint_entries(state, frames={"MES": frame},
                                      regime_csv="spy_daily_live.csv",
                                      data_paths=paths, fill_law=law)
    ck = d / "cp.json"
    boot.write(state, entries=entries, book_path=str(d / "book.json"),
               checkpoint_path=str(ck))
    return str(ck), frame, paths


def test_a_checkpoint_records_the_law_it_was_written_under(tmp_path):
    ck, _f, _p = _checkpoint(tmp_path, PRODUCTION)
    payload = json.loads(Path(ck).read_text(encoding="utf-8"))
    blob = json.dumps(payload)
    assert PRODUCTION in blob and ARTIFACT not in blob


@pytest.mark.parametrize("written,read_as", [(ARTIFACT, PRODUCTION), (PRODUCTION, ARTIFACT)])
def test_a_cross_law_checkpoint_is_refused_in_both_directions(tmp_path, written, read_as):
    """Symmetry matters. A guard that only refused artifact-under-production would let a
    reproduction run resume from live state, which is the same mistake pointing the other
    way."""
    from global_index import track1_bootstrap as boot
    ck, frame, paths = _checkpoint(tmp_path, written)
    ok = boot.accepts(ck, sleeve="roska4_swing", inst="MES", frame=frame,
                      regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                      fill_law=written)
    bad = boot.accepts(ck, sleeve="roska4_swing", inst="MES", frame=frame,
                       regime_csv="spy_daily_live.csv", data_path=paths["MES"],
                       fill_law=read_as)
    assert ok, "the matching law was refused — the test proves nothing about the mismatch"
    assert not bad, f"a {written} checkpoint was accepted by a {read_as} run"


# ── 5. the wiring: what the live slot hands to the writers ──────────────────────────────

def test_the_live_slot_hands_the_production_law_to_the_explanation_writer(tmp_path,
                                                                          monkeypatch):
    """A call-site test, not an implementation one: run the slot and intercept what it passes.

    Non-vacuous by construction — if the slot never reaches the writer, `seen` stays empty and
    the test says so rather than passing.
    """
    import test_track1_stage5e_live_source_20260823 as e5

    d = tmp_path / "ledger"
    d.mkdir()
    monkeypatch.setenv("RAITS_WINDOW_LEDGER_DIR", str(d))
    import global_index.window_ledger as wl
    importlib.reload(wl)
    import global_index.run_live_day_track1 as entry
    importlib.reload(entry)
    try:
        class _Allow:
            allow, unverified, reasons = True, (), ()
            def as_dict(self):
                return {"allow": True, "unverified": [], "reasons": []}

        monkeypatch.setattr(entry.fresh, "evaluate", lambda **kw: _Allow())
        seen = {}
        real = entry.emit_explanations
        monkeypatch.setattr(entry, "emit_explanations",
                            lambda *a, **kw: (seen.update(kw) or real(*a, **kw)))

        frozen, live = e5.frames()
        src = e5.S.LiveTrack1Source(bar_provider=e5.S.FrameBarProvider(live),
                                    labels=e5.labels(), frozen_frames=frozen)
        res = entry.observe_live_slot("roska4_calm", "TRACK1_CALM_1000", now_et=e5.NOW,
                                      provider=e5.S.FrameBarProvider(live),
                                      frozen_frames=frozen, live_source=src,
                                      root=str(d.parent))
        assert res["decided"] is True, res
        assert seen, "the slot never reached the explanation writer — nothing was intercepted"
        assert seen["fill_law"] == PRODUCTION, seen["fill_law"]
    finally:
        monkeypatch.delenv("RAITS_WINDOW_LEDGER_DIR", raising=False)
        importlib.reload(wl)
        importlib.reload(entry)


def test_the_route_checkpoint_writer_stamps_the_production_law(tmp_path):
    """`write_route_checkpoint` takes no fill law from its caller, so whatever it picks is what
    every Track 1 checkpoint will carry."""
    import numpy as np
    import pandas as pd
    import global_index.run_live_day_track1 as entry
    idx = pd.date_range("2026-08-20 09:30", periods=60, freq="1min", tz="America/New_York")
    frames, paths = {}, {}
    for inst in tp.SLEEVE_INSTRUMENTS["roska4_swing"]:
        f = pd.DataFrame({"open": np.ones(60), "high": np.ones(60), "low": np.ones(60),
                          "close": np.ones(60), "volume": np.ones(60)}, index=idx)
        pq = tmp_path / f"{inst}.parquet"
        f.to_parquet(pq)
        frames[inst], paths[inst] = f, str(pq)
    out = entry.write_route_checkpoint(
        "roska4_swing", now_et=pd.Timestamp("2026-08-20 15:55", tz="America/New_York"),
        regime_csv="spy_daily_live.csv", data_paths=paths, frames=frames,
        path=str(tmp_path / "cp.json"), book_path=str(tmp_path / "book.json"))
    blob = Path(out["path"]).read_text(encoding="utf-8")
    assert PRODUCTION in blob, "the route checkpoint does not name the production law"
    assert ARTIFACT not in blob, "the route checkpoint still names the artifact law"


def test_the_live_sleeve_source_runs_the_engine_under_the_production_law(monkeypatch):
    """The fifth callsite, checked where it matters: what params reach `run_instrument`.

    This is the one that changes WHICH TRADES EXIST rather than what a hash says, and it is
    the one no `fill_law` search could find.
    """
    seen = []
    monkeypatch.setattr(NR, "run_instrument",
                        lambda df, lab, cost, params, **kw: (seen.append(params) or ([], {})))
    src = sleeves.LiveSleeveSource()
    monkeypatch.setattr(src, "frames", lambda **kw: {"roska4_swing": {"MES": _stub_join()}})

    class _Cost:
        pass
    src.detect(through=None, labels_by_inst={"MES": object()}, costs={"MES": _Cost()},
               sleeves=["roska4_swing"])
    assert seen, "run_instrument was never reached — no params were observed"
    assert [p.fill_law for p in seen] == [PRODUCTION], [p.fill_law for p in seen]


def _stub_join():
    import numpy as np
    import pandas as pd

    class _J:
        frame = pd.DataFrame({"open": np.ones(3), "high": np.ones(3), "low": np.ones(3),
                              "close": np.ones(3), "volume": np.ones(3)},
                             index=pd.date_range("2026-08-20 09:30", periods=3, freq="1min",
                                                 tz="America/New_York"))

        class report:
            code = "ok"
    return _J()


def test_a_caller_supplied_params_object_still_wins(monkeypatch):
    """Reproduction has to remain possible. The route's law is the DEFAULT, not a lock."""
    seen = []
    monkeypatch.setattr(NR, "run_instrument",
                        lambda df, lab, cost, params, **kw: (seen.append(params) or ([], {})))
    src = sleeves.LiveSleeveSource()
    monkeypatch.setattr(src, "frames", lambda **kw: {"roska4_swing": {"MES": _stub_join()}})
    want = NR.NormalR4Params(fill_law=ARTIFACT)
    src.detect(through=None, labels_by_inst={"MES": object()}, costs={"MES": object()},
               params={"MES": want}, sleeves=["roska4_swing"])
    assert [p.fill_law for p in seen] == [ARTIFACT]
