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


def build(day: str, root: Path, resume_streak: int = RESUME_STREAK_NEEDED):
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
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"đã ghi {a.out}")
    else:
        print(text)
    return 1 if need else 0


if __name__ == "__main__":
    sys.exit(main())
