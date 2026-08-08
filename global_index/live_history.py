"""global_index/live_history.py — the dashboard's history, from what is already on disk.

dump_state emitted one snapshot with `entries: []`, `exits: []`, per-cluster P&L of zero
and empty cluster stats, so in live mode the dashboard's Closed Trades, Daily P&L,
Per-Cluster P&L, Regime Attribution, Cluster Statistics and Holding Distribution all
rendered blank. Not a rendering fault — nobody ever wrote the data. It was built as a
status snapshot, and the panels below it need a history.

Both halves already exist and are already reconciled against IBKR's statement:

    trade_log.jsonl     every fill, with the cluster and regime IBKR knows nothing about
    paper_history.json  one system-equity mark per day

So the snapshot list is a pure function of those two. No third store, and therefore no
third thing that can drift out of step with them — which is the failure this codebase
keeps finding.

Everything here is pure. No I/O, no broker, no clock.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from global_index.statement import point_value


def _day(value) -> str | None:
    """Dates arrive as '2026-08-05' or '2026-08-05 00:00:00'."""
    if not value:
        return None
    return str(value)[:10]


def _hold_days(entry_day: str | None, exit_day: str | None) -> int | None:
    if not entry_day or not exit_day:
        return None
    try:
        import datetime as dt
        a = dt.date.fromisoformat(entry_day)
        b = dt.date.fromisoformat(exit_day)
        return max(0, (b - a).days)
    except Exception:
        return None


def closed_trades(records: list[dict]) -> list[dict]:
    """Pair every CLOSE with its OPEN and price the round trip.

    A close with no matching open keeps `entry_price` and `pnl` as None. Both halves of
    that matter: dropping it would hide a trade that happened, and pricing it at zero
    would invent a result. Three of these exist from 2026-08-03, when send_order read
    filled entries back as Cancelled and logged no price.
    """
    opens: dict = {}
    for r in records:
        if r.get("type") == "OPEN":
            opens[(r.get("inst"), _day(r.get("entry_day")))] = r

    out: list[dict] = []
    for r in records:
        if r.get("type") != "CLOSE":
            continue
        inst = r.get("inst")
        entry_day, exit_day = _day(r.get("entry_day")), _day(r.get("exit_day"))
        o = opens.get((inst, entry_day))
        entry_price = o.get("fill_price") if o else None
        exit_price = r.get("fill_price")
        contracts = int(r.get("contracts") or (o or {}).get("contracts") or 1)
        pv = point_value(inst)

        pnl = None
        if entry_price is not None and exit_price is not None and pv:
            sign = 1 if r.get("direction") == "LONG" else -1
            pnl = (float(exit_price) - float(entry_price)) * pv * contracts * sign

        out.append({
            "inst": inst,
            "cluster": r.get("cluster") or (o or {}).get("cluster"),
            "direction": r.get("direction") or (o or {}).get("direction"),
            "contracts": contracts,
            "entry_day": entry_day,
            "exit_day": exit_day,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "hold_days": _hold_days(entry_day, exit_day),
            "pnl": pnl,
            "exit_reason": r.get("exit_reason"),
            # Attribution is by the regime at ENTRY — that is the state the decision was
            # taken under. Recorded on the OPEN, since a close does not carry it.
            "regime": (o or {}).get("regime") or r.get("regime") or "Unknown",
            "risk_sized": (o or {}).get("risk_sized") or r.get("risk_sized"),
        })
    return out


def _stats(trades: list[dict]) -> dict:
    """Same shape the replay snapshots use, so one dashboard reads both."""
    priced = [t["pnl"] for t in trades if t.get("pnl") is not None]
    unpriced = len(trades) - len(priced)
    if not priced:
        return {"trade_count": len(trades), "win_rate": None, "avg_win": None,
                "avg_loss": None, "largest_loss": None, "unpriced": unpriced}
    wins = [p for p in priced if p > 0]
    losses = [p for p in priced if p <= 0]
    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / len(priced),
        "avg_win": (sum(wins) / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
        "largest_loss": min(priced),
        "unpriced": unpriced,
    }


def _holding(trades: list[dict]) -> dict:
    holds = [t["hold_days"] for t in trades if t.get("hold_days") is not None]
    dist = {f"{d}d": 0 for d in range(1, 6)}
    for h in holds:
        key = f"{int(h)}d"
        if key in dist:
            dist[key] += 1
    return {"median_hold_days": (round(statistics.median(holds), 1) if holds else None),
            "distribution": dist}


def cumulative(closed: list[dict], upto: str) -> dict:
    """Analytics over every trade closed on or before `upto`.

    Cumulative-to-a-day, because the dashboard's slider asks what the book looked like
    on a past date, not what it looks like now.

    A trade with no P&L is counted but not added to any money total. Booking it at zero
    would quietly understate the record.
    """
    upto = _day(upto)
    seen = [t for t in closed if t.get("exit_day") and t["exit_day"] <= upto]

    per_cluster: dict = defaultdict(float)
    per_regime: dict = defaultdict(float)
    by_cluster: dict = defaultdict(list)
    for t in seen:
        by_cluster[t.get("cluster")].append(t)
        if t.get("pnl") is None:
            continue
        per_cluster[t.get("cluster")] += t["pnl"]
        per_regime[t.get("regime") or "Unknown"] += t["pnl"]

    return {
        "per_cluster_pnl": dict(per_cluster),
        "regime_attribution": dict(per_regime),
        "cluster_stats": {c: _stats(ts) for c, ts in by_cluster.items()},
        "holding_distribution": {c: _holding(ts) for c, ts in by_cluster.items()},
    }


def build_snapshots(records: list[dict], paper_history: dict) -> list[dict]:
    """One snapshot per day of the equity curve, oldest first.

    The dashboard stamps every exit with the date of the snapshot it came from, so a
    day carries only the trades that closed on it. Putting the whole history on a single
    snapshot — which is what a one-snapshot payload forces — would date every trade to
    today and flatten the equity chart to a point.

    Fields that only describe the present (open positions, cluster exposure, regime,
    breaker level) are left to the caller to fill on the latest snapshot. They cannot be
    reconstructed for a past day from these two files, and guessing them would put
    today's positions on last week's date.
    """
    days = sorted((paper_history or {}).get("days") or {})
    if not days:
        return []

    closed = closed_trades(records)
    by_exit: dict = defaultdict(list)
    for t in closed:
        if t.get("exit_day"):
            by_exit[t["exit_day"]].append(t)

    snaps = []
    for d in days:
        exits = by_exit.get(d, [])
        realized = sum(t["pnl"] for t in exits if t.get("pnl") is not None)
        snaps.append({
            "date": d,
            "equity": (paper_history["days"] or {}).get(d),
            "decision": {
                "realized_today": round(realized, 2),
                "entries": [],
                "exits": exits,
                "rejected_detail": [],
                "taken_today": {}, "rejected_today": {}, "halted_today": 0,
            },
            **cumulative(closed, upto=d),
        })
    return snaps
