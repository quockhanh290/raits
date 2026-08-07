"""global_index/statement.py — read IBKR's own account of what was traded.

The runner writes trade_log itself, so it can only be as right as the runner was.
Three separate failures in one week left it wrong three different ways:

  2026-08-03  send_order misread three filled OPENs as Cancelled (ib_insync turns any
              IBKR message outside its warning set into a client-side cancel), so no
              fill price was logged. One entire trade — M2K SHORT 2988.00 → 2993.20 —
              left no trace in any local file.
  2026-08-05  a stop fired. The runner sends no order for that, so nothing wrote a
              CLOSE record, and reqExecutions had dropped the fill a day later.
  2026-08-06  the same again.

A statement is the one account of events the runner did not author, which is the only
kind worth reconciling against. Everything here is pure — parse and pair, no I/O beyond
reading the file — so it can be tested without a broker.

Statements come from Account Management → Reports → Activity, or from the Flex Web
Service once a token is configured.
"""
from __future__ import annotations

import csv
from pathlib import Path

# IBKR contract symbols carry the expiry; the runner works in bare instrument names.
_IBKR_SYMBOL_TO_INST = {
    "MESU6": "MES", "MNQU6": "MNQ", "MYMU6": "MYM", "M2KU6": "M2K", "NKDU6": "MNKD",
}

# Rows that move cash without being a trade. Folding these into trading P&L would put
# the monthly CAD interest credit — 1,374.32 on a single line, larger than most trades
# — into the strategy's results.
_CASH_TYPES = ("Position MTM", "Credit Interest", "Debit Interest", "Adjustment",
               "Deposits/Withdrawals", "Other Fees", "Dividends")


def _inst(symbol: str) -> str:
    if symbol in _IBKR_SYMBOL_TO_INST:
        return _IBKR_SYMBOL_TO_INST[symbol]
    # Fall back to stripping a trailing month/year code (MESU6 → MES) rather than
    # guessing: an unrecognised symbol should still be readable, just not silently.
    return symbol[:-2] if len(symbol) > 3 and symbol[-1].isdigit() else symbol


def _num(cell: str) -> float:
    """Statement numbers carry footnote markers like '-21291.47(1)'."""
    cell = (cell or "").split("(")[0].strip()
    return float(cell) if cell not in ("", "-") else 0.0


def point_value(inst: str) -> float | None:
    try:
        from futures.basket import BASKET
        c = BASKET.get(inst)
        if c is not None:
            return float(c.point_value)
    except Exception:
        pass
    try:
        from global_index import specs
        s = getattr(specs, "SPECS", {}).get(inst)
        if s is not None:
            return float(s.point_value)
    except Exception:
        pass
    return None


def parse_transactions(path) -> "tuple[list[dict], list[dict]]":
    """(trades, cash_events) from an IBKR Transaction History CSV.

    Trades keep `signed` straight from the Quantity column, which ALREADY carries the
    sign — Sell rows are negative. Negating it turns every short into a long, which
    pairs every position the wrong way round and produces a P&L of exactly zero.
    """
    trades: list[dict] = []
    cash: list[dict] = []
    with open(Path(path), encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 13 or row[0] != "Transaction History" or row[1] != "Data":
                continue
            date, desc, ttype, symbol = row[2], row[4], row[5], row[6]
            if ttype in ("Buy", "Sell"):
                trades.append({
                    "date": date,
                    "inst": _inst(symbol),
                    "signed": _num(row[7]),      # already signed — do not negate
                    "price": _num(row[8]),
                    "commission": _num(row[11]),
                    "net_amount": _num(row[12]),
                })
            elif ttype in _CASH_TYPES:
                cash.append({"date": date, "type": ttype, "description": desc,
                             "inst": _inst(symbol) if symbol not in ("-", "") else None,
                             "amount": _num(row[12])})
    return trades, cash


def pair_fifo(trades: list[dict]) -> "tuple[list[dict], list[dict]]":
    """(closed_trades, still_open_lots), matching fills first-in-first-out per instrument.

    FIFO is IBKR's own convention for futures, so pairing this way keeps our closed
    trades aligned with the statement rather than inventing a second interpretation.

    A fill on the opposite side to the oldest open lot closes it; a fill on the same
    side opens a new one. That distinction is what separates "close then re-enter on
    the same day" from a trade that never happened.

    Fills are put in date order first, because IBKR writes a statement newest-day-first.
    Paired as they appear, the closes arrive before the opens and every trade comes out
    reversed — entry_day after exit_day, a long reported as a short, the P&L sign
    flipped. The sort is stable, so the statement's own sequence within a day is kept:
    that sequence is what says a sell closed the old position before the next buy
    opened a new one.
    """
    books: dict[str, list[dict]] = {}
    closed: list[dict] = []
    for t in sorted(trades, key=lambda x: x["date"]):
        lots = books.setdefault(t["inst"], [])
        if lots and (lots[0]["signed"] > 0) != (t["signed"] > 0):
            o = lots.pop(0)
            pv = point_value(t["inst"])
            long_side = o["signed"] > 0
            qty = abs(t["signed"])
            pnl = (((t["price"] - o["price"]) * pv * qty * (1 if long_side else -1))
                   if pv else None)
            closed.append({
                "inst": t["inst"],
                "direction": "LONG" if long_side else "SHORT",
                "contracts": qty,
                "entry_day": o["date"], "exit_day": t["date"],
                "entry_price": o["price"], "exit_price": t["price"],
                "pnl": pnl,
                "commission": (o.get("commission", 0.0) or 0.0)
                              + (t.get("commission", 0.0) or 0.0),
            })
        else:
            lots.append(t)
    return closed, [lot for lots in books.values() for lot in lots]
