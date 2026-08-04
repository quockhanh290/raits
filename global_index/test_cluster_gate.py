"""
global_index/test_cluster_gate.py — active_clusters gate for generate_today_signals

Why the gate exists:
  The NKD entry window is between_time("14:00","15:55") on the instrument's session
  clock. NKD's session_tz is Asia/Tokyo, so that window is 14:00-15:55 JST =
  01:00-02:55 ET — eleven hours before the 14:05-15:55 ET cron slots. run_live_day
  is a run-and-exit subprocess, so nothing looks at the market between 15:55 ET and
  09:31 ET; NKD is only ever evaluated long after its window closed.

  Adding night slots fixes that, but a night run must not disturb live Rổ 4
  positions. Skipping the swing block outright would be the worst possible move:
  diff_desired_vs_held builds `desired_live_keys` from non-None signals only and
  exits every held position whose key is missing (signal_layer.py:110-112). A
  skipped cluster reads as "close everything".

  active_clusters therefore marks held positions in inactive clusters as unchanged
  rather than omitting them — the same mechanism the C4 failure path already uses.

  GATE1: swing gated + swing held  -> no exit, no entry  (the whole point)
  GATE2: contrast — omitting the key really would exit (proves GATE1 is not vacuous)
  GATE3: NKD still fires while swing is gated
  GATE4: NKD gated + NKD held -> no exit (dummy survives the desired[key]=None path)
  GATE5: default None = all clusters active (backward compatibility)
  GATE6: gated engines are never called (night slot must not pay swing compute)
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.signal_layer import (generate_today_signals, diff_desired_vs_held,
                                       CLUSTER_SWING, CLUSTER_NKD, CLUSTER_STRESS)

TODAY = pd.Timestamp("2026-08-04")


class _Held:
    def __init__(self, inst, cluster, direction="LONG", entry_day=TODAY):
        self.inst, self.cluster, self.direction = inst, cluster, direction
        self.entry_day, self.contracts = entry_day, 1


class _SwingEngine:
    """Reports every swing position closed — the state that triggers an exit."""
    def __init__(self, basket=None):
        self.calls, self._basket = 0, (basket if basket is not None else {"MES": None,
                                                                          "MYM": None})

    def desired_basket(self, *_a, **_k):
        self.calls += 1
        return dict(self._basket)


class _NkdEngine:
    def __init__(self, sig=None):
        self.calls, self._sig = 0, sig

    def desired_position(self, *_a, **_k):
        self.calls += 1
        return dict(self._sig) if self._sig else None


def _ohlc():
    """OHLC frame spanning >14 sessions — daily_atr_series() resamples to daily and
    ATR14 is NaN with less history, which to_candidate rejects outright."""
    idx = pd.date_range("2026-07-01", "2026-08-04 23:00", freq="30min")
    return pd.DataFrame({"open": 100.0, "high": 101.0, "low": 99.0,
                         "close": 100.0, "volume": 1.0}, index=idx)


def _run(active, held, swing=None, nkd=None):
    swing = swing or _SwingEngine()
    nkd = nkd or _NkdEngine()
    ents, exits = generate_today_signals(
        swing_engine=swing, swing_dfs={"MES": _ohlc(), "MYM": _ohlc()},
        swing_labels={}, swing_costs={},
        nkd_engine=nkd, nkd_df=_ohlc(), nkd_labels={}, nkd_cost=None,
        nkd_inst="MNKD",
        stress_engine=None, stress_bars_1015={}, today_regime="Normal",
        held=held, point_values={"MES": 5.0, "MYM": 0.5, "MNKD": 0.5},
        contracts_by_inst={"MES": 1, "MYM": 1, "MNKD": 1},
        today=TODAY, active_clusters=active,
    )
    return ents, exits, swing, nkd


# ── tests ─────────────────────────────────────────────────────────────────────

def test_gate1_swing_positions_untouched_when_gated():
    """The reason the gate exists: a night NKD run must not close MES/MYM."""
    held = [_Held("MES", CLUSTER_SWING), _Held("MYM", CLUSTER_SWING)]
    ents, exits, _, _ = _run({CLUSTER_NKD}, held)
    assert exits == [], f"gated swing must not be exited, got {exits}"
    assert [e for e in ents if e["cluster"] == CLUSTER_SWING] == []


def test_gate2_contrast_missing_key_really_does_exit():
    """Proves GATE1 tests something: omitting the key exits the position."""
    held = [_Held("MES", CLUSTER_SWING)]
    ents, exits = diff_desired_vs_held({}, held)      # key simply absent
    assert len(exits) == 1 and exits[0].inst == "MES", \
        "an absent key must exit — this is the trap the gate avoids"


def test_gate3_nkd_still_fires_while_swing_is_gated():
    held = [_Held("MES", CLUSTER_SWING)]
    nkd = _NkdEngine({"direction": "LONG", "entry": 63000.0, "stop": 62900.0,
                      "entry_day": TODAY})
    ents, exits, _, _ = _run({CLUSTER_NKD}, held, nkd=nkd)
    assert exits == []
    assert [e for e in ents if e["cluster"] == CLUSTER_NKD], "NKD must still be able to enter"


def test_gate4_nkd_position_untouched_when_nkd_gated():
    """desired[nkd_key] = None must not clobber the hold-dummy."""
    held = [_Held("MNKD", CLUSTER_NKD)]
    ents, exits, _, _ = _run({CLUSTER_SWING}, held)
    assert exits == [], f"gated NKD must not be exited, got {exits}"


def test_gate5_default_none_keeps_all_clusters_active():
    """Every existing caller passes nothing — behaviour must be unchanged."""
    held = [_Held("MES", CLUSTER_SWING)]
    ents, exits, swing, nkd = _run(None, held)
    assert swing.calls == 1 and nkd.calls == 1, "all engines run by default"
    assert len(exits) == 1, "engine reported the trade closed → exit, as before"


def test_gate6_gated_engines_are_not_called():
    """Night slots run every 5 minutes; paying for a swing replay would overrun."""
    _, _, swing, nkd = _run({CLUSTER_NKD}, [_Held("MES", CLUSTER_SWING)])
    assert swing.calls == 0, "gated swing engine must not be invoked"
    assert nkd.calls == 1

    _, _, swing2, nkd2 = _run({CLUSTER_SWING}, [])
    assert nkd2.calls == 0, "gated NKD engine must not be invoked"
    assert swing2.calls == 1


def test_gate7_stress_gated_out_does_not_raise():
    """stress_engine is None here; gating it off must not touch that path."""
    _run({CLUSTER_NKD}, [])
    _run({CLUSTER_SWING, CLUSTER_NKD}, [])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
