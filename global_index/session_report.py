"""
global_index/session_report.py — báo cáo phiên, viết cho người đọc
===================================================================
Không phải bản gom nhóm log. Log viết cho người đã thuộc hệ thống; báo cáo này viết cho
người vừa mở máy buổi sáng và muốn biết **chuyện gì đã xảy ra, có gì phải làm không**.

Mỗi vấn đề được trả lời ba câu:
    - nó là chuyện gì
    - nghĩa là gì với tiền và với vị thế đang mở
    - cần làm gì, cụ thể tới mức copy được câu lệnh

Phần đắt nhất là câu thứ hai. Log không bao giờ nói ra nó.

── Ba cái bẫy trong chính đống log ───────────────────────────────────────────

**Việc không chạy thì không để lại dòng nào.** APScheduler tính lần chạy kế tiếp lúc khởi
động: scheduler lên lúc 09:43 KHÔNG có việc 09:31 bị trễ — nó không có việc 09:31. Không
misfire, không lỗi, log im lặng. Đã xảy ra hai ngày liền (05/08 lên lúc 09:43, 06/08 lúc
10:35), chỉ không mất tiền vì chưa vị thế nào đủ 5 ngày. Nên báo cáo **điểm danh lịch**,
và lịch kỳ vọng lấy từ chính `make_scheduler` chứ không chép tay — chép tay sẽ lệch đúng
vào lúc ai đó thêm hoặc bỏ một việc.

**Tên file log bị chốt lúc tiến trình khởi động.** Một scheduler chạy nhiều ngày vẫn ghi
vào file mang tên ngày nó lên. Mở đúng `scheduler_<hôm nay>.log` là đọc nhầm file. Ở đây
quét MỌI file rồi lọc theo dấu thời gian đầu dòng.

**Log từng bị pytest ghi lẫn.** Đã chặn từ gốc (`attach_file_log` trả về ngay khi thấy
`PYTEST_CURRENT_TEST`), nhưng file cũ vẫn còn dòng kịch bản, nên bộ lọc ở đây giữ lại —
và **đếm rồi báo số dòng đã bỏ**, không bỏ im lặng.

Usage:
    cd d:\\raits
    python -m global_index.session_report                  # hôm nay (giờ ET)
    python -m global_index.session_report --date 2026-08-10
    python -m global_index.session_report --out bao_cao_0810.txt

Mã thoát: 0 = không có gì phải làm, 1 = có.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})\s+(\w+)")


def _to_et(day: str, hhmmss: str):
    """Dấu thời gian trong log là giờ MÁY; báo cáo nói bằng giờ ET. Đổi cho khớp.

    Máy hiện chạy MST (ET − 2h). Bản đầu lấy thẳng chuỗi trong log rồi ghi "mọi giờ là giờ
    ET" — sai hai lần:

      * mọi mốc lệch 2 tiếng;
      * và nặng hơn, RANH GIỚI NGÀY sai đúng chỗ quan trọng nhất. Cửa sổ đêm NKD
        01:10–02:55 ET là 23:10–00:55 giờ máy, vắt qua nửa đêm của máy. Gom theo ngày của
        log thì báo cáo ngày D **bỏ sót** cửa sổ đêm của chính ngày D (nằm trong file ngày
        D−1) và **gộp nhầm** cửa sổ đêm của ngày D+1 — nên các slot nkd_night_01xx hiện ra
        như "không chạy" trong khi chúng chạy bình thường.

    Lấy múi giờ từ hệ thống chứ không viết cứng: chuyển máy sang ET thì độ lệch thành 0 và
    hàm này tự đúng.
    """
    import datetime as _dt
    naive = _dt.datetime.fromisoformat(f"{day} {hhmmss}")
    local = naive.astimezone()                      # gắn múi giờ của máy
    try:
        from zoneinfo import ZoneInfo
        et = local.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        return day, hhmmss
    return et.date().isoformat(), et.strftime("%H:%M:%S")
_MSG_DATE = re.compile("(20[0-9]{2})-([0-9]{2})-([0-9]{2})")

# Dấu vết của dòng do test sinh ra, trong các file log cũ (trước khi chặn từ gốc).
_TEST_MARKERS = (
    "pytest-of-", "pytest-", "\\Temp\\tmp", "/tmp/", "injected ",
    "orderId=stp-", "orderId=mock-", "(stp-", "(mock-", "stp-MES-", "stp-xyz",
    "_RecordingMockBroker", "_naked_broker", "<locals>", "test_spy.csv",
    "ibkr-456", "ibkr-789",
)

CHAN, NANG, VUA = "CHAN", "NANG", "VUA"
_RANK = {CHAN: 0, NANG: 1, VUA: 2}
_NHAN = {CHAN: "CHẶN GIAO DỊCH", NANG: "NẶNG", VUA: "CẦN BIẾT"}

# (khoá tìm trong log, mức, tiêu đề, nghĩa là gì, cần làm gì)
_KNOWN = [
    ("mismatch(es)", CHAN,
     "Hệ thống đã dừng vào lệnh",
     "Sổ của hệ thống và vị thế thật ở IBKR không khớp nhau. Khi đó hệ thống không vào "
     "lệnh mới, vì nó không còn chắc mình đang giữ gì. Vị thế đang mở vẫn được quản lý "
     "bình thường — chỉ lệnh MỚI bị chặn.",
     "Mở TWS đối chiếu với live_positions.json. Khớp rồi thì khởi động lại scheduler."),
    ("HARD-STALE", CHAN,
     "Dữ liệu SPY quá cũ, mọi lệnh vào bị chặn",
     "Chuỗi giá SPY dùng để gán chế độ thị trường đã cũ quá 5 ngày làm việc. Hệ thống "
     "chặn hết lệnh vào thay vì đoán chế độ — hỏng theo hướng an toàn.",
     "python -m global_index.update_spy_csv --csv spy_daily_live.csv"),
    ("CIRCUIT", CHAN,
     "Ngắt mạch rủi ro đã kích hoạt",
     "Lỗ trong ngày hoặc chuỗi lệnh thua đã chạm ngưỡng, hệ thống ngừng vào lệnh mới. "
     "Lưu ý: nó KHÔNG đóng vị thế đang mở — chỉ chặn lệnh vào.",
     "Xem lại các lệnh trong ngày trước khi mở lại."),
    ("B3 ORPHAN", NANG,
     "IBKR có vị thế mà sổ không biết",
     "Tài khoản đang giữ một vị thế hệ thống không ghi nhận. Nó sẽ không được quản lý: "
     "không có stop, không thoát theo luật, không tính vào rủi ro.",
     "Xác định vị thế đó từ đâu ra. Nếu không do hệ thống mở thì đóng tay, hoặc thêm "
     "vào live_positions.json cho khớp."),
    ("B4 NAKED", NANG,
     "Vị thế đang trần, không có lệnh dừng lỗ",
     "Vị thế đang mở mà sàn không giữ lệnh dừng lỗ nào, và hệ thống KHÔNG tự đặt được "
     "(thường vì không biết mức stop). Lỗ không có gì chặn cho tới khi có người đặt.",
     "Tính lại mức chandelier bằng p0c_verify_swing.py rồi đặt STP tay trong TWS, "
     "hoặc đóng vị thế."),
    ("STP UNPROTECTED", NANG,
     "Cuối phiên còn vị thế không được bảo vệ",
     "Kiểm tra cuối phiên thấy vị thế này không có stop nào phủ đúng hợp đồng của nó. "
     "Nó sẽ qua đêm mà không có gì chặn lỗ.",
     "Dừng scheduler rồi chạy: python -X utf8 global_index/repair_stops.py --execute"),
    ("STP ORPHAN", NANG,
     "Còn lệnh stop treo mà không có vị thế phía sau",
     "Vị thế đã đóng nhưng lệnh stop chưa huỷ được. Lệnh này khi khớp sẽ MỞ một vị thế "
     "mới ngược chiều — nó không đóng gì cả. Đây đúng là chuyện đã xảy ra ngày 10/08 "
     "với MYM #12.",
     "IBKR chỉ cho huỷ từ đúng clientId đã đặt lệnh. Xem dòng 'placed by clientId=N' "
     "trong log rồi chạy: python -X utf8 global_index/repair_stops.py "
     "--client-id N --execute"),
    ("thoat OK nhung da ghi", NANG,
     "Một việc báo thành công nhưng bên trong có lỗi nặng",
     "Tiến trình con thoát mã 0 vì việc CHÍNH đã xong, nhưng nó có ghi lỗi nặng cho một "
     "việc phụ. Đây là cách một lệnh stop mồ côi sống nguyên buổi ngày 10/08 mà không "
     "ai biết.",
     "Đọc các dòng ngay dưới nó trong log — chúng được in ra kèm nhãn của việc đó."),
    ("Roll OPEN FAILED", NANG,
     "Đảo hợp đồng hỏng giữa chừng",
     "Hợp đồng cũ đã đóng nhưng hợp đồng mới KHÔNG mở được. Tài khoản đang phẳng trong "
     "khi lẽ ra vẫn phải có vị thế — tức là đang mất phơi nhiễm ngoài ý muốn.",
     "Quyết định mở lại tay trên hợp đồng mới, hoặc bỏ lệnh đó."),
    ("Roll CLOSE FAILED", NANG,
     "Đảo hợp đồng không đóng được chân cũ",
     "Vị thế vẫn nằm trên hợp đồng sắp đáo hạn.",
     "Đóng tay trước ngày đáo hạn."),
    ("cancel_order", NANG,
     "Không huỷ được một lệnh ở sàn",
     "IBKR chỉ nhận lệnh huỷ từ đúng kết nối (clientId) đã đặt lệnh đó. Huỷ từ kết nối "
     "khác sẽ thất bại — và trước 10/08 nó thất bại trong im lặng.",
     "Lấy số clientId trong dòng log rồi huỷ lại từ đúng id đó, hoặc huỷ trong TWS."),
    ("STP ID DRIFT", VUA,
     "Stop vẫn bảo vệ, nhưng sổ ghi sai số hiệu lệnh",
     "Vị thế vẫn an toàn — có stop thật đang chạy. Chỉ là số hiệu trong sổ không trỏ vào "
     "nó, nên khi đóng vị thế hệ thống sẽ huỷ nhầm một lệnh không tồn tại và bỏ lại lệnh "
     "thật treo trên sàn.",
     "Dừng scheduler rồi chạy repair_stops.py để ghi lại đúng số hiệu."),
    ("SOFT-STALE", VUA,
     "Dữ liệu SPY hơi cũ",
     "Chuỗi SPY cũ hơn 2 ngày làm việc. Chưa chặn lệnh nào, nhưng để thêm vài ngày nữa "
     "thì sẽ chặn hết.",
     "Kiểm tra việc pre-flight 13:45 có chạy không."),
]

# Những thứ xuất hiện trong log mà KHÔNG phải vấn đề — nói ra để khỏi bị hiểu nhầm.
_GOOD = [
    ("STP HOAN", "Hoãn đặt stop sang phiên sau — đúng luật đã kiểm định, không phải lỗi"),
    ("cua so hoan", "Vị thế mới chưa đặt stop vì đang trong cửa sổ hoãn có chủ đích"),
    ("B4 REPLACED", "Hệ thống tự đặt lại stop cho một vị thế bị mất stop"),
    ("STP: placed", "Đặt lệnh stop"),
    ("STP: cancelled", "Huỷ lệnh stop khi đóng vị thế"),
    ("DOI CHIEU KHOP", "Đối chiếu với backtest: KHỚP"),
    ("MAX_HOLD", "Đóng vị thế do đủ số ngày giữ"),
    ("completed OK", "Một việc theo lịch chạy xong"),
]



# ── Tiến độ chuyển sang resume ───────────────────────────────────────────────
# Đường giao dịch hiện chạy REPLAY ĐẦY ĐỦ mỗi slot (run_day ~5 phút, đủ chậm để lỡ slot).
# Resume thì chỉ replay phần chưa replay — nhanh hơn nhiều — nhưng chỉ được chuyển khi có
# bằng chứng nó cho ra CÙNG kết quả. Bằng chứng đó là dòng `DOI CHIEU KHOP` do slot cuối
# chạy `--shadow-verify` sinh ra: nó chạy cả hai đường rồi so.
#
# Một phiên chỉ tính là ĐẠT khi **đủ cả 5 mã** khớp và **không mã nào lệch**. Thiếu mã
# không phải "chưa đủ dữ liệu" mà là một câu hỏi chưa được trả lời — 07/08 slot 15:55 chỉ
# sinh dòng cho MNKD, và đó chính là thứ suýt bị đọc thành "đã đối chiếu xong".
#
# Ngưỡng 5 phiên liên tiếp là phán đoán, không phải kết quả đo: không có phép thử nào nói
# đúng bao nhiêu phiên là đủ. Đặt thành hằng số ở đây để nó là một lựa chọn nhìn thấy được,
# đổi bằng --resume-streak khi có lý do.
SHADOW_INSTS = ("MES", "MNQ", "MYM", "M2K", "MNKD")
RESUME_STREAK_NEEDED = 5
_SHADOW = re.compile(r"\[shadow\]\s+(\w+):\s+DOI CHIEU (KHOP|LECH)")


def shadow_history(root: Path) -> dict:
    """{ngày: {"khop": set(mã), "lech": set(mã)}} — quét MỌI file log, mọi ngày."""
    out: dict = {}
    for pat in ("scheduler_*.log", "live_day_*.log"):
        for f in sorted(root.glob(pat)):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln in text.splitlines():
                m = _TS.match(ln)
                if not m:
                    continue
                d = m.group(1)
                if _is_test_line(ln, d):
                    continue
                sm = _SHADOW.search(ln)
                if not sm:
                    continue
                d = _to_et(d, m.group(2))[0]        # gom theo NGÀY ET, không phải ngày máy
                rec = out.setdefault(d, {"khop": set(), "lech": set()})
                rec["khop" if sm.group(2) == "KHOP" else "lech"].add(sm.group(1))
    return out


def resume_progress(hist: dict, upto: str, need: int):
    """(chuỗi phiên ĐẠT liên tiếp tính tới `upto`, các dòng bảng để in)."""
    rows, streak = [], 0
    for d in sorted(hist):
        if d > upto:
            continue
        rec = hist[d]
        missing = [i for i in SHADOW_INSTS if i not in rec["khop"]]
        if rec["lech"]:
            verdict, ok = "LỆCH — " + " ".join(sorted(rec["lech"])), False
        elif missing:
            verdict, ok = "thiếu " + " ".join(missing), False
        else:
            verdict, ok = "ĐẠT", True
        streak = streak + 1 if ok else 0
        rows.append((d, len(rec["khop"]), verdict))
    return streak, rows


def _is_test_line(line: str, day: str = "") -> bool:
    """Dòng do test sinh ra.

    Dấu hiệu chuỗi chỉ bắt được cái đã thấy. Phân biệt mạnh hơn là **ngày nằm trong nội
    dung dòng**: kịch bản test dùng ngày cố định (2024-06-17, 2026-01-07...), còn một dòng
    ghi lúc 10/08/2026 mà nói về ngày cách đó hàng năm thì gần như chắc là test. Ngưỡng 45
    ngày đủ rộng để không loại nhầm dòng nhắc hợp đồng đáo hạn quý sau.
    """
    if any(m in line for m in _TEST_MARKERS):
        return True
    if not day:
        return False
    try:
        d0 = _date.fromisoformat(day)
    except ValueError:
        return False
    for y, mo, dd in _MSG_DATE.findall(line[19:]):
        try:
            if abs((_date(int(y), int(mo), int(dd)) - d0).days) > 45:
                return True
        except ValueError:
            continue
    return False


def read_lines(day: str, root: Path):
    """Mọi dòng có dấu thời gian rơi vào `day`, từ MỌI file log."""
    kept, dropped, files = [], 0, []
    for pat in ("scheduler_*.log", "live_day_*.log"):
        for f in sorted(root.glob(pat)):
            hit = 0
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln in text.splitlines():
                m = _TS.match(ln)
                if not m:
                    continue
                _d, _t = _to_et(m.group(1), m.group(2))
                if _d != day:
                    continue
                if _is_test_line(ln, day):
                    dropped += 1
                    continue
                kept.append((_t, m.group(3), ln))
                hit += 1
            if hit:
                files.append((f.name, hit))
    kept.sort(key=lambda r: r[0])
    return kept, dropped, files


def expected_jobs() -> list:
    """Lịch lấy từ chính `make_scheduler` — không chép tay."""
    try:
        from global_index.run_scheduler import make_scheduler
    except Exception:
        return []
    sched = make_scheduler(port=4002, dry_run=True)
    try:
        out = []
        for j in sched.get_jobs():
            if j.id == "heartbeat":
                continue
            f = {str(x.name): str(x) for x in j.trigger.fields}
            try:
                out.append((int(f["hour"]), int(f["minute"]), j.id))
            except (KeyError, ValueError):
                continue
        return sorted(out)
    finally:
        if getattr(sched, "running", False):
            sched.shutdown(wait=False)


def _ran_labels(lines) -> set:
    out = set()
    for _t, _lvl, ln in lines:
        m = re.search(r"\[([A-Z0-9_\-]{3,})\]", ln)
        if m:
            out.add(m.group(1).lower())
    return out


def _wrap(text: str, pad: str, width: int = 76) -> list:
    out, cur = [], ""
    for w in text.split():
        if cur and len(pad) + len(cur) + 1 + len(w) > width:
            out.append(pad + cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        out.append(pad + cur)
    return out


def _arm_note(pos: dict) -> str:
    """Vị thế này bao giờ mới được đặt stop — trả lời bằng giờ, không bằng tên biến."""
    try:
        import pandas as pd
        from global_index.runner import ET_TZ, _ARM_BY_CLUSTER
        arm = _ARM_BY_CLUSTER.get(pos.get("cluster"))
        if not arm or not pos.get("entry_day"):
            return ""
        tz, hh, mm = arm
        d = (pd.Timestamp(pos["entry_day"]).normalize() + pd.Timedelta(days=1)).date()
        at = (pd.Timestamp(f"{d} {hh:02d}:{mm:02d}", tz=tz)
              .tz_convert(ET_TZ).tz_localize(None))
        return f"Stop sẽ được đặt từ {at.strftime('%H:%M ngày %d/%m')} giờ ET trở đi."
    except Exception:
        return ""


def _today_et() -> str:
    try:
        import pandas as pd
        return str(pd.Timestamp.now(tz="America/New_York").date())
    except Exception:
        return str(_date.today())


def _job_ran(jid: str, ran: set) -> bool:
    return any(jid in r or jid.replace("_", "") in r.replace("_", "") for r in ran)


def _job_had_log_near(lines, hh: int, mm: int) -> bool:
    lo = f"{hh:02d}:{mm:02d}:00"
    hi_h, hi_m = divmod(hh * 60 + mm + 5, 60)
    return any(lo <= t < f"{hi_h % 24:02d}:{hi_m:02d}:00" for t, _l, _n in lines)


def _resume_grid(hist: dict, rows: list) -> list:
    out = []
    for d, _n, verdict in rows[-10:]:
        rec = hist.get(d, {"khop": set(), "lech": set()})
        cells = []
        for inst in SHADOW_INSTS:
            if inst in rec["lech"]:
                state = "lech"
                label = "LỆCH"
            elif inst in rec["khop"]:
                state = "khop"
                label = "KHỚP"
            else:
                state = "missing"
                label = "thiếu"
            cells.append({"inst": inst, "state": state, "label": label})
        out.append({"date": d, "verdict": verdict, "cells": cells})
    return out


def collect_session_report(day: str, root: Path, resume_streak: int = RESUME_STREAK_NEEDED) -> dict:
    """Thu thập dữ liệu báo cáo một lần, để text và HTML cùng đọc một nguồn."""
    _is_today = (day == _today_et())
    lines, dropped, files = read_lines(day, root)
    report = {
        "day": day,
        "root": str(root),
        "is_today": _is_today,
        "lines": lines,
        "dropped": dropped,
        "files": files,
        "empty": not lines,
        "need": True,
    }
    if not lines:
        return report

    found = {}
    for t, _lvl, ln in lines:
        for key, sev, title, mean, act in _KNOWN:
            if key in ln:
                e = found.setdefault(title, [sev, mean, act, 0, t])
                e[3] += 1
                break
    issues = [
        {"title": title, "severity": sev, "severity_label": _NHAN[sev],
         "mean": mean, "action": act, "count": n, "first": first}
        for title, (sev, mean, act, n, first) in
        sorted(found.items(), key=lambda kv: (_RANK[kv[1][0]], -kv[1][3]))
    ]

    good = {}
    for _t, _lvl, ln in lines:
        for key, desc in _GOOD:
            if key in ln:
                good[desc] = good.get(desc, 0) + 1
                break
    normal = [{"desc": desc, "count": n}
              for desc, n in sorted(good.items(), key=lambda kv: -kv[1])]

    exp, ran = expected_jobs(), _ran_labels(lines)
    now_hhmm = lines[-1][0][:5]
    due = 0
    jobs = []
    for hh, mm, jid in exp:
        hhmm = f"{hh:02d}:{mm:02d}"
        if hhmm > now_hhmm:
            continue
        due += 1
        ran_by_label = _job_ran(jid, ran)
        ran_by_window = _job_had_log_near(lines, hh, mm)
        ran_ok = ran_by_label or ran_by_window
        jobs.append({"time": hhmm, "id": jid, "ran": ran_ok,
                     "missing": not ran_ok})
    raw_missing = [f"{j['time']}  {j['id']}" for j in jobs if j["missing"]]
    missing = raw_missing if _is_today else []
    skipped_past_missing = bool(raw_missing and not _is_today)

    positions = []
    try:
        # Đọc từ `root`, KHÔNG phải _ROOT cố định; chỉ dùng cho báo cáo hôm nay.
        raw_positions = json.loads(
            (root / "live_positions.json").read_text(encoding="utf-8")).get("positions", [])
    except Exception:
        raw_positions = []
    if _is_today:
        for pos in raw_positions:
            p = dict(pos)
            p["arm_note"] = _arm_note(pos) if pos.get("stop_order_id") is None else ""
            positions.append(p)

    hist = shadow_history(root)
    streak, rows = resume_progress(hist, day, resume_streak)
    resume = {
        "needed": resume_streak,
        "streak": streak,
        "rows": rows,
        "grid": _resume_grid(hist, rows),
    }

    blockers = [i["title"] for i in issues if i["severity"] == CHAN]
    serious = [i["title"] for i in issues if i["severity"] == NANG]
    need = bool(blockers or serious or (raw_missing and _is_today))

    timeline = []
    last_min = None
    for j in jobs:
        hh, mm = [int(x) for x in j["time"].split(":")]
        cur = hh * 60 + mm
        if last_min is not None and cur - last_min > 30:
            timeline.append({"kind": "gap", "minutes": cur - last_min,
                             "start": f"{last_min // 60:02d}:{last_min % 60:02d}",
                             "end": j["time"]})
        timeline.append({"kind": "job", **j})
        last_min = cur

    report.update({
        "need": need,
        "issues": issues,
        "blockers": blockers,
        "serious": serious,
        "normal": normal,
        "jobs_due": due,
        "jobs_ran": due - len(raw_missing),
        "missing_jobs": missing,
        "raw_missing_jobs": raw_missing,
        "skipped_past_missing": skipped_past_missing,
        "timeline": timeline,
        "positions": positions,
        "current_position_count": len(raw_positions) if _is_today else 0,
        "source": {"line_count": len(lines), "first_time": lines[0][0],
                   "last_time": lines[-1][0], "dropped": dropped},
        "resume": resume,
        "todo": list(dict.fromkeys(i["action"] for i in issues if i["action"])),
    })
    return report


def render_text(report: dict) -> str:
    day = report["day"]
    L = [f"BÁO CÁO PHIÊN  —  {day}   (mọi giờ trong báo cáo là giờ ET)", "=" * 78]
    if report.get("empty"):
        L += ["", "Không có dòng log nào cho ngày này.",
              "Nghĩa là scheduler không chạy, hoặc chạy ở thư mục khác.",
              "→ Cần làm: kiểm tra tiến trình scheduler còn sống không."]
        return "\n".join(L)

    blockers = report["blockers"]
    serious = report["serious"]
    missing = list(report["missing_jobs"])
    positions = list(report["positions"])
    source = report["source"]

    L += ["", "TÓM TẮT", "-" * 78]
    if blockers:
        L += _wrap("Phiên này có chuyện CHẶN GIAO DỊCH: " + "; ".join(blockers)
                   + ". Hệ thống không vào lệnh mới cho tới khi được xử lý.", "  ")
    elif serious:
        L += _wrap(f"Phiên chạy được, nhưng có {len(serious)} vấn đề nặng cần xử lý "
                   "trước phiên sau.", "  ")
    elif missing:
        L += _wrap(f"Không có sự cố, nhưng {len(missing)} việc theo lịch đã không chạy.", "  ")
    else:
        L.append("  Phiên chạy bình thường. Không có gì cần làm.")
    L.append("")
    L.append(f"  Việc theo lịch : {report['jobs_ran']}/{report['jobs_due']} đã tới giờ và có chạy")
    L.append(f"  Đang giữ       : {report['current_position_count']} vị thế")
    L.append(f"  Nguồn          : {source['line_count']} dòng log, {source['first_time']}–{source['last_time']}"
             + (f", đã bỏ {source['dropped']} dòng do test cũ sinh ra" if source["dropped"] else ""))

    L += ["", "VẤN ĐỀ", "-" * 78]
    if not report["issues"]:
        L.append("  Không phát hiện vấn đề nào.")
    for issue in report["issues"]:
        L.append("")
        L.append(f"  [{issue['severity_label']}]  {issue['title']}")
        L.append(f"  lần đầu lúc {issue['first']}, ghi nhận {issue['count']} lần")
        L += _wrap(issue["mean"], "    ")
        if issue["action"]:
            L.append("    → Cần làm:")
            L += _wrap(issue["action"], "       ")

    if report["skipped_past_missing"]:
        L += ["", "VIỆC THEO LỊCH — KHÔNG KIỂM ĐƯỢC CHO NGÀY QUÁ KHỨ", "-" * 78]
        L += _wrap("Điểm danh đối chiếu với lịch job HIỆN TẠI, mà lịch thì đổi theo thời gian. "
                   "Một việc 'không chạy' ngày hôm đó có thể đơn giản là chưa tồn tại. Bỏ qua "
                   "phần này cho ngày quá khứ thay vì đưa ra một danh sách trông như sự cố.", "  ")
    if missing:
        L += ["", "VIỆC THEO LỊCH ĐÃ KHÔNG CHẠY", "-" * 78]
        L += _wrap("Một việc không chạy thì không để lại dòng log nào — đây là phần log không tự "
                   "nói ra được. Nguyên nhân hay gặp nhất: scheduler được khởi động MUỘN hơn giờ "
                   "của việc đó; khi ấy việc đó không hề tồn tại trong lịch, chứ không phải chạy trễ.",
                   "  ")
        L.append("")
        for m in missing:
            L.append(f"     {m}")

    if report["normal"]:
        L += ["", "DIỄN RA BÌNH THƯỜNG", "-" * 78]
        for item in report["normal"]:
            L.append(f"    {item['count']:>5} lần   {item['desc']}")

    resume = report["resume"]
    L += ["", "CHUYỂN SANG RESUME — tiến độ đối chiếu", "-" * 78]
    L += _wrap(f"Điều kiện: {resume['needed']} phiên LIÊN TIẾP có đủ {len(SHADOW_INSTS)} mã "
               "KHỚP và không mã nào LỆCH. Một phiên thiếu mã không phải 'chưa đủ dữ liệu' — "
               "nó là câu hỏi chưa được trả lời.", "  ")
    L.append("")
    L.append(f"  Hiện tại: {resume['streak']}/{resume['needed']} phiên liên tiếp đạt"
             + ("  →  ĐỦ ĐIỀU KIỆN, có thể chuyển"
                if resume["streak"] >= resume["needed"] else ""))
    if not resume["rows"]:
        L.append("")
        L += _wrap("Chưa có phiên nào sinh dòng đối chiếu. Nhớ bật scheduler kèm --shadow-resume; "
                   "không có cờ thì không thu được gì.", "  ")
    else:
        L.append("")
        L.append(f"    {'ngày':<12} {'mã khớp':>8}   kết luận")
        for d, n, verdict in resume["rows"][-10:]:
            L.append(f"    {d:<12} {n}/{len(SHADOW_INSTS):<6}   {verdict}")
    if 0 < resume["streak"] < resume["needed"]:
        L.append("")
        L += _wrap(f"Còn {resume['needed'] - resume['streak']} phiên sạch nữa. Một phiên LỆCH "
                   "làm chuỗi về 0 — và LỆCH là CRITICAL, phải điều tra chứ không đếm tiếp.", "  ")

    L += ["", "ĐANG GIỮ GÌ" if report["is_today"] else "ĐANG GIỮ GÌ (KHÔNG áp dụng)", "-" * 78]
    if not report["is_today"]:
        L += _wrap("`live_positions.json` chỉ chứa trạng thái HIỆN TẠI — nó không lưu vị thế của "
                   "từng ngày. In nó ra ở đây sẽ thành 'ngày 07/08 đang giữ một vị thế vào lệnh "
                   "ngày 10/08', tức một câu vô nghĩa nhưng đọc rất xuôi.", "  ")
    if not positions and report["is_today"]:
        L.append("  Không giữ vị thế nào.")
    for pos in positions:
        sid = pos.get("stop_order_id")
        L.append("")
        L.append(f"  {pos.get('inst')} {pos.get('direction')} {pos.get('contracts')} "
                 f"hợp đồng   ({pos.get('cluster')})")
        L.append(f"    vào lệnh {str(pos.get('entry_day'))[:10]} tại giá {pos.get('entry_price')}")
        if sid is None:
            L += _wrap(f"CHƯA có lệnh stop ở sàn; mức dự kiến {pos.get('stop_price')}. "
                       + pos.get("arm_note", "")
                       + " Nếu vị thế vừa mở phiên trước thì đây là cửa sổ hoãn CÓ CHỦ ĐÍCH — "
                         "backtest cũ cũng chỉ xét stop từ ngày hôm sau, và đặt sớm hơn thì mất "
                         "hết edge.", "    ")
        else:
            L.append(f"    stop đang đặt ở {pos.get('stop_price')}, số hiệu lệnh {sid}")

    L += ["", "=" * 78]
    if report["todo"]:
        L.append("VIỆC CẦN LÀM")
        for i, t in enumerate(report["todo"], 1):
            L.append("")
            L += _wrap(f"{i}. {t}", "  ")
    elif report["need"]:
        L.append("Không có việc sửa cụ thể, nhưng xem lại phần trên.")
    else:
        L.append("Không có việc gì cần làm.")
    return "\n".join(L)


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _html_path_for(day: str, out: str | None, root: Path) -> Path:
    if out:
        return Path(out).with_suffix(".html")
    mmdd = day[5:7] + day[8:10]
    return root / f"bao_cao_{mmdd}.html"


def render_html(report: dict) -> str:
    day = report["day"]
    sev_class = {CHAN: "blocker", NANG: "serious", VUA: "info"}
    issue_cards = []
    for issue in report.get("issues", []):
        cls = sev_class.get(issue["severity"], "info")
        issue_cards.append(f"""
        <article class="issue {cls}">
          <div class="issue-head"><span>{_esc(issue['severity_label'])}</span><strong>{_esc(issue['title'])}</strong></div>
          <p class="muted">lần đầu lúc {_esc(issue['first'])}, ghi nhận {_esc(issue['count'])} lần</p>
          <h3>nghĩa là gì</h3><p>{_esc(issue['mean'])}</p>
          <h3>cần làm gì</h3><p>{_esc(issue['action'])}</p>
        </article>""")
    if not issue_cards:
        issue_cards.append('<p class="empty">Không phát hiện vấn đề nào.</p>')

    timeline_bits = []
    for item in report.get("timeline", []):
        if item["kind"] == "gap":
            timeline_bits.append(
                f'<div class="gap" style="--span:{min(item["minutes"], 180)}">'
                f'<span>{_esc(item["start"])}–{_esc(item["end"])}</span><b>{item["minutes"]} phút trống</b></div>')
        else:
            cls = "miss" if item["missing"] else "ok"
            label = "không thấy log" if item["missing"] else "đã chạy"
            timeline_bits.append(
                f'<div class="job {cls}"><time>{_esc(item["time"])}</time>'
                f'<strong>{_esc(item["id"])}</strong><span>{label}</span></div>')

    if report.get("skipped_past_missing"):
        missing_html = '<p class="note">Ngày quá khứ: bỏ qua danh sách việc-không-chạy vì lịch hiện tại không phải bằng chứng cho lịch ngày đó.</p>'
    elif report.get("missing_jobs"):
        missing_html = "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in report["missing_jobs"]) + "</ul>"
    else:
        missing_html = '<p class="empty">Không có việc theo lịch bị thiếu trong phạm vi kiểm được.</p>'

    normal_html = "".join(
        f'<li><b>{item["count"]}</b><span>{_esc(item["desc"])}</span></li>'
        for item in report.get("normal", [])) or '<li><span>Không có mục bình thường nổi bật.</span></li>'

    resume = report.get("resume", {"streak": 0, "needed": RESUME_STREAK_NEEDED, "grid": []})
    cells = "".join("<i></i>" for _ in range(resume["needed"]))
    fill = max(0, min(resume["streak"], resume["needed"]))
    grid_rows = []
    for row in resume.get("grid", []):
        grid_rows.append("<tr><th>" + _esc(row["date"]) + "</th>" + "".join(
            f'<td class="{c["state"]}"><b>{_esc(c["inst"])}</b><span>{_esc(c["label"])}</span></td>'
            for c in row["cells"]) + f'<td>{_esc(row["verdict"])}</td></tr>')
    if not grid_rows:
        grid_rows.append('<tr><td colspan="7" class="empty">Chưa có phiên nào sinh dòng đối chiếu.</td></tr>')

    pos_html = ""
    if not report.get("is_today"):
        pos_html = '<p class="note">Không áp dụng cho ngày quá khứ: live_positions.json chỉ là trạng thái hiện tại.</p>'
    elif not report.get("positions"):
        pos_html = '<p class="empty">Không giữ vị thế nào.</p>'
    else:
        for pos in report["positions"]:
            stop = (f"stop {_esc(pos.get('stop_price'))}, lệnh {_esc(pos.get('stop_order_id'))}"
                    if pos.get("stop_order_id") is not None
                    else f"chưa có stop ở sàn; mức dự kiến {_esc(pos.get('stop_price'))}. {_esc(pos.get('arm_note'))}")
            pos_html += f"""
            <article class="position">
              <strong>{_esc(pos.get('inst'))} {_esc(pos.get('direction'))}</strong>
              <span>{_esc(pos.get('contracts'))} hợp đồng</span>
              <span>vào {_esc(str(pos.get('entry_day'))[:10])} @ {_esc(pos.get('entry_price'))}</span>
              <span>{stop}</span>
            </article>"""

    todo_html = "".join(f"<li>{_esc(t)}</li>" for t in report.get("todo", [])) or "<li>Không có việc gì cần làm.</li>"
    source = report.get("source", {})
    issue_count = len(report.get("issues", []))
    status = "CHẶN GIAO DỊCH" if report.get("blockers") else ("CẦN XỬ LÝ" if report.get("serious") else "BÌNH THƯỜNG")

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Báo cáo phiên {day}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f5f6f8;color:#111827;font:15px/1.5 Arial,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px}} header{{display:flex;justify-content:space-between;gap:24px;align-items:flex-end;margin-bottom:24px}}
h1{{font-size:34px;margin:0;letter-spacing:0}} h2{{font-size:20px;margin:28px 0 12px}} h3{{font-size:13px;text-transform:uppercase;margin:12px 0 4px;color:#4b5563}}
.pill{{display:inline-block;border-radius:999px;padding:6px 10px;background:#111827;color:white;font-weight:700}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}} .metric,.issue,.position,.panel{{background:white;border:1px solid #d8dde6;border-radius:8px;padding:14px}}
.metric b{{display:block;font-size:24px}} .muted,.empty,.note{{color:#5b6472}} .note{{background:#fff8e6;border:1px solid #f0d48a;border-radius:8px;padding:12px}}
.timeline{{display:flex;gap:6px;align-items:stretch;overflow-x:auto;padding:8px;background:white;border:1px solid #d8dde6;border-radius:8px}}
.job,.gap{{min-width:120px;border-radius:6px;padding:8px;border:1px solid #d8dde6}} .job.ok{{border-left:5px solid #168a49}} .job.miss{{border-left:5px solid #c42828;background:#fff1f1}}
.job time,.gap span{{display:block;font-weight:700}} .job strong{{display:block;font-size:12px;white-space:nowrap}} .job span,.gap b{{font-size:12px;color:#4b5563}} .gap{{min-width:calc(var(--span)*2px);background:#eef1f5;border-style:dashed}}
.issues{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}} .issue.blocker{{border-top:5px solid #991b1b}} .issue.serious{{border-top:5px solid #b45309}} .issue.info{{border-top:5px solid #2563eb}}
.issue-head span{{display:block;font-size:12px;font-weight:700;color:#4b5563}} .issue-head strong{{font-size:17px}}
.normal{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;list-style:none;padding:0}} .normal li{{background:white;border:1px solid #d8dde6;border-radius:8px;padding:10px}} .normal b{{font-size:20px;margin-right:8px}}
.bar{{display:grid;grid-template-columns:repeat({resume["needed"]},1fr);gap:6px;max-width:420px}} .bar i{{height:16px;border-radius:4px;background:#d8dde6}} .bar i:nth-child(-n+{fill}){{background:#168a49}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #d8dde6;border-radius:8px;overflow:hidden}} th,td{{padding:8px;border-bottom:1px solid #e5e7eb;text-align:left}} td b{{display:block}} td span{{font-size:12px}} td.khop{{background:#ecfdf3}} td.lech{{background:#fee2e2}} td.missing{{background:#f3f4f6;color:#6b7280}}
.positions{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}} .position span{{display:block;margin-top:4px}}
ol{{background:white;border:1px solid #d8dde6;border-radius:8px;padding:16px 16px 16px 34px}}
@media(max-width:820px){{main{{padding:16px}} header{{display:block}} .cards,.issues,.normal,.positions{{grid-template-columns:1fr}} h1{{font-size:28px}}}}
</style>
</head>
<body><main>
<header><div><h1>Báo cáo phiên {day}</h1><p class="muted">Mọi giờ trong báo cáo là giờ ET. HTML tự chứa, đọc cùng dữ liệu với bản text.</p></div><span class="pill">{_esc(status)}</span></header>
<section class="cards">
<div class="metric"><span>Việc theo lịch</span><b>{report.get("jobs_ran", 0)}/{report.get("jobs_due", 0)}</b></div>
<div class="metric"><span>Vấn đề</span><b>{issue_count}</b></div>
<div class="metric"><span>Đang giữ</span><b>{report.get("current_position_count", 0)}</b></div>
<div class="metric"><span>Nguồn</span><b>{source.get("line_count", 0)}</b><span class="muted">{_esc(source.get("first_time", ""))}–{_esc(source.get("last_time", ""))}; bỏ {source.get("dropped", 0)} dòng test</span></div>
</section>
<h2>Dòng thời gian trong ngày</h2><section class="timeline">{''.join(timeline_bits)}</section>
<h2>Vấn đề</h2><section class="issues">{''.join(issue_cards)}</section>
<h2>Việc theo lịch không chạy</h2><section class="panel missing-jobs">{missing_html}</section>
<h2>Diễn ra bình thường</h2><ul class="normal">{normal_html}</ul>
<h2>Chuyển sang resume</h2><section class="panel"><p>Tiến độ: <b>{resume["streak"]}/{resume["needed"]}</b> phiên liên tiếp đạt</p><div class="bar">{cells}</div><table><thead><tr><th>ngày</th>{''.join(f'<th>{i}</th>' for i in SHADOW_INSTS)}<th>kết luận</th></tr></thead><tbody>{''.join(grid_rows)}</tbody></table></section>
<h2>Vị thế đang giữ</h2><section class="positions">{pos_html}</section>
<h2>Việc cần làm</h2><ol>{todo_html}</ol>
</main></body></html>"""


def build(day: str, root: Path, resume_streak: int = RESUME_STREAK_NEEDED):
    report = collect_session_report(day, root, resume_streak=resume_streak)
    return render_text(report), report["need"]

    # Kept unreachable only as historical reference for the previous text renderer.
    # Hai phần dưới đây đọc trạng thái HIỆN TẠI, không phải trạng thái của `day`. Với báo
    # cáo hôm nay thì trùng nhau; với ngày quá khứ thì chúng nói dối, và nói dối một cách
    # rất thuyết phục — bản đầu in "MNKD vào lệnh 2026-08-10" trong báo cáo ngày 07/08.
    _is_today = (day == _today_et())
    lines, dropped, files = read_lines(day, root)
    L = [f"BÁO CÁO PHIÊN  —  {day}   (mọi giờ trong báo cáo là giờ ET)", "=" * 78]
    if not lines:
        L += ["", "Không có dòng log nào cho ngày này.",
              "Nghĩa là scheduler không chạy, hoặc chạy ở thư mục khác.",
              "→ Cần làm: kiểm tra tiến trình scheduler còn sống không."]
        return "\n".join(L), True

    found = {}
    for t, _lvl, ln in lines:
        for key, sev, title, mean, act in _KNOWN:
            if key in ln:
                e = found.setdefault(title, [sev, mean, act, 0, t])
                e[3] += 1
                break

    good = {}
    for _t, _lvl, ln in lines:
        for key, desc in _GOOD:
            if key in ln:
                good[desc] = good.get(desc, 0) + 1
                break

    exp, ran = expected_jobs(), _ran_labels(lines)
    now_hhmm = lines[-1][0][:5]
    missing, due = [], 0
    for hh, mm, jid in exp:
        if f"{hh:02d}:{mm:02d}" > now_hhmm:
            continue
        due += 1
        if any(jid in r or jid.replace("_", "") in r.replace("_", "") for r in ran):
            continue
        lo = f"{hh:02d}:{mm:02d}:00"
        hi_h, hi_m = divmod(hh * 60 + mm + 5, 60)
        if any(lo <= t < f"{hi_h % 24:02d}:{hi_m:02d}:00" for t, _l, _n in lines):
            continue
        missing.append(f"{hh:02d}:{mm:02d}  {jid}")

    try:
        # Đọc từ `root`, KHÔNG phải _ROOT cố định. Production thì hai cái trùng nhau
        # (--root mặc định là _ROOT), nhưng chốt cứng _ROOT làm hàm không kiểm được: một
        # bản dựng thử sẽ in vị thế THẬT ra giữa dữ liệu giả.
        positions = json.loads(
            (root / "live_positions.json").read_text(encoding="utf-8")).get("positions", [])
    except Exception:
        positions = []

    blockers = [t for t, e in found.items() if e[0] == CHAN]
    serious = [t for t, e in found.items() if e[0] == NANG]
    # Ngày quá khứ: `missing` tính theo lịch hiện tại nên không phải bằng chứng — không
    # để nó quyết định mã thoát.
    need = bool(blockers or serious or (missing and day == _today_et()))

    # ── tóm tắt ──────────────────────────────────────────────────────────────
    L += ["", "TÓM TẮT", "-" * 78]
    if blockers:
        L += _wrap("Phiên này có chuyện CHẶN GIAO DỊCH: " + "; ".join(blockers)
                   + ". Hệ thống không vào lệnh mới cho tới khi được xử lý.", "  ")
    elif serious:
        L += _wrap(f"Phiên chạy được, nhưng có {len(serious)} vấn đề nặng cần xử lý "
                   "trước phiên sau.", "  ")
    elif missing:
        L += _wrap(f"Không có sự cố, nhưng {len(missing)} việc theo lịch đã không chạy.",
                   "  ")
    else:
        L.append("  Phiên chạy bình thường. Không có gì cần làm.")
    L.append("")
    L.append(f"  Việc theo lịch : {due - len(missing)}/{due} đã tới giờ và có chạy")
    L.append(f"  Đang giữ       : {len(positions)} vị thế")
    L.append(f"  Nguồn          : {len(lines)} dòng log, {lines[0][0]}–{lines[-1][0]}"
             + (f", đã bỏ {dropped} dòng do test cũ sinh ra" if dropped else ""))

    # ── vấn đề ───────────────────────────────────────────────────────────────
    L += ["", "VẤN ĐỀ", "-" * 78]
    if not found:
        L.append("  Không phát hiện vấn đề nào.")
    for title, (sev, mean, act, n, first) in sorted(
            found.items(), key=lambda kv: (_RANK[kv[1][0]], -kv[1][3])):
        L.append("")
        L.append(f"  [{_NHAN[sev]}]  {title}")
        L.append(f"  lần đầu lúc {first}, ghi nhận {n} lần")
        L += _wrap(mean, "    ")
        if act:
            L.append("    → Cần làm:")
            L += _wrap(act, "       ")

    # ── việc không chạy ──────────────────────────────────────────────────────
    if missing and not _is_today:
        L += ["", "VIỆC THEO LỊCH — KHÔNG KIỂM ĐƯỢC CHO NGÀY QUÁ KHỨ", "-" * 78]
        L += _wrap("Điểm danh đối chiếu với lịch job HIỆN TẠI, mà lịch thì đổi theo thời "
                   "gian. Một việc 'không chạy' ngày hôm đó có thể đơn giản là chưa tồn "
                   "tại. Bỏ qua phần này cho ngày quá khứ thay vì đưa ra một danh sách "
                   "trông như sự cố.", "  ")
        missing = []
    if missing:
        L += ["", "VIỆC THEO LỊCH ĐÃ KHÔNG CHẠY", "-" * 78]
        L += _wrap("Một việc không chạy thì không để lại dòng log nào — đây là phần log "
                   "không tự nói ra được. Nguyên nhân hay gặp nhất: scheduler được khởi "
                   "động MUỘN hơn giờ của việc đó; khi ấy việc đó không hề tồn tại trong "
                   "lịch, chứ không phải chạy trễ.", "  ")
        L.append("")
        for m in missing:
            L.append(f"     {m}")

    # ── bình thường ──────────────────────────────────────────────────────────
    if good:
        L += ["", "DIỄN RA BÌNH THƯỜNG", "-" * 78]
        for desc, n in sorted(good.items(), key=lambda kv: -kv[1]):
            L.append(f"    {n:>5} lần   {desc}")

    # ── tiến độ resume ───────────────────────────────────────────────────────
    hist = shadow_history(root)
    streak, rows = resume_progress(hist, day, resume_streak)
    L += ["", "CHUYỂN SANG RESUME — tiến độ đối chiếu", "-" * 78]
    L += _wrap(f"Điều kiện: {resume_streak} phiên LIÊN TIẾP có đủ "
               f"{len(SHADOW_INSTS)} mã KHỚP và không mã nào LỆCH. Một phiên thiếu mã "
               "không phải 'chưa đủ dữ liệu' — nó là câu hỏi chưa được trả lời.", "  ")
    L.append("")
    L.append(f"  Hiện tại: {streak}/{resume_streak} phiên liên tiếp đạt"
             + ("  →  ĐỦ ĐIỀU KIỆN, có thể chuyển"
                if streak >= resume_streak else ""))
    if not rows:
        L.append("")
        L += _wrap("Chưa có phiên nào sinh dòng đối chiếu. Nhớ bật scheduler kèm "
                   "--shadow-resume; không có cờ thì không thu được gì.", "  ")
    else:
        L.append("")
        L.append(f"    {'ngày':<12} {'mã khớp':>8}   kết luận")
        for d, n, verdict in rows[-10:]:
            L.append(f"    {d:<12} {n}/{len(SHADOW_INSTS):<6}   {verdict}")
    if 0 < streak < resume_streak:
        L.append("")
        L += _wrap(f"Còn {resume_streak - streak} phiên sạch nữa. Một phiên LỆCH "
                   "làm chuỗi về 0 — và LỆCH là CRITICAL, phải điều tra chứ không đếm "
                   "tiếp.", "  ")

    # ── đang giữ gì ──────────────────────────────────────────────────────────
    L += ["", "ĐANG GIỮ GÌ" if _is_today else "ĐANG GIỮ GÌ (KHÔNG áp dụng)", "-" * 78]
    if not _is_today:
        L += _wrap("`live_positions.json` chỉ chứa trạng thái HIỆN TẠI — nó không lưu vị "
                   "thế của từng ngày. In nó ra ở đây sẽ thành 'ngày 07/08 đang giữ một vị "
                   "thế vào lệnh ngày 10/08', tức một câu vô nghĩa nhưng đọc rất xuôi.",
                   "  ")
        positions = []
    if not positions and _is_today:
        L.append("  Không giữ vị thế nào.")
    for pos in positions:
        sid = pos.get("stop_order_id")
        L.append("")
        L.append(f"  {pos.get('inst')} {pos.get('direction')} {pos.get('contracts')} "
                 f"hợp đồng   ({pos.get('cluster')})")
        L.append(f"    vào lệnh {str(pos.get('entry_day'))[:10]} tại giá "
                 f"{pos.get('entry_price')}")
        if sid is None:
            L += _wrap(f"CHƯA có lệnh stop ở sàn; mức dự kiến {pos.get('stop_price')}. "
                       + _arm_note(pos)
                       + " Nếu vị thế vừa mở phiên trước thì đây là cửa sổ hoãn CÓ CHỦ "
                         "ĐÍCH — backtest cũng chỉ xét stop từ ngày hôm sau, và đặt sớm "
                         "hơn thì mất hết edge.", "    ")
        else:
            L.append(f"    stop đang đặt ở {pos.get('stop_price')}, số hiệu lệnh {sid}")

    # ── việc cần làm ─────────────────────────────────────────────────────────
    L += ["", "=" * 78]
    todo = list(dict.fromkeys(e[2] for e in found.values() if e[2]))
    if todo:
        L.append("VIỆC CẦN LÀM")
        for i, t in enumerate(todo, 1):
            L.append("")
            L += _wrap(f"{i}. {t}", "  ")
    elif need:
        L.append("Không có việc sửa cụ thể, nhưng xem lại phần trên.")
    else:
        L.append("Không có việc gì cần làm.")
    return "\n".join(L), need


def main() -> int:
    ap = argparse.ArgumentParser(description="Báo cáo một phiên, viết cho người đọc")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD; mặc định hôm nay theo ET")
    ap.add_argument("--root", default=str(_ROOT), help="thư mục chứa log")
    ap.add_argument("--out", default=None, help="ghi ra file thay vì in")
    ap.add_argument("--resume-streak", type=int, default=RESUME_STREAK_NEEDED,
                    help=f"số phiên sạch liên tiếp cần có trước khi chuyển sang resume "
                         f"(mặc định {RESUME_STREAK_NEEDED}; là phán đoán, không phải "
                         f"kết quả đo)")
    a = ap.parse_args()

    if a.date:
        day = a.date
    else:
        try:
            import pandas as pd
            day = str(pd.Timestamp.now(tz="America/New_York").date())
        except Exception:
            day = str(_date.today())

    text, need = build(day, Path(a.root), resume_streak=a.resume_streak)
    if a.out:
        # utf-8-SIG, không phải utf-8 trần. Windows đoán bảng mã theo code page của console
        # khi không có BOM, nên `type bao_cao_0810.txt` in ra "BÃO CÃO PHIÃŠN" thay vì
        # "BÁO CÁO PHIÊN". Một báo cáo không đọc được bằng cách mở thông thường thì coi như
        # không tồn tại. BOM làm `type`, Notepad và Get-Content nhận đúng UTF-8.
        #
        # An toàn: file này chỉ để người đọc, không có gì phân tích nó.
        Path(a.out).write_text(text, encoding="utf-8-sig")
        print(f"đã ghi {a.out}")
    else:
        print(text)
    return 1 if need else 0


if __name__ == "__main__":
    sys.exit(main())
