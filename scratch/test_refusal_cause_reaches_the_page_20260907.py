"""Phân loại lời từ chối phải ĐẾN ĐƯỢC màn hình. TỆP MỚI.

Vì sao có tệp này
-----------------
Tầng phân loại nguyên nhân được xây, kiểm bằng 24 phép kiểm, chứng minh đỏ được sáu kiểu —
và **không ai import nó**. Nó đúng, đo được, và vô hình.

Đó là đúng lỗi kho này đã ghi lại: hai job gắn vào bộ lập lịch, chạy mỗi tối, và bộ đọc nhật
ký không thấy gì — cả khi thành công lẫn khi hỏng. Lần ấy nó được tạo ra **ba giờ sau khi
bài học được viết vào báo cáo**, và lộ ra vì chủ dự án hỏi. Lần này cũng vậy.

Nên phép kiểm này không kiểm phân loại đúng hay sai — tệp kia làm việc đó. Nó kiểm **thông
tin có đi được từ nơi tính ra tới nơi người ta đọc hay không**.

Điều nó canh
------------
Hai tình huống cho cùng một con số, và màn hình phải nói khác nhau:

    ngày lễ       23 slot bị từ chối vì CME đóng lúc 13:00 — không ai phải làm gì
    ngày thường   23 slot bị từ chối vì phiên mở mà không có bar — kiểm job dữ liệu

Hàng đếm ở trên nói "refused 23" cho cả hai.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"
CSS = REPO / "global_index" / "dash" / "realtime" / "realtime.css"
READER = REPO / "monitor" / "backend" / "track1_runtime_reader.py"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ── backend: phân loại có vào payload không ──────────────────────────────────

def _payload() -> dict:
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from monitor.backend.track1_runtime_reader import read_track1_runtime

        return (read_track1_runtime(REPO).get("signals") or {}).get("refusals") or {}
    finally:
        logging.disable(logging.NOTSET)


def test_the_reader_actually_calls_the_classifier():
    assert "track1_refusal_cause" in READER.read_text(encoding="utf-8"), (
        "bộ đọc không gọi tầng phân loại — nó vẫn vô hình")


def test_the_payload_carries_groups_with_a_cause():
    r = _payload()
    assert r.get("present") is True, r
    for g in r.get("groups", []):
        assert g.get("cause"), g
        assert isinstance(g.get("count"), int) and g["count"] > 0, g


def test_the_payload_counts_what_needs_a_person_separately():
    """Con số này là câu hỏi người vận hành đang hỏi. Gộp nó vào tổng là quay về chỗ một
    ngày lễ trông như một ngày hỏng."""
    r = _payload()
    assert "needs_a_person" in r, r
    assert r["needs_a_person"] <= r.get("total", 0)


def test_the_labor_day_session_reads_as_market_closed():
    """Neo vào phiên 07/09 ĐÃ GHI, không vào "hôm nay".

    Bản đầu neo vào hôm nay và đỏ hai giờ sau khi viết, lúc ET lăn sang 08/09 — đúng luật
    "phép đo của chính mình cũng hết hạn". Một ngày đã đóng sổ thì không đổi nữa; "hôm nay"
    thì đổi mỗi đêm, và một phép kiểm đo nó thực ra đang đo cái đồng hồ.
    """
    from monitor.backend.track1_runtime_reader import _refusal_causes

    r = _refusal_causes("20260907", REPO)
    assert r.get("total") == 23, r
    assert r.get("needs_a_person") == 0, r
    assert [g["cause"] for g in r["groups"]] == ["market_closed"], r["groups"]
    assert r["groups"][0]["evidence"]["codes"] == ["missing_session", "stale"], r["groups"][0]


def test_the_live_payload_is_well_formed_on_any_day():
    """Cái duy nhất đúng với MỌI ngày: hình dạng. Số thì tuỳ ngày, và một ngày chưa có slot
    nào là câu trả lời hợp lệ, không phải một lỗi."""
    r = _payload()
    assert r.get("present") is True, r
    assert isinstance(r.get("total"), int) and r["total"] >= 0, r
    assert r["needs_a_person"] <= r["total"], r
    assert sum(g["count"] for g in r["groups"]) == r["total"], r


def test_a_group_that_needs_a_person_carries_what_to_check():
    """Nhãn không kèm việc phải làm là một cái tên mới cho cùng sự bối rối."""
    from global_index import track1_refusal_cause as rc

    for f in rc.FAULTS:
        assert len(rc.ACTIONS.get(f, "").split()) >= 10, f


def test_an_unreadable_day_does_not_break_the_payload(tmp_path):
    """Panel mất một khối thì vẫn là panel; panel không tải được thì không còn là panel."""
    from monitor.backend.track1_runtime_reader import _refusal_causes

    out = _refusal_causes("20991231", tmp_path)
    assert out.get("present") is False and out.get("reading")


# ── frontend: có vẽ ra không ─────────────────────────────────────────────────

pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="cần node")

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const i = src.indexOf('const REFUSAL_WORDS');
const j = src.indexOf('function refusalRow');
if (i < 0 || j < 0) throw new Error('khong tim thay refusalRow');
let d = 0, end = j;
for (let k = src.indexOf('{', j); k < src.length; k++) {
  if (src[k] === '{') d++;
  if (src[k] === '}') { d--; if (!d) { end = k + 1; break; } }
}
const esc = v => String(v == null ? '' : v);
let sig = { refusals: JSON.parse(process.argv[2]) };
eval(src.slice(i, end));
process.stdout.write(refusalRow());
"""


def _row(refusals: dict) -> str:
    # node ghi UTF-8; mặc định của subprocess trên Windows là cp1252 và sẽ nổ ở dấu tiếng Việt
    proc = subprocess.run(["node", "-e", _HARNESS, str(JS),
                           json.dumps(refusals, ensure_ascii=False)],
                          capture_output=True, text=True, timeout=60,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr[:400]
    return proc.stdout


HOLIDAY = {"present": True, "total": 23, "needs_a_person": 0,
           "groups": [{"cause": "market_closed", "fault": "", "count": 23,
                       "needs_a_person": False, "action": "",
                       "detail": "the session closed at 13:00 ET"}]}
BROKEN = {"present": True, "total": 23, "needs_a_person": 23,
          "groups": [{"cause": "system_fault", "fault": "session_absent", "count": 23,
                      "needs_a_person": True, "action": "Check the 13:45 data refresh",
                      "detail": "session open, no bars"}]}


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
def test_the_same_count_reads_differently_on_a_holiday_and_a_broken_day():
    """Đây là toàn bộ lý do tầng này tồn tại. Hai tình huống, cùng con số 23, và màn hình
    phải nói khác nhau."""
    h, b = _row(HOLIDAY), _row(BROKEN)
    assert h != b, "hai tình huống trái ngược mà màn hình nói y hệt nhau"
    assert "none need a person" in h, h
    assert "need a person" in b and "23" in b, b


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
def test_a_group_needing_a_person_is_marked_and_carries_its_action():
    b = _row(BROKEN)
    assert "needs-person" in b, "nhóm cần người không được đánh dấu"
    assert "13:45" in b, "việc phải kiểm không tới được màn hình"


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
def test_a_holiday_group_is_not_marked_as_needing_anyone():
    assert "needs-person" not in _row(HOLIDAY)


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
def test_the_cause_is_named_in_words_not_in_codes():
    """"market_closed" là từ của người viết mã. Người đọc màn hình cần một câu."""
    h = _row(HOLIDAY)
    assert "market_closed" not in h, h
    assert "market closed" in h, h


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
def test_no_refusals_says_so_rather_than_rendering_empty():
    out = _row({"present": True, "total": 0, "needs_a_person": 0, "groups": []})
    assert "no slot was refused" in out


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
def test_an_absent_day_shows_its_reading():
    out = _row({"present": False, "reading": "no slot has run today"})
    assert "no slot has run today" in out


# ── dấu phải nhìn thấy được ──────────────────────────────────────────────────

def test_the_marker_has_a_style():
    """Một class không có luật CSS nào là dấu vô hình — mã nguồn đọc lên như đã giải quyết,
    màn hình thì không đổi."""
    css = CSS.read_text(encoding="utf-8")
    assert ".t1-refusal" in css
    assert re.search(r"\.t1-refusal\.needs-person\s*\{[^}]*color", css)


def test_the_marker_is_not_an_error_colour():
    """Đỏ ở đây sẽ dạy người vận hành rằng một ngày lễ trông như một sự cố."""
    css = CSS.read_text(encoding="utf-8")
    start = css.index("#track1Facts .t1-refusal {")
    block = css[start:css.index("}", start) + 1]   # đúng một khối, không trùm sang selector kế
    assert "--red" not in block, block
    marker = css[css.index("#track1Facts .t1-refusal.needs-person"):]
    assert "--red" not in marker[:marker.index("}") + 1], marker[:120]


def test_the_row_is_wired_into_the_panel():
    """Hàm dựng ra một chuỗi mà không ai gọi cũng vô hình y như tầng phân loại lúc đầu."""
    src = JS.read_text(encoding="utf-8")
    assert "t1Fact('Refusals', refusalRow()" in src
