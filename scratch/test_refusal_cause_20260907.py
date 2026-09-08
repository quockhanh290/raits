"""Một lời từ chối phải nói được VÌ SAO. TỆP MỚI.

Ca đã xảy ra
------------
Ngày 2026-09-07, cả 23 slot của sleeve swing bị từ chối. Bản ghi nói:

    reason = "gate_refused"   detail = "missing_session,stale"

Đúng, và không dùng được. Phải đọc bốn tệp mã, đo lại parquet, và đổi múi giờ mới ra được
câu trả lời thật: **CME đóng cửa lúc 13:00 ET vào Labor Day, còn cửa sổ swing là 14:00–15:55**.
Cổng làm đúng việc — thị trường đóng thì không có bar, và từ chối là câu trả lời đúng.

Cùng cặp mã ấy cũng xuất hiện khi job dữ liệu không chạy và khi nguồn bar hỏng. Ba chuyện
khác hẳn nhau về việc phải làm gì, một chuỗi mã.

Cái phép kiểm này canh
----------------------
Rằng mỗi lời từ chối được xếp vào một trong bốn nhóm, và nhóm thứ tư — **không biết** — tồn
tại thật chứ không bị gộp vào ba nhóm kia. Kho này đã trả giá cho việc gộp "không đo được"
vào "không có gì": một phép dò tiến trình trả danh sách rỗng cho ba kiểu trục trặc, rỗng
nghĩa là "không có bản sao nào đang chạy", và hai bộ lập lịch đã tranh một client id làm
hỏng sáu slot vào lệnh.

Ở đây, đoán bừa "thị trường đóng" khi không đọc được lịch sẽ tha bổng một ngày hệ thật sự
hỏng — và tha bổng đúng vào ngày không ai xem lại, vì bản ghi đã nói là không sao.
"""
from __future__ import annotations

import datetime as dt
import sys
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from global_index import track1_refusal_cause as rc      # noqa: E402

SWING = dict(window_from="14:00", window_to="15:55")


# ── ca thật, neo vào ngày đã đo ──────────────────────────────────────────────

def test_the_labor_day_swing_refusal_is_market_closed():
    """23 slot ngày 07/09. Phiên CME đóng 13:00 ET; cửa sổ swing bắt đầu 14:00."""
    c = rc.classify(session_day="2026-09-07", codes="missing_session,stale", **SWING)
    assert c.cause == rc.MARKET_CLOSED, c
    assert "13:00" in c.detail, c.detail
    assert c.needs_a_person is False


def test_the_same_codes_on_an_open_session_are_a_system_fault():
    """Cùng hai mã, ngày thường -> phải là lỗi hệ.

    Đây là nửa quan trọng: nếu phân loại chỉ nhìn mã thì hai ngày này ra cùng một câu trả
    lời, và cả tệp này vô nghĩa.
    """
    c = rc.classify(session_day="2026-09-08", codes="missing_session,stale", **SWING)
    assert c.cause == rc.SYSTEM_FAULT, c
    assert c.needs_a_person is True


def test_a_weekend_is_market_closed():
    c = rc.classify(session_day="2026-09-05", codes="missing_session", **SWING)
    assert c.cause == rc.MARKET_CLOSED


def test_the_evidence_names_the_session_hours():
    """Một phân loại không nói được vì sao nó phân loại như thế là thứ sẽ được tin trong
    đúng cái ngày nó sai."""
    c = rc.classify(session_day="2026-09-07", codes="missing_session,stale", **SWING)
    assert c.evidence.get("session"), c.evidence
    assert c.evidence["session"][1].endswith("13:00:00"), c.evidence["session"]


# ── không biết là một câu trả lời, không phải một chỗ để đoán ────────────────

def test_no_calendar_gives_unknown_not_market_closed(monkeypatch):
    """Không có lịch thì câu trung thực là "không biết".

    Đọc thành "thị trường đóng" sẽ tha bổng một ngày hệ hỏng, và tha bổng lặng lẽ.
    """
    monkeypatch.setattr(rc, "_session_bounds", lambda d: None)
    monkeypatch.setattr(rc, "_is_a_session", lambda d: None)
    c = rc.classify(session_day="2026-09-07", codes="missing_session,stale", **SWING)
    assert c.cause == rc.UNKNOWN, c
    assert c.needs_a_person is True, "không biết vì sao hệ từ chối thì phải có người nhìn"


def test_a_different_clock_gives_unknown_rather_than_a_wrong_comparison():
    """Nikkei đọc giờ Tokyo; giờ phiên đọc được là ET. So hai đồng hồ khác nhau cho ra một
    câu trả lời trông đúng — kho này đã mất một ngày vì đúng loại nhầm lẫn đó."""
    c = rc.classify(session_day="2026-09-07", codes="missing_session",
                    window_from="14:00", window_to="15:55", clock="Asia/Tokyo")
    assert c.cause == rc.UNKNOWN, c


# ── lỗi dữ liệu thì lịch không cứu được ──────────────────────────────────────

def test_a_join_fault_is_a_system_fault_even_on_a_foreign_clock():
    """19 slot Nikkei ngày 04/09: chuỗi hợp đồng đã roll, hai nửa bất đồng giá.

    Trước khi tầng này biết đến lỗi nối dữ liệu, chúng rơi vào "không biết" chỉ vì cửa sổ
    của sleeve ấy tính bằng giờ Tokyo — một lỗi thật bị xếp nhầm vì lý do không liên quan.
    """
    c = rc.classify(session_day="2026-09-04",
                    codes="MNKD: the live half and history disagree on 1069 of 1080 shared",
                    window_from="14:00", window_to="15:55", clock="Asia/Tokyo")
    assert c.cause == rc.SYSTEM_FAULT, c
    assert "disagree on" in str(c.evidence.get("join_fault")), c.evidence


def test_a_join_fault_beats_a_closed_market():
    """Dữ liệu đã về nhưng SAI thì giờ phiên không giải thích được, kể cả ngày thị trường
    đóng. Ngày 29/08 là thứ Bảy và có hai lượt chạy tay báo bất đồng — xếp chúng vào "không
    phải lỗi" là giấu một chuyện đáng nhìn sau một ngày nghỉ."""
    c = rc.classify(session_day="2026-08-29",
                    codes="ES: the live half and history disagree on 3 of 100 shared", **SWING)
    assert c.cause == rc.SYSTEM_FAULT, c


def test_a_malformed_frame_is_a_system_fault():
    c = rc.classify(session_day="2026-09-07", codes="tz_mismatch", **SWING)
    assert c.cause == rc.SYSTEM_FAULT
    assert "hình dạng" in c.detail


# ── chưa tới lúc là chuyện khác hẳn ──────────────────────────────────────────

def test_too_early_alone_is_data_not_yet():
    c = rc.classify(session_day="2026-09-08", codes="too_early", **SWING)
    assert c.cause == rc.DATA_NOT_YET
    assert c.needs_a_person is False


def test_too_early_with_other_codes_is_not_excused():
    """Chỉ MỘT mình "chưa tới lúc" mới là chưa tới lúc. Kèm mã khác thì có chuyện khác.

    Mã thứ hai ở đây cố ý KHÔNG phải mã hình dạng. Bản đầu của phép kiểm này dùng
    `tz_mismatch`, và nhánh hình dạng bắt nó trước — nên khi tôi thử phá điều kiện "chỉ
    toàn mã chờ" thành "có bất kỳ mã chờ nào", phép kiểm vẫn xanh. Nó đang canh một nhánh
    khác với nhánh nó tưởng. `stale` đi thẳng tới đúng nhánh cần canh.
    """
    c = rc.classify(session_day="2026-09-08", codes="too_early,stale", **SWING)
    assert c.cause == rc.SYSTEM_FAULT, c


# ── chạy trên chính bằng chứng đã ghi ────────────────────────────────────────

def test_every_recorded_refusal_lands_in_a_named_cause():
    """Không lời từ chối nào rơi ra ngoài bốn nhóm — và tập phải không rỗng."""
    import glob
    import json

    seen = 0
    for f in sorted(glob.glob(str(REPO / "global_index/track1_runtime/signals/*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("status") != "SLOT_REFUSED":
                continue
            seen += 1
            assert rc.classify_slot(d).cause in rc.CAUSES
    assert seen >= 50, f"chỉ thấy {seen} lời từ chối — phép kiểm không đo gì"


def test_the_recorded_history_is_not_all_one_bucket():
    """Nếu mọi thứ rơi vào một nhóm thì tầng phân loại không phân loại gì cả."""
    import collections
    import glob
    import json

    by = collections.Counter()
    for f in sorted(glob.glob(str(REPO / "global_index/track1_runtime/signals/*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("status") == "SLOT_REFUSED":
                by[rc.classify_slot(d).cause] += 1
    assert len(by) >= 2, by
    assert by.get(rc.MARKET_CLOSED, 0) >= 20, ("ngày lễ 07/09 phải cho ít nhất 23 lời từ "
                                               f"chối thuộc nhóm thị trường đóng: {by}")


def test_it_changes_no_verdict():
    """Tầng này chỉ dịch. Nó không được import bởi cổng, bộ chấm hay bộ thực thi — nếu có,
    một phân loại sai sẽ đổi được một quyết định, và đó không phải việc của nó."""
    import ast

    for name in ("track1_gates.py", "track1_paper_readiness.py",
                 "track1_shadow_acceptance.py", "track1_paper_executor.py"):
        src = (REPO / "global_index" / name).read_text(encoding="utf-8")
        assert "track1_refusal_cause" not in src, name
        ast.parse(src)
