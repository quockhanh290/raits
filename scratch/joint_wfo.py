"""WFO CHUNG ba truc tren thuoc do da sua — CHI DOC.

Luoi 1 chieu khong dung duoc: da do duoc argmax cua hold va ema DICH khi doi co so stop.
Nen quet chung ema x max_hold x f(stop = f x ATR ngay), muc tieu = P&L DA SUA KHOP LENH,
vu trang D+1 14:05, ratchet=False (luat live).

Bai nay KHONG de chon tham so. No tra loi ba cau, theo dung thu tu cong ma du an tu dat:
  1. Co o nao duong khong, va bao nhieu o trong 60?
  2. O tot nhat nam tren CAO NGUYEN hay dung mot minh? (dinh nhon = nhieu)
  3. Chon o tren cac nam TRUOC roi do o nam SAU — viec CHON co tong quat hoa khong?
Chi cau 3 moi la phieu quyet dinh. Cau 1-2 de doc hinh dang.

Moc mem: (ema=30, hold=5, f=0.12) = $6.807.

    python scratch/joint_wfo.py --data-dir data/cache/futures/frozen_sim
        --regime-csv spy_daily_live.csv --end 2024-12-31
"""
from __future__ import annotations
import argparse, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

EMAS = [20, 30, 50]
HOLDS = [3, 5, 7, 10]
FRACS = [0.12, 0.25, 0.5, 1.0, 2.5]
ARM = 14 + 5 / 60


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--regime-csv", required=True)
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--slippage-ticks", type=float, default=2.0)
    a = ap.parse_args()

    from futures.basket import SWING_TF_PARAM, BASKET
    from futures.swing_tf import basket_labels, costs_for_basket, load_basket
    from futures._validated_core import _swing_cache, daily_atr_series
    from raits.strategies.trend_follow import TrendFollowStrategy
    from model_sameday_stop import build_sig_cache, run_loop

    mult = SWING_TF_PARAM["chandelier_atr_mult"]
    dfs = load_basket(a.data_dir)
    cut = pd.Timestamp(a.end)
    for k in list(dfs):
        df = dfs[k]
        c = cut.tz_localize(df.index.tz) if df.index.tz is not None else cut
        dfs[k] = df[df.index <= c]
    labels = basket_labels(a.regime_csv)
    costs = costs_for_basket(slippage_ticks=a.slippage_ticks)

    caches, datrs = {}, {}
    for k in dfs:
        datrs[k] = daily_atr_series(dfs[k])
        caches[k] = _swing_cache(dfs[k], datrs[k])

    strats, sigs = {}, {}
    for e in EMAS:
        cfg = dict(TrendFollowStrategy().config)
        cfg["ema_period"] = e
        cfg["chandelier_atr_mult"] = mult
        s = TrendFollowStrategy(cfg)
        strats[e] = s
        sigs[e] = {k: build_sig_cache(caches[k], labels, s, e,
                                      set(s.config["allowed_regimes"])) for k in dfs}
        print("  sig cache ema={} xong".format(e), flush=True)

    def make_sig(e, k, f):
        out = {}
        for day, (ts_, sg) in sigs[e][k].items():
            try:
                da = float(datrs[k].asof(pd.Timestamp(day)))
            except Exception:
                continue
            if not np.isfinite(da) or da <= 0:
                continue
            s2 = dict(sg)
            ep = float(s2["entry_price"])
            s2["initial_stop"] = (ep - f * da) if s2["direction"] == "LONG" else (ep + f * da)
            out[day] = (ts_, s2)
        return out

    def corr_one(t, inst):
        if t["reason"] != "CHANDELIER":
            return 0.0
        cache = caches[inst]
        ts, hl = cache.get("ts", {}), cache["hl"]
        d0 = pd.Timestamp(t["day"]).normalize()
        d1 = pd.Timestamp(t["exit_day"]).normalize()
        if d1 != d0 + pd.Timedelta(days=1):
            return 0.0
        dts = ts.get(d1)
        if dts is None or not len(dts):
            return 0.0
        naive = dts.tz_localize(None) if dts.tz is not None else dts
        arm = d0 + pd.Timedelta(days=1) + pd.Timedelta(hours=ARM)
        j = int(np.searchsorted(np.asarray(naive), np.datetime64(arm)))
        if j >= len(naive):
            return 0.0
        et = pd.Timestamp(t["exit_time"])
        if et.tzinfo is not None:
            et = et.tz_localize(None)
        if et != pd.Timestamp(naive[j]):
            return 0.0
        op = float(hl[d1][2][j])
        stp = float(t["exit"])
        w = (stp - op) if t["direction"] == "LONG" else (op - stp)
        return w * BASKET[inst].point_value if w > 0 else 0.0

    grid = {}
    for e in EMAS:
        for hold in HOLDS:
            for f in FRACS:
                ay = defaultdict(float)
                n = 0
                for k in dfs:
                    sg = make_sig(e, k, f)
                    tr, _ = run_loop(dfs[k], labels, costs[k], strat=strats[e],
                                     ema_period=e, mult=mult, max_hold_days=hold,
                                     cache=caches[k], same_day_stop=False,
                                     stop_slip_ticks=0.0, sig_cache=sg,
                                     stop_active_hour=ARM, ratchet=False)
                    for t in tr:
                        ay[str(t.get("exit_day") or t["day"])[:4]] += t["pnl"] - corr_one(t, k)
                        n += 1
                grid[(e, hold, f)] = dict(years=dict(ay), tot=sum(ay.values()), n=n)
        print("  ema={} xong".format(e), flush=True)

    years = sorted({y for c in grid.values() for y in c["years"]})
    keys = sorted(grid, key=lambda x: -grid[x]["tot"])

    print("\n" + "=" * 80)
    print("1. HINH DANG LUOI (60 o, P&L da sua, ca ky)")
    print("=" * 80)
    pos = sum(1 for c in grid.values() if c["tot"] > 0)
    print("  o duong: {}/{}  | trung vi ${:,.0f} | min ${:,.0f} | max ${:,.0f}"
          .format(pos, len(grid),
                  np.median([c["tot"] for c in grid.values()]),
                  min(c["tot"] for c in grid.values()),
                  max(c["tot"] for c in grid.values())))
    print("\n  10 o cao nhat:")
    for k in keys[:10]:
        print("    ema={:<3} hold={:<3} f={:<5} ${:>10,.0f}  ({} lenh)"
              .format(k[0], k[1], k[2], grid[k]["tot"], grid[k]["n"]))
    print("\n  5 o thap nhat:")
    for k in keys[-5:]:
        print("    ema={:<3} hold={:<3} f={:<5} ${:>10,.0f}".format(k[0], k[1], k[2],
                                                                    grid[k]["tot"]))

    print("\n" + "=" * 80)
    print("2. O TOT NHAT CO NAM TREN CAO NGUYEN KHONG?")
    print("=" * 80)
    b = keys[0]
    print("  o tot nhat: ema={} hold={} f={} -> ${:,.0f}".format(b[0], b[1], b[2],
                                                                 grid[b]["tot"]))
    print("  cac o KE BEN (doi mot buoc tren mot truc):")
    for e in EMAS:
        for hold in HOLDS:
            for f in FRACS:
                k = (e, hold, f)
                d = sum([e != b[0], hold != b[1], f != b[2]])
                if d != 1:
                    continue
                ie, ih, iff = EMAS.index(e), HOLDS.index(hold), FRACS.index(f)
                be, bh, bf = EMAS.index(b[0]), HOLDS.index(b[1]), FRACS.index(b[2])
                if abs(ie - be) + abs(ih - bh) + abs(iff - bf) != 1:
                    continue
                print("    ema={:<3} hold={:<3} f={:<5} ${:>10,.0f}".format(e, hold, f,
                                                                            grid[k]["tot"]))
    print("\n  P&L tung nam cua o tot nhat:")
    for y in years:
        print("    {}  ${:>10,.0f}".format(y, grid[b]["years"].get(y, 0.)))

    print("\n" + "=" * 80)
    print("3. WALK-FORWARD — chon o tren cac nam TRUOC, do o nam SAU (phieu quyet dinh)")
    print("=" * 80)
    tot = 0.0
    picks = []
    for i, y in enumerate(years):
        if i < 2:
            continue
        prev = years[:i]
        best = max(grid, key=lambda k: sum(grid[k]["years"].get(p, 0.) for p in prev))
        v = grid[best]["years"].get(y, 0.)
        tot += v
        picks.append("({},{},{})".format(best[0], best[1], best[2]))
        print("    {} | chon ema={:<3} hold={:<3} f={:<5} | P&L nam do ${:>10,.0f}"
              .format(y, best[0], best[1], best[2], v))
    print("    TONG NGOAI MAU ${:,.0f}".format(tot))
    print("    o da chon: {}".format(", ".join(picks)))
    print("    (so sanh: giu nguyen hien trang ema=30 hold=5 f=0.12 tren cung cac nam = ${:,.0f})"
          .format(sum(grid[(30, 5, 0.12)]["years"].get(y, 0.) for y in years[2:])))

    print("\n=== MOC MEM ===")
    print("  (30, 5, 0.12) = ${:,.0f} — lan truoc $6,807".format(grid[(30, 5, 0.12)]["tot"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
