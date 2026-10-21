# -*- coding: utf-8 -*-
"""The tool that measures real Calm fills against the backtest's 10:00 / 15:55 opens.

A gap report that cannot be red is worthless, so the cases that matter most are the ones where it
must refuse to print a number: a missing bar, a fill on another price scale, no fills at all.
"""
import json

import pandas as pd
import pytest

from global_index import calm_execution_gap as G

DAY = "2026-10-06"


def _frame(open_1000=7000.00, open_1555=7010.00):
    """Naive-ET one-minute bars with the two opens the tool reads, and nothing else."""
    idx = pd.DatetimeIndex([f"{DAY} 10:00", f"{DAY} 15:55"])
    return pd.DataFrame({"open": [open_1000, open_1555], "high": 0.0, "low": 0.0,
                         "close": 0.0, "volume": 1.0}, index=idx)


def _open_row(fill, *, direction="LONG", inst="MES", ts=f"{DAY}T14:00:16+00:00", planned=6999.75):
    return {"type": "OPEN", "cluster": G.CLUSTER, "inst": inst, "direction": direction,
            "entry_day": DAY, "fill_price": fill, "expected_entry": planned, "ts": ts}


def _close_row(fill, *, direction="LONG", inst="MES", reason="TIME_EXIT",
               ts=f"{DAY}T19:54:25+00:00"):
    return {"type": "CLOSE", "cluster": G.CLUSTER, "inst": inst, "direction": direction,
            "exit_day": DAY, "exit_reason": reason, "fill_price": fill, "ts": ts}


def test_a_long_entry_filled_above_the_open_is_worse_by_that_many_ticks_and_dollars():
    (m,) = G.measure([_open_row(7000.50)], {"MES": _frame()})
    assert m["status"] == "measured"
    assert m["ticks"] == pytest.approx(2.0) and m["usd"] == pytest.approx(2.50)     # MES: $1.25 a tick
    assert m["planned_vs_open_ticks"] == pytest.approx(1.0)                          # 09:59 close was 6999.75


def test_a_long_exit_filled_below_the_open_is_worse():
    (m,) = G.measure([_close_row(7009.00)], {"MES": _frame()})
    assert m["ticks"] == pytest.approx(4.0) and m["usd"] == pytest.approx(5.00)


def test_a_better_fill_than_the_backtest_reads_negative_not_zero():
    a, b = G.measure([_open_row(6999.50), _close_row(7011.00)], {"MES": _frame()})
    assert a["ticks"] < 0 and b["ticks"] < 0


def test_the_sign_is_right_for_a_short_too():
    sopen, sclose = G.measure([_open_row(6999.50, direction="SHORT"),
                               _close_row(7011.00, direction="SHORT")], {"MES": _frame()})
    assert sopen["ticks"] == pytest.approx(2.0)      # a short entry SELLS: below the open is worse
    assert sclose["ticks"] == pytest.approx(4.0)     # a short exit BUYS: above the open is worse


def test_latency_is_seconds_after_the_instant_the_order_was_meant_to_go():
    a, b = G.measure([_open_row(7000.0), _close_row(7010.0)], {"MES": _frame()})
    assert a["latency_s"] == pytest.approx(16.0)             # 14:00:16Z = 10:00:16 ET
    assert b["latency_s"] == pytest.approx(-35.0)            # 15:54:25 ET is 35 s BEFORE 15:55


def test_a_missing_bar_is_unmeasured_never_a_zero_gap():
    (m,) = G.measure([_close_row(7009.0)], {"MES": _frame().iloc[:1]})      # no 15:55 bar yet
    assert m["status"] == "unmeasured" and "15:55" in m["reason"] and "ticks" not in m


def test_a_fill_on_another_price_scale_is_unmeasured_not_a_giant_gap():
    (m,) = G.measure([_open_row(5400.0)], {"MES": _frame()})
    assert m["status"] == "unmeasured" and "scale" in m["reason"]


def test_an_instrument_with_no_bars_and_a_row_without_a_price_are_unmeasured():
    a, = G.measure([_open_row(7000.0)], {})
    b, = G.measure([{**_open_row(7000.0), "fill_price": None}], {"MES": _frame()})
    assert a["status"] == b["status"] == "unmeasured"


def test_only_calm_opens_and_calm_time_exits_are_read(tmp_path):
    log = tmp_path / "t.jsonl"
    rows = [_open_row(7000.0), _close_row(7010.0), _close_row(7010.0, reason="MAX_HOLD"),
            {**_open_row(7000.0), "cluster": "roska4_swing"}]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n{torn", encoding="utf-8")
    got = G.load_rows(log)
    kinds = [(r["type"], r.get("exit_reason")) for r in got]
    assert kinds == [("OPEN", None), ("CLOSE", "TIME_EXIT"), ("TORN", None)], kinds


def test_summary_per_leg():
    ms = G.measure([_open_row(7000.50), _open_row(7000.00, inst="MES"),
                    _close_row(7009.00)], {"MES": _frame()})
    s = G.summarize(ms)
    assert s["OPEN"]["n_measured"] == 2 and s["OPEN"]["mean_ticks"] == pytest.approx(1.0)
    assert s["CLOSE"]["n_measured"] == 1 and s["CLOSE"]["mean_usd"] == pytest.approx(5.0)


# ── the command, end to end ──────────────────────────────────────────────────

def _write_bars(data_dir, opens=True):
    f = _frame()
    f = f if opens else f.iloc[:1]
    f.index = f.index.tz_localize(G.ET).tz_convert("UTC")
    data_dir.mkdir(parents=True, exist_ok=True)
    f.to_parquet(data_dir / "ES_continuous_1m_8y.parquet")


def _run(tmp_path, rows, *, bars=True, capsys=None, day=None):
    log = tmp_path / "t.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    d = tmp_path / "bars"
    if bars is not None:
        _write_bars(d, opens=bars)
    argv = ["--trade-log", str(log), "--data-dir", str(d)] + (["--day", day] if day else [])
    return G.main(argv)


def test_the_command_reports_and_exits_zero_when_it_measured_something(tmp_path, capsys):
    rc = _run(tmp_path, [_open_row(7000.50), _close_row(7009.0)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ENTRY vs 10:00 open: n=1" in out and "EXIT  vs 15:55 open: n=1" in out


def test_no_fills_is_not_a_clean_result(tmp_path, capsys):
    assert _run(tmp_path, []) == 3
    assert "NOT a clean result" in capsys.readouterr().out


def test_fills_with_no_bars_at_all_exit_nonzero_and_say_unmeasured(tmp_path, capsys):
    rc = _run(tmp_path, [_open_row(7000.5), _close_row(7009.0)], bars=None)
    out = capsys.readouterr().out
    assert rc == 2, "nothing could be measured, and the exit code must not call that success"
    assert out.count("UNMEASURED") == 2 and "no fill measured" in out


def test_a_leg_whose_bar_has_not_arrived_is_reported_unmeasured_beside_the_measured_one(tmp_path, capsys):
    rc = _run(tmp_path, [_open_row(7000.5), _close_row(7009.0)], bars=False)   # no 15:55 bar yet
    out = capsys.readouterr().out
    assert rc == 0
    assert "ENTRY vs 10:00 open: n=1" in out
    assert "EXIT  vs 15:55 open: no fill measured (1 unmeasured)" in out and "UNMEASURED" in out


def test_the_day_filter_selects_by_the_fills_own_date(tmp_path, capsys):
    other = {**_open_row(7000.5), "entry_day": "2026-10-07"}
    assert _run(tmp_path, [other], day=DAY) == 3
