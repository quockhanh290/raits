"""Stage 5ZZZ-CC / CD. The stored frame is brought to the market's scale, and a roll is named.

WHY THIS IS A DIRECTION AND NOT A DETAIL. The appender keeps the file where it was built: on a
roll it lifts the NEW bars up to match the file and records the running offset, so the day IBKR
rolls its continuous series the file and a raw fetch stop being the same scale. Both directions
silence the overlap check -- simulated against the REAL appender on copies, 2026-09-04, with a
store one roll-spread low and a sidecar naming another contract:

    CONTRACT ROLLED NKDM6 -> NKDU6 -- re-anchored, offset -530, IQR 0% of the shift
    afterwards BOTH `store - offset` and `live + offset` agreed on all 1,828 shared minutes

The comparison cannot choose. The price the strategy reads can:

    real market      65,115
    store lowered    65,070      (the last stored bar, minutes older -- same scale)
    live lifted      64,585      (a whole roll-spread below the market)

Entry is a MarketOrder and carries no price; the stop is not. `place_stop` sends the number the
strategy computed from these bars, so lifting the live half would put every stop a roll-spread
from where it belongs. The store comes down to the market instead.

Today every offset is 0.0 and the conversion is a no-op. That is why it lands now, before the
day it starts to matter -- IBKR does not publish a roll date and the series does not roll on
our calendar, so the only way to know is to be watching when it happens.
"""
from __future__ import annotations

import inspect
import json

import pandas as pd
import pytest

from global_index import track1_live_source as LS
from global_index import update_ibkr_daily as U


# -- reading the anchor --------------------------------------------------------------------
def _sidecar(tmp_path, entry):
    p = tmp_path / "_splice_offsets.json"
    p.write_text(json.dumps({"MNKD": entry}), encoding="utf-8")
    return p


def test_the_anchor_is_the_offset_and_the_contract(tmp_path):
    p = _sidecar(tmp_path, {"offset": -530.0, "contract": "NKDU6"})
    assert U.stored_anchor("MNKD", p) == (-530.0, "NKDU6")


def test_a_missing_file_refuses_rather_than_reading_as_zero(tmp_path):
    """Zero means "no conversion needed" and is indistinguishable from "could not look it up".
    Folding the second into the first restores today's behaviour on the one day it matters."""
    with pytest.raises(U.SpliceAnchorUnavailable):
        U.stored_anchor("MNKD", tmp_path / "nothing.json")


def test_an_instrument_with_no_entry_refuses(tmp_path):
    p = _sidecar(tmp_path, {"offset": 0.0, "contract": "NKDU6"})
    with pytest.raises(U.SpliceAnchorUnavailable):
        U.stored_anchor("MES", p)


def test_an_unparseable_file_refuses(tmp_path):
    p = tmp_path / "_splice_offsets.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(U.SpliceAnchorUnavailable):
        U.stored_anchor("MNKD", p)


# -- applying it, and the direction --------------------------------------------------------
def _store(tmp_path, closes):
    idx = pd.date_range("2026-09-03 09:00", periods=len(closes), freq="1min", tz="UTC")
    df = pd.DataFrame({"open": closes, "high": closes, "low": closes,
                       "close": closes, "volume": 1}, index=idx)
    p = tmp_path / "store.parquet"
    df.to_parquet(p)
    return p


def test_a_zero_offset_changes_nothing(tmp_path, monkeypatch):
    """The state today, and the reason this can land before the roll: it is inert."""
    p = _store(tmp_path, [64610.0] * 10)
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (0.0, "NKDU6"))
    df = LS.frozen_frame("MNKD", p)
    assert float(df["close"].iloc[-1]) == 64610.0


def test_the_store_comes_DOWN_to_the_market(tmp_path, monkeypatch):
    """The direction, stated as an arithmetic identity rather than a preference.

    The appender's offset is "add this to a raw fetch to reach the stored frame". A store built
    one roll-spread low carries offset -530, and subtracting it returns the market's own level.
    """
    market, spread = 65115.0, 530.0
    p = _store(tmp_path, [market - spread] * 10)
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (-spread, "NKDU6"))
    df = LS.frozen_frame("MNKD", p)
    assert float(df["close"].iloc[-1]) == pytest.approx(market), float(df["close"].iloc[-1])


def test_it_is_not_the_other_direction(tmp_path, monkeypatch):
    """Written as its own test because both directions silence the overlap check and only this
    one keeps a stop order on the price it was computed for. `market + offset` would be
    64,585 -- a whole roll-spread below where the order fills."""
    market, spread = 65115.0, 530.0
    p = _store(tmp_path, [market - spread] * 10)
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (-spread, "NKDU6"))
    got = float(LS.frozen_frame("MNKD", p)["close"].iloc[-1])
    assert got != pytest.approx(market - 2 * spread), "the store was lifted, not lowered"


def test_every_price_column_moves_together(tmp_path, monkeypatch):
    """A shift applied to close alone would leave highs below closes -- bars that cannot exist,
    and indicators built on them would be quietly wrong rather than loudly."""
    p = _store(tmp_path, [64585.0] * 5)
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (-530.0, "NKDU6"))
    df = LS.frozen_frame("MNKD", p)
    for col in ("open", "high", "low", "close"):
        assert float(df[col].iloc[-1]) == pytest.approx(65115.0), col


def test_an_unreadable_anchor_refuses_the_frame(tmp_path, monkeypatch):
    """Fail closed. A frame nobody can place on a scale is not a frame to decide on."""
    p = _store(tmp_path, [64610.0] * 5)

    def boom(inst, path=None):
        raise U.SpliceAnchorUnavailable("no sidecar")

    monkeypatch.setattr(U, "stored_anchor", boom)
    with pytest.raises(LS.LiveSourceRefused):
        LS.frozen_frame("MNKD", p)


def test_the_parquet_on_disk_is_never_written(tmp_path, monkeypatch):
    """The past stays as it was recorded. The conversion is in memory, on the way out."""
    p = _store(tmp_path, [64585.0] * 5)
    before = p.read_bytes()
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (-530.0, "NKDU6"))
    LS.frozen_frame("MNKD", p)
    assert p.read_bytes() == before


# -- naming the roll instead of discovering it ---------------------------------------------
class _Prov:
    def __init__(self, contract):
        self.last_bars_contract = contract


def test_a_rolled_series_is_refused_by_name(monkeypatch):
    """Without this the symptom arrives as `overlap_disagreement` -- "a clock, a contract or a
    source error" -- which is true, useless, and took most of a night to take apart."""
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (0.0, "NKDU6"))
    with pytest.raises(LS.LiveSourceRefused) as e:
        LS._refuse_series_rolled("MNKD", _Prov("NKDZ6"))
    msg = str(e.value)
    assert "NKDZ6" in msg and "NKDU6" in msg, msg
    assert "13:45" in msg, "the message does not say what puts it right"


def test_a_matching_contract_passes_and_reports_it(monkeypatch):
    """Returned on a normal day too, so the quarter leaves a trail rather than one alarm."""
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (0.0, "NKDU6"))
    assert LS._refuse_series_rolled("MNKD", _Prov("NKDU6")) == "NKDU6"


def test_a_provider_that_names_no_contract_is_not_refused(monkeypatch):
    """A file or mock provider has no contract to report and must keep working; silence here
    is absence of evidence, not evidence of a roll."""
    monkeypatch.setattr(U, "stored_anchor", lambda inst, path=None: (0.0, "NKDU6"))
    assert LS._refuse_series_rolled("MNKD", _Prov("")) == ""


def test_the_roll_check_runs_before_the_overlap_check():
    """A roll makes the overlap disagree, so the generic refusal would be the only thing on the
    record if it went first."""
    src = inspect.getsource(LS.live_frame)
    assert src.index("_refuse_series_rolled(") < src.index("_refuse_overlap_disagreement("), src


def test_the_broker_reports_the_contract_the_bars_came_from():
    """The value the check reads. Set where it is known -- the line that resolved it -- and
    forwarded through the provider, because nothing downstream can see past that wrapper."""
    from global_index import ibkr_broker as B

    assert "self.last_bars_contract" in inspect.getsource(B.IBKRBroker._fetch_raw)
    fwd = inspect.getsource(LS.IBKRBarProvider.fetch_session_bars)
    assert "last_bars_contract" in fwd, "the provider drops what the broker recorded"
