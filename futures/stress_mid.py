"""
futures/stress_mid.py — STRESS_MID sleeve engine (production wrapper, GĐ0)
=========================================================================
Promotes the validated STRESS_MID adapter (intraday SHORT in Stress regime,
10:15 → 14:00) to a production class, analogous to swing_tf.py. Wraps the validated
StressMidAdapter (validated, the exact code that produced STRESS_MID vault GO)
so production == validated by construction.

Role: STRESS sleeve (hedge), NOT a steady engine — trades only Stress regime
(~5 trades/yr, hibernates calm years). Deployed ALONGSIDE swing TF; their
combined exposure is capped by net_exposure.py.

Dependency: futures._validated_core (internalized StressMidAdapter). No root scripts.
"""
from __future__ import annotations
from dataclasses import dataclass


# validated STRESS_MID params (pooled vault used defaults; MNQ was best, beta -0.03)
STRESS_MID_PARAM = {"target_rr": 2.0, "max_stop_pct": 0.015, "stop_pad": 0.001}


@dataclass
class StressMidEngine:
    target_rr: float = STRESS_MID_PARAM["target_rr"]
    max_stop_pct: float = STRESS_MID_PARAM["max_stop_pct"]
    stop_pad: float = STRESS_MID_PARAM["stop_pad"]

    def backtest(self, df, labels, cost):
        """Run validated STRESS_MID for ONE instrument → list of trade dicts
        (day, exit_day, regime, direction, entry, exit, points, pnl). Stress days only."""
        from futures._validated_core import StressMidAdapter, resample_5m
        import pandas as pd
        adapter = StressMidAdapter({
            "target_rr": self.target_rr,
            "max_stop_pct": self.max_stop_pct,
            "stop_pad": self.stop_pad})
        out = []
        for day, g in df.groupby(df.index.normalize()):
            key = pd.Timestamp(day).tz_localize(None).normalize()
            reg = labels.get(key)
            if reg in adapter.allowed:               # {"Stress"}
                for t in adapter.run_day(resample_5m(g), reg, cost):
                    out.append(dict(day=pd.Timestamp(t.day).date(),
                                    exit_day=pd.Timestamp(t.day).date(),
                                    regime=t.regime, direction=t.direction,
                                    entry=round(t.entry, 2), exit=round(t.exit, 2),
                                    points=round(t.points, 2), pnl=round(t.pnl, 2),
                                    reason="STRESS_MID",
                                    entry_time=t.entry_time,
                                    exit_time=t.exit_time,
                                    exit_reason=(t.meta.get("reason") if t.meta else None)))
        return out

    def backtest_basket(self, dfs: dict, labels, costs: dict):
        return {name: self.backtest(dfs[name], labels, costs[name]) for name in dfs}

    # ── live entry signal at 10:15 (intraday; sleeve cannot use EOD reconcile) ─
    def entry_signal(self, bars_through_1015, regime: str):
        """Entry decision at 10:15 from today's bars (9:30→10:15). Returns
        {direction, entry, stop, target} or None. Mirrors the validated adapter's
        entry rule. MUST be reconcile-tested vs StressMidAdapter before live use
        (re-extraction → verify trade-for-trade on historical Stress days)."""
        import pandas as pd
        if regime != "Stress":
            return None
        day = bars_through_1015.between_time("09:30", "10:15")
        if len(day) < 5:
            return None
        open_px = float(day.iloc[0]["open"])
        entry = float(day.iloc[-1]["close"])           # close at 10:15
        tp = (day["high"] + day["low"] + day["close"]) / 3.0
        v = day["volume"]
        vwap = float((tp * v).sum() / v.sum()) if v.sum() > 0 else entry
        if entry >= vwap or entry >= open_px:          # need below VWAP AND below open
            return None
        swing = day.between_time("09:45", "10:15")
        ref = float(swing["high"].max()) if not swing.empty else entry * 1.005
        stop = ref * (1 + self.stop_pad)
        stop_dist = stop - entry
        if stop_dist <= 0 or stop_dist / entry > self.max_stop_pct:
            return None
        target = entry - self.target_rr * stop_dist
        return dict(direction="SHORT", entry=entry, stop=stop, target=target)
