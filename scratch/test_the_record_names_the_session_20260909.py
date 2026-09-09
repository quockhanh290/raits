"""Ngày 18/09 phải phân biệt được trong hồ sơ. TỆP MỚI.

Quyết định của chủ dự án về phiên đáo hạn quý sắp tới là **"chạy bình thường và ghi lại"**.

Nửa "chạy bình thường" tự nó xảy ra — không phải làm gì cả. Nửa "ghi lại" thì không: trước
tệp này, không chỗ nào trong hồ sơ hay trên bảng điều khiển nói hôm đó là ngày gì. Người mở
lại bản ghi ngày 18/09 sẽ thấy một ngày bình thường, và phải **tự nhớ** rằng nó không bình
thường. Đó chính là không ghi lại.

Vì sao ngày ấy đáng ghi
------------------------
Đó là phiên đáo hạn quý **đầu tiên** tuyến này chạy với dữ liệu đủ. Mọi phiên đáo hạn quý từ
2017-03-17 tới 2024-09-20 đều mất trọn cửa sổ RTH trong chính các tệp mà backtest và đường
chạy thật cùng đọc — 31 phiên, cả bốn công cụ Mỹ. Nên cửa sổ mà mọi ngưỡng được đóng băng
trên đó **không chứa một phiên nào thuộc loại này**.

Điều tệp này canh
-----------------
    1. ngày đó được gọi tên, và tên ấy SUY RA từ lịch chứ không viết cứng
    2. ngày thường cũng nói ra là ngày thường — một hàng trống và một hàng chưa ai viết
       trông giống hệt nhau, và chỉ một trong hai nghĩa là "không có gì phải biết"
    3. lịch không trả lời được thì im lặng, không biến ngày thường thành ngày báo động
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import global_index.track1_session_note as SN     # noqa: E402

JS = REPO / "global_index" / "dash" / "realtime" / "realtime.js"


# ── suy ra, không viết cứng ──────────────────────────────────────────────────

def test_the_coming_expiry_is_named():
    assert SN.is_quarterly_expiry(dt.date(2026, 9, 18))
    assert SN.QUARTERLY_EXPIRY in SN.notes_for(dt.date(2026, 9, 18))


@pytest.mark.parametrize("y,m,d", [(2026, 3, 20), (2026, 6, 19), (2026, 12, 18),
                                   (2025, 9, 19), (2024, 12, 20), (2018, 12, 21)])
def test_the_third_friday_is_counted_not_looked_up(y, m, d):
    assert SN.third_friday(y, m) == dt.date(y, m, d)


def test_a_third_friday_outside_the_quarterly_months_is_not_an_expiry():
    assert not SN.is_quarterly_expiry(SN.third_friday(2026, 7))
    assert not SN.is_quarterly_expiry(SN.third_friday(2026, 10))


def test_an_ordinary_day_carries_no_note():
    assert SN.notes_for(dt.date(2026, 9, 9)) == []
    assert SN.line_for(dt.date(2026, 9, 9)) == ""


def test_no_function_decides_from_a_written_down_date():
    """Một danh sách ngày là một lời mô tả, và những lời như thế đã trôi khỏi thứ chúng mô tả
    năm lần trong kho này.

    Hỏi đúng câu, và bản đầu của phép kiểm này hỏi sai HAI lần: nó soi cả docstring — nơi ngày
    tháng là bằng chứng đo được, đúng chỗ chúng phải ở — và cả bảng `MEANING`, nơi ngày nằm
    trong một câu giải thích chứ không phải một luật. Thứ phải canh là **thân hàm**: không hàm
    nào được quyết định dựa trên một ngày viết sẵn.
    """
    import ast

    src = (REPO / "global_index" / "track1_session_note.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    assert len(fns) >= 4, "không tìm thấy hàm nào — phép kiểm sẽ xanh trên hư không"

    bad = []
    for fn in fns:
        body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                               and isinstance(fn.body[0].value, ast.Constant)
                               and isinstance(fn.body[0].value.value, str)) else fn.body
        for node in body:
            for c in ast.walk(node):
                if isinstance(c, ast.Constant) and isinstance(c.value, str):
                    import re
                    if re.search(r"\b20\d\d-\d\d-\d\d\b", c.value):
                        bad.append((fn.name, c.value[:40]))
    assert not bad, bad


# ── các loại ngày khác, và ca kép ────────────────────────────────────────────

def test_an_early_close_is_named():
    assert SN.EARLY_CLOSE in SN.notes_for(dt.date(2025, 11, 28))


def test_a_shut_exchange_is_named():
    assert SN.EXCHANGE_SHUT in SN.notes_for(dt.date(2025, 12, 25))


def test_an_equity_holiday_that_cme_trades_is_named():
    """Labor Day: chứng khoán Mỹ nghỉ, CME chạy nửa buổi. Sleeve nào chạy được là do vị trí
    cửa sổ, và người đọc hồ sơ cần biết điều đó."""
    assert SN.EQUITY_HOLIDAY in SN.notes_for(dt.date(2026, 9, 7))


def test_a_day_can_carry_two_notes():
    """19/06/2026 vừa là đáo hạn quý vừa là Juneteenth. Chọn một trong hai là mất một nửa
    sự thật."""
    got = SN.notes_for(dt.date(2026, 6, 19))
    assert SN.QUARTERLY_EXPIRY in got and SN.EQUITY_HOLIDAY in got, got


def test_every_note_explains_itself():
    for n in (SN.QUARTERLY_EXPIRY, SN.EARLY_CLOSE, SN.EXCHANGE_SHUT, SN.EQUITY_HOLIDAY):
        assert len(SN.MEANING[n].split()) >= 15, n


def test_the_next_expiry_is_reported_before_it_arrives():
    """Sau khi nó qua thì ai cũng biết. Giá trị nằm ở chỗ nói trước."""
    assert SN.next_quarterly_expiry(dt.date(2026, 9, 9)) == dt.date(2026, 9, 18)
    assert SN.next_quarterly_expiry(dt.date(2026, 9, 18)) == dt.date(2026, 12, 18)


def test_a_calendar_that_cannot_answer_stays_quiet(monkeypatch):
    """Im lặng, không đóng. Module này không quyết định gì, nên một lịch hỏng không được biến
    ngày thường thành ngày báo động — nhưng phần suy từ lịch ngày vẫn phải còn."""
    import builtins

    real = builtins.__import__

    def no_cal(name, *a, **k):
        if name == "raits.live.trading_calendar":
            raise ImportError("không có lịch")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_cal)
    assert SN.notes_for(dt.date(2026, 9, 18)) == [SN.QUARTERLY_EXPIRY]   # vẫn đếm được
    assert SN.notes_for(dt.date(2025, 12, 25)) == []                     # không đoán bừa


# ── nó phải tới được màn hình ────────────────────────────────────────────────

def test_the_reader_carries_it():
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from monitor.backend.track1_runtime_reader import read_track1_runtime

        n = read_track1_runtime(REPO).get("session_note") or {}
    finally:
        logging.disable(logging.NOTSET)
    assert n.get("present") is True, n
    assert "notes" in n and "next_quarterly_expiry" in n, n


def test_the_row_is_wired_into_the_panel():
    assert "t1Fact('Session', sessionNoteRow())" in JS.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="cần node")
@pytest.mark.parametrize("payload,want", [
    ({"present": True, "notes": [], "line": "",
      "next_quarterly_expiry": "2026-09-18", "days_until_next": 9}, "ordinary session"),
    ({"present": True, "notes": ["quarterly_expiry"], "line": "quarterly expiry — settles 09:30",
      "next_quarterly_expiry": "2026-12-18", "days_until_next": 91}, "quarterly expiry"),
    ({"present": False, "reading": "could not be determined"}, "could not be determined"),
])
def test_the_row_says_something_in_every_state(payload, want):
    """Kể cả ngày thường. Một hàng trống và một hàng chưa ai viết trông giống hệt nhau."""
    harness = r"""
const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');
const i=src.indexOf('function sessionNoteRow');let d=0,end=i;
for(let k=src.indexOf('{',i);k<src.length;k++){if(src[k]==='{')d++;if(src[k]==='}'){d--;if(!d){end=k+1;break;}}}
const esc=v=>String(v==null?'':v);let t1={session_note:JSON.parse(process.argv[2])};
eval(src.slice(i,end));process.stdout.write(sessionNoteRow());
"""
    r = subprocess.run(["node", "-e", harness, str(JS), json.dumps(payload, ensure_ascii=False)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr[:300]
    assert want in r.stdout, r.stdout
