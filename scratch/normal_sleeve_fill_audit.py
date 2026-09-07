"""
scratch/normal_sleeve_fill_audit.py - independent fill-feasibility audit of the
Normal sleeve (Ro 4 swing TF + the MNKD/NKD extra sleeve). Scratch/research only.

READ-ONLY with respect to production code. Nothing here writes to futures/,
global_index/ or raits/. The engine is driven through scratch/harness.py exactly
the way scratch/normal_sleeve_validation.py drives it, so the trades audited here
ARE the trades the current Normal config produces - not a re-implementation.

WHAT IT DOES
------------
Per window (floor 2018-2024 / 2025 OOS / 2026-to-date):

 1. Run global_index.deploy_sim.main() ONCE under the current Normal config,
    intercepting futures._validated_core.backtest_swing_tf so that
      * the RAW trade list (before any fill correction) is stashed per instrument
      * the list handed back to deploy_sim is the harness-corrected one, i.e. the
        list the current config actually books.
    deploy_sim's own printed metrics are then the ANCHOR: the re-assembly below
    must reproduce them to the dollar before any new number is read.

 2. Audit every trade against the instrument's own 1-minute bars:
      outside_exit_bar        exit price outside the exit bar's [low, high]
      outside_exit_day        exit price outside the exit day's [low, high]
      signal_after_entry      fill instant earlier than signal availability
      same_or_before_bar_exit exit timestamp at/earlier than the entry fill instant
      exit_before_entry       exit day earlier than entry day

 3. Build a CORRECTED trade table under the conservative path law:
      LONG  stop fill = min(stop, exit-bar open)
      SHORT stop fill = max(stop, exit-bar open)
    i.e. a stop the market gapped through fills at the ACTUAL bar open,
    unconditionally. The engine only does this when a >15-minute time break
    precedes the bar, which is why a thin overnight price jump between two
    adjacent 1-minute bars books a fill at a price that never traded.

 4. Re-assemble and replay six variants through deploy_sim's OWN risk layer
    (MultiClusterGuard + CircuitBreaker + the same sizer) and report full metrics.

    python scratch/normal_sleeve_fill_audit.py --which floor vault2025 vault2026
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import scratch.harness as H
from scratch.harness import ARM_LIVE, Cfg, patched_engine
from scratch.directional_market_filter_probe import allowed_short_days, feature_frame

ACCOUNT = 50_000.0
PRICE_EPS = 0.011          # trade prices are round(x, 2); bar OHLC is not
R4 = ["MES", "MNQ", "MYM", "M2K"]


# =============================================================================
# 1. run one window, capture raw + booked trades
# =============================================================================
def run_window(which: str, spy_csv: str) -> dict:
    """Drive deploy_sim once under the current Normal config. Returns everything
    needed to audit and to re-assemble variants."""
    import futures._validated_core as VC
    import futures.stress_mid as SM
    import futures.swing_tf as ST
    import global_index.deploy_sim as DS
    import raits.strategies.trend_follow as tf

    cap = dict(r4_dfs={}, raw={}, booked={}, fix_n=0, fix_tot=0.0)
    stat = {"n": 0, "tot": 0.0}
    cfg = Cfg(fix_fill=False,                 # we apply _correct ourselves, see below
              arm_hours=ARM_LIVE, ratchet=False, roska4_only=False,
              ema=50, stop_basis=2.0)
    orig_bt, bt_fn = patched_engine(cfg, stat)

    old_allowed = list(tf.DEFAULT_CONFIG["allowed_regimes"])
    old_generate = tf.TrendFollowStrategy.generate_signal
    old_defaults = dict(tf.DEFAULT_CONFIG)
    old_stress_cls = SM.StressMidEngine
    old_swing_cls = ST.SwingTFEngine

    short_days = allowed_short_days(feature_frame(spy_csv), "below_sma50")

    def filtered_generate(self, *a, **kw):
        sig = old_generate(self, *a, **kw)
        if not sig or sig.get("direction") != "SHORT":
            return sig
        resume_bar = a[1]
        day = pd.Timestamp(resume_bar.name).tz_localize(None).normalize()
        return sig if day in short_days else None

    class PatchedSwingTFEngine:
        def __init__(self):
            self._inner = old_swing_cls(ema_period=30, chandelier_atr_mult=2.5,
                                        max_hold_days=5)

        def backtest_basket(self, dfs, labels, costs, **kw):
            cap["r4_dfs"] = dict(dfs)          # name -> df, for id() mapping
            return self._inner.backtest_basket(dfs, labels, costs, **kw)

    class NoStressEngine:
        def backtest_basket(self, dfs, labels, costs):
            return {name: [] for name in dfs}

    def capturing_bt(df, labels, cost, **kw):
        """RAW trades out of the engine; stash them, hand back the harness-corrected
        list so deploy_sim books exactly what the current config books."""
        raw = bt_fn(df, labels, cost, **kw)
        if kw.get("return_open") or kw.get("resume_pos") is not None:
            return raw
        booked, n, tot = H._correct(raw, df, cost.point_value, ARM_LIVE)
        cap["raw"][id(df)] = ([dict(t) for t in raw], df, float(cost.point_value))
        cap["booked"][id(df)] = [dict(t) for t in booked]
        cap["fix_n"] += n
        cap["fix_tot"] += tot
        return booked

    VC.backtest_swing_tf = capturing_bt
    tf.DEFAULT_CONFIG["allowed_regimes"] = ["Normal"]
    tf.TrendFollowStrategy.generate_signal = filtered_generate
    ST.SwingTFEngine = PatchedSwingTFEngine
    SM.StressMidEngine = NoStressEngine

    argv = [x for x in H.ARGV[which] if x != "--include-stress"]
    buf = io.StringIO()
    try:
        old_argv = sys.argv
        sys.argv = ["deploy_sim"] + argv
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old_argv
    finally:
        VC.backtest_swing_tf = orig_bt
        tf.DEFAULT_CONFIG.clear()
        tf.DEFAULT_CONFIG.update(old_defaults)
        tf.DEFAULT_CONFIG["allowed_regimes"] = old_allowed
        tf.TrendFollowStrategy.generate_signal = old_generate
        SM.StressMidEngine = old_stress_cls
        ST.SwingTFEngine = old_swing_cls

    out = buf.getvalue()
    cap["ds_out"] = out
    cap["ds_metrics"] = parse_ds(out)
    cap["argv"] = argv

    id2name = {id(df): n for n, df in cap["r4_dfs"].items()}
    inst = {}
    for k, (raw, df, pv) in cap["raw"].items():
        name = id2name.get(k) or _nkd_instrument(argv)
        inst[name] = dict(raw=raw, booked=cap["booked"][k], df=df, pv=pv)
    cap["inst"] = inst
    return cap


def _nkd_instrument(argv) -> str:
    if "--nkd-instrument" in argv:
        return argv[argv.index("--nkd-instrument") + 1]
    return "MNKD"


def parse_ds(out: str) -> dict:
    m = {}
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("net $"):
            try:
                m["net"] = float(s.split("net $")[1].split("|")[0].strip().replace(",", ""))
                m["calmar"] = float(s.split("Calmar")[1].split("|")[0].strip())
                m["pf"] = float(s.split("PF")[1].split("|")[0].strip())
                m["sharpe"] = float(s.split("Sharpe")[1].strip())
            except Exception:
                pass
        if s.startswith("MaxDD $"):
            try:
                m["maxdd"] = float(s.split("MaxDD $")[1].split("(")[0].strip().replace(",", ""))
            except Exception:
                pass
    return m


# =============================================================================
# 2. fill-feasibility audit
# =============================================================================
def bar_lookup(df: pd.DataFrame):
    """(ts -> OHLC row), (ts -> 5m window agg), day high / day low - from the
    instrument's own 1-minute bars."""
    idx = df.index
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    l = df["low"].to_numpy(); c = df["close"].to_numpy()
    naive = idx.tz_localize(None) if idx.tz is not None else idx
    day_key = pd.DatetimeIndex(naive).normalize()
    dh = pd.Series(h, index=day_key).groupby(level=0).max()
    dl = pd.Series(l, index=day_key).groupby(level=0).min()

    def _norm(ts):
        t = pd.Timestamp(ts)
        if t.tz is None and idx.tz is not None:
            t = t.tz_localize(idx.tz)
        elif t.tz is not None and idx.tz is None:
            t = t.tz_localize(None)
        return t

    def at(ts):
        if ts is None:
            return None
        j = idx.get_indexer([_norm(ts)])[0]
        if j < 0:
            return None
        return dict(ts=idx[j], o=float(o[j]), h=float(h[j]), l=float(l[j]),
                    c=float(c[j]), i=int(j))

    def window(ts, minutes=5):
        if ts is None:
            return None
        t = _norm(ts)
        lo = idx.searchsorted(t, "left")
        hi = idx.searchsorted(t + pd.Timedelta(minutes=minutes), "left")
        if hi <= lo:
            return None
        return dict(o=float(o[lo]), h=float(h[lo:hi].max()), l=float(l[lo:hi].min()),
                    c=float(c[hi - 1]), n=int(hi - lo))

    return at, window, dh, dl


def audit_trades(name: str, trades: list, df: pd.DataFrame) -> dict:
    at, window, day_hi, day_lo = bar_lookup(df)
    res = dict(inst=name, n=len(trades), outside_exit_bar=0, outside_exit_day=0,
               signal_after_entry=0, same_or_before_bar_exit=0, exit_before_entry=0,
               missing_exit_bar=0, entry_not_bar_close=0, favourable=0, adverse=0,
               outside_dollars=0.0, samples=[])
    for t in trades:
        et, xt = t.get("entry_time"), t.get("exit_time")
        d0 = pd.Timestamp(t["day"]).normalize()
        d1 = pd.Timestamp(t["exit_day"]).normalize()
        px = float(t["exit"])
        reasons = []

        if d1 < d0:
            res["exit_before_entry"] += 1
            reasons.append("exit_day < entry_day")

        # Entry convention: entry_time labels the START of the 5m resume bar and
        # the fill is that bar's CLOSE, so signal instant == fill instant == et+5m.
        ew = window(et, 5) if et is not None else None
        if ew is not None and abs(ew["c"] - float(t["entry"])) > PRICE_EPS:
            res["entry_not_bar_close"] += 1
            reasons.append("entry price != resume-bar close")
        fill_ts = (pd.Timestamp(et) + pd.Timedelta(minutes=5)) if et is not None else None
        if fill_ts is not None and xt is not None and pd.Timestamp(xt) <= fill_ts:
            res["same_or_before_bar_exit"] += 1
            reasons.append("exit <= entry fill instant")

        b = at(xt)
        if b is None:
            res["missing_exit_bar"] += 1
            reasons.append("exit bar not present in data")
        else:
            if px < b["l"] - PRICE_EPS or px > b["h"] + PRICE_EPS:
                res["outside_exit_bar"] += 1
                gap = (b["l"] - px) if px < b["l"] else (px - b["h"])
                res["outside_dollars"] += gap
                # favourable = the impossible fill HELPED the trade
                if t["direction"] == "LONG":
                    fav = px > b["h"]
                else:
                    fav = px < b["l"]
                res["favourable" if fav else "adverse"] += 1
                side = "below bar low" if px < b["l"] else "above bar high"
                reasons.append("exit " + side)
            try:
                dhi, dlo = float(day_hi.loc[d1]), float(day_lo.loc[d1])
                if px < dlo - PRICE_EPS or px > dhi + PRICE_EPS:
                    res["outside_exit_day"] += 1
                    reasons.append("exit outside exit-day range")
            except KeyError:
                pass
        if reasons and len(res["samples"]) < 12:
            res["samples"].append(dict(
                inst=name, day=str(t["day"]), exit_day=str(t["exit_day"]),
                entry_time=str(et), exit_time=str(xt), direction=t["direction"],
                trade_reason=str(t.get("reason")), entry=float(t["entry"]), exit=px,
                bar=(None if b is None else
                     "O{o:.2f} H{h:.2f} L{l:.2f} C{c:.2f}".format(**b)),
                why="; ".join(reasons), pnl=float(t["pnl"])))
    return res


# =============================================================================
# 3. corrected fill law
# =============================================================================
def correct_trades(trades: list, df: pd.DataFrame, pv: float, cost_rt: float):
    """Conservative path law on stop exits: a stop the market gapped through fills
    at the ACTUAL bar open, whether or not a time break preceded that bar.
    MAX_HOLD and GAP already fill at the bar open, so they are untouched."""
    at, _w, _dh, _dl = bar_lookup(df)
    out, n, tot = [], 0, 0.0
    for t in trades:
        t = dict(t)
        if t.get("reason") in ("CHANDELIER", "DISASTER"):
            b = at(t.get("exit_time"))
            if b is not None:
                stop = float(t["exit"])
                fill = min(stop, b["o"]) if t["direction"] == "LONG" else max(stop, b["o"])
                if abs(fill - stop) > 1e-9:
                    w = (stop - fill) if t["direction"] == "LONG" else (fill - stop)
                    pts = ((fill - float(t["entry"])) if t["direction"] == "LONG"
                           else (float(t["entry"]) - fill))
                    t["exit"] = round(fill, 2)
                    t["points"] = round(pts, 2)
                    t["pnl"] = round(pts * pv - cost_rt, 2)
                    n += 1
                    tot += w * pv
        out.append(t)
    return out, n, tot


# =============================================================================
# 4. re-assembly through deploy_sim's own risk layer
# =============================================================================
def _real_risk(atr_series, mult, point_value, entry_day, contracts):
    try:
        av = atr_series.asof(pd.Timestamp(entry_day))
    except Exception:
        av = np.nan
    if av is None or pd.isna(av):
        av = float(atr_series.median())
    return contracts * mult * float(av) * point_value


def assemble(inst_trades: dict, meta: dict, account=ACCOUNT, n_contracts=1):
    """inst_trades: {inst: [trade dicts]}. meta: {inst: dict(cluster, atr, mult, pv)}.
    Mirrors deploy_sim.main()'s assembly + replay."""
    import global_index.deploy_sim as DS
    from global_index.net_exposure_multi import MultiClusterGuard
    try:
        from futures.circuit_breaker import CircuitBreaker
    except Exception:
        CircuitBreaker = None

    all_tr = []
    for inst, lst in inst_trades.items():
        m = meta[inst]
        for t in lst:
            ed = pd.Timestamp(t["day"])
            xd = pd.Timestamp(t["exit_day"]) if t.get("exit_day") else ed
            if ed.tz is not None:
                ed = ed.tz_localize(None)
            if xd.tz is not None:
                xd = xd.tz_localize(None)
            all_tr.append(dict(inst=inst, cluster=m["cluster"], entry=ed, exit=xd,
                               direction=t["direction"], pnl1=t["pnl"],
                               atr=m["atr"], mult=m["mult"], pv=m["pv"],
                               _atr_entry=ed))
    if not all_tr:
        empty = pd.Series(dtype=float)
        return empty, dict(taken={}, rejected={}, halted=0), DS.metrics(empty), 0.0

    for t in all_tr:
        t["risk_sized"] = _real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], 1)
        t["pnl_sized"] = t["pnl1"]
    d1, _ = DS.replay(all_tr, account, MultiClusterGuard(account=account), {}, CircuitBreaker)
    m1 = DS.metrics(d1)

    contracts_by = {inst: (1 if m["cluster"] == "global_nkd" else n_contracts)
                    for inst, m in meta.items()}
    for t in all_tr:
        n = 1 if t["cluster"] == "global_nkd" else n_contracts
        t["risk_sized"] = _real_risk(t["atr"], t["mult"], t["pv"], t["_atr_entry"], n)
        t["pnl_sized"] = t["pnl1"] * n
    guard = MultiClusterGuard(account=account)
    sized, st = DS.replay(all_tr, account, guard, contracts_by, CircuitBreaker)
    return sized, st, DS.metrics(sized), m1["maxdd"]


def row(label: str, sized: pd.Series, st: dict, m: dict, ntr: int, audit: dict,
        account=ACCOUNT) -> dict:
    yrs = max((sized.index[-1] - sized.index[0]).days / 365.25, 0.1) if len(sized) else 1.0
    return dict(label=label, net=m["pnl"], pf=m["pf"], sharpe=m["sharpe"],
                calmar=m["calmar"], maxdd=m["maxdd"], maxdd_pct=m["maxdd"] / account,
                ret_yr=m["pnl"] / account / yrs, trades=ntr,
                taken=sum(st["taken"].values()) if st["taken"] else 0,
                rejected=sum(st["rejected"].values()) if st["rejected"] else 0,
                halted=st["halted"],
                yearly=({int(y): float(g.sum()) for y, g in sized.groupby(sized.index.year)}
                        if len(sized) else {}),
                **{k: audit.get(k, 0) for k in
                   ("outside_exit_bar", "outside_exit_day", "signal_after_entry",
                    "same_or_before_bar_exit", "exit_before_entry", "entry_not_bar_close")})


def _merge_audit(lst) -> dict:
    keys = ("outside_exit_bar", "outside_exit_day", "signal_after_entry",
            "same_or_before_bar_exit", "exit_before_entry", "entry_not_bar_close")
    return {k: sum(d.get(k, 0) for d in lst) for k in keys}


def _round_turn(c, is_nkd: bool, slip_ticks: float) -> float:
    """Round-turn cost the engine charged for this instrument."""
    if is_nkd:
        from global_index._core import FuturesCost as GIFC
        return GIFC(point_value=c.point_value, tick=c.tick,
                    commission_rt=c.commission_rt,
                    slippage_ticks_per_side=slip_ticks).round_turn_cost()
    from futures.cost import FuturesCost
    return FuturesCost(point_value=c.point_value, tick=c.tick,
                       slippage_ticks_per_side=slip_ticks).round_turn_cost()


def _slip_ticks(argv) -> float:
    if "--slippage-ticks" in argv:
        return float(argv[argv.index("--slippage-ticks") + 1])
    return 1.0


# =============================================================================
# main
# =============================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--which", nargs="+", default=["floor", "vault2025", "vault2026"])
    ap.add_argument("--spy-csv", default="spy_daily_live.csv")
    ap.add_argument("--out", default="scratch/normal_sleeve_fill_audit_20260821.txt")
    ap.add_argument("--json-out", default="scratch/normal_sleeve_fill_audit_20260821.json")
    a = ap.parse_args()

    from futures._validated_core import daily_atr_series
    from futures.basket import BASKET
    from global_index import specs as gi_specs

    buf = io.StringIO()

    def emit(s=""):
        print(s, flush=True)
        buf.write(s + "\n")

    emit("=" * 118)
    emit("NORMAL SLEEVE - INDEPENDENT FILL-FEASIBILITY AUDIT   (scratch / research only)")
    emit("=" * 118)
    emit("config: Normal regime only | Ro4 EMA50 | NKD ema=10 mult=2.5 | 2x daily ATR stop,")
    emit("        fixed (no ratchet), armed 14:05 local on the next session | max_hold 5d |")
    emit("        SHORT only when SPY D-1 close < SMA50 | 2 ticks/side | 1 micro | $50,000")
    emit("        Stress sleeve disabled. 'original' = what the current config books,")
    emit("        i.e. harness day+1-arm fill correction already applied.")
    emit("")

    results = {}
    for which in a.which:
        emit("#" * 118)
        emit("WINDOW: " + which)
        emit("#" * 118)
        cap = run_window(which, a.spy_csv)
        argv = cap["argv"]
        nkd_inst = _nkd_instrument(argv)
        slip = _slip_ticks(argv)
        dsm = cap["ds_metrics"]
        emit("  argv: " + " ".join(argv))
        emit("  deploy_sim ANCHOR (current config, Ro4+NKD original fill):")
        emit("    net ${:,.0f} | PF {:.2f} | Sharpe {:.2f} | Calmar {:.2f} | MaxDD ${:,.0f}".format(
            dsm.get("net", 0), dsm.get("pf", 0), dsm.get("sharpe", 0),
            dsm.get("calmar", 0), dsm.get("maxdd", 0)))
        emit("    harness day+1-arm fill correction inside that config: {} trades, ${:,.0f} "
             "(1-contract basis)".format(cap["fix_n"], cap["fix_tot"]))
        emit("")

        meta, booked, corrected, audits_o, audits_c = {}, {}, {}, {}, {}
        corr_stat = {}
        for name, d in cap["inst"].items():
            is_nkd = (name == nkd_inst)
            c = gi_specs.SPECS[nkd_inst] if is_nkd else BASKET[name]
            meta[name] = dict(cluster="global_nkd" if is_nkd else "roska4_swing",
                              atr=daily_atr_series(d["df"]),
                              mult=2.5, pv=float(c.point_value))
            booked[name] = d["booked"]
            rt = _round_turn(c, is_nkd, slip)
            ct, cn, ctot = correct_trades(d["raw"], d["df"], float(c.point_value), rt)
            corrected[name] = ct
            corr_stat[name] = (cn, ctot)
            audits_o[name] = audit_trades(name, booked[name], d["df"])
            audits_c[name] = audit_trades(name, ct, d["df"])

        hdr = "  {:<6} {:>6} {:>12} {:>12} {:>10} {:>13} {:>12} {:>9} {:>7}".format(
            "inst", "trades", "out_exit_bar", "out_exit_day", "sig>entry",
            "same_bar_exit", "entry!=close", "favourable", "adverse")
        emit("  PER-INSTRUMENT FILL AUDIT - 'original' (what the current config books)")
        emit(hdr)
        for name in list(R4) + [nkd_inst]:
            r = audits_o.get(name)
            if not r:
                continue
            emit("  {:<6} {:>6} {:>12} {:>12} {:>10} {:>13} {:>12} {:>9} {:>7}".format(
                name, r["n"], r["outside_exit_bar"], r["outside_exit_day"],
                r["signal_after_entry"], r["same_or_before_bar_exit"],
                r["entry_not_bar_close"], r["favourable"], r["adverse"]))
        emit("")
        emit("  PER-INSTRUMENT FILL AUDIT - 'corrected' (conservative path law)")
        emit(hdr)
        for name in list(R4) + [nkd_inst]:
            r = audits_c.get(name)
            if not r:
                continue
            emit("  {:<6} {:>6} {:>12} {:>12} {:>10} {:>13} {:>12} {:>9} {:>7}".format(
                name, r["n"], r["outside_exit_bar"], r["outside_exit_day"],
                r["signal_after_entry"], r["same_or_before_bar_exit"],
                r["entry_not_bar_close"], r["favourable"], r["adverse"]))
        emit("")
        emit("  corrected-fill law repricing (vs raw engine output, 1-contract basis):")
        for name in list(R4) + [nkd_inst]:
            if name in corr_stat:
                emit("    {:<6} {:>4} trades repriced, ${:>10,.0f} removed".format(
                    name, corr_stat[name][0], corr_stat[name][1]))
        emit("")

        n_bad = sum(v["outside_exit_bar"] for v in audits_o.values())
        bad = [s for name in audits_o for s in audits_o[name]["samples"]]
        emit("  FAILING SAMPLES (original) - showing up to 12; total outside_exit_bar = {}".format(n_bad))
        for s in bad[:12]:
            emit("    {inst:<5} entry {day} {entry_time} -> exit {exit_day} {exit_time} "
                 "{direction:<5} {trade_reason:<10} entry {entry:.2f} exit {exit:.2f} | "
                 "bar {bar} | {why} | pnl ${pnl:,.0f}".format(**s))
        if not bad:
            emit("    (none)")
        emit("")

        # ---- variants -------------------------------------------------------
        def pick(names, table):
            return ({n: table[n] for n in names if n in table},
                    {n: meta[n] for n in names if n in meta})

        v_r4_t, v_r4_m = pick(R4, booked)
        v_nkd_o_t, v_nkd_m = pick([nkd_inst], booked)
        v_nkd_c_t, _ = pick([nkd_inst], corrected)
        v_both_o_t, v_both_m = pick(R4 + [nkd_inst], booked)
        v_both_c_t, _ = pick(R4 + [nkd_inst], corrected)
        v_mixed_t = dict(v_r4_t); v_mixed_t[nkd_inst] = corrected[nkd_inst]

        variants = [
            ("R4 only (NKD excluded)", v_r4_t, v_r4_m, audits_o),
            ("NKD only, original", v_nkd_o_t, v_nkd_m, audits_o),
            ("NKD only, corrected", v_nkd_c_t, v_nkd_m, audits_c),
            ("R4 + NKD, original", v_both_o_t, v_both_m, audits_o),
            ("R4 + NKD, corrected NKD", v_mixed_t, v_both_m, None),
            ("R4 + NKD, corrected both", v_both_c_t, v_both_m, audits_c),
        ]

        rows = []
        for label, tr, mt, au_src in variants:
            sized, st, m, _dd1 = assemble(tr, mt)
            if au_src is None:
                au = _merge_audit([audits_o[n] for n in R4 if n in tr]
                                  + [audits_c[nkd_inst]])
            else:
                au = _merge_audit([au_src[n] for n in tr])
            ntr = sum(len(v) for v in tr.values())
            rows.append(row(label, sized, st, m, ntr, au))

        emit("  VARIANT METRICS (deploy_sim risk layer: MultiClusterGuard + CircuitBreaker, 1 micro, $50k)")
        emit("  {:<26} {:>10} {:>6} {:>7} {:>7} {:>9} {:>8} {:>8} {:>7} {:>6} {:>5} {:>5} {:>12}".format(
            "variant", "net$", "PF", "Sharpe", "Calmar", "MaxDD$", "MaxDD%",
            "ret/yr", "trades", "taken", "rej", "halt", "out_exit_bar"))
        for r in rows:
            emit("  {label:<26} {net:>10,.0f} {pf:>6.2f} {sharpe:>7.2f} {calmar:>7.2f} "
                 "{maxdd:>9,.0f} {maxdd_pct:>8.1%} {ret_yr:>8.1%} {trades:>7} {taken:>6} "
                 "{rejected:>5} {halted:>5} {outside_exit_bar:>12}".format(**r))
        emit("")
        years = sorted({y for r in rows for y in r["yearly"]})
        emit("  YEARLY NET$ per variant")
        emit("  {:<26} {}".format("variant", " ".join("{:>10}".format(y) for y in years)))
        for r in rows:
            emit("  {:<26} {}".format(r["label"], " ".join(
                "{:>10,.0f}".format(r["yearly"].get(y, 0.0)) for y in years)))
        emit("")

        anch = next(r for r in rows if r["label"] == "R4 + NKD, original")
        ok = (abs(anch["net"] - dsm.get("net", -1e9)) < 1.0
              and abs(anch["calmar"] - dsm.get("calmar", -1e9)) < 0.005
              and abs(anch["maxdd"] - dsm.get("maxdd", -1e9)) < 1.0)
        emit("  [SELF-CHECK] re-assembly reproduces deploy_sim: net ${:,.0f} vs ${:,.0f}, "
             "Calmar {:.2f} vs {:.2f}, MaxDD ${:,.0f} vs ${:,.0f} -> {}".format(
                 anch["net"], dsm.get("net", 0), anch["calmar"], dsm.get("calmar", 0),
                 anch["maxdd"], dsm.get("maxdd", 0),
                 "PASS" if ok else "FAIL - DO NOT READ ANY NUMBER ABOVE"))
        emit("")

        results[which] = dict(
            anchor=dsm, anchor_ok=bool(ok), rows=rows,
            corrected_repricing={k: dict(n=v[0], dollars=v[1]) for k, v in corr_stat.items()},
            audit_original={k: {kk: vv for kk, vv in v.items() if kk != "samples"}
                            for k, v in audits_o.items()},
            audit_corrected={k: {kk: vv for kk, vv in v.items() if kk != "samples"}
                             for k, v in audits_c.items()},
            samples=bad, fix_n=cap["fix_n"], fix_tot=cap["fix_tot"])

    Path(a.out).write_text(buf.getvalue(), encoding="utf-8")
    Path(a.json_out).write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print("\nwrote " + a.out + " and " + a.json_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
