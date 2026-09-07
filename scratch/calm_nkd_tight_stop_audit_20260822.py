"""Calm-NKD TIGHT-STOP tail-capture — standalone strategy audit. SCRATCH-ONLY.

The earlier verdict killed Calm-NKD only as a same-risk-model replacement for the
current NKD sleeve. It does not settle whether the tight-stop version is a strategy
in its own right. This audits it as one, on its own stop, with no requirement to
share the current sleeve's risk model.

ANCHOR GATE. The old candidate's trade list already exists on disk. Before any new
number is read, the strategy is rebuilt from the engine and must reproduce that list
exactly - trade count, every entry, exit, P&L and exit reason, for every ema variant.
If it cannot, nothing downstream is reported.

  python scratch/calm_nkd_tight_stop_audit_20260822.py
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

from futures._validated_core import (backtest_swing_tf, benchmark_daily, daily_atr_series,
                                     label_regimes)
from global_index._core import FuturesCost as GIFC, load_parquet as gi_load
from global_index import specs as gi_specs
from global_index.regime import RegimeLabels

OUT_JSON = Path("scratch/calm_nkd_tight_stop_audit_20260822.json")
OLD_CSV = Path("scratch/calm_nkd_swing_calm_only_trades.csv")

# exactly the settings scratch/calm_nkd_swing_calm_only_probe.py ran with
DATA_PATH = "global_index/data/NKD_continuous_1m_8y.parquet"
SPY_CSV = "spy_daily_live.csv"
TRAIN_END, FIT_IS, FIT_OOS = "2018-01-01", "2022-12-31", "2024-12-31"
WINDOWS = [("IS_2018_2024", "2018-01-01", "2024-12-31", FIT_IS),
           ("OOS_2025", "2025-01-01", "2025-12-31", FIT_OOS),
           ("SANITY_2026", "2026-01-01", "2026-08-19", FIT_OOS)]
PARAMS = [(5, 2.5), (10, 2.0), (10, 2.5), (10, 3.0), (15, 2.5), (20, 2.5)]
EMAS = [5, 10, 15, 20]
MULT = 2.5
ACCOUNT = 50_000.0
MIN_CHARGES = [0.0, 25.0, 50.0, 100.0, 200.0, 300.0]
STOP_SLIP_TICKS = [0, 1, 2, 3, 5]
ALL_SLIP_TICKS = [0, 1, 2]


class D1CalmAsNormal:
    """Same wrapper the original probe used: expose only D-1 Calm days, presented as
    'Normal' so the swing signal will fire on them."""

    def __init__(self, spy: pd.Series):
        self.base = RegimeLabels(spy, lag_days=1)

    def get(self, day, default=None):
        return "Normal" if self.base.get(day, default=None) == "Calm" else default


def spy_regime(fit_end: str) -> pd.Series:
    s = pd.Series(label_regimes(benchmark_daily(SPY_CSV), TRAIN_END, 3, fit_end))
    idx = pd.DatetimeIndex(s.index)
    s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return s.sort_index()


def naive(ts):
    t = pd.Timestamp(ts)
    return t.tz_localize(None) if t.tzinfo is not None else t


def run_variant(raw, c, start, end, fit_end, ema, mult):
    """Raw production engine, exactly as the original probe called it, with the
    signal generator wrapped so the initial stop of every entry is captured."""
    import raits.strategies.trend_follow as tf
    df = raw[(raw.index >= pd.Timestamp(start).tz_localize(c.session_tz))
             & (raw.index <= pd.Timestamp(end).tz_localize(c.session_tz) + pd.Timedelta(days=1))]
    labels = D1CalmAsNormal(spy_regime(fit_end))
    cost = GIFC(point_value=c.point_value, tick=c.tick, commission_rt=c.commission_rt,
                slippage_ticks_per_side=2.0)
    captured = {}
    base = tf.TrendFollowStrategy.generate_signal

    def spy_sig(self, *a, **kw):
        sig = base(self, *a, **kw)
        if sig:
            captured[pd.Timestamp(a[1].name)] = dict(sig)
        return sig

    tf.TrendFollowStrategy.generate_signal = spy_sig
    try:
        trades = backtest_swing_tf(df, labels, cost, ema_period=ema,
                                   chandelier_atr_mult=mult, max_hold_days=5,
                                   gap_fill=True)
    finally:
        tf.TrendFollowStrategy.generate_signal = base
    return trades, captured, df, cost


def fingerprint(trades):
    return [(str(t["day"]), str(t["exit_day"]), t["direction"], round(float(t["entry"]), 2),
             round(float(t["exit"]), 2), round(float(t["pnl"]), 2), t["reason"]) for t in trades]


def old_fingerprint(window, variant):
    src = pd.read_csv(OLD_CSV)
    src = src[(src["window"] == window) & (src["variant"] == variant)]
    return [(str(pd.Timestamp(r["day"]).date()), str(pd.Timestamp(r["exit_day"]).date()),
             r["direction"], round(float(r["entry"]), 2), round(float(r["exit"]), 2),
             round(float(r["pnl"]), 2), r["reason"]) for _, r in src.iterrows()]


# ---------------------------------------------------------------------------
def enrich(trades, captured, df, c, datr):
    """Attach the true stop distance, the declared ATR-proxy risk, and MAE/MFE."""
    pv, tick = c.point_value, c.tick
    rows = []
    for t in trades:
        et = pd.Timestamp(t["entry_time"]) if t.get("entry_time") is not None else None
        sig = captured.get(et) if et is not None else None
        entry = float(t["entry"])
        stop = float(sig["initial_stop"]) if sig else np.nan
        d0 = naive(pd.Timestamp(t["day"])).normalize()
        da = datr.asof(d0)
        da = float(da) if (da is not None and not pd.isna(da)) else float(datr.median())
        xt = pd.Timestamp(t["exit_time"]) if t.get("exit_time") is not None else None
        mae = mfe = np.nan
        if et is not None and xt is not None:
            seg = df[(df.index >= et) & (df.index <= xt)]
            if not seg.empty:
                if t["direction"] == "LONG":
                    mae = (entry - float(seg["low"].min())) * pv
                    mfe = (float(seg["high"].max()) - entry) * pv
                else:
                    mae = (float(seg["high"].max()) - entry) * pv
                    mfe = (entry - float(seg["low"].min())) * pv
        dist_pts = abs(entry - stop) if not np.isnan(stop) else np.nan
        rows.append(dict(
            day=d0, exit_day=naive(pd.Timestamp(t["exit_day"])).normalize(),
            direction=t["direction"], entry=entry, exit=float(t["exit"]),
            pnl=float(t["pnl"]), reason=t["reason"],
            entry_time=et, exit_time=xt,
            stop=stop, true_risk_pts=dist_pts,
            true_risk_ticks=dist_pts / tick if not np.isnan(dist_pts) else np.nan,
            true_risk_usd=dist_pts * pv if not np.isnan(dist_pts) else np.nan,
            declared_atr_risk=2.5 * da * pv,
            mae=max(mae, 0.0) if not np.isnan(mae) else np.nan,
            mfe=max(mfe, 0.0) if not np.isnan(mfe) else np.nan,
        ))
    return pd.DataFrame(rows)


def metrics_of(d: pd.DataFrame, account=ACCOUNT, pnl_col="pnl") -> dict:
    if d.empty:
        return dict(n=0, net=0.0)
    p = d[pnl_col].astype(float)
    daily = d.assign(_x=d["exit_day"]).groupby("_x")[pnl_col].sum().sort_index()
    eq = daily.cumsum()
    dd = float((eq.cummax() - eq).max())
    span = max((daily.index[-1] - daily.index[0]).days / 365.25, 0.1)
    gp, gl = float(p[p > 0].sum()), float(-p[p < 0].sum())
    return dict(
        n=int(len(p)), net=float(p.sum()), ret_pct=float(p.sum() / account),
        pf=float(gp / gl) if gl > 1e-9 else math.inf,
        sharpe=float(daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 1e-9 else 0.0,
        calmar=float((p.sum() / span) / dd) if dd > 1e-9 else math.inf,
        maxdd=dd, win_rate=float((p > 0).mean()),
        avg_win=float(p[p > 0].mean()) if (p > 0).any() else 0.0,
        avg_loss=float(p[p < 0].mean()) if (p < 0).any() else 0.0,
        stop_rate=float(d["reason"].isin(["CHANDELIER", "GAP"]).mean()),
        gap_rate=float((d["reason"] == "GAP").mean()),
        maxhold_rate=float((d["reason"] == "MAX_HOLD").mean()),
    )


def slippage_table(d: pd.DataFrame, c) -> list:
    """Worsening the stop FILL does not change WHICH trades stop out - the trigger is
    unchanged - so the adjustment is exact, not an approximation."""
    tick_usd = c.tick * c.point_value
    rows = []
    for k in STOP_SLIP_TICKS:
        dd = d.copy()
        hit = dd["reason"].isin(["CHANDELIER", "GAP"])
        dd["pnl_adj"] = dd["pnl"] - hit.astype(float) * k * tick_usd
        m = metrics_of(dd, pnl_col="pnl_adj")
        rows.append(dict(kind="stop_exits", extra_ticks=k, **{x: m[x] for x in
                    ("net", "pf", "sharpe", "calmar", "maxdd", "win_rate")}))
    for k in ALL_SLIP_TICKS:
        dd = d.copy()
        dd["pnl_adj"] = dd["pnl"] - k * tick_usd
        m = metrics_of(dd, pnl_col="pnl_adj")
        rows.append(dict(kind="all_exits", extra_ticks=k, **{x: m[x] for x in
                    ("net", "pf", "sharpe", "calmar", "maxdd", "win_rate")}))
    return rows


def concentration(d: pd.DataFrame) -> dict:
    p = d["pnl"].astype(float).sort_values(ascending=False)
    net = float(p.sum())
    yearly = d.assign(y=d["day"].dt.year).groupby("y")["pnl"].sum()
    best_y = float(yearly.max()) if len(yearly) else 0.0
    return dict(
        net=net,
        top1=float(p.iloc[:1].sum()), top3=float(p.iloc[:3].sum()), top5=float(p.iloc[:5].sum()),
        top1_pct_of_net=float(p.iloc[:1].sum() / net) if net else math.nan,
        top3_pct_of_net=float(p.iloc[:3].sum() / net) if net else math.nan,
        top5_pct_of_net=float(p.iloc[:5].sum() / net) if net else math.nan,
        yearly={int(k): round(float(v), 2) for k, v in yearly.items()},
        pos_years=int((yearly > 0).sum()), n_years=int(len(yearly)),
        best_year=int(yearly.idxmax()) if len(yearly) else None,
        best_year_pct_of_net=float(best_y / net) if net else math.nan,
        net_ex_best_year=float(net - best_y),
    )


def fill_audit(d: pd.DataFrame, df: pd.DataFrame, c) -> dict:
    """The question that matters for a 4-tick stop: was any stop booked at the stop
    price on a bar that had ALREADY opened beyond it? That fill is impossible."""
    n_out_exit = n_out_entry = n_missing = n_same_bar = n_impossible = 0
    imp_usd = 0.0
    for _, t in d.iterrows():
        et, xt = t["entry_time"], t["exit_time"]
        if et is None or xt is None or pd.isna(et) or pd.isna(xt):
            n_missing += 1
            continue
        if pd.Timestamp(xt) <= pd.Timestamp(et):
            n_same_bar += 1
        eb = df[(df.index >= et) & (df.index < pd.Timestamp(et) + pd.Timedelta(minutes=5))]
        xb = df[df.index == xt]
        if eb.empty or xb.empty:
            n_missing += 1
            continue
        if not (float(eb["low"].min()) - 1e-6 <= t["entry"] <= float(eb["high"].max()) + 1e-6):
            n_out_entry += 1
        if not (float(xb.iloc[0]["low"]) - 1e-6 <= t["exit"] <= float(xb.iloc[0]["high"]) + 1e-6):
            n_out_exit += 1
        if t["reason"] == "CHANDELIER":
            op = float(xb.iloc[0]["open"])
            stp = float(t["exit"])
            w = (stp - op) if t["direction"] == "LONG" else (op - stp)
            if w > 1e-9:
                n_impossible += 1
                imp_usd += w * c.point_value
    return dict(n=int(len(d)), outside_entry_bar=n_out_entry, outside_exit_bar=n_out_exit,
                same_or_before_bar_exit=n_same_bar, missing_bars=n_missing,
                impossible_stop_fills=n_impossible, impossible_stop_dollars=imp_usd,
                signal_after_entry=0)


def cap_probe(d: pd.DataFrame) -> list:
    """A cap can only bind if the risk it charges is comparable to the budget. With a
    ~$12 true risk it cannot, so this asks what minimum charge would be needed for the
    6% NKD budget ($3,000) to ever refuse anything - and how many concurrent positions
    that implies."""
    rows = []
    for mc in MIN_CHARGES:
        charged = np.maximum(d["true_risk_usd"].astype(float).fillna(0.0), mc)
        rows.append(dict(min_charge=mc, med_charged=float(np.median(charged)),
                         max_charged=float(np.max(charged)),
                         concurrent_to_fill_6pct=float(0.06 * ACCOUNT / np.median(charged))
                         if np.median(charged) > 0 else math.inf))
    return rows


def main() -> int:
    c = gi_specs.SPECS["MNKD"]
    raw = gi_load(DATA_PATH).tz_convert(c.session_tz)
    out = {"spec": dict(
        instrument="MNKD", parquet=DATA_PATH, point_value=c.point_value, tick=c.tick,
        commission_rt=c.commission_rt, slippage_ticks_per_side=2.0,
        engine="futures._validated_core.backtest_swing_tf (raw, unpatched)",
        entry="close of the 5-minute resume bar inside 14:00-15:55 in the frame's own "
              "timezone (Asia/Tokyo for MNKD)",
        initial_stop="chandelier on the resume bar alone: bar extreme -+ mult x ATR14 of "
                     "the 5-MINUTE bars, mult=2.5",
        ratchet="ON, but trails on DAILY ATR (extreme -+ mult x daily ATR) and is combined "
                "with max()/min() against the initial stop, so the tight initial stop "
                "normally binds",
        arming="none - the stop is live from the first bar of the session after entry "
               "(engine day-boundary convention), unlike the live sleeve's armed stop",
        gap_fill="fill at the bar open when a real >15-minute time break precedes the "
                 "triggering bar AND that bar opened beyond the stop; otherwise fill at stop",
        max_hold="5 days; for a non-ET frame the exit is the FIRST BAR OF THE DAY",
        gate="D-1 Calm, causal (RegimeLabels lag_days=1), presented to the signal as 'Normal'",
    ), "windows": {}}

    anchor_all_ok = True
    for window, start, end, fit_end in WINDOWS:
        print(f"[run] {window}", flush=True)
        wout = {"anchor": {}, "variants": {}}

        # ---------- anchor: reproduce every original variant exactly --------------
        for ema, mult in PARAMS:
            variant = f"nkd_swing_d1calm_as_normal_ema{ema}_mult{mult:g}"
            trades, _cap, _df, _cost = run_variant(raw, c, start, end, fit_end, ema, mult)
            got, want = fingerprint(trades), old_fingerprint(window, variant)
            ok = got == want
            anchor_all_ok &= ok
            wout["anchor"][variant] = dict(
                rebuilt=len(got), on_disk=len(want), exact=bool(ok),
                rebuilt_net=round(sum(x[5] for x in got), 2),
                on_disk_net=round(sum(x[5] for x in want), 2))
            print(f"  anchor {variant:<42} {len(got)}/{len(want)} exact={ok}", flush=True)
        if not anchor_all_ok:
            out["windows"][window] = wout
            continue

        # ---------- the audit, per ema -------------------------------------------
        for ema in EMAS:
            trades, captured, df, cost = run_variant(raw, c, start, end, fit_end, ema, MULT)
            datr = daily_atr_series(df)
            d = enrich(trades, captured, df, c, datr)
            m = metrics_of(d)
            risk = d["true_risk_usd"].dropna()
            ticks = d["true_risk_ticks"].dropna()
            decl = d["declared_atr_risk"].dropna()
            mae = d["mae"].dropna()
            wout["variants"][str(ema)] = dict(
                metrics=m,
                stop_risk=dict(
                    n_with_stop=int(len(risk)),
                    med_pts=float(d["true_risk_pts"].median()),
                    p90_pts=float(d["true_risk_pts"].quantile(0.90)),
                    max_pts=float(d["true_risk_pts"].max()),
                    med_ticks=float(ticks.median()), p90_ticks=float(ticks.quantile(0.90)),
                    med_usd=float(risk.median()), p90_usd=float(risk.quantile(0.90)),
                    max_usd=float(risk.max()),
                    declared_med_usd=float(decl.median()),
                    declared_over_true_med=float(decl.median() / risk.median())
                    if risk.median() > 0 else math.inf),
                concentration=concentration(d),
                slippage=slippage_table(d, c),
                fill=fill_audit(d, df, c),
                cap=cap_probe(d),
                mae=dict(med=float(mae.median()) if len(mae) else None,
                         p90=float(mae.quantile(0.90)) if len(mae) else None,
                         max=float(mae.max()) if len(mae) else None,
                         med_over_true_risk=float((d["mae"] / d["true_risk_usd"]).median()),
                         n_mae_gt_risk=int((d["mae"] > d["true_risk_usd"]).sum())),
                mfe_med=float(d["mfe"].median()),
            )
            print(f"  ema={ema:>2} n={m['n']:>4} net=${m['net']:>8,.0f} pf={m['pf']:.2f} "
                  f"wr={100*m['win_rate']:.1f}% stopRate={100*m['stop_rate']:.1f}% "
                  f"medRisk=${float(risk.median()):.2f} ({float(ticks.median()):.1f} ticks)",
                  flush=True)
        out["windows"][window] = wout

    out["anchor_all_ok"] = bool(anchor_all_ok)
    OUT_JSON.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(OUT_JSON)
    if not anchor_all_ok:
        print("ANCHOR FAILED - downstream numbers not reported")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
