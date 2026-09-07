"""LAP QUANG TRAN TRIET DE: stop song ngay tu luc khop, tren co so ON DINH. — CHI DOC.

Ly do ton tai cua viec hoan stop la muc stop qua hep — bang 1/21 dai ngay, 50% vi the cham
no trong 2 tieng dau. Dat ngay luc khop thi bi nhieu quet sach (−$10.832 theo ghi chep cua
du an).

NHUNG lap luan do chi dung voi stop HEP. Mot muc stop tinh theo ATR NGAY rong gap ~20 lan —
nhieu quanh diem vao khong quet noi. Khi do ly do de hoan BIEN MAT, va co the dat len san
ngay tu giay dau tien: khong con quang tran nao ca.

O DOI CHUNG: stop hep hien tai + dat ngay luc khop. PHAI cho ket qua te. Neu no khong te
thi co che toi mo ta sai va khong duoc doc phan con lai.

CAM KET TRUOC: phanh=0 truoc, P&L sau; cao nguyen +-30%; chi sau khi chon moi thu vault;
vault xau di -> dong huong.

    python scratch/nogap_sweep.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, r"d:\raits\scratch")

import harness as H

GRID = [
    ("DOI CHUNG: stop hep, dat ngay", dict(same_day=True, arm_hours=0.0)),
    ("stop 0.5 x ATRngay, dat ngay",  dict(same_day=True, arm_hours=0.0, stop_basis=0.5)),
    ("stop 1.0 x ATRngay, dat ngay",  dict(same_day=True, arm_hours=0.0, stop_basis=1.0)),
    ("stop 1.5 x ATRngay, dat ngay",  dict(same_day=True, arm_hours=0.0, stop_basis=1.5)),
    ("stop 2.5 x ATRngay, dat ngay",  dict(same_day=True, arm_hours=0.0, stop_basis=2.5)),
]


def halts(out):
    for ln in out.splitlines():
        if "circuit-breaker halts" in ln:
            try:
                return int(ln.split(":")[-1].strip())
            except Exception:
                return None
    return None


def maxdd(out):
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith("MaxDD $"):
            try:
                return s.split("(")[1].split(")")[0]
            except Exception:
                return "?"
    return "?"


def main() -> int:
    if not H.anchor(strict=False):
        print("!! mo neo FAIL")
        return 1
    H._CACHE.clear()

    print("\n" + "=" * 88)
    print("LAP QUANG TRAN — stop song tu luc khop, co so ATR NGAY (deploy, IS 2018-2024)")
    print("=" * 88)
    print("  {:<34} {:>11} {:>8} {:>9} {:>7}".format("cau hinh", "net", "Calmar",
                                                     "MaxDD", "phanh"))
    print("  " + "-" * 74)
    res = []
    for nhan, kw in GRID:
        cfg = H.Cfg(fix_fill=True, ratchet=False, roska4_only=False, **kw)
        r = H.run_deploy(cfg, "baseline")
        H._CACHE.clear()
        row = dict(nhan=nhan, net=r["net"], cal=r["calmar"],
                   halt=halts(r["out"]), dd=maxdd(r["out"]))
        res.append(row)
        print("  {:<34} {:>11,.0f} {:>8.2f} {:>9} {:>7}"
              .format(nhan, row["net"] or 0, row["cal"] or 0, row["dd"], row["halt"]))
        sys.stdout.flush()

    print("\n=== DOI CHUNG ===")
    dc = res[0]
    print("  stop hep dat ngay: net ${:,.0f}".format(dc["net"] or 0))
    print("  -> {}".format("DAT (te nhu du kien, co che dung)" if (dc["net"] or 0) < 0
                           else "KHONG DAT — co che mo ta sai, DUNG doc phan duoi"))

    print("\n=== AP QUY TAC CHON ===")
    kp = [r for r in res[1:] if r["halt"] == 0]
    print("  phanh = 0: {}/{}".format(len(kp), len(res) - 1))
    for r in kp:
        print("     {:<34} net {:>10,.0f}  Calmar {:.2f}".format(r["nhan"], r["net"], r["cal"]))
    if not kp:
        print("  KHONG cau hinh nao dat -> dong huong theo cam ket")
        return 0
    best = max(kp, key=lambda r: r["net"])
    i = [r["nhan"] for r in res].index(best["nhan"])
    ke = [res[j] for j in (i - 1, i + 1) if 1 <= j < len(res)]
    print("\n  chon: {} (net ${:,.0f})".format(best["nhan"], best["net"]))
    print("  o ke ben:")
    for r in ke:
        pct = (r["net"] - best["net"]) / abs(best["net"]) * 100 if best["net"] else 0
        print("     {:<34} {:>10,.0f}  ({:+.0f}%)".format(r["nhan"], r["net"], pct))
    ok = all(abs((r["net"] - best["net"]) / abs(best["net"])) <= 0.30 for r in ke) if best["net"] else False
    print("  -> {}".format("CAO NGUYEN (dat)" if ok else "DINH NHON (khong dat)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
