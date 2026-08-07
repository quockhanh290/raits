"""global_index/test_statement.py — reading IBKR's own record of what was traded

The runner's trade_log is written by the runner, so it can only be as right as the
runner was. Three separate failures this week left it wrong in three different ways:

  2026-08-03  send_order misread three filled OPENs as Cancelled, so no fill price was
              logged for any of them. One whole trade (M2K SHORT 2988.00 → 2993.20)
              left no trace in any local file.
  2026-08-05  a stop fired; the runner sends no order for that, so nothing wrote a
              CLOSE record. reqExecutions had forgotten it a day later.
  2026-08-06  same again.

The statement is the one account of events the runner did not author. This module
parses it and pairs the fills, so the log can be checked against something independent
rather than against itself.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from global_index.statement import pair_fifo, parse_transactions

# Trimmed from DUR125337.TRANSACTIONS.7D.csv — the shapes that matter.
_CSV = """Statement,Header,Field Name,Field Value
Statement,Data,Title,Transaction History
Summary,Data,Base Currency,CAD
Transaction History,Header,Date,Account,Description,Transaction Type,Symbol,Quantity,Price,Price Currency,Gross Amount ,Commission,Net Amount
Transaction History,Data,2026-08-06,DUR125337,M2K 18SEP26 Position MTM,Position MTM,M2KU6,-,-,-,114.2141,-,114.2141
Transaction History,Data,2026-08-06,DUR125337,M2K 18SEP26,Buy,M2KU6,1.0,3038.6,USD,-21291.47(1),-0.854854,-207.56
Transaction History,Data,2026-08-06,DUR125337,FX Translations P&L,Adjustment,-,-,-,-,-6.56,-,-6.56
Transaction History,Data,2026-08-05,DUR125337,CAD Credit Interest for Jul-2026,Credit Interest,-,-,-,-,1374.32,-,1374.32
Transaction History,Data,2026-08-05,DUR125337,M2K 18SEP26,Sell,M2KU6,-1.0,3033.0,USD,21249.19(1),-0.854732,52.39
Transaction History,Notes,"1. Values shown are in notional terms."
"""


def _rows(tmp_path):
    p = tmp_path / "stmt.csv"
    p.write_text(_CSV, encoding="utf-8")
    return p


# ── parsing ───────────────────────────────────────────────────────────────────

def test_st1_only_real_fills_are_trades(tmp_path):
    """Position MTM, interest and FX adjustments are cash events, not trades.

    Folding them in would put the CAD interest credit — 1,374.32 in one line, larger
    than most trades — into trading P&L.
    """
    trades, cash = parse_transactions(_rows(tmp_path))
    assert [t["inst"] for t in trades] == ["M2K", "M2K"], (
        "only Buy/Sell rows are fills"
    )
    kinds = {c["type"] for c in cash}
    assert kinds == {"Position MTM", "Adjustment", "Credit Interest"}, kinds
    assert not any(c["type"] in ("Buy", "Sell") for c in cash)


def test_st2_quantity_is_already_signed(tmp_path):
    """The Quantity column carries the sign: Sell rows are negative.

    Negating it again turns every short into a long — every position paired wrong and
    every P&L came out zero.
    """
    trades, _ = parse_transactions(_rows(tmp_path))
    by_price = {t["price"]: t["signed"] for t in trades}
    assert by_price[3033.0] == -1.0, "a Sell must stay negative"
    assert by_price[3038.6] == +1.0


def test_st3_symbols_map_to_runner_names(tmp_path):
    trades, _ = parse_transactions(_rows(tmp_path))
    assert {t["inst"] for t in trades} == {"M2K"}, "M2KU6 is M2K to the runner"


# ── FIFO pairing ──────────────────────────────────────────────────────────────

def _t(date, inst, signed, price):
    return {"date": date, "inst": inst, "signed": signed, "price": price}


def test_st4_a_short_covered_is_a_short(tmp_path):
    """Sell then Buy is a short round trip, and a higher cover price is a loss."""
    closed, open_lots = pair_fifo([
        _t("2026-08-05", "M2K", -1.0, 3033.0),
        _t("2026-08-06", "M2K", +1.0, 3038.6),
    ])
    assert len(closed) == 1 and not open_lots
    c = closed[0]
    assert c["direction"] == "SHORT"
    assert (c["entry_price"], c["exit_price"]) == (3033.0, 3038.6)
    assert c["pnl"] == pytest.approx(-28.00), "M2K point value is $5"


def test_st5_a_long_round_trip():
    closed, _ = pair_fifo([
        _t("2026-08-03", "MES", +1.0, 7634.75),
        _t("2026-08-05", "MES", -1.0, 7771.50),
    ])
    assert closed[0]["direction"] == "LONG"
    assert closed[0]["pnl"] == pytest.approx(683.75)


def test_st6_close_then_reopen_on_the_same_day():
    """2026-08-05 on MES: the sell closes the old long, the buy opens a new one.

    Pairing these the wrong way round would invent a trade that never happened.
    """
    closed, open_lots = pair_fifo([
        _t("2026-08-03", "MES", +1.0, 7634.75),
        _t("2026-08-05", "MES", -1.0, 7771.50),
        _t("2026-08-05", "MES", +1.0, 7767.00),
    ])
    assert len(closed) == 1
    assert closed[0]["exit_day"] == "2026-08-05"
    assert len(open_lots) == 1 and open_lots[0]["price"] == 7767.00


def test_st7_two_sells_where_the_first_closes_and_the_second_opens():
    """2026-08-05 on MYM: same side twice, only the first is a close."""
    closed, open_lots = pair_fifo([
        _t("2026-08-03", "MYM", +1.0, 53345.0),
        _t("2026-08-05", "MYM", -1.0, 54702.0),
        _t("2026-08-05", "MYM", -1.0, 54631.0),
    ])
    assert len(closed) == 1
    assert closed[0]["pnl"] == pytest.approx(678.50), "MYM point value is $0.50"
    assert open_lots[0]["signed"] == -1.0, "the second sell is a new short"


def test_st9_statement_order_is_newest_first_and_must_not_reverse_a_trade():
    """IBKR lists a statement newest-day-first.

    Paired in file order the closes arrive before the opens, and every trade comes out
    backwards: entry_day after exit_day, LONG reported as SHORT, and a P&L with the
    wrong sign. Run against the real statement this produced
    'MES SHORT 2026-08-05 → 2026-08-03'.
    """
    newest_first = [
        _t("2026-08-05", "MES", -1.0, 7771.50),
        _t("2026-08-03", "MES", +1.0, 7634.75),
    ]
    closed, open_lots = pair_fifo(newest_first)

    assert len(closed) == 1 and not open_lots
    c = closed[0]
    assert c["direction"] == "LONG", "bought first, sold later — that is a long"
    assert c["entry_day"] < c["exit_day"], (
        f"entry must precede exit; got {c['entry_day']} → {c['exit_day']}"
    )
    assert (c["entry_price"], c["exit_price"]) == (7634.75, 7771.50)
    assert c["pnl"] == pytest.approx(683.75)


def test_st10_same_day_order_is_preserved_when_sorting_by_date():
    """Within one day the statement's own sequence decides which fill closes what.

    On 2026-08-05 MES sells at 7771.50 (closing the old long) then buys at 7767.00
    (opening a new one). Reordering those two would invent a trade.
    """
    closed, open_lots = pair_fifo([
        _t("2026-08-05", "MES", -1.0, 7771.50),
        _t("2026-08-05", "MES", +1.0, 7767.00),
        _t("2026-08-03", "MES", +1.0, 7634.75),
    ])
    assert len(closed) == 1
    assert (closed[0]["entry_price"], closed[0]["exit_price"]) == (7634.75, 7771.50)
    assert len(open_lots) == 1 and open_lots[0]["price"] == 7767.00


def test_st8_positions_still_open_are_not_reported_as_closed():
    closed, open_lots = pair_fifo([_t("2026-08-06", "M2K", -1.0, 3015.20)])
    assert closed == []
    assert len(open_lots) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
