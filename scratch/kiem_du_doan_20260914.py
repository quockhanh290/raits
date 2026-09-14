"""Đối chiếu scratch/du_doan_truoc_20260914.md với thực tế. CHỈ ĐỌC.

    python scratch/kiem_du_doan_20260914.py

Không kết nối IBKR, không ghi gì. Mỗi mục in ĐÚNG / SAI / chờ — không mục nào được im lặng.

Khác bản 20260910 ở hai chỗ, cả hai là lỗi của bản trước:
  - đọc sổ neo và nhật ký theo NGÀY CỤ THỂ của sự kiện, không theo "hôm nay"
  - chỉ đếm slot của đúng sleeve và đúng khung giờ đã dự đoán
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[1]
SIGNALS = REPO / "global_index" / "track1_runtime" / "signals"
OK, BAD, WAIT = "ĐÚNG", "SAI ", "chờ "
US = ("roska4_calm", "roska4_stress", "roska4_swing")
ROLL_CODES = ("overlap_disagreement", "series_rolled")
rows: list = []


def say(tag, what, detail=""):
    rows.append((tag, what, detail))


def slots(day: str) -> list:
    """Mọi dòng tín hiệu của một ngày ET, mỗi dòng: (sleeve, slot_id, hhmm, kết quả)."""
    f = SIGNALS / f"track1_signals_{day}.jsonl"
    if not f.exists():
        return []
    out = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except Exception:                                      # noqa: BLE001
            continue
        sid = str(d.get("slot_id") or "")
        hhmm = sid[-4:] if sid[-4:].isdigit() else ""
        res = d.get("reason") if d.get("status") == "SLOT_REFUSED" else (d.get("status") or d.get("reason"))
        out.append((str(d.get("sleeve") or ""), sid, hhmm, str(res or "")))
    return out


def count(rows_, sleeves, *, from_hhmm="0000"):
    seen: dict = {}
    for sl, sid, hhmm, res in rows_:
        if sl in sleeves and hhmm >= from_hhmm:
            seen[res] = seen.get(res, 0) + 1
    return seen


# ── A: Stress (từ 11:00) + Swing hôm nay ────────────────────────────────────
def event_a():
    r = slots("20260914")
    for sleeve, start in (("roska4_stress", "1100"), ("roska4_swing", "0000")):
        seen = count(r, (sleeve,), from_hhmm=start)
        label = f"A {sleeve}"
        if not seen:
            say(WAIT, label, "chưa có slot nào")
            continue
        shown = ", ".join(f"{k}={v}" for k, v in sorted(seen.items()))
        if seen.get("decided"):
            say(BAD, label, f"có slot CHẠY ĐƯỢC — cửa sổ không chạm bar cũ ({shown})")
        elif seen.get("series_rolled"):
            say(BAD, label, f"từ chối bằng series_rolled — sổ neo không như tôi nghĩ ({shown})")
        elif set(seen) == {"overlap_disagreement"}:
            say(OK, label, f"toàn bộ overlap_disagreement ({shown})")
        else:
            say(BAD, label, f"lý do khác dự đoán ({shown})")


# ── B: pre-flight 13:45 hôm nay ─────────────────────────────────────────────
WANT = {"MES": (-67.75, "MESZ6"), "MNQ": (-300.5, "MNQZ6"), "MYM": (-418.0, "MYMZ6"),
        "M2K": (-21.7, "M2KZ6"), "MNKD": (147.0, "NKDZ6")}


def event_b():
    log = REPO / "scheduler_0914.log"
    txt = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    pf = [l for l in txt.splitlines() if "[PRE-FLIGHT]" in l and ("OK" in l or "FAILED" in l)
          and "Starting" not in l]
    if not pf:
        say(WAIT, "B pre-flight 13:45", "chưa có dòng kết quả")
        return
    say(OK if "OK" in pf[-1] else BAD, "B pre-flight 13:45", pf[-1].split("—", 1)[-1].strip()[:70])
    try:
        book = json.loads((REPO / "global_index" / "data" / "_ibkr_splice_offsets.json")
                          .read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        say(WAIT, "B sổ neo", f"không đọc được: {exc}")
        return
    moved = [f"{k} {book.get(k)}" for k, (off, con) in WANT.items()
             if abs(float((book.get(k) or {}).get("offset", 1e9)) - off) > 0.01
             or (book.get(k) or {}).get("contract") != con]
    say(BAD if moved else OK, "B sổ neo không đổi", "; ".join(moved) if moved else "cả năm y như sáng 14/09")


# ── C: thứ Ba 15/09 ─────────────────────────────────────────────────────────
def event_c():
    r = slots("20260915")
    for sleeves, label in ((US, "C rổ Mỹ 15/09"), (("global_nkd",), "C NKD 15/09")):
        seen = count(r, sleeves)
        if not seen:
            say(WAIT, label, "chưa có slot nào")
            continue
        bad = {k: v for k, v in seen.items() if k in ROLL_CODES}
        shown = ", ".join(f"{k}={v}" for k, v in sorted(seen.items()))
        say(BAD if bad else OK, label,
            (f"còn lời từ chối do roll — luật 'mất đúng một phiên' SAI ({shown})") if bad
            else f"không lời từ chối nào do roll ({shown})")


def main():
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)
    print("=" * 76)
    print(f"Đối chiếu dự đoán ghi trước 14/09  ·  {now:%a %d/%m %H:%M} ET")
    print("=" * 76)
    event_a(); event_b(); event_c()
    for tag, what, detail in rows:
        print(f"  [{tag}] {what:<24} {detail}")
    bad = sum(t == BAD for t, _, _ in rows)
    wait = sum(t == WAIT for t, _, _ in rows)
    print("-" * 76)
    print(f"  {bad} mục SAI — dừng và xem lại." if bad else
          f"  chưa đủ dữ liệu ({wait} mục chờ)." if wait else
          "  Toàn bộ ĐÚNG — luật 'mất đúng phiên đầu sau roll' được xác nhận ngoài mẫu.")
    print("-" * 76)


if __name__ == "__main__":
    main()
