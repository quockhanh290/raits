"""Chuỗi SPY chỉ được ghi giá đóng cửa ĐÃ CHỐT — không bao giờ giá giữa phiên. TỆP MỚI.

Chuyện đã xảy ra ngày 14/09/2026
--------------------------------
Lượt pre-flight 13:45 ET gọi `update_spy_csv`, và nó lấy dữ liệu "tới hôm nay". Hôm đó Polygon
trả về một thanh ngày ĐANG DỞ DANG cho 14/09, và mã ghi luôn:

    ghi lúc     13:46:50 ET          hai tiếng mười bốn phút trước giờ đóng cửa
    giá trị     762.8137             bốn chữ số thập phân — mọi giá đóng cửa khác chỉ có hai
    giá thật    760.88               Polygon trả lại sau giờ đóng cửa

Rồi cả thang buổi tối bị vô hiệu hoá bởi chính dòng ấy: nấc 18:20 thấy "14/09 đã có" nên không
lấy gì, xác minh không có gì để so, và báo HỎNG; hai nấc sau được lệnh bỏ qua khi đã đủ ngày nên
báo OK. Giá đóng cửa thật không bao giờ được lấy về. Nhãn chế độ của 14/09 đã tính trên giá 13:46.

Lần này nhãn vẫn ra Calm với cả hai giá, nên chưa lệch quyết định nào. Đó là may, không phải thiết
kế: một ngày giằng co thì 1,93 điểm có thể lật nhãn.

Hợp đồng đã có sẵn, chỉ là mã không tuân theo
----------------------------------------------
`test_track1_stage5q5_freshness_boundary`: *"lượt 13:45 không được kỳ vọng mang giá đóng cửa hôm
nay"*. Thiết kế đã nói rõ. Mã ghi dữ liệu thì không có một dòng nào chặn điều đó.

Và cùng lỗi ba-đồng-hồ: mã dùng `date.today()` — ngày của MÁY (Calgary), không phải ngày ET.

Điều tệp này canh
-----------------
    1. mốc "đã chốt" tính theo giờ ET, không theo đồng hồ máy
    2. trước mốc ấy, dòng của hôm nay KHÔNG được ghi — kể cả khi nguồn trả nó về
    3. sau mốc ấy, giá thật được ghi
    4. một dòng dở dang có sẵn từ trước tự được thay bằng giá thật ở lượt sau
    5. lượt buổi sáng không gọi nguồn khi hôm qua đã có
    6. lọc xong mà không còn gì thì KHÔNG được xoá cửa sổ 30 ngày
"""
from __future__ import annotations

import ast
import datetime as dt
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import global_index.update_spy_csv as S          # noqa: E402

assert Path(S.__file__).resolve().is_relative_to(REPO), S.__file__

ET = ZoneInfo("America/New_York")
CALGARY = ZoneInfo("America/Edmonton")
FIX = REPO / "scratch" / "fixtures" / "spy_tail_20260914.csv"
PARTIAL_1346 = 762.8137     # thứ đã được ghi lúc 13:46:50 ET ngày 14/09 — đo được
FINAL_1409 = 760.88         # giá đóng cửa Polygon trả lại sau giờ đóng cửa — đo được


def at(y, m, d, hh, mm, tz=ET):
    return dt.datetime(y, m, d, hh, mm, tzinfo=tz)


# ── 1. mốc "đã chốt" tính theo giờ ET ──────────────────────────────────────

@pytest.mark.parametrize("now,want", [
    (at(2026, 9, 14, 13, 46), dt.date(2026, 9, 13)),     # đúng lúc sự cố
    (at(2026, 9, 14, 17, 59), dt.date(2026, 9, 13)),     # sát trước mốc
    (at(2026, 9, 14, 18, 0), dt.date(2026, 9, 14)),      # đúng mốc
    (at(2026, 9, 14, 18, 20), dt.date(2026, 9, 14)),     # nấc đầu của thang buổi tối
    (at(2026, 9, 15, 0, 45), dt.date(2026, 9, 14)),      # lượt cuối trước NKD
])
def test_the_last_final_close_is_measured_on_the_et_clock(now, want):
    assert S.final_close_through(now) == want


def test_the_machine_clock_does_not_decide():
    """22:45 ở Calgary ngày 14/09 là 00:45 ET ngày 15/09. `date.today()` trên máy nói 14 — và
    trả lời sai câu hỏi, vì câu hỏi là ngày giao dịch nào đã chốt."""
    assert S.final_close_through(at(2026, 9, 14, 22, 45, CALGARY)) == dt.date(2026, 9, 14)
    assert S.final_close_through(at(2026, 9, 14, 11, 46, CALGARY)) == dt.date(2026, 9, 13)


def test_a_naive_clock_is_refused_not_guessed():
    with pytest.raises(ValueError):
        S.final_close_through(dt.datetime(2026, 9, 14, 13, 46))


def test_the_updater_no_longer_asks_the_machine_for_today():
    """Ghim bằng cây cú pháp, không bằng tìm chuỗi: bản đầu của các phép kiểm kiểu này trong
    kho từng đỏ vì một câu trong chú thích."""
    tree = ast.parse(Path(S.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "update_spy_csv")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "today"]
    assert not calls, "update_spy_csv vẫn gọi .today()"


# ── thế giới nhỏ: tệp thật, nguồn giả đóng vai Polygon ─────────────────────

def _world(tmp_path, *, last="2026-09-11", partial_row=False):
    """Tệp = 70 dòng SPY thật, cắt tới `last`. Tuỳ chọn thêm dòng dở dang của 14/09."""
    df = pd.read_csv(FIX)
    df = df[df["date"] <= last].copy()
    if partial_row:
        df = pd.concat([df, pd.DataFrame([{"date": "2026-09-14", "close": PARTIAL_1346}])])
    p = tmp_path / "spy_daily_live.csv"
    df.to_csv(p, index=False)
    return p


class Feed:
    """Đóng vai Polygon. `honours_to=False` là nguồn trả về cả thanh dở dang của hôm nay dù không
    được hỏi — để chứng minh chốt nằm ở phía ta, không phụ thuộc vào việc nguồn cư xử tốt."""

    def __init__(self, *, today_value, honours_to=True):
        self.today_value = today_value
        self.honours_to = honours_to
        self.calls = []

    def __call__(self, api_key, from_date, to_date):
        self.calls.append((from_date, to_date))
        real = pd.read_csv(FIX)
        real = real[real["date"] < "2026-09-14"]
        rows = real[(real["date"] >= str(from_date))].copy()
        if self.today_value is not None:
            rows = pd.concat([rows, pd.DataFrame([{"date": "2026-09-14",
                                                   "close": self.today_value}])])
        if self.honours_to:
            rows = rows[rows["date"] <= str(to_date)]
        return rows.reset_index(drop=True)


def _run(monkeypatch, tmp_path, csv, feed, now):
    from global_index import regime_verify as _rv

    monkeypatch.setattr(S, "fetch_spy_close", feed)
    # Phép xác minh dựng lại cả mô hình HMM — là một hành vi khác, có phép kiểm riêng. Ở đây chỉ
    # hỏi DÒNG NÀO được ghi, nên thay nó bằng một câu trả lời trung tính.
    monkeypatch.setattr(S, "verify_historical_prices", lambda *a, **k: 0)
    monkeypatch.setattr(S, "verify_regime_labels", lambda *a, **k: _rv.VerifyResult(
        status=_rv.UNKNOWN, code=_rv.NO_SNAPSHOT, detail="stubbed in test",
        checked_at=_rv._now(), inputs={}))
    out = S.update_spy_csv(csv, "k", snapshot_dir=tmp_path / "snap",
                           verify_root=str(tmp_path / "verify"), now=now)
    return out, pd.read_csv(csv).set_index("date")["close"]


# ── 2. trước mốc chốt, hôm nay KHÔNG được ghi ──────────────────────────────

@pytest.mark.parametrize("honours_to", [True, False])
def test_the_1346_partial_is_never_written(monkeypatch, tmp_path, honours_to):
    """Đúng tình huống 14/09, trên giá thật. Kể cả nguồn không tôn trọng `to` và cứ trả thanh dở
    dang về, dòng ấy vẫn không được vào tệp."""
    csv = _world(tmp_path)
    feed = Feed(today_value=PARTIAL_1346, honours_to=honours_to)
    _out, s = _run(monkeypatch, tmp_path, csv, feed, at(2026, 9, 14, 13, 46))
    assert "2026-09-14" not in s.index, s.tail(3)
    assert s.index[-1] == "2026-09-11"


def test_the_morning_run_asks_only_for_finished_days(monkeypatch, tmp_path):
    csv = _world(tmp_path)
    feed = Feed(today_value=PARTIAL_1346)
    _run(monkeypatch, tmp_path, csv, feed, at(2026, 9, 14, 13, 46))
    assert feed.calls and all(to <= dt.date(2026, 9, 13) for _f, to in feed.calls), feed.calls


# ── 3. sau mốc chốt, giá thật được ghi ─────────────────────────────────────

def test_the_evening_run_writes_the_real_close(monkeypatch, tmp_path):
    csv = _world(tmp_path)
    _out, s = _run(monkeypatch, tmp_path, csv, Feed(today_value=FINAL_1409),
                   at(2026, 9, 14, 18, 20))
    assert s["2026-09-14"] == pytest.approx(FINAL_1409)


def test_the_evening_run_is_not_defeated_by_the_morning_one(monkeypatch, tmp_path):
    """Chuỗi sự kiện đầy đủ của 14/09, với bản sửa: sáng không ghi gì cho hôm nay, nên tối nấc
    18:20 thấy thiếu 14/09 và lấy về đúng giá — thay vì báo "đã đủ" rồi bỏ qua."""
    csv = _world(tmp_path)
    _run(monkeypatch, tmp_path, csv, Feed(today_value=PARTIAL_1346), at(2026, 9, 14, 13, 46))
    _out, s = _run(monkeypatch, tmp_path, csv, Feed(today_value=FINAL_1409),
                   at(2026, 9, 14, 18, 20))
    assert s["2026-09-14"] == pytest.approx(FINAL_1409)


# ── 4. dòng dở dang có sẵn thì tự lành ─────────────────────────────────────

def test_a_partial_row_already_on_disk_is_replaced_by_the_next_fetch(monkeypatch, tmp_path):
    """Tệp đang giữ dòng dở dang (như trước khi sửa). Lượt tối hôm sau lấy lại 30 ngày và THAY
    nó bằng giá thật — không cần ai nhớ tới."""
    csv = _world(tmp_path, partial_row=True)
    _out, s = _run(monkeypatch, tmp_path, csv, Feed(today_value=FINAL_1409),
                   at(2026, 9, 15, 18, 20))
    assert s["2026-09-14"] == pytest.approx(FINAL_1409), s.tail(2)


# ── 5. buổi sáng không gọi nguồn khi hôm qua đã có ─────────────────────────

def test_the_morning_after_a_good_evening_fetches_nothing(monkeypatch, tmp_path):
    csv = _world(tmp_path, last="2026-09-14")
    before = csv.read_bytes()
    feed = Feed(today_value=None)
    out, _s = _run(monkeypatch, tmp_path, csv, feed, at(2026, 9, 15, 13, 46))
    assert feed.calls == [], feed.calls
    assert csv.read_bytes() == before
    assert out.rows_added == 0


# ── 6. lọc xong mà rỗng thì không được xoá cửa sổ ──────────────────────────

def test_an_empty_result_after_filtering_does_not_erase_the_window(monkeypatch, tmp_path):
    """Đoạn ghép giữ các dòng CŨ HƠN đầu cửa sổ rồi nối phần vừa lấy. Nếu phần vừa lấy rỗng sau
    khi lọc, đoạn ghép sẽ bỏ nguyên 30 ngày gần nhất — và vẫn báo thành công."""
    csv = _world(tmp_path)
    before = pd.read_csv(csv)

    def only_today(api_key, from_date, to_date):
        return pd.DataFrame([{"date": "2026-09-14", "close": PARTIAL_1346}])

    _out, s = _run(monkeypatch, tmp_path, csv, only_today, at(2026, 9, 14, 13, 46))
    assert len(s) == len(before), (len(s), len(before))
    assert s.index[-1] == "2026-09-11"


def test_nothing_else_in_the_file_moves(monkeypatch, tmp_path):
    csv = _world(tmp_path)
    before = pd.read_csv(csv).set_index("date")["close"]
    _out, s = _run(monkeypatch, tmp_path, csv, Feed(today_value=FINAL_1409),
                   at(2026, 9, 14, 18, 20))
    common = before.index.intersection(s.index)
    assert (before[common] - s[common]).abs().max() < 1e-9
    assert set(s.index) - set(before.index) == {"2026-09-14"}


def test_no_evidence_is_written_outside_the_temp_dir(monkeypatch, tmp_path):
    """Phép kiểm này ghi vào `verify_root` và `snapshot_dir` của nó, không bao giờ vào kho."""
    csv = _world(tmp_path)
    _run(monkeypatch, tmp_path, csv, Feed(today_value=FINAL_1409), at(2026, 9, 14, 18, 20))
    assert (tmp_path / "snap").exists()
