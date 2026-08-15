"""Build a read-only Paper P&L vs backtest audit report.

The Paper dashboard needs a clean expected-equity source. This script keeps the
two useful comparisons separate:

1. equity_window: the runner/backtest-curve convention, using the compact
   backtest_curve.json date->equity marks.
2. trade_filter: trades whose entry_day is at or after the paper epoch, realized
   on their exit day.

It writes no trading state and places no orders.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from global_index.statement import pair_fifo, parse_transactions, point_value
_REJECTED_DETAIL = re.compile(
    r"REJECTED\s+(?P<direction>LONG|SHORT)\s+(?P<inst>[A-Z0-9]+)\s+\((?P<cluster>[^)]+)\)"
    r"\s+risk_sized=\$(?P<risk_sized>[-\d.,]+)\s+[—-]\s+(?P<reason>.+)$",
    re.IGNORECASE,
)


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


def _optional_json(path: Path) -> dict[str, Any]:
    try:
        return _json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _optional_js_json(path: Path) -> dict[str, Any]:
    try:
        return _replay(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _date(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)[:10]


def _asof(curve: dict[str, float], day: str) -> float | None:
    keys = [key for key in curve if key <= day]
    return curve[max(keys)] if keys else None


def _trade_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("inst", "cluster", "direction", "entry_day", "exit_day"))


def _trade_base_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("inst", "cluster", "direction", "entry_day"))


def _trade_id(row: dict[str, Any]) -> str:
    return _trade_base_key(row)


def _broker_id_text(row: dict[str, Any] | None) -> str | None:
    if not row:
        return None
    if row.get("broker_trade_id"):
        return str(row.get("broker_trade_id"))
    ids = row.get("broker_ids") if isinstance(row.get("broker_ids"), dict) else {}
    if not ids:
        return None
    return " | ".join(f"{key}:{value}" for key, value in sorted(ids.items()) if value) or None


def _signal_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "") for key in ("date", "inst", "cluster", "direction", "action"))


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _same_money(left: Any, right: Any, tol: float = 0.005) -> bool:
    a = _number(left)
    b = _number(right)
    return a is not None and b is not None and abs(a - b) <= tol


def _verdict(status: str, title: str, summary: str, facts: list[str] | None = None,
             target: str | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "title": title,
        "summary": summary,
        "facts": facts or [],
        "target": target,
    }


def _pnl_verdicts(report: dict[str, Any]) -> dict[str, Any]:
    pl = report.get("statement_pnl_compare") if isinstance(report.get("statement_pnl_compare"), dict) else {}
    lifecycle = report.get("lifecycle_compare") if isinstance(report.get("lifecycle_compare"), dict) else {}
    parity = report.get("open_position_parity") if isinstance(report.get("open_position_parity"), dict) else {}
    signal = report.get("signal_compare") if isinstance(report.get("signal_compare"), dict) else {}
    classified_signal = signal.get("classified") if isinstance(signal.get("classified"), dict) else {}
    entry = report.get("entry_compare") if isinstance(report.get("entry_compare"), dict) else {}
    daily = report.get("daily") if isinstance(report.get("daily"), list) else []
    rows = lifecycle.get("rows") if isinstance(lifecycle.get("rows"), list) else []

    pb_recon = _same_money(lifecycle.get("paper_minus_backtest_sum"), pl.get("paper_minus_backtest_realized"))
    flex_grid = pl.get("paper_minus_flex_epoch_rebased_realized", pl.get("paper_minus_statement_entry_epoch_realized"))
    pf_recon = _same_money(lifecycle.get("paper_minus_flex_sum"), flex_grid)
    lifecycle_unresolved = int(lifecycle.get("unresolved") or 0)
    missing_sources = sum(
        1 for row in rows
        if any(str((row.get(side) or {}).get("status") or "") == "MISSING" for side in ("paper", "backtest", "flex"))
    )
    delta_rows = sum(
        1 for row in rows
        if abs(_number(row.get("paper_minus_backtest_pnl")) or 0.0) > 0.005
        or abs(_number(row.get("paper_minus_flex_pnl")) or 0.0) > 0.005
    )
    open_diff = len(parity.get("paper_only") or []) + len(parity.get("backtest_only") or [])
    signal_unresolved = int(classified_signal.get("unresolved") or 0)
    entry_unresolved = int(entry.get("unresolved") or 0)
    stale_daily = sum(1 for row in daily if row.get("curve_status") and row.get("curve_status") != "covered")

    trade_master_status = (
        "BREACH" if lifecycle_unresolved or missing_sources or not pb_recon or not pf_recon
        else "EXPLAINED" if delta_rows
        else "PASS"
    )
    decision_status = "BREACH" if signal_unresolved or entry_unresolved or open_diff else "PASS"
    daily_diff = _number(daily[-1].get("trade_filter_realized_diff")) if daily else None
    daily_status = "PENDING" if stale_daily else "EXPLAINED" if abs(daily_diff or 0.0) > 0.005 else "PASS"
    overview_unresolved = lifecycle_unresolved + missing_sources + open_diff + signal_unresolved + entry_unresolved + (0 if pb_recon else 1) + (0 if pf_recon else 1)

    paper_latest = daily[-1].get("paper_trade_realized_cum") if daily else None
    backtest_latest = daily[-1].get("backtest_trade_realized_cum") if daily else None
    flex_latest = round(sum(_number(row.get("flex_pnl")) or 0.0 for row in (pl.get("paper_flex_bridge") or [])), 2)
    timeline_ok = (
        _same_money(paper_latest, pl.get("paper_epoch_closed_realized"))
        and _same_money(backtest_latest, pl.get("backtest_epoch_closed_realized"))
        and _same_money(flex_latest, pl.get("flex_epoch_rebased_realized", pl.get("statement_entry_epoch_realized")))
    )

    return {
        "overview": _verdict(
            "BREACH" if overview_unresolved else "EXPLAINED" if trade_master_status == "EXPLAINED" or daily_status == "EXPLAINED" else "PASS",
            "Overview verdicts",
            "Headline reconciliation has unresolved/breach items." if overview_unresolved else "Headline reconciliation is table-explained and has no unresolved items.",
            [f"unresolved {overview_unresolved}", f"P-B {'RECONCILED' if pb_recon else 'CHECK'}", f"P-F {'RECONCILED' if pf_recon else 'CHECK'}"],
            "pnl-tab-overview",
        ),
        "trade_master": _verdict(
            trade_master_status,
            "Trade master reconcile",
            "Trade rows reconcile to headline totals." if trade_master_status != "BREACH" else "Trade rows have unresolved sources or footer totals do not match the grid.",
            [f"rows {len(rows)}", f"delta rows {delta_rows}", f"missing {missing_sources}", f"unresolved {lifecycle_unresolved}"],
            "pnl-tab-trades",
        ),
        "components": _verdict(
            "BREACH" if not pb_recon or not pf_recon else "EXPLAINED" if delta_rows else "PASS",
            "Component variance",
            "Component deltas reconcile to headline totals." if pb_recon and pf_recon else "Component deltas do not reconcile to headline totals.",
            [f"P-B {'RECONCILED' if pb_recon else 'CHECK'}", f"P-F {'RECONCILED' if pf_recon else 'CHECK'}"],
            "pnl-tab-trades",
        ),
        "decision": _verdict(
            decision_status,
            "Decision path",
            "Signal, entry, and open-position parity have no unresolved rows." if decision_status == "PASS" else "Signal, entry, or open-position parity has unresolved rows.",
            [f"signal unresolved {signal_unresolved}", f"entry unresolved {entry_unresolved}", f"open diff {open_diff}"],
            "pnl-tab-decision",
        ),
        "timeline": _verdict(
            "PASS" if timeline_ok else "BREACH",
            "Timeline reconcile",
            "Timeline final values reconcile to headline P&L grid." if timeline_ok else "Timeline final values do not reconcile to headline P&L grid.",
            [f"daily stale {stale_daily}", f"latest trade diff {daily_diff if daily_diff is not None else '--'}"],
            "pnl-tab-timeline",
        ),
        "daily": _verdict(
            daily_status,
            "Daily divergence",
            "Daily rows are fresh and divergence is explainable by trade rows." if daily_status != "PENDING" else "Some daily rows are stale.",
            [f"rows {len(daily)}", f"stale {stale_daily}"],
            "pnl-tab-timeline",
        ),
    }


def _gross_pnl(inst: Any, direction: Any, entry_price: Any, exit_price: Any, qty: Any = 1) -> float | None:
    entry = _number(entry_price)
    exit_ = _number(exit_price)
    contracts = _number(qty) or 1.0
    pv = point_value(str(inst or ""))
    if entry is None or exit_ is None or pv is None:
        return None
    side = 1 if str(direction or "").upper() == "LONG" else -1
    return round((exit_ - entry) * pv * contracts * side, 2)


def _pnl_components(inst: Any, direction: Any, entry_price: Any, exit_price: Any,
                    qty: Any, net_pnl: Any, fee: Any = None, source: str = "") -> dict[str, Any]:
    gross = _gross_pnl(inst, direction, entry_price, exit_price, qty)
    net = _number(net_pnl)
    fee_n = _number(fee)
    model_cost = round(net - gross, 2) if net is not None and gross is not None and fee_n is None else None
    net_with_fee = round(gross + fee_n, 2) if gross is not None and fee_n is not None else net
    return {
        "gross_pnl": gross,
        "fee": fee_n,
        "model_commission": None,
        "model_slippage": None,
        "model_cost": model_cost,
        "net_pnl": round(net, 2) if net is not None else None,
        "net_with_fee": net_with_fee,
        "component_source": source,
    }


def _slippage_pnl_impact(inst: Any, slip_points: Any, qty: Any = 1) -> float | None:
    slip = _number(slip_points)
    pv = point_value(str(inst or ""))
    contracts = _number(qty) or 1.0
    if slip is None or pv is None:
        return None
    return round(-slip * pv * contracts, 2)


def _exported_or_reconstructed_components(item: dict[str, Any], contracts: Any, pnl: Any) -> dict[str, Any]:
    fallback = _pnl_components(
        item.get("inst"), item.get("direction"), item.get("entry_price"), item.get("exit_price"),
        contracts, pnl, source="backtest_reconstructed_gross_vs_exported_pnl_sized",
    )
    exported = item.get("pnl_components")
    if not isinstance(exported, dict):
        exported = {
            key: item.get(key)
            for key in ("gross_pnl", "model_commission", "model_slippage", "model_cost", "net_pnl")
            if item.get(key) is not None
        }
    if not exported:
        return fallback
    merged = dict(fallback)
    merged.update(exported)
    merged["gross_pnl"] = _number(merged.get("gross_pnl"))
    merged["fee"] = _number(merged.get("fee"))
    merged["model_commission"] = _number(merged.get("model_commission"))
    merged["model_slippage"] = _number(merged.get("model_slippage"))
    merged["model_cost"] = _number(merged.get("model_cost"))
    merged["net_pnl"] = _number(merged.get("net_pnl"))
    net_with_fee = _number(merged.get("net_with_fee"))
    merged["net_with_fee"] = net_with_fee if net_with_fee is not None else merged.get("net_pnl")
    merged["component_source"] = merged.get("component_source") or "backtest_replay_exported_components"
    return merged


def _days_between(left: str | None, right: str | None) -> int | None:
    if not left or not right:
        return None
    from datetime import date

    try:
        return (date.fromisoformat(left) - date.fromisoformat(right)).days
    except ValueError:
        return None


def _classified_trades(paper_trades: list[dict[str, Any]], backtest_trades: list[dict[str, Any]]) -> dict[str, Any]:
    bt_by_key = {_trade_key(row): row for row in backtest_trades}
    bt_by_base: dict[str, list[dict[str, Any]]] = {}
    for row in backtest_trades:
        bt_by_base.setdefault(_trade_base_key(row), []).append(row)

    used_bt: set[str] = set()
    rows: list[dict[str, Any]] = []
    for paper in paper_trades:
        exact_key = _trade_key(paper)
        base_key = _trade_base_key(paper)
        backtest = bt_by_key.get(exact_key)
        classification = "MATCHED_SAME_DATES"
        reason = "same instrument, cluster, direction, entry day, and exit day"
        if not backtest:
            candidates = [item for item in bt_by_base.get(base_key, []) if _trade_key(item) not in used_bt]
            backtest = candidates[0] if candidates else None
            classification = "KNOWN_EXIT_TIMING_DRIFT" if backtest else "PAPER_ONLY"
            reason = (
                "same trade identity but paper/live exit day differs; known live path can defer stop/exit handling after the 14h/EOD decision"
                if backtest else
                "paper close has no backtest trade with same instrument, cluster, direction, and entry day"
            )
        if backtest:
            used_bt.add(_trade_key(backtest))
        paper_pnl = float(paper.get("pnl") or 0.0)
        bt_pnl = float(backtest.get("pnl") or 0.0) if backtest else None
        rows.append({
            "classification": classification,
            "reason": reason,
            "trade_id": _trade_id(paper),
            "inst": paper.get("inst"),
            "cluster": paper.get("cluster"),
            "direction": paper.get("direction"),
            "entry_day": paper.get("entry_day"),
            "paper_exit_day": paper.get("exit_day"),
            "backtest_exit_day": backtest.get("exit_day") if backtest else None,
            "exit_day_delta": _days_between(paper.get("exit_day"), backtest.get("exit_day")) if backtest else None,
            "paper_pnl": round(paper_pnl, 2),
            "backtest_pnl": round(bt_pnl, 2) if bt_pnl is not None else None,
            "pnl_diff": round(paper_pnl - bt_pnl, 2) if bt_pnl is not None else None,
            "paper_components": paper.get("components") or {},
            "backtest_components": backtest.get("components") if backtest else {},
            "paper_exit_reason": paper.get("exit_reason"),
            "backtest_exit_reason": backtest.get("exit_reason") if backtest else None,
        })

    for backtest in backtest_trades:
        if _trade_key(backtest) in used_bt:
            continue
        rows.append({
            "classification": "BACKTEST_ONLY",
            "reason": "backtest trade has no paper close with same instrument, cluster, direction, and entry day",
            "trade_id": _trade_id(backtest),
            "inst": backtest.get("inst"),
            "cluster": backtest.get("cluster"),
            "direction": backtest.get("direction"),
            "entry_day": backtest.get("entry_day"),
            "paper_exit_day": None,
            "backtest_exit_day": backtest.get("exit_day"),
            "exit_day_delta": None,
            "paper_pnl": None,
            "backtest_pnl": round(float(backtest.get("pnl") or 0.0), 2),
            "pnl_diff": None,
            "paper_components": {},
            "backtest_components": backtest.get("components") or {},
            "paper_exit_reason": None,
            "backtest_exit_reason": backtest.get("exit_reason"),
        })

    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["classification"])
        counts[key] = counts.get(key, 0) + 1
    unresolved = counts.get("PAPER_ONLY", 0) + counts.get("BACKTEST_ONLY", 0)
    return {"counts": dict(sorted(counts.items())), "unresolved": unresolved, "rows": rows}


def _paper_closes(path: Path, epoch: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    open_by_key: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        items.append(item)
        if str(item.get("type")).upper() == "OPEN":
            day = _date(item.get("entry_day") or item.get("ts"))
            if day:
                open_by_key[_trade_base_key({
                    "inst": item.get("inst"),
                    "cluster": item.get("cluster"),
                    "direction": item.get("direction"),
                    "entry_day": day,
                })] = item
    rows = []
    for item in items:
        if str(item.get("type")).upper() != "CLOSE":
            continue
        entry_day = _date(item.get("entry_day"))
        exit_day = _date(item.get("exit_day"))
        if not entry_day or entry_day < epoch:
            continue
        open_item = open_by_key.get(_trade_base_key({
            "inst": item.get("inst"),
            "cluster": item.get("cluster"),
            "direction": item.get("direction"),
            "entry_day": entry_day,
        })) or {}
        entry_price = open_item.get("fill_price") or open_item.get("expected_entry")
        exit_price = item.get("fill_price")
        contracts = item.get("contracts") or open_item.get("contracts")
        pnl = float(item.get("pnl_sized") or 0.0)
        commission = _number(open_item.get("commission")) or 0.0
        if _number(item.get("commission")) is not None:
            commission += _number(item.get("commission")) or 0.0
        commission = round(commission, 2) if commission else None
        components = _pnl_components(
            item.get("inst"), item.get("direction"), entry_price, exit_price, contracts, pnl, commission,
            source="paper_trade_log_reconstructed_gross_vs_pnl_sized",
        )
        components.update({
            "entry_expected_price": _number(open_item.get("expected_entry")),
            "entry_fill_price": _number(open_item.get("fill_price")),
            "entry_slippage_points": _number(open_item.get("slip")),
            "entry_slippage_pnl": _slippage_pnl_impact(item.get("inst"), open_item.get("slip"), contracts),
            "exit_expected_price": _number(item.get("expected_stop") or item.get("expected_exit")),
            "exit_fill_price": _number(item.get("fill_price")),
            "exit_slippage_points": _number(item.get("slip")),
            "exit_slippage_pnl": _slippage_pnl_impact(item.get("inst"), item.get("slip"), contracts),
        })
        rows.append({
            "inst": item.get("inst"),
            "cluster": item.get("cluster"),
            "direction": item.get("direction"),
            "entry_day": entry_day,
            "exit_day": exit_day,
            "pnl": pnl,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "expected_entry": open_item.get("expected_entry"),
            "entry_slip": open_item.get("slip"),
            "expected_exit": item.get("expected_stop") or item.get("expected_exit"),
            "exit_slip": item.get("slip"),
            "commission": commission,
            "contracts": contracts,
            "components": components,
            "source_trade_id": _trade_base_key({
                "inst": item.get("inst"),
                "cluster": item.get("cluster"),
                "direction": item.get("direction"),
                "entry_day": entry_day,
            }),
            "exit_reason": item.get("exit_reason"),
            "source": item.get("source"),
        })
    return rows


def _paper_open_signals(path: Path, epoch: str) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(item.get("type")).upper() != "OPEN":
            continue
        day = _date(item.get("entry_day") or item.get("ts"))
        if not day or day < epoch:
            continue
        rows.append({
            "date": day,
            "inst": item.get("inst"),
            "cluster": item.get("cluster"),
            "direction": item.get("direction"),
            "action": "OPEN",
            "risk_sized": item.get("risk_sized"),
            "price": item.get("expected_entry") or item.get("fill_price"),
            "expected_entry": item.get("expected_entry"),
            "fill_price": item.get("fill_price"),
            "entry_slip": item.get("slip"),
            "entry_slippage_pnl": _slippage_pnl_impact(item.get("inst"), item.get("slip"), item.get("contracts")),
            "commission": item.get("commission"),
            "contracts": item.get("contracts"),
            "source": "trade_log",
        })
    return rows


def _paper_rejected_signals(root: Path, epoch: str) -> list[dict[str, Any]]:
    rows = []
    for path in [*sorted(root.glob("scheduler_*.log")), *sorted(root.glob("live_day_*.log"))]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line_no, line in enumerate(lines, start=1):
            day = _date(line[:10])
            if not day or day < epoch or "REJECTED" not in line:
                continue
            match = _REJECTED_DETAIL.search(line)
            if not match:
                continue
            groups = match.groupdict()
            rows.append({
                "date": day,
                "inst": groups.get("inst"),
                "cluster": groups.get("cluster"),
                "direction": groups.get("direction"),
                "action": "REJECTED",
                "risk_sized": float((groups.get("risk_sized") or "0").replace(",", "")),
                "reason": groups.get("reason"),
                "source": f"{path.name}:{line_no}",
            })
    return rows


def _backtest_entries(path: Path, epoch: str) -> list[dict[str, Any]]:
    data = _replay(path)
    rows = []
    for snap in data.get("snapshots") or []:
        for item in (snap.get("decision") or {}).get("entries") or []:
            entry_day = _date(item.get("entry_time")) or _date(snap.get("date"))
            if not entry_day or entry_day < epoch:
                continue
            exit_day = item.get("exit_day") or _date(item.get("exit_time"))
            contracts = item.get("contracts") or item.get("n_contracts") or 1
            pnl = float(item.get("pnl_sized") or 0.0)
            components = _exported_or_reconstructed_components(item, contracts, pnl)
            rows.append({
                "inst": item.get("inst"),
                "cluster": item.get("cluster"),
                "direction": item.get("direction"),
                "entry_day": entry_day,
                "exit_day": exit_day,
                "pnl": pnl,
                "exit_reason": item.get("exit_reason"),
                "entry_price": item.get("entry_price"),
                "exit_price": item.get("exit_price"),
                "contracts": contracts,
                "components": components,
                "source_trade_id": _trade_base_key({
                    "inst": item.get("inst"),
                    "cluster": item.get("cluster"),
                    "direction": item.get("direction"),
                    "entry_day": entry_day,
                }),
            })
    return rows


def _backtest_signals(path: Path, epoch: str) -> list[dict[str, Any]]:
    data = _replay(path)
    rows = []
    for snap in data.get("snapshots") or []:
        day = _date(snap.get("date"))
        if not day or day < epoch:
            continue
        decision = snap.get("decision") or {}
        for item in decision.get("entries") or []:
            rows.append({
                "date": _date(item.get("entry_time")) or day,
                "inst": item.get("inst"),
                "cluster": item.get("cluster"),
                "direction": item.get("direction"),
                "action": "OPEN",
                "risk_sized": item.get("risk_sized"),
                "price": item.get("entry_price"),
                "entry_price": item.get("entry_price"),
                "exit_day": item.get("exit_day") or _date(item.get("exit_time")),
                "source": "replay_snapshots.decision.entries",
            })
        for item in decision.get("rejected_detail") or []:
            rows.append({
                "date": day,
                "inst": item.get("inst"),
                "cluster": item.get("cluster"),
                "direction": item.get("direction"),
                "action": "REJECTED",
                "risk_sized": item.get("risk_sized"),
                "reason": item.get("reason") or item.get("detail"),
                "source": "replay_snapshots.decision.rejected_detail",
            })
    return rows


def _checkpoint_open_signals(root: Path, epoch: str) -> list[dict[str, Any]]:
    checkpoint = _optional_json(root / "global_index" / "replay_checkpoint.json")
    rows = []
    for inst, item in (checkpoint.get("instruments") or {}).items():
        if not isinstance(item, dict):
            continue
        pos = item.get("pos") if isinstance(item.get("pos"), dict) else None
        if not pos:
            continue
        day = _date(pos.get("entry_day") or pos.get("entry_time"))
        if not day or day < epoch:
            continue
        direction = str(pos.get("dir") or "").upper()
        cluster = "global_nkd" if inst == "MNKD" else "roska4_swing"
        rows.append({
            "date": day,
            "inst": inst,
            "cluster": cluster,
            "direction": direction,
            "action": "OPEN",
            "risk_sized": None,
            "price": pos.get("entry"),
            "entry_price": pos.get("entry"),
            "entry_time": str(pos.get("entry_time") or ""),
            "exit_day": None,
            "open_position": True,
            "source": "replay_checkpoint.open_position",
        })
    return rows


def _classified_signals(paper_signals: list[dict[str, Any]], backtest_signals: list[dict[str, Any]]) -> dict[str, Any]:
    paper_by_key: dict[str, list[dict[str, Any]]] = {}
    bt_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in paper_signals:
        paper_by_key.setdefault(_signal_key(row), []).append(row)
    for row in backtest_signals:
        bt_by_key.setdefault(_signal_key(row), []).append(row)
    keys = sorted(set(paper_by_key) | set(bt_by_key))
    rows = []
    counts: dict[str, int] = {}
    for key in keys:
        paper_count = len(paper_by_key.get(key, []))
        bt_count = len(bt_by_key.get(key, []))
        sample = (paper_by_key.get(key) or bt_by_key.get(key) or [{}])[0]
        paper_sample = (paper_by_key.get(key) or [None])[0]
        backtest_sample = (bt_by_key.get(key) or [None])[0]
        action = str(sample.get("action") or "").upper()
        paper_price = _number((paper_sample or {}).get("price"))
        bt_price = _number((backtest_sample or {}).get("price"))
        paper_risk = _number((paper_sample or {}).get("risk_sized"))
        bt_risk = _number((backtest_sample or {}).get("risk_sized"))
        price_diff = round(paper_price - bt_price, 2) if paper_price is not None and bt_price is not None else None
        risk_diff = round(paper_risk - bt_risk, 2) if paper_risk is not None and bt_risk is not None else None
        if paper_count and bt_count:
            classification = "MATCHED_SIGNAL"
            reason = "paper and backtest emitted the same date/instrument/cluster/direction/action signal"
            reason_code = "MATCHED_DECISION"
        elif paper_count:
            classification = "PAPER_ONLY_SIGNAL"
            if action == "OPEN":
                reason_code = "PAPER_ONLY_OPEN_NO_REPLAY_DECISION"
                reason = (
                    "paper/live emitted and filled an OPEN, but the replay snapshot has no matching OPEN decision for "
                    "the same date/instrument/cluster/direction; compare live candidate inputs, open-book state, caps, "
                    "and replay bundle for that decision timestamp"
                )
            else:
                reason_code = "PAPER_ONLY_REJECT_NO_REPLAY_REJECT"
                reason = "paper/live retained a rejected candidate that is not present in replay rejected_detail for the same signal identity"
        else:
            classification = "BACKTEST_ONLY_SIGNAL"
            reason_code = "BACKTEST_ONLY_SIGNAL_NOT_SEEN_IN_PAPER"
            reason = "backtest replay emitted a signal that is not present in retained paper OPEN/REJECTED evidence"
        counts[classification] = counts.get(classification, 0) + 1
        rows.append({
            "classification": classification,
            "reason_code": reason_code,
            "reason": reason,
            "date": sample.get("date"),
            "inst": sample.get("inst"),
            "cluster": sample.get("cluster"),
            "direction": sample.get("direction"),
            "action": sample.get("action"),
            "paper_count": paper_count,
            "backtest_count": bt_count,
            "paper_price": paper_price,
            "backtest_price": bt_price,
            "price_diff": price_diff,
            "price_compare_status": "MATCH" if price_diff == 0 else "DIFF" if price_diff is not None else "MISSING",
            "paper_risk": paper_risk,
            "backtest_risk": bt_risk,
            "risk_diff": risk_diff,
            "risk_compare_status": "MATCH" if risk_diff == 0 else "DIFF" if risk_diff is not None else "MISSING",
            "paper_sample": paper_sample,
            "backtest_sample": backtest_sample,
        })
    unresolved = counts.get("PAPER_ONLY_SIGNAL", 0) + counts.get("BACKTEST_ONLY_SIGNAL", 0)
    return {"counts": dict(sorted(counts.items())), "unresolved": unresolved, "rows": rows}


def _entry_compare(paper_signals: list[dict[str, Any]], backtest_signals: list[dict[str, Any]],
                   statement: dict[str, Any]) -> dict[str, Any]:
    paper_entries = [row for row in paper_signals if row.get("action") == "OPEN"]
    bt_entries = [row for row in backtest_signals if row.get("action") == "OPEN"]
    paper_by_key: dict[str, list[dict[str, Any]]] = {}
    bt_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in paper_entries:
        paper_by_key.setdefault(_signal_key(row), []).append(row)
    for row in bt_entries:
        bt_by_key.setdefault(_signal_key(row), []).append(row)
    statement_fills = statement.get("fills") if isinstance(statement.get("fills"), list) else []
    stmt_by_key: dict[str, list[dict[str, Any]]] = {}
    for fill in statement_fills:
        if fill.get("signed") == 0:
            continue
        direction = "LONG" if float(fill.get("signed") or 0) > 0 else "SHORT"
        key = "|".join(str(fill.get(k) or "") for k in ("date", "inst")) + f"|{direction}"
        stmt_by_key.setdefault(key, []).append(fill)

    rows = []
    counts: dict[str, int] = {}
    keys = sorted(set(paper_by_key) | set(bt_by_key))
    for key in keys:
        paper = (paper_by_key.get(key) or [None])[0]
        backtest = (bt_by_key.get(key) or [None])[0]
        sample = paper or backtest or {}
        stmt_key = "|".join(str(sample.get(k) or "") for k in ("date", "inst", "direction"))
        stmt = (stmt_by_key.get(stmt_key) or [None])[0]
        paper_expected = _number((paper or {}).get("expected_entry") or (paper or {}).get("price"))
        paper_fill = _number((paper or {}).get("fill_price"))
        bt_entry = _number((backtest or {}).get("entry_price") or (backtest or {}).get("price"))
        stmt_price = _number((stmt or {}).get("price"))
        if paper and backtest:
            classification = "MATCHED_ENTRY"
            reason = "paper admitted/filled an entry and replay admitted the same entry identity"
        elif paper:
            classification = "PAPER_ONLY_ENTRY"
            reason = "paper admitted/filled an entry that replay did not admit for the same date/instrument/cluster/direction"
        else:
            classification = "BACKTEST_ONLY_ENTRY"
            reason = "replay admitted an entry that is absent from retained paper fill history"
        audit_ref = None
        audit_label = None
        if (
            str(sample.get("inst") or "") == "M2K"
            and str(sample.get("date") or "") == "2026-08-10"
            and (
                str((backtest or {}).get("source") or "") == "replay_checkpoint.open_position"
                or classification != "MATCHED_ENTRY"
            )
        ):
            audit_ref = "audit-m2k-entry"
            audit_label = "M2K checkpoint audit"
        counts[classification] = counts.get(classification, 0) + 1
        rows.append({
            "classification": classification,
            "reason": reason,
            "trade_id": _trade_base_key(sample),
            "date": sample.get("date"),
            "inst": sample.get("inst"),
            "cluster": sample.get("cluster"),
            "direction": sample.get("direction"),
            "paper_expected_entry": paper_expected,
            "paper_fill_price": paper_fill,
            "broker_statement_price": stmt_price,
            "backtest_entry_price": bt_entry,
            "paper_fill_vs_expected": round(paper_fill - paper_expected, 2) if paper_fill is not None and paper_expected is not None else None,
            "paper_expected_vs_backtest": round(paper_expected - bt_entry, 2) if paper_expected is not None and bt_entry is not None else None,
            "paper_fill_vs_backtest": round(paper_fill - bt_entry, 2) if paper_fill is not None and bt_entry is not None else None,
            "broker_vs_paper_fill": round(stmt_price - paper_fill, 2) if stmt_price is not None and paper_fill is not None else None,
            "broker_verified": stmt_price is not None and paper_fill is not None and abs(stmt_price - paper_fill) < 1e-9,
            "audit_ref": audit_ref,
            "audit_label": audit_label,
            "paper_sample": paper,
            "backtest_sample": backtest,
            "broker_sample": stmt,
        })
    unresolved = counts.get("PAPER_ONLY_ENTRY", 0) + counts.get("BACKTEST_ONLY_ENTRY", 0)
    return {"counts": dict(sorted(counts.items())), "unresolved": unresolved, "rows": rows}


def _lifecycle_key(inst: Any, cluster: Any, direction: Any, entry_day: Any) -> str:
    return "|".join(str(value or "") for value in (inst, cluster, direction, _date(entry_day)))


def _ensure_lifecycle(rows: dict[str, dict[str, Any]], inst: Any, cluster: Any,
                      direction: Any, entry_day: Any) -> dict[str, Any]:
    key = _lifecycle_key(inst, cluster, direction, entry_day)
    row = rows.setdefault(key, {
        "key": key,
        "trade_id": key,
        "inst": inst,
        "cluster": cluster,
        "direction": direction,
        "entry_day": _date(entry_day),
        "paper": {"status": "MISSING"},
        "backtest": {"status": "MISSING"},
        "flex": {"status": "MISSING"},
        "audit_ref": None,
        "audit_label": None,
    })
    for field, value in (("inst", inst), ("cluster", cluster), ("direction", direction), ("entry_day", _date(entry_day))):
        if row.get(field) in {None, ""} and value not in {None, ""}:
            row[field] = value
    return row


def _lifecycle_side(status: str, entry_price: Any = None, exit_day: Any = None,
                    exit_price: Any = None, pnl: Any = None, source: Any = None,
                    qty: Any = None, reason: Any = None, fee: Any = None,
                    source_trade_id: Any = None, broker_trade_id: Any = None,
                    expected_entry: Any = None, entry_slip: Any = None,
                    entry_slippage_pnl: Any = None, expected_exit: Any = None,
                    exit_slip: Any = None, exit_slippage_pnl: Any = None,
                    components: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "entry_price": _number(entry_price),
        "exit_day": _date(exit_day),
        "exit_price": _number(exit_price),
        "pnl": round(float(pnl), 2) if _number(pnl) is not None else None,
        "source": source,
        "qty": qty,
        "fee": _number(fee),
        "source_trade_id": source_trade_id,
        "broker_trade_id": broker_trade_id,
        "expected_entry": _number(expected_entry),
        "entry_slip": _number(entry_slip),
        "entry_slippage_pnl": _number(entry_slippage_pnl),
        "expected_exit": _number(expected_exit),
        "exit_slip": _number(exit_slip),
        "exit_slippage_pnl": _number(exit_slippage_pnl),
        "components": components or {},
        "reason": reason,
    }


def _fill_statement_cluster(inst: Any, direction: Any, entry_day: Any,
                            rows: dict[str, dict[str, Any]]) -> str:
    matches = [
        row.get("cluster") for row in rows.values()
        if row.get("inst") == inst
        and row.get("direction") == direction
        and row.get("entry_day") == _date(entry_day)
        and row.get("cluster")
    ]
    if matches:
        return str(matches[0])
    return "global_nkd" if inst == "MNKD" else "roska4_swing"


def _lifecycle_compare(paper_signals: list[dict[str, Any]], paper_trades: list[dict[str, Any]],
                       backtest_signals: list[dict[str, Any]], backtest_trades: list[dict[str, Any]],
                       statement_pnl_compare: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for signal in paper_signals:
        if signal.get("action") != "OPEN":
            continue
        row = _ensure_lifecycle(rows, signal.get("inst"), signal.get("cluster"), signal.get("direction"), signal.get("date"))
        row["paper"] = _lifecycle_side(
            "OPEN",
            entry_price=signal.get("fill_price") or signal.get("price"),
            source=signal.get("source"),
            qty=signal.get("contracts"),
            expected_entry=signal.get("expected_entry"),
            entry_slip=signal.get("entry_slip"),
            entry_slippage_pnl=signal.get("entry_slippage_pnl"),
            source_trade_id=_trade_base_key({
                "inst": signal.get("inst"),
                "cluster": signal.get("cluster"),
                "direction": signal.get("direction"),
                "entry_day": signal.get("date"),
            }),
        )
    for trade in paper_trades:
        row = _ensure_lifecycle(rows, trade.get("inst"), trade.get("cluster"), trade.get("direction"), trade.get("entry_day"))
        row["paper"] = {
            **row.get("paper", {}),
            **_lifecycle_side(
                "CLOSED",
                entry_price=trade.get("entry_price") or (row.get("paper") or {}).get("entry_price"),
                exit_day=trade.get("exit_day"),
                exit_price=trade.get("exit_price"),
                pnl=trade.get("pnl"),
                source=trade.get("source"),
                qty=trade.get("contracts"),
                reason=trade.get("exit_reason"),
                fee=trade.get("commission"),
                source_trade_id=trade.get("source_trade_id") or _trade_id(trade),
                expected_entry=trade.get("expected_entry") or (row.get("paper") or {}).get("expected_entry"),
                entry_slip=trade.get("entry_slip") if trade.get("entry_slip") is not None else (row.get("paper") or {}).get("entry_slip"),
                entry_slippage_pnl=(trade.get("components") or {}).get("entry_slippage_pnl") if (trade.get("components") or {}).get("entry_slippage_pnl") is not None else (row.get("paper") or {}).get("entry_slippage_pnl"),
                expected_exit=trade.get("expected_exit"),
                exit_slip=trade.get("exit_slip"),
                exit_slippage_pnl=(trade.get("components") or {}).get("exit_slippage_pnl"),
                components=trade.get("components"),
            ),
        }
    for signal in backtest_signals:
        if signal.get("action") != "OPEN":
            continue
        row = _ensure_lifecycle(rows, signal.get("inst"), signal.get("cluster"), signal.get("direction"), signal.get("date"))
        status = "OPEN" if signal.get("open_position") else "ENTRY"
        row["backtest"] = _lifecycle_side(
            status,
            entry_price=signal.get("entry_price") or signal.get("price"),
            source=signal.get("source"),
            source_trade_id=_trade_base_key({
                "inst": signal.get("inst"),
                "cluster": signal.get("cluster"),
                "direction": signal.get("direction"),
                "entry_day": signal.get("date"),
            }),
        )
        if str(signal.get("source") or "") == "replay_checkpoint.open_position":
            row["audit_ref"] = "audit-m2k-entry"
            row["audit_label"] = "checkpoint open-position audit"
    for trade in backtest_trades:
        row = _ensure_lifecycle(rows, trade.get("inst"), trade.get("cluster"), trade.get("direction"), trade.get("entry_day"))
        row["backtest"] = {
            **row.get("backtest", {}),
            **_lifecycle_side(
                "CLOSED",
                entry_price=trade.get("entry_price") or (row.get("backtest") or {}).get("entry_price"),
                exit_day=trade.get("exit_day"),
                exit_price=trade.get("exit_price"),
                pnl=trade.get("pnl"),
                source="replay_snapshots.decision.entries",
                reason=trade.get("exit_reason"),
                source_trade_id=trade.get("source_trade_id") or _trade_id(trade),
                components=trade.get("components"),
            ),
        }
    for flex in statement_pnl_compare.get("flex_epoch_rebased_closed") or []:
        direction = _statement_direction(flex)
        cluster = _fill_statement_cluster(flex.get("inst"), direction, flex.get("entry_day"), rows)
        row = _ensure_lifecycle(rows, flex.get("inst"), cluster, direction, flex.get("entry_day"))
        row["flex"] = _lifecycle_side(
            "CLOSED",
            entry_price=flex.get("entry_price"),
            exit_day=flex.get("exit_day"),
            exit_price=flex.get("exit_price"),
            pnl=flex.get("pnl"),
            source=flex.get("source"),
            qty=flex.get("contracts"),
            fee=flex.get("commission"),
            source_trade_id=_trade_base_key({
                "inst": flex.get("inst"),
                "cluster": cluster,
                "direction": direction,
                "entry_day": flex.get("entry_day"),
            }),
            broker_trade_id=_broker_id_text(flex),
            components=flex.get("components") or _pnl_components(
                flex.get("inst"), direction, flex.get("entry_price"), flex.get("exit_price"),
                flex.get("contracts"), flex.get("pnl"), flex.get("commission"),
                source="flex_reconstructed_gross_plus_broker_commission",
            ),
        )
    for flex in statement_pnl_compare.get("flex_epoch_rebased_open_lots") or []:
        direction = _statement_direction(flex)
        cluster = _fill_statement_cluster(flex.get("inst"), direction, flex.get("date"), rows)
        row = _ensure_lifecycle(rows, flex.get("inst"), cluster, direction, flex.get("date"))
        row["flex"] = _lifecycle_side(
            "OPEN",
            entry_price=flex.get("price"),
            source="flex_epoch_rebased_open_lot",
            qty=abs(_number(flex.get("signed")) or 0) or flex.get("contracts"),
            fee=flex.get("commission"),
            source_trade_id=_trade_base_key({
                "inst": flex.get("inst"),
                "cluster": cluster,
                "direction": direction,
                "entry_day": flex.get("date"),
            }),
            broker_trade_id=_broker_id_text(flex),
        )
    out = []
    counts: dict[str, int] = {}
    paper_minus_backtest_sum = 0.0
    paper_minus_flex_sum = 0.0
    for row in sorted(rows.values(), key=lambda item: (str(item.get("entry_day") or ""), str(item.get("inst") or ""), str(item.get("direction") or ""))):
        statuses = {name: (row.get(name) or {}).get("status") for name in ("paper", "backtest", "flex")}
        non_missing = [value for value in statuses.values() if value and value != "MISSING"]
        closed_pnls = [
            (name, (row.get(name) or {}).get("pnl"))
            for name in ("paper", "backtest", "flex")
            if (row.get(name) or {}).get("status") == "CLOSED"
        ]
        pnl_values = [value for _, value in closed_pnls if value is not None]
        if len(non_missing) == 3 and len(set(non_missing)) == 1 and (len(pnl_values) < 2 or max(pnl_values) - min(pnl_values) == 0):
            classification = "MATCHED_LIFECYCLE"
            reason = "paper, backtest, and Flex have the same lifecycle status and realised P&L where closed"
        elif len(non_missing) == 3:
            classification = "THREE_WAY_DIFF"
            reason = "paper, backtest, and Flex all have the trade identity but lifecycle or realised P&L differs"
        elif len(non_missing) == 2:
            classification = "TWO_WAY_ONLY"
            reason = "trade identity exists in two sources and is missing from the third"
        else:
            classification = "ONE_WAY_ONLY"
            reason = "trade identity exists in only one source"
        counts[classification] = counts.get(classification, 0) + 1
        row["classification"] = classification
        row["reason"] = reason
        row["paper_minus_backtest_pnl"] = (
            round((row["paper"].get("pnl") or 0.0) - (row["backtest"].get("pnl") or 0.0), 2)
            if row["paper"].get("pnl") is not None and row["backtest"].get("pnl") is not None else None
        )
        row["paper_minus_flex_pnl"] = (
            round((row["paper"].get("pnl") or 0.0) - (row["flex"].get("pnl") or 0.0), 2)
            if row["paper"].get("pnl") is not None and row["flex"].get("pnl") is not None else None
        )
        if row["paper_minus_backtest_pnl"] is not None:
            paper_minus_backtest_sum += float(row["paper_minus_backtest_pnl"])
        if row["paper_minus_flex_pnl"] is not None:
            paper_minus_flex_sum += float(row["paper_minus_flex_pnl"])
        out.append(row)
    unresolved = counts.get("ONE_WAY_ONLY", 0) + counts.get("TWO_WAY_ONLY", 0)
    return {
        "counts": dict(sorted(counts.items())),
        "unresolved": unresolved,
        "paper_minus_backtest_sum": round(paper_minus_backtest_sum, 2),
        "paper_minus_flex_sum": round(paper_minus_flex_sum, 2),
        "rows": out,
    }


def _cum_by_day(rows: list[dict[str, Any]], days: list[str]) -> dict[str, float]:
    by_exit: dict[str, float] = {}
    for row in rows:
        exit_day = row.get("exit_day")
        if exit_day:
            by_exit[exit_day] = by_exit.get(exit_day, 0.0) + float(row.get("pnl") or 0.0)
    total = 0.0
    out = {}
    for day in days:
        total += by_exit.get(day, 0.0)
        out[day] = round(total, 2)
    return out


def _position_key(row: dict[str, Any]) -> str:
    return "|".join(str(row.get(key) or "")[:10] if key == "entry_day" else str(row.get(key) or "")
                    for key in ("inst", "cluster", "direction", "entry_day"))


def _summarize_position(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "inst": row.get("inst"),
        "cluster": row.get("cluster"),
        "direction": row.get("direction") or row.get("dir"),
        "entry_day": _date(row.get("entry_day") or row.get("entry_time")),
        "contracts": row.get("contracts"),
        "risk_sized": row.get("risk_sized") or row.get("risk_dollars"),
        "entry_price": row.get("entry_price") or row.get("entry"),
        "stop_order_id": row.get("stop_order_id"),
        "source": row.get("source"),
    }


def _open_position_parity(root: Path, replay_data: dict[str, Any], latest_paper_day: str | None) -> dict[str, Any]:
    live_positions = _optional_json(root / "live_positions.json")
    paper_positions = [_summarize_position(row) for row in live_positions.get("positions") or [] if isinstance(row, dict)]
    snaps = [snap for snap in replay_data.get("snapshots") or [] if isinstance(snap, dict) and _date(snap.get("date"))]
    if latest_paper_day:
        eligible = [snap for snap in snaps if str(_date(snap.get("date"))) <= latest_paper_day]
    else:
        eligible = snaps
    latest_replay = eligible[-1] if eligible else {}
    replay_positions = [
        _summarize_position(row)
        for row in latest_replay.get("open_positions") or []
        if isinstance(row, dict)
    ]
    checkpoint = _optional_json(root / "global_index" / "replay_checkpoint.json")
    checkpoint_positions = []
    for inst, item in (checkpoint.get("instruments") or {}).items():
        if not isinstance(item, dict) or not isinstance(item.get("pos"), dict):
            continue
        pos = {
            **item["pos"],
            "inst": inst,
            "cluster": "global_nkd" if inst == "MNKD" else "roska4_swing",
            "source": "replay_checkpoint.open_position",
        }
        checkpoint_positions.append(_summarize_position(pos))
    if checkpoint_positions:
        replay_positions = checkpoint_positions
    paper_keys = {_position_key(row) for row in paper_positions}
    replay_keys = {_position_key(row) for row in replay_positions}
    paper_day = str((live_positions.get("breaker") or {}).get("cur_day") or latest_paper_day or "")
    replay_day = str(_date(latest_replay.get("date")) or "")
    status = "MATCH" if paper_keys == replay_keys else "STALE_REPLAY" if replay_day and paper_day and replay_day < paper_day and not checkpoint_positions else "MISMATCH"
    return {
        "status": status,
        "paper_day": paper_day or None,
        "replay_day": replay_day or None,
        "paper_open_count": len(paper_positions),
        "replay_open_count": len(replay_positions),
        "backtest_position_source": "replay_checkpoint.open_position" if checkpoint_positions else "replay_snapshots.open_positions",
        "paper_only": [row for row in paper_positions if _position_key(row) in sorted(paper_keys - replay_keys)],
        "backtest_only": [row for row in replay_positions if _position_key(row) in sorted(replay_keys - paper_keys)],
        "paper_positions": paper_positions,
        "backtest_positions": replay_positions,
        "note": "Parity compares current retained paper positions against replay checkpoint open positions when available; replay snapshot open_positions are used only when no checkpoint position exists.",
    }


def _latest_flex_statement(root: Path) -> dict[str, Any]:
    paths = sorted((root / "monitor" / "inputs" / "ibkr_flex").glob("*.csv"), key=lambda p: p.stat().st_mtime)
    if not paths:
        return {"status": "MISSING", "path": None, "fills": [], "closed": [], "open_lots": [], "cash": []}
    path = paths[-1]
    try:
        fills, cash = parse_transactions(path)
        closed, open_lots = pair_fifo(fills)
    except Exception as exc:
        return {"status": "ERROR", "path": str(path.relative_to(root)), "error": str(exc),
                "fills": [], "closed": [], "open_lots": [], "cash": []}
    return {
        "status": "OBSERVED",
        "path": str(path.relative_to(root)),
        "fills_count": len(fills),
        "closed_count": len(closed),
        "open_lot_count": len(open_lots),
        "cash_count": len(cash),
        "fills": fills,
        "closed": closed,
        "open_lots": open_lots,
        "cash": cash,
    }


def _sum_pnl(rows: list[dict[str, Any]]) -> float:
    return round(sum(float(row.get("pnl") or 0.0) for row in rows), 2)


def _statement_direction(row: dict[str, Any]) -> str | None:
    if row.get("direction"):
        return str(row.get("direction")).upper()
    signed = _number(row.get("signed"))
    if signed is None:
        return None
    if signed > 0:
        return "LONG"
    if signed < 0:
        return "SHORT"
    return None


def _paper_flex_bridge(paper_trades: list[dict[str, Any]], entry_epoch: list[dict[str, Any]],
                       carry_exit: list[dict[str, Any]], open_entry_epoch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flex_by_key: dict[str, list[dict[str, Any]]] = {}
    for row in entry_epoch:
        key = "|".join(str(row.get(k) or "") for k in ("inst", "direction", "entry_day"))
        flex_by_key.setdefault(key, []).append(row)
    used: set[int] = set()
    rows = []
    for paper in paper_trades:
        key = "|".join(str(paper.get(k) or "") for k in ("inst", "direction", "entry_day"))
        candidates = flex_by_key.get(key) or []
        flex = next((row for row in candidates if id(row) not in used), None)
        open_lot = next((
            row for row in open_entry_epoch
            if row.get("inst") == paper.get("inst")
            and _statement_direction(row) == paper.get("direction")
            and str(row.get("date") or "") == str(paper.get("entry_day") or "")
        ), None)
        fifo_carry = next((
            row for row in carry_exit
            if row.get("inst") == paper.get("inst")
            and row.get("direction") == paper.get("direction")
            and row.get("exit_day") == paper.get("exit_day")
        ), None)
        if flex:
            used.add(id(flex))
            diff = round(float(paper.get("pnl") or 0.0) - float(flex.get("pnl") or 0.0), 2)
            classification = "MATCHED" if diff == 0 else "MATCHED_PNL_DIFF"
            reason = "same instrument, direction, and entry day in paper and Flex"
        elif open_lot:
            diff = float(paper.get("pnl") or 0.0)
            classification = "PAPER_CLOSED_FLEX_OPEN"
            reason = (
                "paper marks this epoch trade closed, but Flex still has the epoch lot open"
                + ("; the broker close was FIFO-matched to a pre-epoch lot" if fifo_carry else "")
            )
        else:
            diff = float(paper.get("pnl") or 0.0)
            classification = "PAPER_ONLY_FLEX_MISSING"
            reason = "paper closed trade has no matching Flex closed lot or open epoch lot"
        rows.append({
            "classification": classification,
            "reason": reason,
            "trade_id": _trade_id(paper),
            "inst": paper.get("inst"),
            "direction": paper.get("direction"),
            "entry_day": paper.get("entry_day"),
            "paper_exit_day": paper.get("exit_day"),
            "paper_pnl": round(float(paper.get("pnl") or 0.0), 2),
            "paper_source_trade_id": paper.get("source_trade_id") or _trade_id(paper),
            "paper_entry_price": paper.get("entry_price"),
            "paper_exit_price": paper.get("exit_price"),
            "paper_components": paper.get("components") or {},
            "flex_exit_day": flex.get("exit_day") if flex else None,
            "flex_pnl": round(float(flex.get("pnl") or 0.0), 2) if flex else None,
            "flex_broker_trade_id": _broker_id_text(flex),
            "flex_entry_price": flex.get("entry_price") if flex else None,
            "flex_exit_price": flex.get("exit_price") if flex else None,
            "flex_commission": flex.get("commission") if flex else None,
            "flex_components": flex.get("components") if flex else {},
            "paper_minus_flex": round(diff, 2),
            "flex_open_lot_price": open_lot.get("price") if open_lot else None,
            "fifo_carry_entry_day": fifo_carry.get("entry_day") if fifo_carry and not flex else None,
            "fifo_carry_pnl": round(float(fifo_carry.get("pnl") or 0.0), 2) if fifo_carry and not flex else None,
        })
    for flex in entry_epoch:
        if id(flex) in used:
            continue
        rows.append({
            "classification": "FLEX_ONLY_CLOSED",
            "reason": "Flex closed lot entered after epoch has no matching paper closed trade",
            "trade_id": "|".join(str(value or "") for value in (flex.get("inst"), _fill_statement_cluster(flex.get("inst"), flex.get("direction"), flex.get("entry_day"), {}), flex.get("direction"), flex.get("entry_day"))),
            "inst": flex.get("inst"),
            "direction": flex.get("direction"),
            "entry_day": flex.get("entry_day"),
            "paper_exit_day": None,
            "paper_pnl": None,
            "paper_source_trade_id": None,
            "paper_entry_price": None,
            "paper_exit_price": None,
            "paper_components": {},
            "flex_exit_day": flex.get("exit_day"),
            "flex_pnl": round(float(flex.get("pnl") or 0.0), 2),
            "flex_broker_trade_id": _broker_id_text(flex),
            "flex_entry_price": flex.get("entry_price"),
            "flex_exit_price": flex.get("exit_price"),
            "flex_commission": flex.get("commission"),
            "flex_components": flex.get("components") or {},
            "paper_minus_flex": None,
            "flex_open_lot_price": None,
            "fifo_carry_entry_day": None,
            "fifo_carry_pnl": None,
        })
    return rows


def _epoch_rebased_flex(fills: list[dict[str, Any]], paper_signals: list[dict[str, Any]],
                        epoch: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Pair Flex fills from a paper zero-position base.

    Filtering fills by date is not enough: a broker fill inside the epoch can be a
    close for a pre-epoch carry lot. Only fills matching a retained paper OPEN are
    allowed to create a new epoch lot; unmatched zero-book fills are retained as
    ignored carry-close evidence.
    """
    expected: dict[str, int] = {}
    for row in paper_signals:
        if row.get("action") != "OPEN":
            continue
        day = _date(row.get("date"))
        if not day or day < epoch:
            continue
        key = "|".join(str(row.get(k) or "") for k in ("date", "inst", "direction"))
        expected[key] = expected.get(key, 0) + 1

    books: dict[str, list[dict[str, Any]]] = {}
    closed: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    opened: dict[str, int] = {}
    for fill in sorted((row for row in fills if str(row.get("date") or "") >= epoch), key=lambda x: x["date"]):
        inst = fill.get("inst")
        signed = _number(fill.get("signed")) or 0.0
        direction = "LONG" if signed > 0 else "SHORT" if signed < 0 else None
        lots = books.setdefault(str(inst), [])
        if lots and (lots[0]["signed"] > 0) != (signed > 0):
            o = lots.pop(0)
            long_side = o["signed"] > 0
            qty = abs(signed)
            # Money comes from the statement, not from a local multiplier.
            #
            # This used to be (exit - entry) * point_value(inst) * qty. The paper ledger
            # prices its own fills with the same point_value, so both sides of
            # "paper minus Flex" carried any multiplier error equally and it cancelled to
            # 0.00 — the check could not fail for the one defect it exists to catch. It
            # read 0.00 for four days while MNKD orders filled on a contract worth ten
            # times what specs.py declared, and the broker was $1,260 further down than
            # the books showed.
            #
            # Proceeds already carry the multiplier and the sign (negative on a buy), so
            # a closed pair's gross realised P&L is the sum of its two legs. Falling back
            # to point_value when the statement lacks proceeds would reinstate the blind
            # spot silently, so an unpriceable pair reports None instead.
            entry_proceeds = _number(o.get("proceeds"))
            exit_proceeds = _number(fill.get("proceeds"))
            pnl_basis = None
            if entry_proceeds is not None and exit_proceeds is not None:
                pnl = entry_proceeds + exit_proceeds
                pnl_basis = "statement_proceeds"
            else:
                pnl = None
            # IBKR's own realised figure for the same pair, kept as an independent read.
            fifo = _number(o.get("fifo_pnl")) or 0.0
            fifo += _number(fill.get("fifo_pnl")) or 0.0
            closed.append({
                "pnl_basis": pnl_basis,
                "fifo_pnl": round(fifo, 2) if pnl_basis else None,
                "inst": inst,
                "direction": "LONG" if long_side else "SHORT",
                "contracts": qty,
                "entry_day": o["date"],
                "exit_day": fill["date"],
                "entry_price": o["price"],
                "exit_price": fill["price"],
                "pnl": pnl,
                "commission": (o.get("commission", 0.0) or 0.0)
                              + (fill.get("commission", 0.0) or 0.0),
                "broker_trade_id": _broker_id_text({"broker_ids": {**(o.get("broker_ids") or {}), **(fill.get("broker_ids") or {})}}),
                "entry_broker_ids": o.get("broker_ids") or {},
                "exit_broker_ids": fill.get("broker_ids") or {},
                "source": "flex_epoch_rebased",
                "components": _pnl_components(
                    inst, "LONG" if long_side else "SHORT", o["price"], fill["price"], qty, pnl,
                    (o.get("commission", 0.0) or 0.0) + (fill.get("commission", 0.0) or 0.0),
                    source="flex_reconstructed_gross_plus_broker_commission",
                ),
            })
            continue
        key = "|".join(str(value or "") for value in (fill.get("date"), inst, direction))
        if opened.get(key, 0) < expected.get(key, 0):
            opened[key] = opened.get(key, 0) + 1
            lots.append(fill)
        else:
            ignored.append({
                **fill,
                "direction": direction,
                "reason": "zero-base ignored fill: no matching paper OPEN identity; likely pre-epoch carry close",
            })
    return closed, [lot for lots in books.values() for lot in lots], ignored


def _statement_pnl_compare(statement: dict[str, Any], paper_trades: list[dict[str, Any]],
                           backtest_trades: list[dict[str, Any]], paper_signals: list[dict[str, Any]],
                           daily: list[dict[str, Any]], epoch: str) -> dict[str, Any]:
    fills = statement.get("fills") if isinstance(statement.get("fills"), list) else []
    closed = statement.get("closed") if isinstance(statement.get("closed"), list) else []
    open_lots = statement.get("open_lots") if isinstance(statement.get("open_lots"), list) else []
    rebased_closed, rebased_open_lots, rebased_ignored_fills = _epoch_rebased_flex(fills, paper_signals, epoch)
    entry_epoch = [row for row in closed if str(row.get("entry_day") or "") >= epoch]
    open_entry_epoch = [row for row in open_lots if str(row.get("date") or "") >= epoch]
    exit_window = [row for row in closed if str(row.get("exit_day") or "") >= epoch]
    carry_exit = [row for row in exit_window if str(row.get("entry_day") or "") < epoch]
    paper_realized = _sum_pnl(paper_trades)
    backtest_realized = _sum_pnl(backtest_trades)
    latest_ledger_offset = _number((daily[-1] if daily else {}).get("system_ledger_vs_trade_filter"))
    offset_matching_carry = [
        row for row in carry_exit
        if latest_ledger_offset is not None and abs(float(row.get("pnl") or 0.0) - latest_ledger_offset) < 1e-9
    ]
    carry_matches_offset = (
        latest_ledger_offset is not None
        and bool(offset_matching_carry)
    )
    selective_carry = offset_matching_carry[:1]
    ledger_aligned_closed = [*rebased_closed, *selective_carry]
    ledger_aligned_realized = _sum_pnl(ledger_aligned_closed)
    paper_flex_bridge = _paper_flex_bridge(paper_trades, rebased_closed, carry_exit, rebased_open_lots)
    paper_flex_bridge_diff_sum = round(sum(float(row.get("paper_minus_flex") or 0.0) for row in paper_flex_bridge), 2)
    return {
        "status": statement.get("status") or "MISSING",
        "source": statement.get("path"),
        "epoch": epoch,
        "actual_system_ledger_semantics": "runner realised trade ledger / sleeve equity, not IBKR NetLiquidation",
        "paper_epoch_closed_realized": paper_realized,
        "backtest_epoch_closed_realized": backtest_realized,
        "paper_minus_backtest_realized": round(paper_realized - backtest_realized, 2),
        "flex_epoch_rebased_realized": _sum_pnl(rebased_closed),
        "paper_minus_flex_epoch_rebased_realized": round(paper_realized - _sum_pnl(rebased_closed), 2),
        "flex_ledger_aligned_realized": ledger_aligned_realized,
        "paper_minus_flex_ledger_aligned_realized": round(paper_realized - ledger_aligned_realized, 2),
        "ledger_aligned_minus_system_ledger_pnl": (
            round(ledger_aligned_realized - (paper_realized + latest_ledger_offset), 2)
            if latest_ledger_offset is not None else None
        ),
        "ledger_alignment_override": {
            "status": "ACTIVE" if selective_carry else "INACTIVE",
            "scope": "selective",
            "reason": (
                "Intentional carry-in override: include only the Flex closed lot that exactly explains "
                "the runner system-ledger offset, without moving the global strategy rebase date."
                if selective_carry else
                "No exact ledger-offset carry close was found, so no selective carry-in override is active."
            ),
            "global_rebase_changed": False,
            "included_carry_closed": selective_carry,
        },
        "raw_statement_entry_epoch_realized": _sum_pnl(entry_epoch),
        "statement_entry_epoch_realized": _sum_pnl(rebased_closed),
        "paper_minus_statement_entry_epoch_realized": round(paper_realized - _sum_pnl(entry_epoch), 2),
        "excluded_pre_epoch_exit_window_realized": _sum_pnl(carry_exit),
        "excluded_pre_epoch_closed_count": len(carry_exit),
        "latest_system_ledger_vs_paper_trade_filter": latest_ledger_offset,
        "ledger_offset_explanation": (
            "MATCH_PRE_EPOCH_CARRY_FILL" if carry_matches_offset else
            "PARTIAL_OR_UNRESOLVED_WITH_CURRENT_STATEMENT"
        ),
        "note": (
            "Flex P&L compare is epoch-rebased: it filters fills to date >= paper epoch, starts from zero position, "
            "then pairs those fills inside the window. Raw IBKR FIFO remains broker provenance, but pre-epoch lots are "
            "excluded from the main comparable base."
        ),
        "paper_flex_bridge": paper_flex_bridge,
        "paper_flex_bridge_diff_sum": paper_flex_bridge_diff_sum,
        "flex_ledger_aligned_closed": ledger_aligned_closed,
        "flex_epoch_rebased_closed": rebased_closed,
        "flex_epoch_rebased_open_lots": rebased_open_lots,
        "flex_epoch_rebased_ignored_fills": rebased_ignored_fills,
        "flex_epoch_rebased_ignored_count": len(rebased_ignored_fills),
        "raw_statement_entry_epoch_closed": entry_epoch,
        "ledger_offset_matching_carry_closed": offset_matching_carry,
        "raw_statement_entry_epoch_open_lots": open_entry_epoch,
    }


def _backtest_artifact_audit(root: Path, replay_data: dict[str, Any], epoch: str) -> dict[str, Any]:
    focus_day = "2026-08-10"
    checkpoint = _optional_json(root / "global_index" / "replay_checkpoint.json")
    checkpoint_m2k = ((checkpoint.get("instruments") or {}).get("M2K") or {})
    checkpoint_pos = checkpoint_m2k.get("pos") if isinstance(checkpoint_m2k.get("pos"), dict) else {}
    snap = next((item for item in replay_data.get("snapshots") or []
                 if _date(item.get("date")) == focus_day), {})
    decision = snap.get("decision") if isinstance(snap.get("decision"), dict) else {}
    replay_entries = decision.get("entries") if isinstance(decision.get("entries"), list) else []
    replay_m2k_entries = [row for row in replay_entries if row.get("inst") == "M2K"]
    parquet_path = root / "data" / "cache" / "futures" / "RTY_continuous_1m_8y.parquet"
    parquet = {"status": "MISSING", "path": str(parquet_path.relative_to(root))}
    try:
        import pandas as pd

        meta = pd.read_parquet(parquet_path, columns=["close"])
        day = meta.loc[focus_day]
        parquet.update({
            "status": "OBSERVED",
            "min": str(meta.index.min()),
            "max": str(meta.index.max()),
            "focus_day_bars": int(len(day)),
            "focus_day_min": str(day.index.min()),
            "focus_day_max": str(day.index.max()),
        })
    except Exception as exc:
        parquet.update({"status": "ERROR", "error": str(exc)})
    checkpoint_has_m2k = (
        str(checkpoint_pos.get("dir") or "").upper() == "LONG"
        and _date(checkpoint_pos.get("entry_day")) == focus_day
    )
    replay_has_m2k = bool(replay_m2k_entries)
    return {
        "status": "OBSERVED" if checkpoint_has_m2k and not replay_has_m2k else "OBSERVED",
        "focus": "M2K LONG OPEN on 2026-08-10",
        "classification": (
            "REPLAY_SNAPSHOT_OMITS_OPEN_CHECKPOINT_POSITION"
            if checkpoint_has_m2k and not replay_has_m2k else "NO_ARTIFACT_DIVERGENCE_DETECTED"
        ),
        "reason": (
            "A fresh regenerate still leaves M2K out of replay_snapshots.decision.entries because that bundle is built "
            "from closed/known trades. The current per-instrument replay checkpoint retains the still-open M2K LONG "
            "from 2026-08-10, so compare must use replay_checkpoint.open_position for open-entry parity and reserve "
            "replay_snapshots entries for closed/known trade P&L."
            if checkpoint_has_m2k and not replay_has_m2k else
            "Replay snapshot and current checkpoint do not show the focused M2K artifact mismatch."
        ),
        "epoch": epoch,
        "focus_day": focus_day,
        "replay_snapshot_has_m2k_entry": replay_has_m2k,
        "replay_snapshot_entries": replay_entries,
        "current_checkpoint_has_m2k_long": checkpoint_has_m2k,
        "current_checkpoint_m2k": checkpoint_m2k,
        "parquet": parquet,
    }


def _signal_path_audit(root: Path) -> dict[str, Any]:
    evidence = []
    patterns = [
        "send_order: placed OPEN BUY M2K",
        "send_order: FILLED OPEN M2K",
        "[shadow] M2K: tu checkpoint 2026-08-09 -> LONG",
        "[shadow] M2K: DOI CHIEU KHOP",
        "B3: broker/file positions match (3 position(s))",
        "roska4_swing gross 10.9% > cap 5.0%",
    ]
    for path in [root / "live_day_0810.log", root / "scheduler_0810.log"]:
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            if any(pattern in line for pattern in patterns):
                evidence.append({"source": f"{path.name}:{i}", "line": line})
    return {
        "status": "OBSERVED" if evidence else "MISSING",
        "focus": "M2K paper-only entry on 2026-08-10",
        "classification": (
            "paper/live entry was generated from live spliced-bar/checkpoint path and broker-filled; replay snapshot did not admit the same entry"
        ),
        "dependency_note": (
            "Raw desired signal is computed from bars/model, but live entry/exit events depend on held positions via diff_desired_vs_held; cap admission depends on existing open positions via guard.admits."
        ),
        "evidence": evidence[:80],
    }


def build_report(root: Path) -> dict[str, Any]:
    history_path = root / "global_index" / "paper_history.json"
    curve_path = root / "global_index" / "backtest_curve.json"
    replay_path = root / "global_index" / "replay_snapshots_data.js"
    trade_log_path = root / "trade_log.jsonl"
    live_state_path = root / "global_index" / "live_state_data.js"

    history = _json(history_path)
    curve_doc = _json(curve_path)
    replay_data = _replay(replay_path)
    live_state = _optional_js_json(live_state_path)
    statement = _latest_flex_statement(root)
    curve = curve_doc.get("equity") or {}
    epoch = str(history.get("epoch"))
    account = float(history.get("account") or curve_doc.get("account") or 0.0)
    days = sorted(day for day in (history.get("days") or {}) if day >= epoch)
    bt_epoch = _asof(curve, epoch)
    first_actual = float((history.get("days") or {}).get(days[0])) if days else None

    backtest_trades = _backtest_entries(replay_path, epoch)
    paper_trades = _paper_closes(trade_log_path, epoch)
    paper_signals = [*_paper_open_signals(trade_log_path, epoch), *_paper_rejected_signals(root, epoch)]
    backtest_signals = [*_backtest_signals(replay_path, epoch), *_checkpoint_open_signals(root, epoch)]
    bt_trade_cum = _cum_by_day(backtest_trades, days)
    paper_trade_cum = _cum_by_day(paper_trades, days)

    rows = []
    last_curve_day = max(curve) if curve else None
    for day in days:
        actual = float(history["days"][day])
        bt_now = curve.get(day)
        expected_account_window = None
        expected_actual_window = None
        if bt_now is not None and bt_epoch is not None:
            expected_account_window = round(account + (float(bt_now) - float(bt_epoch)), 2)
            if first_actual is not None:
                expected_actual_window = round(first_actual + (float(bt_now) - float(bt_epoch)), 2)
        expected_trade = round(account + bt_trade_cum.get(day, 0.0), 2)
        paper_trade_filter_equity = round(account + paper_trade_cum.get(day, 0.0), 2)
        rows.append({
            "date": day,
            "actual_equity": actual,
            "actual_equity_source": "system_ledger_realized_only",
            "expected_equity_account_window": expected_account_window,
            "expected_equity_actual_window": expected_actual_window,
            "expected_equity_trade_filter": expected_trade,
            "paper_trade_filter_equity": paper_trade_filter_equity,
            "paper_trade_realized_cum": paper_trade_cum.get(day, 0.0),
            "backtest_trade_realized_cum": bt_trade_cum.get(day, 0.0),
            "system_ledger_vs_trade_filter": round(actual - paper_trade_filter_equity, 2),
            "account_window_diff": round(actual - expected_account_window, 2) if expected_account_window is not None else None,
            "trade_filter_realized_diff": round(paper_trade_cum.get(day, 0.0) - bt_trade_cum.get(day, 0.0), 2),
            "curve_status": "covered" if bt_now is not None else f"stale_through:{last_curve_day}",
        })

    paper_by_key = {_trade_key(row): row for row in paper_trades}
    bt_by_key = {_trade_key(row): row for row in backtest_trades}
    matched = sorted(set(paper_by_key) & set(bt_by_key))
    classified = _classified_trades(paper_trades, backtest_trades)
    signal_compare = _classified_signals(paper_signals, backtest_signals)
    entry_compare = _entry_compare(paper_signals, backtest_signals, statement)
    open_position_parity = _open_position_parity(root, replay_data, days[-1] if days else None)
    signal_path_audit = _signal_path_audit(root)
    backtest_artifact_audit = _backtest_artifact_audit(root, replay_data, epoch)
    statement_pnl_compare = _statement_pnl_compare(statement, paper_trades, backtest_trades, paper_signals, rows, epoch)
    lifecycle_compare = _lifecycle_compare(paper_signals, paper_trades, backtest_signals, backtest_trades, statement_pnl_compare)
    live_meta = live_state.get("meta") if isinstance(live_state.get("meta"), dict) else {}
    live_final_equity = _number(live_meta.get("final_equity"))
    live_net_pnl = _number(live_meta.get("net_pnl"))
    realtime_system_ledger_pnl = (
        round(live_final_equity - account, 2)
        if live_final_equity is not None and account is not None else live_net_pnl
    )
    latest_daily = rows[-1] if rows else {}
    offset_trace = {
        "status": "MATCHED_PRE_EPOCH_CARRY"
        if statement_pnl_compare.get("ledger_offset_matching_carry_closed")
        else "UNRESOLVED",
        "conclusion": (
            "The runner system ledger includes one intentionally selected Flex carry-in close. "
            "Zero-base strategy comparison keeps excluding it; ledger-aligned reconcile includes it on purpose."
            if statement_pnl_compare.get("ledger_offset_matching_carry_closed") else
            "No exact Flex carry-close match was found for the runner ledger offset."
        ),
        "matching_carry_closed": statement_pnl_compare.get("ledger_offset_matching_carry_closed") or [],
        "ignored_zero_base_fills": statement_pnl_compare.get("flex_epoch_rebased_ignored_fills") or [],
        "comparable_source_of_truth": "flex_ledger_aligned_realized",
        "comparable_flex_realized": statement_pnl_compare.get("flex_ledger_aligned_realized"),
        "system_ledger_is_comparable": bool(statement_pnl_compare.get("ledger_alignment_override", {}).get("included_carry_closed")),
    }

    report = {
        "source": "paper_pnl_compare",
        "inputs": {
            "paper_history": str(history_path.relative_to(root)),
            "backtest_curve": str(curve_path.relative_to(root)),
            "replay_snapshots": str(replay_path.relative_to(root)),
            "trade_log": str(trade_log_path.relative_to(root)),
            "live_state": str(live_state_path.relative_to(root)),
        },
        "convention": {
            "epoch": epoch,
            "account": account,
            "curve_generated": curve_doc.get("generated"),
            "actual_equity_source": "system_ledger_realized_only",
            "actual_equity_note": "Actual is runner system equity from paper_history/live_state, not IBKR NetLiquidation.",
            "formula_account_window": "account + (backtest_curve[date] - backtest_curve[epoch])",
            "formula_trade_filter": "account + cumulative pnl for trades with entry_day >= epoch, realized on exit_day",
            "formula_paper_trade_filter": "account + cumulative paper trade_log pnl_sized for CLOSED trades with entry_day >= epoch",
        },
        "pnl_reconcile": {
            "actual_source": "paper_history.days / live_state.meta.final_equity",
            "actual_semantics": "runner system ledger / sleeve equity, realised-only by design",
            "not_ibkr_equity": True,
            "realtime_system_ledger_pnl": realtime_system_ledger_pnl,
            "realtime_system_ledger_formula": "live_state.meta.final_equity - paper_history.account",
            "realtime_final_equity": live_final_equity,
            "realtime_account_base": account,
            "paper_closed_trade_realized": _number(latest_daily.get("paper_trade_realized_cum")),
            "system_ledger_offset_vs_paper_closed_trades": _number(latest_daily.get("system_ledger_vs_trade_filter")),
            "system_ledger_offset_trace": offset_trace,
            "broker_equity_context": {
                "source": "live_state.meta.broker_equity and live_positions.breaker.last_broker_equity",
                "value": live_meta.get("broker_equity"),
                "not_used_for_pnl_compare": True,
            },
            "bridge_note": (
                "system_ledger_vs_trade_filter is the retained ledger offset versus CLOSED trade_log P&L from the paper epoch. "
                "It is not classified as interest, mark-to-market, or broker cash movement unless an IBKR ledger source is added."
            ),
        },
        "daily": rows,
        "trade_filter": {
            "backtest_closed_or_known_trades": len(backtest_trades),
            "paper_closed_trades": len(paper_trades),
            "matched_trade_keys": len(matched),
            "backtest_trades": backtest_trades,
            "paper_trades": paper_trades,
            "paper_only_keys": sorted(set(paper_by_key) - set(bt_by_key)),
            "backtest_only_keys": sorted(set(bt_by_key) - set(paper_by_key)),
            "classified": classified,
        },
        "signal_compare": {
            "paper_signals": paper_signals,
            "backtest_signals": backtest_signals,
            "classified": signal_compare,
        },
        "entry_compare": entry_compare,
        "lifecycle_compare": lifecycle_compare,
        "open_position_parity": open_position_parity,
        "signal_path_audit": signal_path_audit,
        "backtest_artifact_audit": backtest_artifact_audit,
        "statement_pnl_compare": statement_pnl_compare,
        "ibkr_statement": {
            key: value for key, value in statement.items()
            if key not in {"fills", "closed", "cash"}
        },
        "notes": [
            "Do not compare raw backtest equity level to paper equity level; backtest has compounded since 2018.",
            "Actual/system ledger is not IBKR NetLiquidation; broker equity is context only unless an IBKR ledger/Flex source is wired into the comparison.",
            "paper_history and trade_log can diverge when the epoch starts with carried state or open-position marks; this is shown as system_ledger_vs_trade_filter.",
            "A day beyond backtest_curve.generated must remain missing/stale, not flat-filled.",
            "Exit-day mismatches with the same trade identity are classified separately because the paper/live path can defer stop/exit handling after the 14h/EOD decision.",
            "Signal compare is pre-fill/pre-exit: it checks whether paper and replay emitted the same OPEN/REJECTED decisions by date/instrument/cluster/direction/action.",
            "Entry compare is post-admission/post-fill: it checks whether an OPEN actually admitted/filled in paper and whether IBKR statement confirms the fill.",
        ],
    }
    report["verdicts"] = _pnl_verdicts(report)
    return report


# The dashboard does not compute this report; it reads the file this script writes.
# So a fix to the money logic reaches the screen only when somebody remembers to rerun
# the script -- and until then the panel shows the old code's numbers, looking exactly
# as authoritative as fresh ones. That happened on 2026-08-14: pair_fifo was switched to
# broker Proceeds and the dashboard kept reporting local-point_value lots with no sign
# anything was behind. Stamping the sources lets the reader say so.
SOURCE_FILES = ("monitor/paper_pnl_compare.py", "global_index/statement.py")


def source_signature(root: Path) -> dict[str, Any]:
    """Content hash of the modules whose logic decides this report's numbers.

    Content, not mtime: a checkout or a touch changes mtime without changing behaviour,
    and a stale-warning that cries wolf gets switched off.
    """
    import hashlib

    parts = {}
    for rel in SOURCE_FILES:
        path = root / rel
        try:
            parts[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except OSError:
            parts[rel] = None
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "monitor" / "paper_pnl_compare.json")
    args = parser.parse_args(argv)
    report = build_report(args.root)
    report["source_signature"] = source_signature(args.root)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    latest = report["daily"][-1] if report["daily"] else {}
    print(json.dumps(latest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
