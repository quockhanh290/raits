"""Cau hinh nguoi dung yeu cau: EMA=50, stop=2 x ATR ngay, vu trang 14:05 D+1,
khong ratchet, co sua khop lenh. Deploy, TRONG MAU 2018-2024. Khong dung vault.

Cau hinh hien hanh chay cung luot lam moc — no phai tai tao $3.716, neu khong thi
moi truong da doi va khong duoc doc so con lai.
"""
import sys
sys.path.insert(0, r"d:\raits"); sys.path.insert(0, r"d:\raits\scratch")
import harness as H

CH = [
    ("HIEN HANH  ema30, stop 2,5xATR5",
     H.Cfg(fix_fill=True, arm_hours=H.ARM_LIVE, ratchet=False, roska4_only=False)),
    ("YEU CAU    ema50, stop 2,0xATRngay",
     H.Cfg(fix_fill=True, arm_hours=H.ARM_LIVE, ratchet=False, roska4_only=False,
           ema=50, stop_basis=2.0)),
]


def lay(out, khoa):
    for ln in out.splitlines():
        s = ln.strip()
        if s.startswith(khoa):
            return s
    return ""


for nhan, cfg in CH:
    r = H.run_deploy(cfg, "baseline")
    H._CACHE.clear()
    print("\n" + "=" * 74)
    print(nhan)
    print("=" * 74)
    print("  net ${:,.0f}   Calmar {:.2f}".format(r["net"] or 0, r["calmar"] or 0))
    for k in ("MaxDD", "circuit-breaker", "trades", "win"):
        s = lay(r["out"], k)
        if s:
            print("  " + s)
    print("  [sua khop lenh] {} lenh, ${:,.0f}".format(r["sua_n"], r["sua_tot"]))
    inyr = False
    for ln in r["out"].splitlines():
        t = ln.strip()
        if t.startswith("per-year"):
            inyr = True; print("  per-year:"); continue
        if inyr:
            if t[:2] == "20":
                print("    " + t)
            elif t.startswith("---") or not t:
                break
    sys.stdout.flush()
