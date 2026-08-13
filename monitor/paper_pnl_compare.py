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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _replay(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw[raw.find("{"):raw.rfind("}") + 1])


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
            "paper_exit_reason": paper.get("exit_reason"),
            "backtest_exit_reason": backtest.get("exit_reason") if backtest else None,
        })

    for backtest in backtest_trades:
        if _trade_key(backtest) in used_bt:
            continue
        rows.append({
            "classification": "BACKTEST_ONLY",
            "reason": "backtest trade has no paper close with same instrument, cluster, direction, and entry day",
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
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(item.get("type")).upper() != "CLOSE":
            continue
        entry_day = _date(item.get("entry_day"))
        exit_day = _date(item.get("exit_day"))
        if not entry_day or entry_day < epoch:
            continue
        rows.append({
            "inst": item.get("inst"),
            "cluster": item.get("cluster"),
            "direction": item.get("direction"),
            "entry_day": entry_day,
            "exit_day": exit_day,
            "pnl": float(item.get("pnl_sized") or 0.0),
            "exit_reason": item.get("exit_reason"),
            "source": item.get("source"),
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
            rows.append({
                "inst": item.get("inst"),
                "cluster": item.get("cluster"),
                "direction": item.get("direction"),
                "entry_day": entry_day,
                "exit_day": exit_day,
                "pnl": float(item.get("pnl_sized") or 0.0),
                "exit_reason": item.get("exit_reason"),
                "entry_price": item.get("entry_price"),
                "exit_price": item.get("exit_price"),
            })
    return rows


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


def build_report(root: Path) -> dict[str, Any]:
    history_path = root / "global_index" / "paper_history.json"
    curve_path = root / "global_index" / "backtest_curve.json"
    replay_path = root / "global_index" / "replay_snapshots_data.js"
    trade_log_path = root / "trade_log.jsonl"

    history = _json(history_path)
    curve_doc = _json(curve_path)
    curve = curve_doc.get("equity") or {}
    epoch = str(history.get("epoch"))
    account = float(history.get("account") or curve_doc.get("account") or 0.0)
    days = sorted(day for day in (history.get("days") or {}) if day >= epoch)
    bt_epoch = _asof(curve, epoch)
    first_actual = float((history.get("days") or {}).get(days[0])) if days else None

    backtest_trades = _backtest_entries(replay_path, epoch)
    paper_trades = _paper_closes(trade_log_path, epoch)
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
        rows.append({
            "date": day,
            "actual_equity": actual,
            "expected_equity_account_window": expected_account_window,
            "expected_equity_actual_window": expected_actual_window,
            "expected_equity_trade_filter": expected_trade,
            "paper_trade_realized_cum": paper_trade_cum.get(day, 0.0),
            "backtest_trade_realized_cum": bt_trade_cum.get(day, 0.0),
            "account_window_diff": round(actual - expected_account_window, 2) if expected_account_window is not None else None,
            "trade_filter_realized_diff": round(paper_trade_cum.get(day, 0.0) - bt_trade_cum.get(day, 0.0), 2),
            "curve_status": "covered" if bt_now is not None else f"stale_through:{last_curve_day}",
        })

    paper_by_key = {_trade_key(row): row for row in paper_trades}
    bt_by_key = {_trade_key(row): row for row in backtest_trades}
    matched = sorted(set(paper_by_key) & set(bt_by_key))
    classified = _classified_trades(paper_trades, backtest_trades)

    return {
        "source": "paper_pnl_compare",
        "inputs": {
            "paper_history": str(history_path.relative_to(root)),
            "backtest_curve": str(curve_path.relative_to(root)),
            "replay_snapshots": str(replay_path.relative_to(root)),
            "trade_log": str(trade_log_path.relative_to(root)),
        },
        "convention": {
            "epoch": epoch,
            "account": account,
            "curve_generated": curve_doc.get("generated"),
            "formula_account_window": "account + (backtest_curve[date] - backtest_curve[epoch])",
            "formula_trade_filter": "account + cumulative pnl for trades with entry_day >= epoch, realized on exit_day",
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
        "notes": [
            "Do not compare raw backtest equity level to paper equity level; backtest has compounded since 2018.",
            "paper_history and trade_log can diverge when the epoch starts with carried state or open-position marks.",
            "A day beyond backtest_curve.generated must remain missing/stale, not flat-filled.",
            "Exit-day mismatches with the same trade identity are classified separately because the paper/live path can defer stop/exit handling after the 14h/EOD decision.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "monitor" / "paper_pnl_compare.json")
    args = parser.parse_args(argv)
    report = build_report(args.root)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    latest = report["daily"][-1] if report["daily"] else {}
    print(json.dumps(latest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
