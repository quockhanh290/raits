"""Đối chiếu dự đoán ghi trước (scratch/du_doan_truoc_20260910.md) với thực tế. CHỈ ĐỌC.

Chạy sau job 13:45, và lại sau cửa sổ NKD 01:10 sáng hôm sau:

    python scratch/kiem_du_doan_20260910.py

Không kết nối IBKR, không ghi gì. Đọc sổ neo, nhật ký scheduler và các tệp bằng chứng.
Mỗi mục in ĐÚNG / SAI / chưa có dữ liệu — không có mục nào được phép im lặng.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path

# Console Windows mặc định cp1252 và sẽ ném UnicodeEncodeError ở dòng in đầu tiên.
# Ép về UTF-8 tại đây thay vì bắt người chạy phải đặt biến môi trường.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                              # noqa: BLE001
    pass

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

OK, BAD, WAIT = "ĐÚNG", "SAI ", "chờ "
rows: list = []


def say(tag: str, what: str, detail: str = "") -> None:
    rows.append((tag, what, detail))


# ── Sự kiện 1: job 13:45 ───────────────────────────────────────────────────
def check_preflight() -> None:
    path = REPO / "global_index" / "data" / "_ibkr_splice_offsets.json"
    try:
        book = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        say(WAIT, "sổ neo", f"không đọc được: {exc}")
        return

    nkd = book.get("MNKD") or {}
    off, con = float(nkd.get("offset", 0.0)), str(nkd.get("contract", ""))
    if con == "NKDU6":
        say(WAIT, "MNKD neo lại", "sổ neo vẫn NKDU6 — job 13:45 chưa chạy")
    elif con == "NKDZ6" and 145.0 <= off <= 149.0:
        say(OK, "MNKD neo lại", f"NKDZ6, độ lệch {off:+.1f} (dự đoán 145–149)")
    elif con == "NKDZ6":
        say(BAD, "MNKD neo lại", f"NKDZ6 nhưng độ lệch {off:+.1f} NGOÀI khoảng 145–149")
    else:
        say(BAD, "MNKD neo lại", f"hợp đồng lạ: {con!r}")

    stray = [k for k in ("MES", "MNQ", "MYM", "M2K")
             if float((book.get(k) or {}).get("offset", 0.0)) != 0.0]
    if stray:
        say(BAD, "rổ Mỹ giữ nguyên", f"đã đổi độ lệch: {stray} — dự đoán là chưa roll")
    else:
        say(OK, "rổ Mỹ giữ nguyên", "cả bốn vẫn độ lệch 0,0")

    logs = sorted(glob.glob(str(REPO / "scheduler_*.log")))
    today = dt.date.today().strftime("%m%d")
    log = REPO / f"scheduler_{today}.log"
    if not log.exists():
        say(WAIT, "pre-flight 13:45", "chưa có nhật ký hôm nay")
        return
    txt = log.read_text(encoding="utf-8", errors="replace")
    if "[PRE-FLIGHT] OK" in txt:
        say(OK, "pre-flight 13:45", "completed OK — ngày không bị khoá")
    elif "[IBKR_UPDATE]" in txt and "FAILED" in txt:
        say(BAD, "pre-flight 13:45", "FAILED — dự đoán là thoát 0")
    else:
        say(WAIT, "pre-flight 13:45", "chưa thấy dòng kết quả")


# ── Sự kiện 2 & 3: cửa sổ NKD ──────────────────────────────────────────────
def refusals_for(day: dt.date) -> dict:
    tag = day.strftime("%Y%m%d")
    seen: dict = {}
    for f in glob.glob(str(REPO / "global_index" / "**" / f"*{tag}*.jsonl"), recursive=True):
        for line in open(f, encoding="utf-8", errors="replace"):
            if "MNKD" not in line and "global_nkd" not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:                                  # noqa: BLE001
                continue
            r = d.get("refusal") or d.get("reason") or d.get("code")
            if r:
                seen[str(r)] = seen.get(str(r), 0) + 1
    return seen


def check_window(day: dt.date, expect_block: bool, label: str) -> None:
    seen = refusals_for(day)
    if not seen:
        say(WAIT, label, f"chưa có dòng bằng chứng nào cho {day}")
        return
    rolled = seen.get("series_rolled", 0)
    overlap = seen.get("overlap_disagreement", 0)
    decided = seen.get("decided", 0)
    shown = ", ".join(f"{k}={v}" for k, v in sorted(seen.items()))

    if expect_block:
        if overlap and not rolled:
            say(OK, label, f"chặn bằng overlap_disagreement như dự đoán ({shown})")
        elif rolled:
            say(BAD, label, f"vẫn chặn bằng series_rolled — neo lại KHÔNG tới nơi ({shown})")
        elif decided and not overlap:
            say(BAD, label, f"CHẠY ĐƯỢC — tôi đã hiểu sai cổng so giá ({shown})")
        else:
            say(BAD, label, f"chặn bằng lý do khác dự đoán ({shown})")
    else:
        if decided and not (rolled or overlap):
            say(OK, label, f"chạy bình thường như dự đoán ({shown})")
        else:
            say(BAD, label, f"vẫn còn từ chối — 'tự lành sau 2 ngày' SAI ({shown})")


def main() -> None:
    now_et = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)
    print("=" * 74)
    print(f"Đối chiếu dự đoán ghi trước  ·  {now_et:%d/%m/%Y %H:%M} ET")
    print("=" * 74)

    print("\nSỰ KIỆN 1 — job 13:45 hôm nay")
    check_preflight()
    n = len(rows)

    print("\nSỰ KIỆN 2 — cửa sổ NKD 01:10 sáng 11/09")
    check_window(dt.date(2026, 9, 11), True, "NKD 11/09")

    print("\nSỰ KIỆN 3 — cửa sổ NKD 01:10 thứ Hai 14/09")
    check_window(dt.date(2026, 9, 14), False, "NKD 14/09")

    print()
    for i, (tag, what, detail) in enumerate(rows):
        if i == n:
            pass
        print(f"  [{tag}] {what:<22} {detail}")

    bad = sum(1 for t, _, _ in rows if t == BAD)
    wait = sum(1 for t, _, _ in rows if t == WAIT)
    print()
    print("-" * 74)
    if bad:
        print(f"  {bad} mục SAI — DỪNG, không xây bản sửa cổng cho tới khi hiểu vì sao.")
    elif wait:
        print(f"  chưa đủ dữ liệu ({wait} mục còn chờ). Chạy lại sau sự kiện kế tiếp.")
    else:
        print("  Toàn bộ dự đoán ĐÚNG — mô hình được xác nhận ngoài mẫu.")
    print("-" * 74)


if __name__ == "__main__":
    main()
