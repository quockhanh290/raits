"""Quet truc STOP o TANG DEPLOY, tren ky IS. — CHI DOC.

Sau moi phep quet o tang 1 hop dong deu phang, nhung da chung minh HAI LAN rang ket qua
1 hop dong khong mang sang deploy — vi o deploy co CIRCUIT BREAKER, mot nguong phi tuyen,
con o 1 hop dong thi khong co gi ca.

Co che duy nhat da xac dinh ma luat stop co the thanh tien: **giu sut von duoi nguong phanh
de he khong bi dong cua**. O cau hinh hien tai phanh no 1.072 lan va he tat sau 2022.

CAM KET TRUOC (viet truoc khi nhin so):
  1. Chon theo SO LAN PHANH NO = 0 truoc, P&L sau — vi co che la nguong, khong phai loi the.
  2. Doi CAO NGUYEN: o duoc chon phai co o ke ben trong khoang +-30%.
  3. Chi sau khi chon xong moi dem ra thu tren hai vault. KHONG quet tren vault.
  4. Vault xau di -> DONG HUONG, khong tim cach giai thich.

    python scratch/stop_sweep_deploy.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, r"d:\raits")
sys.path.insert(0, r"d:\raits\scratch")

import harness as H

ARM = H.ARM_LIVE

# (nhan, cau hinh) — quanh luat live: arm=14:05, khong ratchet, sua khop lenh, ca hai sleeve
GRID = [
    ("vu trang 0h (ranh gioi ngay)", dict(arm_hours=0.0)),
    ("vu trang 5h",                  dict(arm_hours=5.0)),
    ("vu trang 9.52h",               dict(arm_hours=9.52)),
    ("vu trang 12h",                 dict(arm_hours=12.0)),
    ("vu trang 14:05  (LUAT LIVE)",  dict(arm_hours=ARM)),
    ("vu trang 16h",                 dict(arm_hours=16.0)),
    ("vu trang 20h",                 dict(arm_hours=20.0)),
    ("+ tham hoa 2x",                dict(arm_hours=ARM, disaster=2.0)),
    ("+ tham hoa 3x",                dict(arm_hours=ARM, disaster=3.0)),
    ("+ tham hoa 5x",                dict(arm_hours=ARM, disaster=5.0)),
    ("+ tham hoa 8x",                dict(arm_hours=ARM, disaster=8.0)),
    ("stop 0.25 x ATRngay",          dict(arm_hours=ARM, stop_basis=0.25)),
    ("stop 0.5 x ATRngay",           dict(arm_hours=ARM, stop_basis=0.5)),
    ("stop 1.0 x ATRngay",           dict(arm_hours=ARM, stop_basis=1.0)),
    ("stop 2.5 x ATRngay",           dict(arm_hours=ARM, stop_basis=2.5)),
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


def run(nhan, kw, which="baseline"):
    cfg = H.Cfg(fix_fill=True, ratchet=False, roska4_only=False, **kw)
    r = H.run_deploy(cfg, which)
    H._CACHE.clear()
    return dict(nhan=nhan, net=r["net"], cal=r["calmar"],
                halt=halts(r["out"]), dd=maxdd(r["out"]))


def main() -> int:
    print("=" * 92)
    print("CONG MO NEO")
    print("=" * 92)
    if not H.anchor(strict=False):
        print("!! mo neo FAIL — dung")
        return 1
    H._CACHE.clear()

    print("\n" + "=" * 92)
    print("QUET TRUC STOP — TANG DEPLOY, ky IS 2018-2024, 1 micro, 2-tick")
    print("=" * 92)
    print("  {:<30} {:>11} {:>8} {:>9} {:>8}".format("cau hinh", "net", "Calmar",
                                                     "MaxDD", "phanh"))
    print("  " + "-" * 72)
    res = []
    for nhan, kw in GRID:
        r = run(nhan, kw)
        res.append(r)
        print("  {:<30} {:>11,.0f} {:>8.2f} {:>9} {:>8}"
              .format(nhan, r["net"] or 0, r["cal"] or 0, r["dd"], r["halt"]))
        sys.stdout.flush()

    print("\n" + "=" * 92)
    print("AP QUY TAC CHON DA CAM KET TRUOC")
    print("=" * 92)
    khong_phanh = [r for r in res if r["halt"] == 0]
    print("  buoc 1 — cau hinh co phanh no = 0: {} / {}".format(len(khong_phanh), len(res)))
    for r in khong_phanh:
        print("     {:<30} net {:>10,.0f}  Calmar {:.2f}".format(r["nhan"], r["net"], r["cal"]))
    if not khong_phanh:
        print("  KHONG cau hinh nao dat -> dong huong theo cam ket")
        return 0
    best = max(khong_phanh, key=lambda r: r["net"])
    print("\n  buoc 2 — trong so do, P&L cao nhat: {}  (net ${:,.0f}, Calmar {:.2f})"
          .format(best["nhan"], best["net"], best["cal"]))
    i = [r["nhan"] for r in res].index(best["nhan"])
    ke = [res[j] for j in (i - 1, i + 1) if 0 <= j < len(res)]
    print("  buoc 3 — cao nguyen? cac o ke ben:")
    for r in ke:
        pct = (r["net"] - best["net"]) / abs(best["net"]) * 100 if best["net"] else 0
        print("     {:<30} net {:>10,.0f}  ({:+.0f}% so voi o duoc chon)"
              .format(r["nhan"], r["net"], pct))
    ok = all(abs((r["net"] - best["net"]) / abs(best["net"])) <= 0.30 for r in ke) if best["net"] else False
    print("     -> {}".format("CAO NGUYEN (dat)" if ok else "DINH NHON (khong dat cam ket)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
