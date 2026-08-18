"""
futures/swing_tf.py — swing TREND_FOLLOW engine (production wrapper, GĐ0)
========================================================================
Approach (a): wrap the VALIDATED backtest_swing_tf so production == validated
numbers BY CONSTRUCTION (identical code path). Gives the runner/sizer a clean
class interface. Reconcile is automatic; reconcile_gd0.py documents it and
catches future drift.

Dependency: futures._validated_core (internalized validated logic) + raits.*
(raits.hmm for regimes, raits.strategies.trend_follow for entry). No root scripts.
"""
from __future__ import annotations
from dataclasses import dataclass

import pandas as pd

from futures.basket import BASKET, SWING_TF_PARAM, REGIME, data_filename
from futures.cost import FuturesCost


@dataclass
class SwingTFEngine:
    """Swing trend-follow engine for one or more instruments. Stateless backtest
    wrappers now; live position-state interface lands in GĐ4 (runner + IBKR)."""
    ema_period: int = SWING_TF_PARAM["ema_period"]
    chandelier_atr_mult: float = SWING_TF_PARAM["chandelier_atr_mult"]
    max_hold_days: int = SWING_TF_PARAM["max_hold_days"]

    # ── validated backtest (single instrument) ────────────────────────────────
    def backtest(self, df, labels, cost, *, entry_days=None, gap_fill=True):
        """Run the validated swing backtest for ONE instrument → list of trade dicts.
        Reuses backtest_swing_tf — the exact code that produced WFO 2.31 / vault 3.21."""
        from futures._validated_core import backtest_swing_tf
        return backtest_swing_tf(
            df, labels, cost,
            ema_period=self.ema_period,
            chandelier_atr_mult=self.chandelier_atr_mult,
            max_hold_days=self.max_hold_days,
            entry_days=entry_days, gap_fill=gap_fill)

    # ── validated backtest (basket) ───────────────────────────────────────────
    def backtest_basket(self, dfs: dict, labels, costs: dict, *, gap_fill=True):
        """dfs / costs: dict instrument -> df / FuturesCost.
        Returns dict instrument -> list of trade dicts."""
        return {name: self.backtest(dfs[name], labels, costs[name], gap_fill=gap_fill)
                for name in dfs}

    # ── live signal: the position the engine WANTS to hold right now ───────────
    def desired_position(self, df, labels, cost, *, reason_out=None):
        """Run the validated backtest on data-through-now and return the OPEN
        position at the end (the live target). Live runner reconciles the broker
        to this → live == backtest by construction. Returns dict or None:
        {direction, entry, stop, entry_day}.

        reason_out: optional single-entry dict. When given, and the backtest closed a
        trade on this data's last day, it receives that trade's exit reason
        (CHANDELIER / GAP / MAX_HOLD).

        The reason has always existed -- backtest_swing_tf writes it on every trade it
        closes -- but this method discarded the trade list and kept only the open
        position, so the live path lost it at exactly the point where the position stops
        being desired. Downstream, a CLOSE reached the trade log with exit_reason=None
        and the exit_path_coverage gate could never fill: not for lack of samples, but
        because nothing recorded which path each exit took.

        Keyword-only with a None default so every existing caller and test double is
        unaffected, and so this stays observational: nothing here changes what is
        returned or what the runner then does.
        """
        from futures._validated_core import backtest_swing_tf
        trades, pos = backtest_swing_tf(
            df, labels, cost,
            ema_period=self.ema_period,
            chandelier_atr_mult=self.chandelier_atr_mult,
            max_hold_days=self.max_hold_days, return_open=True)
        if reason_out is not None:
            self._record_exit_reason(reason_out, trades, df)
        if pos is None:
            return None
        return dict(direction=pos["dir"], entry=float(pos["entry"]),
                    stop=float(pos["stop"]), entry_day=pos["entry_day"])

    @staticmethod
    def _record_exit_reason(reason_out: dict, trades, df) -> None:
        """Report a reason only for a trade that closed on the last bar's own day.

        Without the date check the last trade in the list would be reported forever:
        a position closed a week ago would relabel today's exit with last week's reason,
        which is worse than no label at all -- it reads as evidence.
        """
        if not trades or df is None or len(df.index) == 0:
            return
        last = trades[-1]
        reason = last.get("reason")
        exit_day = last.get("exit_day")
        if not reason or exit_day is None:
            return
        # So hai vế trong CÙNG một khung giờ.
        #
        # Bản đầu so `pd.Timestamp(exit_day)` — naive, dựng từ chuỗi ngày — với
        # `df.index[-1]` — mang múi giờ, vì khung sống là America/New_York. Phép `!=`
        # giữa naive và có-múi-giờ không ném lỗi, nó chỉ luôn trả True. Nên điều kiện
        # KHÔNG BAO GIỜ thoả trên đường sống và hàm này chưa từng gán được nhãn nào.
        #
        # Đo được 2026-08-18: lấy đúng ngày của thanh cuối làm exit_day, hàm vẫn báo
        # "khác nhau"; bỏ múi giờ hai vế thì bằng. Hệ quả: cả 4 lệnh đóng trong kỳ giấy
        # không mang lý do, `exit_path_coverage` đứng ở 0/0/0, và đồng hồ 60 ngày chạy
        # trên một cổng không thể tiến.
        #
        # `tz_localize(None)` chứ không `tz_convert(None)`: cần giữ NGÀY THEO GIỜ SÀN,
        # còn convert sẽ đổi sang UTC trước rồi mới bỏ, làm lệch ngày ở các phiên tối.
        try:
            _exit = pd.Timestamp(exit_day)
            _last = pd.Timestamp(df.index[-1])
            if _exit.tz is not None:
                _exit = _exit.tz_localize(None)
            if _last.tz is not None:
                _last = _last.tz_localize(None)
            if _exit.normalize() != _last.normalize():
                return
        except (TypeError, ValueError):
            return
        reason_out["reason"] = str(reason)
        reason_out["exit_day"] = str(exit_day)

    def desired_basket(self, dfs: dict, labels, costs: dict, *, reasons_out=None):
        """dict instrument -> desired_position (or None) across the basket.

        reasons_out: optional dict; receives {instrument: {reason, exit_day}} for any
        instrument whose backtest closed a trade on the last bar's day.
        """
        out = {}
        for name in dfs:
            per_inst = {} if reasons_out is not None else None
            out[name] = self.desired_position(dfs[name], labels, costs[name],
                                              reason_out=per_inst)
            if per_inst:
                reasons_out[name] = per_inst
        return out


def costs_for_basket(slippage_ticks: float = 1.0) -> dict:
    """FuturesCost per basket instrument, using exchange tick specs from basket.py."""
    return {name: FuturesCost(point_value=c.point_value, tick=c.tick,
                              slippage_ticks_per_side=slippage_ticks)
            for name, c in BASKET.items()}


def load_basket(data_dir: str, vault_start: str | None = None):
    """Load each basket instrument's parquet. Returns dict instrument -> DataFrame.
    If vault_start given, keeps only bars BEFORE it (WFO region)."""
    from futures._validated_core import load_parquet
    import pandas as pd
    from pathlib import Path
    dfs = {}
    for name, c in BASKET.items():
        df = load_parquet(str(Path(data_dir) / data_filename(c)))
        if vault_start:
            vs = pd.Timestamp(vault_start)
            df = df[df.index < vs.tz_localize(df.index.tz)]
        dfs[name] = df
    return dfs


def basket_labels(regime_csv: str, hmm_train_end: str = "2018-01-01",
                  vault_cut: str | None = None):
    """Regime labels via the VALIDATED path (label_regimes / raw HMM, SPY-based)."""
    from futures._validated_core import benchmark_daily, label_regimes
    import pandas as pd
    daily = benchmark_daily(regime_csv)
    if vault_cut:
        daily = daily[daily.index < pd.Timestamp(vault_cut)]
    return label_regimes(daily, hmm_train_end, REGIME["n_components"], REGIME["hmm_fit_end"])
