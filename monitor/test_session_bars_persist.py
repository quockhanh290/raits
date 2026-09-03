"""Giữ lại bar mà slot đã quyết định trên đó — và chứng minh việc giữ ấy không tốn gì.

Ba câu hỏi, theo đúng thứ tự rủi ro:

    ghi ra có đọc lại được không
    ghi hỏng thì có ném lỗi lên đường slot không
    ghi hỏng thì dòng bằng chứng phía sau nó có còn được ghi không

Câu thứ ba mới là câu đắt. Lệnh ghi bar nằm TRƯỚC `obs.record` trong cùng một hàm, nên một
exception ở đó sẽ nuốt luôn dòng data-observation — thứ mà audit đếm để biết slot có thật sự
nhìn vào dữ liệu hay không. Mất bức tranh là một cái giá; mất bằng chứng là cái giá khác hẳn.
"""
from __future__ import annotations

import datetime as _dt

import pytest

pd = pytest.importorskip("pandas")

from global_index import track1_data_observation as obs  # noqa: E402


DAY = "2026-09-02"
INST = "MNKD"


def _frame(n: int = 6):
    idx = pd.date_range("2026-09-02 01:10", periods=n, freq="5min")
    return pd.DataFrame(
        {"open": [66800.0 + i for i in range(n)],
         "high": [66820.0 + i for i in range(n)],
         "low": [66780.0 + i for i in range(n)],
         "close": [66810.0 + i for i in range(n)],
         "volume": [100 + i for i in range(n)]},
        index=idx)


class _Joined:
    """Đủ để `instrument_row` và `record_bars` làm việc, không hơn."""

    def __init__(self, frame):
        self.frame = frame
        self.inst = INST

    def as_dict(self):
        return {"inst": INST, "provider": "ibkr", "provider_rows": len(self.frame),
                "code": "ok", "live_rows_offered": len(self.frame)}


def test_the_bars_a_slot_decided_on_can_be_read_back(tmp_path):
    frame = _frame()
    out = obs.record_bars(frame, root=tmp_path, day=DAY, inst=INST)

    assert out is not None, "không ghi được gì"
    assert out == obs.bars_path_for(tmp_path, DAY, INST)
    back = pd.read_parquet(out)
    assert len(back) == len(frame)
    assert list(back.columns) == list(frame.columns)
    # Cùng giá trị, không chỉ cùng hình dạng — một file đúng số dòng mà sai số thì tệ hơn
    # một file không có.
    assert back["close"].tolist() == frame["close"].tolist()
    # Không để lại file tạm: người đọc poll 8 giây một lần không được thấy bản nửa vời.
    assert not list(out.parent.glob("*.tmp")), list(out.parent.glob("*.tmp"))


def test_nothing_is_written_for_an_empty_or_missing_frame(tmp_path):
    assert obs.record_bars(None, root=tmp_path, day=DAY, inst=INST) is None
    assert obs.record_bars(_frame(0), root=tmp_path, day=DAY, inst=INST) is None
    assert obs.record_bars(_frame(), root=tmp_path, day=DAY, inst="") is None
    assert not obs.bars_path_for(tmp_path, DAY, INST).exists()


def test_a_write_that_fails_returns_none_instead_of_raising(tmp_path):
    class Exploding:
        def __len__(self):
            return 3

        def to_parquet(self, *a, **k):
            raise OSError("đĩa đầy")

    assert obs.record_bars(Exploding(), root=tmp_path, day=DAY, inst=INST) is None


def test_the_slot_still_records_that_it_looked_at_data_when_the_bar_write_fails(
        tmp_path, monkeypatch):
    """Cổng của bản sửa này.

    `record_bars` được gọi ngay trước `obs.record` trong `_write_data_observation`. Nếu nó
    ném lỗi, hàm thoát sớm và dòng data-observation không bao giờ được ghi — audit sẽ đọc
    thành "slot này không nhìn vào dữ liệu", một phát biểu sai về đường giao dịch.
    """
    from global_index import run_live_day_track1 as rl

    def boom(*a, **k):
        raise RuntimeError("ghi bar hỏng")

    monkeypatch.setattr(obs, "record_bars", boom)

    rl._write_data_observation(
        sleeve="global_nkd", day=DAY, slot_id="TRACK1_NKD_0110",
        joined={INST: _Joined(_frame())}, refusal=None, decided=True,
        reason="decided", candidates=0, data_paths={INST: ""}, root=str(tmp_path))

    rows, malformed = obs.read(root=tmp_path, day=DAY)
    assert not malformed, malformed
    # Chốt trước khi duyệt: danh sách rỗng thì mọi assert dưới đây pass mà không kiểm gì.
    assert len(rows) == 1, f"dòng bằng chứng đã mất khi lệnh ghi bar hỏng: {rows}"
    assert rows[0].get("slot_id") == "TRACK1_NKD_0110"
    assert (rows[0].get("instruments") or []), "dòng ghi ra nhưng không mang instrument nào"


def test_the_file_is_written_on_the_same_clock_as_the_daily_store(tmp_path):
    """Đo được 2026-09-03: hai nguồn lệch nhau đúng 9 tiếng và không mốc nào khớp.

    Quét mọi độ lệch giờ rồi khớp theo giá: 100% của 1.546 mốc trùng khít ở đúng -9,0 giờ,
    dưới 2% ở mọi độ lệch khác. Tokyo là UTC+9, nên index của kho ngày là UTC không múi giờ
    còn khung của slot mang Asia/Tokyo. Bên đọc quy chuẩn một cái về đồng hồ của rổ và để yên
    cái kia, nên hai nguồn bị cắt lệch nhau 9 tiếng — và trang sẽ vẽ cửa sổ của nguồn này lên
    dữ liệu của nguồn kia.

    Chuẩn hoá ở CHỖ GHI chứ không ở chỗ đọc: một đáp án trên đĩa, thay vì một quy tắc mà mọi
    người đọc phải nhớ.
    """
    idx = pd.date_range("2026-09-02 09:00", periods=12, freq="5min", tz="Asia/Tokyo")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
                         index=idx)
    out = obs.record_bars(frame, root=tmp_path, day="2026-09-02", inst=INST)
    assert out is not None
    back = pd.read_parquet(out)

    got = pd.DatetimeIndex(back.index)
    assert got.tz is None, f"vẫn còn múi giờ: {got.tz}"
    # Cùng khoảnh khắc, viết theo UTC — 09:00 Tokyo là 00:00 UTC.
    assert str(got.min()) == "2026-09-02 00:00:00", str(got.min())
    assert (got == idx.tz_convert("UTC").tz_localize(None)).all()


def test_only_the_session_is_kept_not_the_history_behind_it(tmp_path):
    """Đo được 2026-09-03: một lần ghi ra 2.052.686 dòng, 28 MB, trải từ 2018-01-02.

    Khung mà slot cầm là LỊCH SỬ ĐÃ ĐÔNG cộng nửa live nối vào — không phải khung của phiên.
    Ghi nguyên nó, mỗi slot, mỗi công cụ, là khoảng 1,8 GB đĩa mỗi cửa sổ phiên để giữ lại ba
    tiếng bar. Phép kiểm này chặn đúng chỗ đó.
    """
    n = 60 * 24 * 400                       # hơn một năm bar phút
    idx = pd.date_range("2025-06-01", periods=n, freq="1min", tz="Asia/Tokyo")
    frame = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1},
                         index=idx)
    day = "2026-01-15"
    assert day in {str(d) for d in pd.Index(idx.date).astype(str)}, "ngày thử không nằm trong khung"

    out = obs.record_bars(frame, root=tmp_path, day=day, inst=INST)
    assert out is not None
    back = pd.read_parquet(out)

    kept = sorted({str(d) for d in pd.DatetimeIndex(back.index).date})
    assert kept == ["2026-01-14", "2026-01-15", "2026-01-16"], kept
    # Và số dòng phải giảm hẳn, không chỉ "đúng ngày": một bản cắt đúng nhãn mà vẫn mang cả
    # năm thì phép kiểm trên vẫn xanh.
    assert len(back) < len(frame) / 100, f"{len(back)} trên {len(frame)} — gần như không cắt"


def test_the_same_session_written_twice_leaves_one_file_carrying_the_later_one(tmp_path):
    """Hai mươi hai slot không được để lại hai mươi hai bản sao.

    Mỗi lần gọi mang CÙNG một phiên với nhiều dữ liệu hơn, nên lần ghi cuối là bản đầy đủ.
    """
    obs.record_bars(_frame(6), root=tmp_path, day=DAY, inst=INST)
    obs.record_bars(_frame(9), root=tmp_path, day=DAY, inst=INST)

    files = sorted(obs.bars_path_for(tmp_path, DAY, INST).parent.iterdir())
    assert len(files) == 1, files
    assert len(pd.read_parquet(files[0])) == 9


def test_the_path_is_dated_and_named_for_the_instrument(tmp_path):
    p = obs.bars_path_for(tmp_path, DAY, "mnkd")
    assert p.name == "MNKD_20260902.parquet", p.name
    # Ngày khác thì file khác — nếu không, phiên hôm nay sẽ đè lên phiên hôm qua và câu hỏi
    # "ngày nào hiện nến ngày đó" quay lại đúng chỗ cũ.
    other = obs.bars_path_for(tmp_path, "2026-09-01", "mnkd")
    assert other != p
    yesterday = (_dt.date.fromisoformat(DAY) - _dt.timedelta(days=1)).isoformat()
    assert obs.bars_path_for(tmp_path, yesterday, INST).name == "MNKD_20260901.parquet"


# ── và phía đọc: bảng điều khiển không bao giờ được trả về ngày khác ────────────────────

def _spec():
    from monitor.backend import track1_market_view as mvb
    return mvb, mvb.SLEEVES["global_nkd"]


def test_a_day_with_no_bars_returns_none_instead_of_another_session():
    """Đây là bản sửa mà chủ dự án yêu cầu: ngày nào thì hiện nến ngày đó.

    Trước đây, khi kho không có ngày được hỏi, hàm này lùi về phiên gần nhất kho CÓ và trả
    kèm ngày đó. Trong một cửa sổ chạy đêm, điều đó có nghĩa là nến hôm qua được vẽ dưới các
    slot hôm nay — đúng cái bất đối xứng mà nhánh detector đã tự giải quyết bằng câu "old
    numbers under a card labelled with today's session are worse than none".
    """
    mvb, spec = _spec()
    # Một ngày không phiên nào có thể tồn tại, nên không phụ thuộc dữ liệu trên máy.
    bars, session_day, note = mvb._sliced(spec["instrument"], "2099-01-01", spec, ".")
    assert bars == []
    assert session_day is None, f"vẫn thay bằng phiên khác: {session_day}"
    assert "2099-01-01" in note, note


def test_the_day_that_comes_back_is_always_the_day_that_was_asked_for():
    mvb, spec = _spec()
    asked = ["2026-09-01", "2026-08-25", "2026-07-04", "2099-01-01"]
    seen = {}
    for day in asked:
        bars, session_day, _ = mvb._sliced(spec["instrument"], day, spec, ".")
        seen[day] = (len(bars), session_day)
        assert session_day in (None, day), f"hỏi {day} nhưng trả {session_day}"
    # Chốt: nếu kho trên máy này rỗng thì mọi dòng trên đều (0, None) và phép kiểm không
    # phân biệt được "không thay ngày" với "không đọc được gì".
    assert any(n for n, _ in seen.values()), f"không ngày nào có bar — phép kiểm rỗng: {seen}"


def test_the_frame_the_slot_wrote_is_preferred_over_the_daily_store(tmp_path):
    """Trong lúc phiên đang chạy, chỉ khung của slot mới có bar hôm nay.

    Kho ngày được append lúc 13:45 ET, nên với rổ Nhật nó đi sau cửa sổ mười một tiếng. Nếu
    thứ tự này đảo lại thì bản sửa không có tác dụng trong đúng khoảng thời gian nó sinh ra
    để phục vụ.
    """
    mvb, spec = _spec()
    day = "2026-09-01"
    from_store, session_day, _ = mvb._sliced(spec["instrument"], day, spec, ".")
    if not from_store:
        pytest.skip(f"kho trên máy này không có {day}; phép so hai nguồn cần cả hai")

    # Cùng ngày, cùng khung giờ, nhưng giá khác hẳn — nếu kết quả mang giá này thì khung của
    # slot đã thắng.
    marker = 12345.0
    # Nhãn trong payload là ET. Nói rõ múi giờ ra thay vì đưa vào một index naive: chỗ ghi
    # quy mọi thứ về UTC, chỗ đọc quy về ET, nên một fixture "naive" là một fixture không nói
    # nó đang ở đồng hồ nào — và nó sẽ lệch đúng bằng độ chênh múi giờ.
    idx = pd.to_datetime([b["time"] for b in from_store]).tz_localize("America/New_York")
    frame = pd.DataFrame({"open": marker, "high": marker, "low": marker,
                          "close": marker, "volume": 1}, index=idx)
    assert obs.record_bars(frame, root=tmp_path, day=day, inst=spec["instrument"])

    mvb._bar_cache.clear()          # cache khoá theo mtime của nguồn; nguồn mới thì khoá mới
    bars, session_day, _ = mvb._sliced(spec["instrument"], day, spec, tmp_path)
    assert bars, "không đọc được khung của slot"
    assert session_day == day
    assert bars[0]["close"] == marker, (
        f"kho ngày thắng khung của slot: {bars[0]}")
    mvb._bar_cache.clear()


def test_the_hours_on_the_chart_are_the_hours_the_window_is_declared_in(tmp_path):
    """Đo được 2026-09-03 lúc 11:37 ET: rổ Stress trả nến chạy 09:35 tới 12:40 — hơn một
    tiếng ở TƯƠNG LAI — trong khi sổ ghi của chính slot đặt bar mới nhất ở 11:35 ET. Rổ
    Swing, cửa sổ còn chưa mở, hiện mười hai nến của nó.

    Cả hai kho giữ index theo UTC; mọi giờ hàm này cắt theo đều là ET (`context_start_et`,
    `window_start_et`). Cắt nhãn UTC bằng con số ET thì lệch đúng bằng độ chênh múi giờ, và
    trang in ra giờ sai dưới đúng cái tên đúng.

    `spec["clock"]` KHÔNG phải đáp án: đó là đồng hồ giao dịch của rổ — Tokyo với rổ Nhật —
    còn giờ context thì không nằm trên nó (00:10-03:05 Tokyo không chứa nổi một cửa sổ chạy
    14:10-15:55 Tokyo).
    """
    from monitor.backend import track1_market_view as mvb
    spec = mvb.SLEEVES["roska4_stress"]
    day = "2026-09-03"

    # 13:35–14:00 UTC là 09:35–10:00 ở New York, tức nằm trong context 09:35–12:40.
    idx = pd.date_range(f"{day} 13:35", periods=6, freq="5min", tz="UTC")
    frame = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
                          "volume": 1}, index=idx)
    assert obs.record_bars(frame, root=tmp_path, day=day, inst=spec["instrument"])

    mvb._bar_cache.clear()
    bars, session_day, _ = mvb._sliced(spec["instrument"], day, spec, tmp_path)
    mvb._bar_cache.clear()

    assert bars, "không đọc được nến nào — phép kiểm này sẽ rỗng"
    assert session_day == day
    got = [b["time"][11:] for b in bars]
    assert got[0] == "09:35", f"nhãn đầu {got[0]} — chart đang ghi giờ UTC dưới tên ET: {got}"
    assert got[-1] == "10:00", got
