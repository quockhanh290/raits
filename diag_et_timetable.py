"""Toan bo moc thoi gian cua he thong, quy ve gio ET, cho ca hai mua.

Lay tu HANG SO TRONG CODE chu khong go tay: _ARM_BY_CLUSTER, cac job cua scheduler,
StressMidAdapter.ENTRY/EXIT, va session_tz cua tung sleeve.

Vi sao can: ba dong ho cung ton tai (ET, JST, UTC) va bon lan trong mot phien lam viec
da co ket luan sai vi tron chung. Bang nay la mot cho duy nhat de doi chieu.
"""
from __future__ import annotations
import sys
from pathlib import Path
if str(Path.cwd()) not in sys.path:
    sys.path.insert(0, str(Path.cwd()))

import pandas as pd
from global_index.runner import _ARM_BY_CLUSTER
from global_index.specs import SPECS
from futures._validated_core import StressMidAdapter

ET = "America/New_York"
SUM, WIN = "2026-07-15", "2026-01-15"


def to_et(day, hhmm, tz):
    t = pd.Timestamp(f"{day} {hhmm}", tz=tz).tz_convert(ET)
    return t.strftime("%H:%M"), t.date().isoformat()[-5:]


def row(name, hhmm_from, hhmm_to, tz, note=""):
    out = [name]
    for d in (SUM, WIN):
        a, da = to_et(d, hhmm_from, tz)
        if hhmm_to:
            b, db = to_et(d, hhmm_to, tz)
            out.append(f"{a}-{b}")
        else:
            out.append(a)
    out.append(note)
    return out


ad = StressMidAdapter()
rows = [
    row("Ro 4  — cua so vao lenh", "14:00", "15:55", ET, "co dinh ET"),
    row("NKD   — cua so vao lenh", "14:00", "15:55", SPECS["MNKD"].session_tz,
        "co dinh JST -> troi 1h theo DST"),
    row("STRESS— vao lenh", ad.ENTRY.strftime("%H:%M"), None, ET, "co dinh ET"),
    row("STRESS— thoat", ad.EXIT.strftime("%H:%M"), None, ET, "co dinh ET"),
    None,
    row("Ro 4  — VU TRANG stop",
        f"{_ARM_BY_CLUSTER['roska4_swing'][1]:02d}:{_ARM_BY_CLUSTER['roska4_swing'][2]:02d}",
        None, _ARM_BY_CLUSTER["roska4_swing"][0], "14h sau 00:00 ET"),
    row("NKD   — VU TRANG stop",
        f"{_ARM_BY_CLUSTER['global_nkd'][1]:02d}:{_ARM_BY_CLUSTER['global_nkd'][2]:02d}",
        None, _ARM_BY_CLUSTER["global_nkd"][0], "14h sau 00:00 JST"),
    None,
    row("nghi bao tri CME", "17:00", "18:00", ET, "co dinh ET — KHONG vu trang o day"),
]

print()
print("=" * 96)
print("MOC THOI GIAN HE THONG — QUY VE GIO ET")
print("=" * 96)
print(f"  {'':32} | {'mua he (EDT)':>13} | {'mua dong (EST)':>13} | ghi chu")
print("  " + "-" * 92)
for r in rows:
    if r is None:
        print("  " + "-" * 92)
        continue
    print(f"  {r[0]:32} | {r[1]:>13} | {r[2]:>13} | {r[3]}")

print()
print("  JOB CUA SCHEDULER (deu co dinh theo ET, khong doi theo mua)")
print("  " + "-" * 92)
for lbl, t in (("slot dem NKD", "01:10-02:55"), ("MAX_HOLD exit", "09:31"),
               ("STRESS_MID entry", "10:20"), ("pre-flight", "13:45"),
               ("slot giao dich", "14:05-15:55")):
    print(f"  {lbl:32} | {t:>13} | {t:>13} |")
print()
