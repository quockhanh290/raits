"""Còn chỗ nào trên trang đang trả lời về tuyến cũ nữa không. TỆP MỚI.

Vì sao có tệp này
-----------------
Trong một buổi tối, năm chỗ khác nhau trên bảng điều khiển hoá ra đang nói về tuyến đã nghỉ
hưu, trong khi tuyến mới đã tiếp quản:

    nhãn tuyến trên thẻ công việc   gán "tuyến cũ" cho mọi thứ không mang tiền tố Track 1,
                                    nên ba job SPY — hai trong đó tồn tại VÌ Nikkei — bị dán
                                    nhãn của tuyến chúng ít liên quan nhất
    bảng lịch                       hỏi "sàn chứng khoán Mỹ có mở không" cho một tuyến giao
                                    dịch hợp đồng tương lai trên CME
    mười một lượt quét bảo vệ       vẫn chạy, canh một cuốn sổ rỗng từ 04/09, và sẽ gọi mọi
                                    vị thế Track 1 là "mồ côi" ở mức nghiêm trọng
    đồng hồ trên cùng panel         đọc tệp trạng thái đứng yên từ 24/08
    bảng thị trường                 neo về 04/09 vào một ngày CME mở, tự ghi lý do là "hôm
                                    nay không phải ngày giao dịch"

Không cái nào là lỗi logic. **Mỗi cái đều đúng vào ngày nó được viết ra**, rồi thứ nó mô tả
đổi đi mà nó ở lại. Năm lần trong một buổi thì lần thứ sáu nhiều khả năng đang ở đâu đó, và
tìm bằng cách mò từng cái là cách đã để lọt năm lần đầu.

Phép kiểm này KHÔNG cấm chạm vào nguồn của tuyến cũ
---------------------------------------------------
Cấm là sai: nhiều chỗ đọc chúng có chủ đích và đúng — bộ đọc vị thế tuyến cũ tồn tại để hiện
cuốn sổ đang cạn, và nó gắn nhãn tuyến ngay tại nguồn. Cái phép kiểm đòi là **mỗi chỗ chạm
phải được ai đó nhìn qua và ghi lý do**. Một chỗ mới xuất hiện mà chưa ai xét thì đỏ.

Cùng khuôn với `SHARED_INFRA_JOBS` và `MIRROR_EXEMPT` đã có trong kho: đặt tên chứ không suy.
Một danh sách suy ra được sẽ im lặng đúng lúc có thứ mới, và im lặng là thứ đã để lọt năm lần.

Hai chiều đều đỏ
----------------
Thiếu (có chỗ chạm không nằm trong bảng) và thừa (bảng còn mục đã biến mất) đều làm đỏ. Chiều
thứ hai chống bảng mục nát: một bảng đầy mục không còn thật là bảng không ai tin nữa.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Nguồn dữ liệu và luật THUỘC VỀ TUYẾN CŨ. Chạm vào một trong số này là chạm vào tuyến đã
#: nghỉ hưu, dù cố ý hay không.
LEGACY_SOURCES: dict = {
    "live_state_data": "tệp trạng thái runner tuyến cũ ghi; đứng yên từ 24/08",
    "live_positions.json": "sổ vị thế tuyến cũ; giữ 0 vị thế từ 04/09",
    "trade_log.jsonl": "nhật ký giao dịch dùng chung; Track 1 ghi vào tệp riêng",
    "runner_events_": "nhật ký sự kiện của runner tuyến cũ",
    "STATE_SLOTS": "45 slot vào lệnh của tuyến cũ; không còn đăng ký ở chế độ chỉ-Track-1",
    "is_trading_day": "lịch NYSE; tuyến này giao dịch trên CME",
}

#: Nơi phép kiểm nhìn: mọi thứ dựng nên trang.
SCAN_DIRS = ("monitor/backend", "global_index/dash")
SCAN_SUFFIXES = (".py", ".js")

#: Mỗi cặp (tệp, nguồn) đã được nhìn qua, kèm lý do. Chưa xét thì để ở `PENDING_REVIEW`.
#: Lý do phải nói vì sao chỗ ấy chạm vào tuyến cũ mà vẫn ĐÚNG.
REVIEWED: dict = {
    ("runner_positions_reader.py", "live_positions.json"):
        "Cố ý, và gắn nhãn ngay tại nguồn: bộ đọc này TRẢ VỀ sổ tuyến cũ và tự đặt "
        "route='legacy' cùng một câu nói rõ đây là sổ đang cạn. Đúng chỗ nhất để nhãn ra đời.",
    ("schedule_status.py", "is_trading_day"):
        "Đã sửa 2026-09-06: bảng lịch nay hỏi lịch CME. Lần chạm còn lại là câu văn trong "
        "tài liệu của hàm mới, giải thích vì sao lịch chứng khoán không phải câu hỏi đúng.",
    ("track1_market_view.py", "is_trading_day"):
        "Đã sửa 2026-09-07: hỏi lịch CME trước, và chỉ lùi về lịch chứng khoán khi không có "
        "thư viện lịch — khi ấy câu trả lời cũ vẫn hơn không có câu nào.",
    ("schedule_status.py", "STATE_SLOTS"):
        "Bảng lịch phải biết 45 slot ấy tồn tại để KHÔNG liệt kê chúng ở chế độ chỉ-Track-1. "
        "Biết để trừ đi, không phải để hiện ra.",
    ("track1_runtime_reader.py", "live_positions.json"):
        "Nhắc tên để nói rằng Track 1 KHÔNG đọc tệp này: câu ghi chú trên trang phân biệt sổ "
        "của hai tuyến, và bộ đọc chỉ mở đường dẫn của Track 1.",
    ("job_journal_reader.py", "live_state_data"):
        "Nhật ký công việc nhận diện lỗi ghi trạng thái theo tên tệp trong dòng log. Nó đọc "
        "log, không đọc tệp ấy.",
    ("app.py", "live_state_data"):
        "Điểm cuối phục vụ tệp trạng thái tuyến cũ nguyên trạng cho trang cũ. Track 1 có "
        "điểm cuối riêng.",
    ("app.py", "live_positions.json"):
        "Cùng lý do: đường dẫn truyền vào bộ đọc vị thế tuyến cũ, thứ tự gắn nhãn.",
}

#: Đã thấy, CHƯA ai xét. Đây là công việc nhìn thấy được, không phải chỗ để giấu.
#:
#: Để riêng thay vì nhét vào `REVIEWED` với một lý do bịa: "đã liệt kê" không phải "đã xét",
#: và gộp hai thứ đó lại là biến phép kiểm này thành thứ luôn xanh. Danh sách ngắn đi khi có
#: người thật sự đọc từng chỗ.
PENDING_REVIEW: set = {
    ("paper_evidence_reader.py", "live_positions.json"),
    ("paper_evidence_reader.py", "live_state_data"),
    ("paper_evidence_reader.py", "trade_log.jsonl"),
    ("entry_time_reader.py", "live_positions.json"),
    ("entry_time_reader.py", "trade_log.jsonl"),
    ("execution_quality_reader.py", "trade_log.jsonl"),
    ("report_reader.py", "live_positions.json"),
    ("report_reader.py", "live_state_data"),
    ("report_reader.py", "runner_events_"),
    ("report_reader.py", "trade_log.jsonl"),
    ("runner_event_reader.py", "runner_events_"),
    ("open_issue_reader.py", "live_state_data"),
    ("paper.js", "live_positions.json"),
    ("paper.js", "live_state_data"),
    ("realtime.js", "live_positions.json"),
    ("realtime.js", "live_state_data"),
    ("realtime.js", "trade_log.jsonl"),
    ("live.js", "live_state_data"),
}

#: Dòng chỉ là chú thích thì không tính — một tệp giải thích vì sao nó KHÔNG dùng nguồn cũ
#: không phải là một tệp dùng nguồn cũ. Đây chính là cái bẫy đã chặn nhầm một commit tối nay:
#: một cổng an toàn khớp chuỗi con trên văn bản tự do và bắt lời văn thay vì bắt hành vi.
_COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")


def _touches() -> set:
    found = set()
    for d in SCAN_DIRS:
        for path in sorted((REPO / d).rglob("*")):
            if path.suffix not in SCAN_SUFFIXES or not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                if _COMMENT.match(line):
                    continue
                for src in LEGACY_SOURCES:
                    if src in line:
                        found.add((path.name, src))
    return found


def _known() -> set:
    return set(REVIEWED) | PENDING_REVIEW


# ── phép kiểm tự chứng minh nó đo được thứ gì ────────────────────────────────

def test_the_scan_actually_finds_something():
    """Không có dòng này thì mọi assert dưới đây pass trên tập rỗng."""
    found = _touches()
    assert len(found) >= 20, f"chỉ tìm thấy {len(found)} chỗ chạm — bộ quét hỏng rồi"


def test_every_reviewed_entry_carries_a_real_reason():
    """Một lý do rỗng hay một chữ 'ok' là một mục chưa xét mang áo đã xét."""
    for key, why in REVIEWED.items():
        assert len(why.split()) >= 8, (key, why)


# ── cái chính ────────────────────────────────────────────────────────────────

def test_no_place_on_the_page_reads_the_retired_route_unreviewed():
    """Chỗ mới chạm vào nguồn của tuyến cũ mà chưa ai xét.

    Đây là phép kiểm đáng lẽ đã bắt được cả năm ca tối 2026-09-06: mỗi ca là một tệp dựng
    nên trang, đọc một nguồn hoặc một luật của tuyến đã nghỉ, mà không ai nhìn lại kể từ khi
    tuyến mới tiếp quản.
    """
    new = sorted(_touches() - _known())
    assert not new, (
        "có chỗ mới đang trả lời về tuyến cũ mà chưa ai xét:\n  "
        + "\n  ".join(f"{f} -> {s}  ({LEGACY_SOURCES[s]})" for f, s in new)
        + "\n\nXét nó, rồi thêm vào REVIEWED kèm lý do, hoặc vào PENDING_REVIEW nếu chưa kịp.")


def test_the_table_has_no_entries_that_no_longer_exist():
    """Chiều ngược lại. Một bảng đầy mục không còn thật là bảng không ai tin nữa — và nó che
    mất chỗ thật, đúng như một danh sách job giữ tay từng in '69 passed' cho phần nó không
    hề gọi."""
    stale = sorted(_known() - _touches())
    assert not stale, (
        "bảng còn mục đã biến mất khỏi mã nguồn — xoá đi:\n  "
        + "\n  ".join(f"{f} -> {s}" for f, s in stale))


def test_the_pending_list_is_visible_work_not_a_hiding_place():
    """Danh sách chờ xét phải NGẮN ĐI theo thời gian. Ghim trần ở mức hôm nay đặt ra, nên
    thêm một mục mới vào đó mà không xét chỗ nào cũng làm đỏ."""
    assert len(PENDING_REVIEW) <= 18, (
        f"{len(PENDING_REVIEW)} mục chờ xét, trần là 18. Danh sách này để rút ngắn, "
        f"không phải để chứa thêm.")


def test_the_five_places_fixed_that_evening_stay_fixed():
    """Neo vào những ca đã đo, để một lần hồi quy đọc ra thành tên cụ thể thay vì một con số.

    Ba trong năm ca không còn chạm nguồn cũ nữa (nhãn tuyến, đồng hồ, lượt quét), nên chúng
    vắng mặt khỏi bản quét là đúng. Hai ca còn lại vẫn chạm — và phải nằm trong REVIEWED, vì
    lý do chúng chạm là lý do đã được viết ra.
    """
    for key in (("schedule_status.py", "is_trading_day"),
                ("track1_market_view.py", "is_trading_day")):
        assert key in REVIEWED, key
        assert "CME" in REVIEWED[key], f"{key}: lý do phải nói rõ nó đã chuyển sang lịch nào"
