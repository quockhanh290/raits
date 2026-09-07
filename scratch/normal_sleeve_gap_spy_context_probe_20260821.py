"""
Normal sleeve gap/open + SPY D-1 context probe - scratch/research only.

Loads corrected Normal sleeve trade tables and post-processes simple causal
context filters. No production code is changed.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

from scratch.normal_sleeve_position_sizing_policy_20260821 import replay
from scratch.normal_sleeve_risk_policy_probe_20260821 import (
    R4,
    build_book,
    build_meta,
    load_trade_json,
)
from scratch.normal_sleeve_volume_filter_probe_20260821 import load_frames


OUT = Path("scratch/normal_sleeve_gap_spy_context_probe_20260821.txt")
JSON_OUT = Path("scratch/normal_sleeve_gap_spy_context_probe_20260821.json")


def load_spy(path: str = "spy_daily_live.csv") -> pd.DataFrame:
    spy = pd.read_csv(path)
    spy.columns = [c.lower() for c in spy.columns]
    spy["date"] = pd.to_datetime(spy["date"]).dt.normalize()
    spy = spy.sort_values("date").set_index("date")
    spy["spy_ret1"] = spy["close"].pct_change()
    spy["spy_ret3"] = spy["close"].pct_change(3)
    spy["spy_sma50"] = spy["close"].rolling(50, min_periods=50).mean()
    spy["spy_above50"] = spy["close"] > spy["spy_sma50"]
    spy["spy_rv20"] = spy["spy_ret1"].rolling(20, min_periods=20).std()
    out = spy.reset_index().rename(columns={"date": "spy_feature_date"})
    return out[["spy_feature_date", "spy_ret1", "spy_ret3", "spy_above50", "spy_rv20"]]


def spy_thresholds(spy_attached_floor: pd.DataFrame) -> dict:
    d = spy_attached_floor.drop_duplicates("entry")
    return {
        "spy_rv20_p70": float(d["spy_rv20"].quantile(0.70)),
        "spy_rv20_p80": float(d["spy_rv20"].quantile(0.80)),
        "spy_ret1_p10": float(d["spy_ret1"].quantile(0.10)),
    }


def _rth(df: pd.DataFrame) -> pd.DataFrame:
    return df[(df.index.time >= pd.Timestamp("09:30").time()) & (df.index.time <= pd.Timestamp("16:00").time())]


def instrument_contexts(frames: dict[str, pd.DataFrame]) -> dict[tuple[str, pd.Timestamp], dict]:
    out = {}
    for inst, df in frames.items():
        idx = df.index.tz_localize(None) if df.index.tz is not None else df.index
        dfn = df.copy()
        dfn.index = idx
        rth = _rth(dfn).copy()
        if rth.empty:
            continue
        rth["_day"] = rth.index.normalize()
        grouped = rth.groupby("_day", sort=True)
        daily_df = pd.DataFrame({
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
        })
        daily_df["range_pct"] = (daily_df["high"] - daily_df["low"]) / daily_df["close"].abs().clip(lower=1e-9)
        prev_df = daily_df.shift(1)
        for day, cur in daily_df.iterrows():
            prev = prev_df.loc[day]
            if prev.isna().any():
                continue
            prange = max(prev["high"] - prev["low"], 1e-9)
            gap = (cur["open"] - prev["close"]) / max(abs(prev["close"]), 1e-9)
            open_loc = (cur["open"] - prev["low"]) / prange
            prev_cloc = (prev["close"] - prev["low"]) / prange
            prev_ret = (prev["close"] - prev["open"]) / max(abs(prev["open"]), 1e-9)
            out[(inst, day.normalize())] = {
                "gap": gap,
                "gap_abs": abs(gap),
                "open_loc": open_loc,
                "open_inside_prior": 0.0 <= open_loc <= 1.0,
                "open_not_deep_below_prior": open_loc >= -0.05,
                "prev_cloc": prev_cloc,
                "prev_ret": prev_ret,
                "prev_trend_down": prev_ret < 0.0 and prev_cloc <= 0.35,
                "prev_range_pct": prev["range_pct"],
            }
    return out


def load_book_with_context(which: str, spy: pd.DataFrame) -> list[dict]:
    raw = load_trade_json(which)
    meta = build_meta(raw)
    nkd = raw["nkd_instrument"]
    trades = {k: raw["corrected"][k] for k in R4}
    trades[nkd] = raw["corrected"][nkd]
    book = build_book(trades, meta)
    ctx = instrument_contexts(load_frames(raw))
    for t in book:
        key = (t["inst"], pd.Timestamp(t["entry"]).normalize())
        t.update(ctx.get(key, {}))
    rows = pd.DataFrame([{"ix": i, "entry": pd.Timestamp(t["entry"]).normalize()} for i, t in enumerate(book)])
    rows = pd.merge_asof(
        rows.sort_values("entry"),
        spy.sort_values("spy_feature_date"),
        left_on="entry",
        right_on="spy_feature_date",
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("ix")
    for row in rows.to_dict("records"):
        t = book[int(row["ix"])]
        for k in ("spy_ret1", "spy_ret3", "spy_above50", "spy_rv20"):
            t[k] = row.get(k)
    return book


def applies(t: dict, scope: str) -> bool:
    if scope == "all":
        return True
    if scope == "r4":
        return t["cluster"] == "roska4_swing"
    if scope == "nkd":
        return t["cluster"] == "global_nkd"
    if scope == "r4_long":
        return t["cluster"] == "roska4_swing" and t["direction"] == "LONG"
    if scope == "r4_short":
        return t["cluster"] == "roska4_swing" and t["direction"] == "SHORT"
    raise ValueError(scope)


def finite(t: dict, key: str) -> float:
    x = t.get(key, np.nan)
    try:
        return float(x)
    except Exception:
        return float("nan")


def rule_pass(t: dict, rule: dict) -> bool:
    if rule["scope"] != "none" and not applies(t, rule["scope"]):
        return True
    if rule["kind"] == "none":
        return True
    gap = finite(t, "gap")
    open_loc = finite(t, "open_loc")
    prev_range = finite(t, "prev_range_pct")
    spy_ret1 = finite(t, "spy_ret1")
    spy_ret3 = finite(t, "spy_ret3")
    spy_rv20 = finite(t, "spy_rv20")
    if rule["kind"] == "gap_not_deep":
        return np.isfinite(gap) and gap >= -0.006
    if rule["kind"] == "gap_flat":
        return np.isfinite(gap) and -0.006 <= gap <= 0.004
    if rule["kind"] == "open_inside":
        return np.isfinite(open_loc) and 0.0 <= open_loc <= 1.0
    if rule["kind"] == "open_not_deep":
        return np.isfinite(open_loc) and open_loc >= -0.05
    if rule["kind"] == "gap_not_deep_inside":
        return np.isfinite(gap) and np.isfinite(open_loc) and gap >= -0.006 and 0.0 <= open_loc <= 1.0
    if rule["kind"] == "prev_range_cap":
        return np.isfinite(prev_range) and prev_range <= rule["prev_range_cap"]
    if rule["kind"] == "spy_not_crash":
        return np.isfinite(spy_ret1) and spy_ret1 >= rule["spy_ret1_p10"]
    if rule["kind"] == "spy_ret_mild_down":
        return np.isfinite(spy_ret1) and -0.015 <= spy_ret1 <= 0.0
    if rule["kind"] == "spy_ret3_down":
        return np.isfinite(spy_ret3) and spy_ret3 <= 0.0
    if rule["kind"] == "spy_rv80":
        return np.isfinite(spy_rv20) and spy_rv20 <= rule["spy_rv20_p80"]
    if rule["kind"] == "gap_inside_spy_not_crash":
        return (
            np.isfinite(gap) and np.isfinite(open_loc) and np.isfinite(spy_ret1)
            and gap >= -0.006 and 0.0 <= open_loc <= 1.0 and spy_ret1 >= rule["spy_ret1_p10"]
        )
    if rule["kind"] == "gap_inside_rv80":
        return (
            np.isfinite(gap) and np.isfinite(open_loc) and np.isfinite(spy_rv20)
            and gap >= -0.006 and 0.0 <= open_loc <= 1.0 and spy_rv20 <= rule["spy_rv20_p80"]
        )
    raise ValueError(rule["kind"])


def rules(th: dict, floor_books: dict[str, list[dict]]) -> list[dict]:
    out = [dict(name="none", scope="none", kind="none")]
    for scope in ("all", "r4", "nkd", "r4_long", "r4_short"):
        for kind in (
            "gap_not_deep",
            "gap_flat",
            "open_inside",
            "open_not_deep",
            "gap_not_deep_inside",
            "spy_not_crash",
            "spy_ret_mild_down",
            "spy_ret3_down",
            "spy_rv80",
            "gap_inside_spy_not_crash",
            "gap_inside_rv80",
        ):
            r = dict(name=f"{scope}_{kind}", scope=scope, kind=kind, **th)
            out.append(r)
    # Prior range cap is derived once from floor trade days, then reused OOS.
    vals = [finite(t, "prev_range_pct") for t in floor_books["floor"] if np.isfinite(finite(t, "prev_range_pct"))]
    for q in (0.7, 0.8, 0.9):
        cap = float(np.quantile(vals, q)) if vals else float("inf")
        for scope in ("all", "r4", "nkd"):
            out.append(dict(name=f"{scope}_prev_range_le_p{int(q*100)}", scope=scope, kind="prev_range_cap", prev_range_cap=cap, **th))
    return out


def run_rule(book: list[dict], rule: dict) -> dict:
    kept = [t for t in book if rule_pass(t, rule)]
    skipped = [t for t in book if not rule_pass(t, rule)]
    cur = replay(kept, swing_gross=0.050, swing_net=0.044, nkd_cap=0.060, breaker=0.15, release="latch")
    strict = replay(kept, swing_gross=0.025, swing_net=0.025, nkd_cap=0.060, breaker=0.15, release="latch")
    return {
        "rule": rule["name"],
        "kept": len(kept),
        "skipped": len(skipped),
        "skipped_pnl": float(sum(t["pnl_sized"] for t in skipped)),
        "net": cur["net"],
        "pf": cur["pf"],
        "sharpe": cur["sharpe"],
        "calmar": cur["calmar"],
        "maxdd_pct": cur["maxdd_pct"],
        "halted": cur["halted_days"],
        "blocked": cur["blocked_trades"],
        "strict025_net": strict["net"],
        "strict025_pf": strict["pf"],
        "strict025_calmar": strict["calmar"],
        "strict025_maxdd_pct": strict["maxdd_pct"],
    }


def fmt_pf(x: float) -> str:
    return "inf" if math.isinf(x) else f"{x:.2f}"


def main() -> int:
    report = []

    def emit(s: str = ""):
        print(s, flush=True)
        report.append(s)

    spy = load_spy()
    books = {w: load_book_with_context(w, spy) for w in ("floor", "vault2025", "vault2026")}
    th = spy_thresholds(pd.DataFrame(books["floor"]))
    grid = rules(th, books)
    results = {}
    for which, book in books.items():
        rows = [dict(which=which, **run_rule(book, rule)) for rule in grid]
        results[which] = rows
        base = next(r for r in rows if r["rule"] == "none")
        ranked = sorted(
            [r for r in rows if r["kept"] >= max(40, int(base["kept"] * 0.35))],
            key=lambda r: (r["calmar"], r["net"]),
            reverse=True,
        )
        emit("#" * 118)
        emit(f"WINDOW: {which}")
        emit("#" * 118)
        emit("base: net ${:,.0f} PF {} Sharpe {:.2f} Calmar {:.2f} MaxDD {:.1%} kept {}".format(
            base["net"], fmt_pf(base["pf"]), base["sharpe"], base["calmar"], base["maxdd_pct"], base["kept"]))
        emit("  {:<36} {:>5} {:>6} {:>10} {:>5} {:>7} {:>7} {:>8} {:>7}".format(
            "rule", "kept", "skip", "net$", "PF", "Sharpe", "Calmar", "MaxDD%", "block"))
        for r in ranked[:28]:
            emit("  {:<36} {:>5} {:>6} {:>10,.0f} {:>5} {:>7.2f} {:>7.2f} {:>8.1%} {:>7}".format(
                r["rule"], r["kept"], r["skipped"], r["net"], fmt_pf(r["pf"]), r["sharpe"],
                r["calmar"], r["maxdd_pct"], r["blocked"]))
        emit("")

    emit("=" * 118)
    emit("CROSS-WINDOW FOR FLOOR-TOP RULES")
    emit("=" * 118)
    by = {w: {r["rule"]: r for r in rows} for w, rows in results.items()}
    floor_base = next(r for r in results["floor"] if r["rule"] == "none")
    floor_top = sorted(
        [r for r in results["floor"] if r["kept"] >= max(40, int(floor_base["kept"] * 0.35))],
        key=lambda r: (r["calmar"], r["net"]),
        reverse=True,
    )[:18]
    emit("  {:<36} {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7} | {:>10} {:>5} {:>7}".format(
        "rule", "floor$", "PF", "Calmar", "2025$", "PF", "Calmar", "2026$", "PF", "Calmar"))
    for fr in floor_top:
        r25 = by["vault2025"][fr["rule"]]
        r26 = by["vault2026"][fr["rule"]]
        emit("  {:<36} {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f} | {:>10,.0f} {:>5} {:>7.2f}".format(
            fr["rule"], fr["net"], fmt_pf(fr["pf"]), fr["calmar"],
            r25["net"], fmt_pf(r25["pf"]), r25["calmar"],
            r26["net"], fmt_pf(r26["pf"]), r26["calmar"]))

    JSON_OUT.write_text(json.dumps({"thresholds": th, "results": results}, indent=2), encoding="utf-8")
    OUT.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
