"""Hai ô trên trang bảo người đọc đi tìm thứ chúng đang cầm. TỆP MỚI.

MỘT — ô "no bar evaluated"
--------------------------
Khi detector dừng trước khi quét bar nào, ô ấy in: *"Setup rules nói nó dừng ở đâu; các chỉ
số nó dừng trên nằm ở Conditions bên dưới."* Người đọc phải mở tab khác.

Nhưng lý do đã được tính sẵn ngay trong hàm dựng ô — đọc từ cổng đầu tiên không đạt, hoặc từ
câu chẩn đoán của chiến lược — rồi gán vào một biến không ai dùng. Phiên 07/09 nó chứa:

    global_nkd      "regime 'Calm'; this sleeve trades Normal"
    roska4_stress   "Instruments below open and VWAP 3 (needs >= 4); ..."

Câu đầu trả lời trong một dòng vì sao sleeve Nikkei không quét bar nào.

HAI — hàng job "có nói gì đó"
-----------------------------
Câu gộp ở đầu nhật ký công việc hứa: *"Mọi hàng nói điều gì khác là hàng có chuyện khác xảy
ra."* Cơ chế đánh dấu duy nhất bám vào trạng thái — viền xanh cho đã-phục-hồi, đỏ cho hỏng.

Đo trên phiên 07/09: **48 trên 48 thẻ đều `completed`**, kể cả thẻ duy nhất mang nội dung
riêng (lượt SPY 04:45, "nothing to do — the daily series covers 2026-09-04"). Nên hàng mà câu
gộp vừa hứa sẽ nổi lên trông y hệt 47 hàng nó vừa gộp đi.

Cả hai đều là một ô biết câu trả lời và không nói ra.
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

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="cần node")

_HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const pick = n => {
  const i = src.indexOf('function ' + n);
  if (i < 0) throw new Error('khong tim thay ' + n);
  let d = 0;
  for (let k = src.indexOf('{', i); k < src.length; k++) {
    if (src[k] === '{') d++;
    if (src[k] === '}') { d--; if (!d) return src.slice(i, k + 1); }
  }
};
const mvEsc = v => String(v == null ? '' : v);
const mvEmpty = (m, d) => `<div class="mv-empty"><b>${mvEsc(m)}</b>` +
                          (d ? `<span>${mvEsc(d)}</span>` : '') + `</div>`;
const mvBarGrid = () => '';
eval(pick('mvBarGridCard'));
process.stdout.write(mvBarGridCard(JSON.parse(process.argv[2])) || '');
"""


def _card(sleeve: dict) -> str:
    proc = subprocess.run(["node", "-e", _HARNESS, str(JS), json.dumps(sleeve)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[:400]
    return proc.stdout


# ── một: ô nói ra lý do nó đang cầm ──────────────────────────────────────────

def test_the_card_renders_at_all():
    assert "No bar was evaluated" in _card({"strategy": {}})


def test_a_failed_gate_detail_is_shown_not_pointed_at():
    """Đúng ca `global_nkd` ngày 07/09."""
    html = _card({"strategy": {"diagnostics": {"gates": [
        {"gate": "regime", "passed": False, "detail": "regime 'Calm'; this sleeve trades Normal"},
    ]}}})
    assert "regime 'Calm'; this sleeve trades Normal" in html, html[-300:]
    assert "Conditions below" not in html, "vẫn còn bảo người đọc đi tìm"


def test_a_strategy_detail_is_shown_when_no_gate_failed():
    """Đúng ca `roska4_stress`: không cổng nào bị đánh dấu hỏng, lý do nằm ở câu chẩn đoán."""
    html = _card({"strategy": {"detail": "Instruments below open and VWAP 3 (needs >= 4)"}})
    assert "needs >= 4" in html


def test_the_pointer_sentence_survives_when_nothing_can_be_read():
    """Không có lý do nào đọc được thì câu trỏ là hướng dẫn thật, không phải lời thoái thác."""
    html = _card({"strategy": {}})
    assert "Conditions below" in html
    assert "It stopped here" not in html


def test_a_passing_gate_is_not_mistaken_for_the_reason():
    """Lý do phải là cổng KHÔNG đạt. Lấy cổng đầu tiên bất kể trạng thái sẽ in ra một dòng
    đang PASS làm lý do dừng — sai, và sai một cách nghe rất hợp lý."""
    html = _card({"strategy": {"diagnostics": {"gates": [
        {"gate": "a", "passed": True, "detail": "KHONG_PHAI_LY_DO"},
        {"gate": "b", "passed": False, "detail": "DAY_MOI_LA_LY_DO"},
    ]}}})
    assert "DAY_MOI_LA_LY_DO" in html
    assert "KHONG_PHAI_LY_DO" not in html


# ── hai: hàng có nội dung được đánh dấu ──────────────────────────────────────

def test_a_row_that_says_something_gets_a_class():
    src = JS.read_text(encoding="utf-8")
    assert "says-something" in src, "hàng có nội dung không được gắn dấu nào"
    assert "const speaks = Boolean(rowProblem)" in src


def test_the_marker_has_a_style():
    """Một class không có luật CSS nào là một dấu vô hình — tệ hơn không có dấu, vì mã nguồn
    đọc lên như đã giải quyết."""
    css = CSS.read_text(encoding="utf-8")
    assert ".job-row.says-something" in css
    assert re.search(r"\.job-row\.says-something\s*\{[^}]*border-left-color", css)


def test_an_abnormal_status_still_wins():
    """Thứ tự trong tệp quyết định ai thắng khi một hàng vừa có nội dung vừa có trạng thái
    lạ. Trạng thái phải thắng — nó nói mạnh hơn."""
    css = CSS.read_text(encoding="utf-8")
    says = css.index(".job-row.says-something {")
    for later in (".job-row.status-recovered", ".job-row.status-open"):
        assert css.index(later) > says, f"{later} phải đứng SAU says-something"


def test_the_marker_is_not_an_error_colour():
    """Hàng này không phải lỗi — nó chỉ có gì đó để đọc. Dùng màu đỏ ở đây là dạy người
    vận hành rằng một lượt chạy bình thường trông như hỏng."""
    css = CSS.read_text(encoding="utf-8")
    rule = css[css.index(".job-row.says-something {"):][:200]
    assert "--red" not in rule and "--green" not in rule, rule


def test_todays_journal_marks_exactly_the_one_row_that_speaks():
    """Neo vào dữ liệu thật: phiên 07/09 có đúng một thẻ mang nội dung riêng."""
    from monitor.backend.job_journal_reader import read_job_journal

    jobs = read_job_journal("2026-09-07", REPO)["jobs"]
    assert len(jobs) > 20, f"chỉ {len(jobs)} thẻ — phép kiểm không đo gì"
    speaks = [j for j in jobs if j.get("reason") or j.get("events") or j.get("diagnostics")]
    assert len(speaks) == 1, [j["job_id"] for j in speaks]
    assert speaks[0]["job_id"] == "SPY_LAST_CHANCE_PRE_NKD"
    assert all(j["status"] == "completed" for j in jobs), (
        "nếu có thẻ trạng thái lạ thì phép kiểm này không còn chứng minh được điều nó "
        "muốn chứng minh — rằng dấu theo trạng thái KHÔNG đủ")
