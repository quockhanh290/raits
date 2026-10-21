from __future__ import annotations

import pandas as pd


def test_checkpoint_accepts_entry_day_without_entry_time(monkeypatch):
    from global_index import route_checkpoint as rc
    from global_index import route_params as rp
    from global_index import track1_bootstrap as boot
    from global_index import track1_params as tp

    captured = {}
    monkeypatch.setattr(rc, "CHECKPOINTED_SLEEVES", ("roska4_calm",))
    monkeypatch.setattr(tp, "SLEEVE_INSTRUMENTS", {"roska4_calm": ("MES",)})
    monkeypatch.setattr(tp, "sleeve_config", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(rp, "identity", lambda _cfg: ("params", "hash"))
    monkeypatch.setattr(tp, "file_identity", lambda _path: "source")

    def fake_entry(_df, _last_day, pos, **_kwargs):
        captured["pos"] = pos
        return {"pos": pos}

    monkeypatch.setattr(rc, "make_entry", fake_entry)
    state = {
        "cut_instant": "2026-09-28T15:55:00-04:00",
        "positions": [{
            "sleeve": "roska4_calm",
            "instrument": "MES",
            "direction": "LONG",
            "entry_day": "2026-09-24 00:00:00",
            "entry_price": 5000.0,
            "stop_price": 4900.0,
        }],
    }

    out = boot.checkpoint_entries(
        state,
        frames={"MES": pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-09-24"]))},
        regime_csv="spy_daily_live.csv",
        data_paths={"MES": "mes.parquet"},
        fill_law="production",
    )

    assert out["roska4_calm"]["MES"]["pos"]["entry_day"] == "2026-09-24"
    assert captured["pos"]["entry_day"] == "2026-09-24"


def test_checkpoint_refuses_to_guess_when_position_has_no_entry_date(monkeypatch):
    from global_index import route_checkpoint as rc
    from global_index import route_params as rp
    from global_index import track1_bootstrap as boot
    from global_index import track1_params as tp

    monkeypatch.setattr(rc, "CHECKPOINTED_SLEEVES", ("roska4_calm",))
    monkeypatch.setattr(tp, "SLEEVE_INSTRUMENTS", {"roska4_calm": ("MES",)})
    monkeypatch.setattr(tp, "sleeve_config", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(rp, "identity", lambda _cfg: ("params", "hash"))
    state = {
        "cut_instant": "2026-09-28T15:55:00-04:00",
        "positions": [{
            "sleeve": "roska4_calm",
            "instrument": "MES",
            "direction": "LONG",
            "entry_price": 5000.0,
            "stop_price": 4900.0,
        }],
    }

    try:
        boot.checkpoint_entries(
            state,
            frames={"MES": pd.DataFrame({"close": [1.0]}, index=pd.to_datetime(["2026-09-24"]))},
            regime_csv="spy_daily_live.csv",
            data_paths={"MES": "mes.parquet"},
            fill_law="production",
        )
    except ValueError as exc:
        assert "entry_day and entry_time are both absent" in str(exc)
    else:
        raise AssertionError("checkpoint must not guess an entry day")
