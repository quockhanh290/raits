"""HARNESS — chay engine PRODUCTION voi cac ban sua bat/tat bang co. CHI DOC.

KHONG sao chep dong code nao cua engine. Harness goi thang ham that va tiem ban sua o
dung ranh gioi:
  fix_fill     — gia thoat dung khi stop len san vao thi truong DA di qua muc do.
                 Tru hau ky tren gia thoat: tuong duong CHINH XAC voi sua luat khop lenh,
                 vi trong run_loop sau khi dong vi the chi con moc THOI GIAN di tiep.
  fix_entry    — bat nen resume dong dung chieu lenh (loc bang tin hieu).
  stop_basis   — dat stop = f x ATR NGAY thay vi 2.5 x ATR 5 phut (ghi de initial_stop).
  arm_hours    — gio vu trang stop: None = quy uoc engine (ranh gioi ngay); 14.0833 = luat live.
  ratchet      — True = engine keo stop moi bar; False = luat live (stop co dinh).
  disaster     — muc dung tham hoa = gia vao -+ mult x khoang cach stop, nam tren san tu luc khop.

CONG MO NEO — BAT BUOC. Voi MOI co tat, harness phai tai tao DUNG TOI TUNG DONG bon con so
ghim trong INVARIANTS. Khong trung -> khong doc bat cu thu gi phia sau. Quy tac nay la thu
phan biet phan dung voi phan sai trong dot do 2026-08-18.

CAM KET TRUOC (viet o day de sau nay khong noi long):
  - chon tham so bang WFO CO FOLD tren thuoc do da sua, khong chon tu luoi
  - ky giu rieng 2025 chua tung dung de chon bat cu gi
  - doi CAO NGUYEN: o duoc chon phai co cac o ke ben trong khoang +-30%
  - khong nam nao dong gop qua mot nua tong
  - san Calmar phai dung lai tren CUNG co so truoc khi dem so sanh

    python scratch/harness.py --anchor
    python scratch/harness.py --deploy --arm 14.0833 --no-ratchet --fix-fill
    python scratch/harness.py --sweep-stop-basis --fix-fill --arm 14.0833 --no-ratchet
"""
from __future__ import annotations

import argparse
import io
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

ARM_LIVE = 14 + 5 / 60

# ── moc ghim trong docs/futures/INVARIANTS.md ────────────────────────────────
ARGV = {
    "baseline": ["--data-dir", "data/cache/futures/frozen_sim",
                 "--nkd-parquet", "global_index/data/NKD_frozen_2024.parquet",
                 "--regime-csv", "spy_daily_live.csv", "--end", "2024-12-31",
                 "--n-contracts", "1", "--slippage-ticks", "2"],
    "floor": ["--data-dir", "data/cache/futures/frozen_sim",
              "--nkd-parquet", "global_index/data/NKD_frozen_2024.parquet",
              "--regime-csv", "spy_daily_live.csv", "--end", "2024-12-31",
              "--hmm-fit-end", "2022-12-31", "--n-contracts", "1", "--slippage-ticks", "2"],
    "vault2324": ["--data-dir", "data/cache/futures/frozen_sim",
                  "--nkd-parquet", "global_index/data/NKD_frozen_2024.parquet",
                  "--regime-csv", "spy_daily_live.csv", "--start", "2023-01-01",
                  "--end", "2024-12-31", "--hmm-fit-end", "2022-12-31",
                  "--n-contracts", "1", "--slippage-ticks", "2"],
    "vault2026": ["--data-dir", "data/cache/futures",
                  "--nkd-parquet", "global_index/data/NKD_continuous_1m_8y.parquet",
                  "--regime-csv", "spy_daily_live.csv", "--start", "2026-01-01",
                  "--end", "2026-08-19", "--hmm-fit-end", "2024-12-31",
                  "--n-contracts", "1", "--slippage-ticks", "2", "--include-stress"],
    "vault2025": ["--data-dir", "data/cache/futures/frozen_2025_sim",
                  "--nkd-parquet", "global_index/data/NKD_frozen_2025.parquet",
                  "--regime-csv", "spy_daily_live.csv", "--start", "2025-01-01",
                  "--end", "2025-12-31", "--hmm-fit-end", "2024-12-31",
                  "--n-contracts", "1", "--slippage-ticks", "2", "--include-stress"],
}
PINNED = {"baseline": (42459, 1.72), "floor": (42565, 1.65),
          "vault2324": (10757, 2.86), "vault2025": (7404, 2.54)}


@dataclass
class Cfg:
    fix_fill: bool = False
    fix_entry: bool = False
    stop_basis: float | None = None       # f x ATR ngay; None = giu 2.5 x ATR 5 phut
    arm_hours: float | None = None        # None = quy uoc engine
    ratchet: bool = True
    disaster: float | None = None
    entry_mode: str = "off"        # off | filter (vut bo) | wait (quet toi nen dung chieu)
    ema: int | None = None        # ghi de ema_period cua sleeve swing (Ro 4)
    same_day: bool = False        # stop song NGAY TU LUC KHOP, khong co quang tran
    drop_badstop: bool = False    # bo tin hieu co stop roi sang phia CO LAI
    stop_anchor: str = "bar"       # bar = cuc tri nen (hien tai) | entry = neo vao gia vao
    roska4_only: bool = True              # ap ban sua chi cho Ro 4 (ema=30), khong cho NKD

    def is_engine_default(self) -> bool:
        return (not self.fix_fill and not self.fix_entry and self.stop_basis is None
                and self.arm_hours is None and self.ratchet and self.disaster is None
                and self.entry_mode == "off" and self.stop_anchor == "bar"
                and not self.drop_badstop and not self.same_day
                and self.ema is None)

    def label(self) -> str:
        if self.is_engine_default():
            return "ENGINE (mac dinh, moi co tat)"
        p = []
        if self.arm_hours is not None:
            p.append("vu trang {:g}h".format(self.arm_hours))
        if not self.ratchet:
            p.append("stop co dinh")
        if self.stop_basis is not None:
            p.append("stop {:g}xATRngay".format(self.stop_basis))
        if self.disaster is not None:
            p.append("tham hoa {:g}x".format(self.disaster))
        if self.entry_mode == "filter" or self.fix_entry:
            p.append("LOC BO nen resume sai chieu")
        if self.entry_mode == "wait":
            p.append("QUET TOI nen resume dung chieu")
        if self.stop_anchor == "entry":
            p.append("stop neo vao GIA VAO")
        if self.drop_badstop:
            p.append("CHAN stop sai phia")
        if self.same_day:
            p.append("stop SONG TU LUC KHOP")
        if self.ema is not None:
            p.append("ema={}".format(self.ema))
        if self.fix_fill:
            p.append("SUA KHOP LENH")
        return " + ".join(p)


_CACHE: dict = {}


def _cache(df):
    from futures._validated_core import _swing_cache, daily_atr_series
    k = id(df)
    if k not in _CACHE:
        d = daily_atr_series(df)
        _CACHE[k] = (_swing_cache(df, d), d)
    return _CACHE[k]


def _correct(trades, df, pv, H):
    """Tru phan khop lenh khong the co. Tra ve (trades, so lenh sua, tong tien)."""
    cache, _ = _cache(df)
    ts, hl = cache.get("ts", {}), cache["hl"]
    out, n, tot = [], 0, 0.0
    for t in trades:
        t = dict(t)
        if t["reason"] == "CHANDELIER":
            d0 = pd.Timestamp(t["day"]).normalize()
            d1 = pd.Timestamp(t["exit_day"]).normalize()
            if d1 == d0 + pd.Timedelta(days=1):
                dts = ts.get(d1)
                if dts is not None and len(dts):
                    nv = dts.tz_localize(None) if dts.tz is not None else dts
                    arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=H)
                    j = int(np.searchsorted(np.asarray(nv), np.datetime64(arm)))
                    et = t.get("exit_time")
                    if j < len(nv) and et is not None:
                        et = pd.Timestamp(et)
                        if et.tzinfo is not None:
                            et = et.tz_localize(None)
                        if et == pd.Timestamp(nv[j]):
                            op = float(hl[d1][2][j])
                            stp = float(t["exit"])
                            w = (stp - op) if t["direction"] == "LONG" else (op - stp)
                            if w > 0:
                                t["pnl"] = round(t["pnl"] - w * pv, 2)
                                t["exit"] = round(op, 2)
                                n += 1
                                tot += w * pv
        out.append(t)
    return out, n, tot



def _scan_sig(cache, labels, strat, ema_period, allowed, require_dir):
    """Ban sao vong quet cua build_sig_cache, them lua chon DI TIEP qua nen sai chieu.

    require_dir=False phai cho ra DUNG build_sig_cache — do la phep tu kiem cua ham nay,
    vi cong mo neo khong bao phu duoc no (cong chay voi moi co tat).
    """
    from futures._validated_core import atr14
    out = {}
    for day in cache["days"]:
        reg = labels.get(day)
        if reg not in allowed:
            continue
        bars5 = cache["b5"][day]
        win = bars5.between_time("14:00", "15:55")
        idx = list(win.index)
        for kk in range(1, len(idx)):
            hist = bars5.loc[:idx[kk]]
            if len(hist) < max(ema_period, 14) + 1:
                continue
            ema = strat.calculate_ema(hist, ema_period)
            atr = atr14(hist)
            avgv = float(win["volume"].iloc[max(0, kk - 11):kk - 1].mean())
            if np.isnan(atr) or np.isnan(avgv):
                continue
            sig = strat.generate_signal(win.loc[idx[kk - 1]], win.loc[idx[kk]],
                                        ema, atr, reg, avgv)
            if not sig:
                continue
            if require_dir:
                bar = win.loc[idx[kk]]
                up = float(bar["close"]) > float(bar["open"])
                if (sig["direction"] == "LONG") != up:
                    continue
            out[day] = (idx[kk], sig)
            break
    return out


def selfcheck_scanner():
    """_scan_sig(require_dir=False) phai trung khit build_sig_cache tren ca 4 ma."""
    from futures.basket import SWING_TF_PARAM
    from futures.swing_tf import basket_labels, load_basket
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache
    ema = SWING_TF_PARAM["ema_period"]
    c = dict(TrendFollowStrategy().config)
    c["ema_period"] = ema
    c["chandelier_atr_mult"] = SWING_TF_PARAM["chandelier_atr_mult"]
    strat = TrendFollowStrategy(c)
    dfs = load_basket("data/cache/futures/frozen_sim")
    cut = pd.Timestamp("2024-12-31")
    labels = basket_labels("spy_daily_live.csv")
    ok = True
    print("=" * 84)
    print("TU KIEM BO QUET — _scan_sig(require_dir=False) == build_sig_cache?")
    print("=" * 84)
    for k in dfs:
        df = dfs[k]
        cc = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        df = df[df.index <= cc]
        cache, _ = _cache(df)
        a = build_sig_cache(cache, labels, strat, ema, set(c["allowed_regimes"]))
        b = _scan_sig(cache, labels, strat, ema, set(c["allowed_regimes"]), False)
        same = (set(a) == set(b)) and all(
            a[d][0] == b[d][0]
            and abs(float(a[d][1]["entry_price"]) - float(b[d][1]["entry_price"])) < 1e-9
            for d in a)
        ok = ok and same
        print("  {:<5} build {:>5} tin hieu | scan {:>5} | -> {}"
              .format(k, len(a), len(b), "MATCH" if same else "MISMATCH"))
    print("  KET LUAN: {}".format("PASS" if ok else "FAIL"))
    return ok


def _make_sig(cache, datr, labels, strat, ema, allowed, cfg: Cfg, apply_fixes: bool):
    from model_sameday_stop import build_sig_cache
    from futures._validated_core import atr14
    if apply_fixes and cfg.entry_mode == "wait":
        sig = _scan_sig(cache, labels, strat, ema, allowed, True)
    else:
        sig = build_sig_cache(cache, labels, strat, ema, allowed)
    if not apply_fixes:
        return sig
    out = {}
    for day, (ts_, sg) in sig.items():
        if cfg.fix_entry or cfg.entry_mode == "filter":
            b5 = cache["b5"].get(day)
            if b5 is None:
                continue
            try:
                bar = b5.loc[ts_]
            except Exception:
                continue
            up = float(bar["close"]) > float(bar["open"])
            if (sg["direction"] == "LONG") != up:
                continue
        if cfg.drop_badstop:
            ep0 = float(sg["entry_price"]); st0 = float(sg["initial_stop"])
            d0 = (st0 - ep0) if sg["direction"] == "SHORT" else (ep0 - st0)
            if d0 <= 0:
                continue
        if cfg.stop_anchor == "entry":
            b5c = cache["b5"].get(day)
            if b5c is None:
                continue
            at5 = float(atr14(b5c.loc[:ts_]))
            if not np.isfinite(at5) or at5 <= 0:
                continue
            sg = dict(sg)
            ep = float(sg["entry_price"])
            band = float(strat.config["chandelier_atr_mult"]) * at5
            sg["initial_stop"] = (ep - band) if sg["direction"] == "LONG" else (ep + band)
        if cfg.stop_basis is not None:
            try:
                da = float(datr.asof(pd.Timestamp(day)))
            except Exception:
                continue
            if not np.isfinite(da) or da <= 0:
                continue
            sg = dict(sg)
            ep = float(sg["entry_price"])
            sg["initial_stop"] = (ep - cfg.stop_basis * da) if sg["direction"] == "LONG" \
                else (ep + cfg.stop_basis * da)
        out[day] = (ts_, sg)
    return out


def patched_engine(cfg: Cfg, stat: dict):
    """Tra ve ham thay the cho futures._validated_core.backtest_swing_tf."""
    import futures._validated_core as VC
    orig = VC.backtest_swing_tf
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import run_loop

    def fn(df, labels, cost, *, ema_period=20, chandelier_atr_mult=3.0,
           max_hold_days=5, **kw):
        if kw.get("return_open") or kw.get("resume_pos") is not None:
            return orig(df, labels, cost, ema_period=ema_period,
                        chandelier_atr_mult=chandelier_atr_mult,
                        max_hold_days=max_hold_days, **kw)
        apply_fixes = (not cfg.roska4_only) or (ema_period == 30)
        if cfg.ema is not None and ema_period == 30:
            ema_period = cfg.ema
        use_loop = apply_fixes and (cfg.same_day or cfg.arm_hours is not None or not cfg.ratchet
                                    or cfg.stop_basis is not None or cfg.fix_entry
                                    or cfg.disaster is not None)
        if not use_loop:
            tr = orig(df, labels, cost, ema_period=ema_period,
                      chandelier_atr_mult=chandelier_atr_mult,
                      max_hold_days=max_hold_days, **kw)
            H = 0.0
        else:
            c = dict(TrendFollowStrategy().config)
            c["ema_period"] = ema_period
            c["chandelier_atr_mult"] = chandelier_atr_mult
            s = TrendFollowStrategy(c)
            if cfg.stop_basis is not None and apply_fixes:
                # run_loop GHI DE pos bang lan quet lai khi same_day_stop=True, nen sua
                # sig_cache la khong du. Boc generate_signal thi ca hai duong cung nhan.
                _orig_gs = s.generate_signal
                _datr_local = _cache(df)[1]

                def _gs(pullback_bar, resume_bar, ema_20, atr, hmm_state, avg_volume_10,
                        _o=_orig_gs, _d=_datr_local, _f=cfg.stop_basis):
                    sig = _o(pullback_bar, resume_bar, ema_20, atr, hmm_state,
                             avg_volume_10)
                    if not sig:
                        return sig
                    try:
                        day = pd.Timestamp(resume_bar.name).normalize()
                        if day.tzinfo is not None:
                            day = day.tz_localize(None)
                        da = float(_d.asof(day))
                    except Exception:
                        return sig
                    if not np.isfinite(da) or da <= 0:
                        return sig
                    ep = float(sig["entry_price"])
                    sig = dict(sig)
                    sig["initial_stop"] = (ep - _f * da) if sig["direction"] == "LONG"                         else (ep + _f * da)
                    return sig

                s.generate_signal = _gs
            cache, datr = _cache(df)
            sig = _make_sig(cache, datr, labels, s, ema_period,
                            set(s.config["allowed_regimes"]), cfg, apply_fixes)
            H = ARM_LIVE if cfg.arm_hours is None else cfg.arm_hours
            tr, _ = run_loop(df, labels, cost, strat=s, ema_period=ema_period,
                             mult=chandelier_atr_mult, max_hold_days=max_hold_days,
                             cache=cache, same_day_stop=cfg.same_day,
                             stop_slip_ticks=0.0, activate_after_h=0.0,
                             sig_cache=sig, stop_active_hour=cfg.arm_hours,
                             ratchet=cfg.ratchet, disaster_mult=cfg.disaster)
            if cfg.arm_hours is None:
                H = 0.0
        if cfg.fix_fill and apply_fixes:
            tr, n, tot = _correct(tr, df, cost.point_value, H)
            stat["n"] += n
            stat["tot"] += tot
        return tr

    return orig, fn


def run_deploy(cfg: Cfg, which: str):
    import futures._validated_core as VC
    import global_index.deploy_sim as DS
    stat = {"n": 0, "tot": 0.0}
    orig, fn = patched_engine(cfg, stat)
    VC.backtest_swing_tf = fn
    buf = io.StringIO()
    try:
        old = sys.argv
        sys.argv = ["deploy_sim"] + list(ARGV[which])
        try:
            with redirect_stdout(buf):
                DS.main()
        except SystemExit:
            pass
        finally:
            sys.argv = old
    finally:
        VC.backtest_swing_tf = orig
    out = buf.getvalue()
    net = cal = None
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("net $"):
            try:
                net = float(s.split("net $")[1].split("|")[0].strip().replace(",", ""))
                cal = float(s.split("Calmar")[1].split("|")[0].strip())
            except Exception:
                pass
    return dict(net=net, calmar=cal, out=out, sua_n=stat["n"], sua_tot=stat["tot"])


def anchor(strict=True) -> bool:
    print("=" * 84)
    print("CONG MO NEO — moi co TAT, phai tai tao dung so ghim trong INVARIANTS")
    print("=" * 84)
    ok = True
    for w, (pn, pc) in PINNED.items():
        r = run_deploy(Cfg(), w)
        good = (r["net"] is not None and abs(r["net"] - pn) < 1.0
                and abs(r["calmar"] - pc) < 0.005)
        ok = ok and good
        print("  {:<11} ghim ${:>8,.0f}/{:.2f}  |  do lai ${:>8,.0f}/{:.2f}  -> {}"
              .format(w, pn, pc, r["net"] or 0, r["calmar"] or 0,
                      "MATCH" if good else "MISMATCH"))
    print("\n  KET LUAN CONG: {}".format(
        "PASS — duoc phep doc ket qua phia sau" if ok else
        "FAIL — KHONG doc bat cu ket qua nao"))
    if strict and not ok:
        sys.exit(1)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor", action="store_true", help="chi chay cong mo neo")
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--which", default="baseline", choices=list(ARGV))
    ap.add_argument("--fix-fill", action="store_true")
    ap.add_argument("--fix-entry", action="store_true")
    ap.add_argument("--stop-basis", type=float, default=None)
    ap.add_argument("--arm", type=float, default=None)
    ap.add_argument("--no-ratchet", action="store_true")
    ap.add_argument("--disaster", type=float, default=None)
    ap.add_argument("--entry-mode", default="off", choices=["off", "filter", "wait"])
    ap.add_argument("--stop-anchor", default="bar", choices=["bar", "entry"])
    ap.add_argument("--drop-badstop", action="store_true")
    ap.add_argument("--ema", type=int, default=None)
    ap.add_argument("--same-day", action="store_true",
                    help="stop song ngay tu luc khop — khong co quang tran")
    ap.add_argument("--selfcheck", action="store_true",
                    help="chay tu kiem bo quet roi thoat")
    ap.add_argument("--all-sleeves", action="store_true",
                    help="ap ban sua cho CA NKD (dung voi mo hinh live: NKD cung hoan stop)")
    ap.add_argument("--skip-anchor", action="store_true",
                    help="CHI dung khi da chay cong mo neo trong cung phien")
    a = ap.parse_args()

    if a.selfcheck:
        return 0 if selfcheck_scanner() else 1
    if a.anchor:
        anchor()
        return 0
    if not a.skip_anchor:
        anchor()
        print()

    cfg = Cfg(fix_fill=a.fix_fill, fix_entry=a.fix_entry, stop_basis=a.stop_basis,
              arm_hours=a.arm, ratchet=not a.no_ratchet, disaster=a.disaster,
              roska4_only=not a.all_sleeves,
              entry_mode=a.entry_mode, stop_anchor=a.stop_anchor,
              drop_badstop=a.drop_badstop, same_day=a.same_day, ema=a.ema)
    print("=" * 84)
    print("CAU HINH: {}".format(cfg.label()))
    print("MOC     : {}".format(a.which))
    print("=" * 84)
    r = run_deploy(cfg, a.which)
    print("  net ${:,.0f}  |  Calmar {:.2f}".format(r["net"] or 0, r["calmar"] or 0))
    if cfg.fix_fill:
        print("  [sua khop lenh] {} lenh, ${:,.0f} (co so 1 hop dong, truoc sizing)"
              .format(r["sua_n"], r["sua_tot"]))
    for ln in r["out"].splitlines():
        s = ln.strip()
        if s.startswith("MaxDD") or "circuit-breaker halts" in s:
            print("  " + s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
