"""Track 1's per-day series, from Track 1 evidence only. Plan stage 3.

The legacy runner published `snapshots[]` — one row per day with equity, P&L and exposure — and
the page's history panels were built on it. Track 1 publishes no such file. This builds the series
from what Track 1 does write, and it holds one rule above all others:

    a day with no evidence is REFUSED, never shown as zero.

A zero P&L reads exactly like "the route traded and broke even", and a zero on a day the route
cannot prove it observed is a claim nobody measured. So each day carries a `status`:

    evidenced   the post-window audit for the day exists and the trade log could be read
    pending     today, before the day's audit is written (~16:15 ET)
    refused     a past trading day with no audit — the day's activity is not proven complete

and the running (cumulative) realised P&L STOPS at the first refused day: every later cumulative
figure is None, because a sum over a gap is not a sum.

Realised P&L is computed from the trade log's OWN prices — OPEN fill vs CLOSE fill, times the
contract's point value, times contracts, minus the commissions of BOTH legs — and never from the CLOSE row's
`pnl_sized`. `broker.Fill.pnl_sized` is documented "realized on CLOSE (verify mode: from ledger)",
and the legacy log holds CLOSE rows with a moved price and `pnl_sized: 0.0`. A close that cannot
be paired with its open is reported, and its day's realised figure is None.

The series starts at the paper epoch: the first day an order journal row carries a broker order
id (2026-09-24). Days before it were shadow days; the route could not trade, and a P&L row for
them would describe nothing.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from monitor.backend.paper_evidence_reader import T1_PATHS, TRACK1_ROUTE, _track1_epoch

AUDITS = "global_index/track1_runtime/audits"
COVERAGE = "global_index/track1_runtime/window_coverage"
REGIME = "global_index/track1_runtime/regime_label"
ET = "America/New_York"


def _today_et() -> dt.date:
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo(ET)).date()


def _stamp(day: dt.date) -> str:
    return day.strftime("%Y%m%d")


def _jsonl(path: Path) -> "list[dict] | None":
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            v = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def _point_value(inst: str) -> "float | None":
    try:
        from global_index.track1_params import _contract
        return float(_contract(inst).point_value)
    except Exception:                                   # noqa: BLE001
        return None


def _money(x: "float | None") -> "float | None":
    return None if x is None else round(float(x), 2)


def _pair(close: dict, opens: list) -> "dict | None":
    """The OPEN a CLOSE belongs to: by trade_id when both carry one, else instrument +
    direction + entry day — the identity the safety sweeps' CLOSE rows carry."""
    tid = str(close.get("trade_id") or "")
    if tid:
        for o in opens:
            if str(o.get("trade_id") or "") == tid:
                return o
    for o in opens:
        if (o.get("inst") == close.get("inst") and o.get("direction") == close.get("direction")
                and str(o.get("entry_day") or "")[:10] == str(close.get("entry_day") or "")[:10]):
            return o
    return None


def _realised(close: dict, opens: list) -> "tuple[float | None, str | None]":
    o = _pair(close, opens)
    if o is None:
        return None, "close_without_open"
    pv = _point_value(str(close.get("inst") or ""))
    try:
        entry, exit_ = float(o["fill_price"]), float(close["fill_price"])
        n = int(close.get("filled_qty") or close.get("contracts") or 0)
    except (KeyError, TypeError, ValueError):
        return None, "price_missing"
    if pv is None or n <= 0:
        return None, "no_point_value_or_size"
    sign = 1.0 if str(close.get("direction") or "").upper() == "LONG" else -1.0
    gross = sign * (exit_ - entry) * pv * n
    # A round trip pays twice. The open's commission is booked here, on the day the trade
    # closes, so the realised figure of a round trip is what it really cost; the open day shows
    # its commission separately in `open_close_commissions` and never inside `realised_pnl`.
    return gross - float(close.get("commission") or 0.0) - float(o.get("commission") or 0.0), None


def build_series(root: "str | Path", *, today: "dt.date | None" = None) -> dict[str, Any]:
    from raits.live.trading_calendar import is_trading_day

    root = Path(root)
    today = today or _today_et()
    epoch = _track1_epoch(root)
    if epoch is None:
        return {"days": [], "epoch": None, "status": "no_paper_epoch",
                "reading": "no Track 1 order journal row carries a broker order id; the route "
                           "has no paper days"}
    rows = _jsonl(root / T1_PATHS["trade_log"])
    trade_log_readable = rows is not None
    rows = [r for r in (rows or []) if str(r.get("route") or "") == TRACK1_ROUTE]
    opens = [r for r in rows if str(r.get("type")).upper() == "OPEN"]
    closes = [r for r in rows if str(r.get("type")).upper() == "CLOSE"]

    days: list = []
    cumulative: "float | None" = 0.0
    d = dt.date.fromisoformat(epoch)
    while d <= today:
        if not is_trading_day(d):
            d += dt.timedelta(days=1)
            continue
        day = d.isoformat()
        audit = _jsonl(root / AUDITS / f"track1_audit_{_stamp(d)}.jsonl")
        day_row = next((a for a in reversed(audit or []) if a.get("scope") == "day"), None)
        coverage = _jsonl(root / COVERAGE / f"window_coverage_{_stamp(d)}.jsonl")
        regime_rows = _jsonl(root / REGIME / f"regime_label_{_stamp(d)}.jsonl")
        # The file for day D carries the label computed from closes THROUGH D-1 — the label the
        # route traded D under. Its own `label_date` is kept beside it so nobody reads it as D's.
        # Measured 2026-09-24: that day's file ends with a row labelled from 24/9's OWN close,
        # written that evening — so "the last row" is the NEXT session's label. Only a label dated
        # strictly before D is the one D traded under.
        reg = next((r for r in reversed(regime_rows or [])
                    if r.get("label") and str(r.get("label_date") or "") < day), None)
        day_opens = [o for o in opens if str(o.get("entry_day") or "")[:10] == day]
        day_closes = [c for c in closes if str(c.get("exit_day") or "")[:10] == day]

        if not trade_log_readable:
            status, reason = "refused", "the Track 1 trade log could not be read"
        elif day_row is None and d == today:
            status, reason = "pending", "today's post-window audit is not written yet (~16:15 ET)"
        elif day_row is None:
            status, reason = "refused", ("no post-window audit exists for this trading day, so "
                                         "the day's activity is not proven complete")
        else:
            status, reason = "evidenced", None

        realised = None
        unpaired = []
        commissions = None
        if status == "evidenced":
            total = 0.0
            for c in day_closes:
                pnl, why = _realised(c, opens)
                if pnl is None:
                    unpaired.append({"inst": c.get("inst"), "reason": why})
                else:
                    total += pnl
            realised = None if unpaired else _money(total)
            commissions = _money(sum(float(o.get("commission") or 0.0) for o in day_opens)
                                 + sum(float(c.get("commission") or 0.0) for c in day_closes))
        # A sum over a gap is not a sum: the first day without a realised figure ends the chain.
        if cumulative is not None and realised is not None:
            cumulative = _money(cumulative + realised)
        elif status != "pending":
            cumulative = None

        days.append({
            "date": day, "status": status, "refusal_reason": reason,
            "audit_verdict": (day_row or {}).get("verdict"),
            "window_coverage_rows": None if coverage is None else len(coverage),
            "regime_traded_under": (reg or {}).get("label"),
            "regime_label_date": (reg or {}).get("label_date"),
            "opens": [{"inst": o.get("inst"), "direction": o.get("direction"),
                       "contracts": o.get("contracts"), "fill_price": o.get("fill_price"),
                       "order_id": o.get("order_id"), "sleeve": o.get("cluster")}
                      for o in day_opens] if status == "evidenced" else None,
            "closes": len(day_closes) if status == "evidenced" else None,
            "unpaired_closes": unpaired or None,
            "realised_pnl": realised,
            "open_close_commissions": commissions,
            "cumulative_realised_pnl": cumulative if status == "evidenced" else None,
        })
        d += dt.timedelta(days=1)

    return {"days": days, "epoch": epoch, "status": "built",
            "reading": ("one row per trading day since the first sent order; refused days are "
                        "listed with the reason and never shown as zero"),
            "pnl_basis": ("OPEN vs CLOSE fill price x point value x contracts, minus both legs' "
                          "commissions, booked on the close day; never the CLOSE row's "
                          "pnl_sized")}
