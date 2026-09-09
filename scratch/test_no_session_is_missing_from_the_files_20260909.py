"""Ngày CÓ bar nhưng THIẾU phiên. TỆP MỚI.

Lỗi đã xảy ra
-------------
Mọi phiên đáo hạn quý từ 2017-03-17 tới 2024-09-20 — 31 ngày, cả bốn công cụ Mỹ — mất **trọn
cửa sổ RTH** trong chính các tệp mà backtest và đường chạy thật cùng đọc. Bar chạy tới 09:29
rồi dừng, nối lại vào 18:00 Chủ nhật: hợp đồng quý đáo hạn lúc 09:30 và chuỗi liên tục bám
hợp đồng cũ tới tick cuối, không bắt sang kỳ hạn mới cho tới phiên sau.

Cả ba sleeve Mỹ đều quyết định trong RTH, nên trong 31 ngày ấy **không sleeve nào có thể giao
dịch** — trong cả backtest lẫn khi chạy. Từ 2024-12-20 tệp đã đủ.

Vì sao không ai thấy suốt bằng ấy năm
--------------------------------------
Đợt rà soát lỗ hổng parquet trước kết luận 2017 → 2026-07-22 **sạch**. Nó không sai — nó hỏi
câu khác: *"ngày này có bar không"*. Ngày 2024-09-20 **có** 515 bar, nên nó đi qua. Toàn bộ
515 bar ấy nằm trước 09:30.

Đây đúng họ lỗi kho này đã ghi: **tên phép kiểm hứa rộng hơn thứ nó kiểm**.

Chủ dự án đã quyết KHÔNG lấy lại 31 phiên ấy. Yêu cầu là: hiện tại chạy đúng, và **lỗi cùng
loại không tái diễn**. Tệp này là nửa thứ hai.

Nó hỏi câu còn thiếu
--------------------
Với mọi ngày CME có phiên trong các tệp tuyến đang đọc: cửa sổ RTH có đủ bar không? Các ngày
hỏng đã biết được khai tên và có TRẦN, nên một ngày hỏng thứ 32 không lặng lẽ nhập bọn.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Các tệp đường chạy thật đọc. Lấy từ chính hàm dựng đường dẫn của runner, không chép tay.
def _paths() -> dict:
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from global_index.run_live_day_track1 import default_data_paths

        return default_data_paths()
    finally:
        logging.disable(logging.NOTSET)


RTH_LO, RTH_HI = dt.time(9, 30), dt.time(16, 0)

#: Ngày RTH TRỐNG HOÀN TOÀN đã biết, theo công cụ. Trần, không phải danh sách gợi ý.
#:
#: Tất cả đều là thứ Sáu thứ ba của tháng 3/6/9/12 trong 2017-03 → 2024-09. Không lấy lại —
#: quyết định của chủ dự án — nên chúng ở đây để phép kiểm không kêu mỗi lần chạy, và để một
#: ngày thứ 32 thì kêu.
#: Con số này là số ĐÃ LỌC theo lịch NYSE, không phải số ngày không có RTH. MYM có 550 ngày
#: không có RTH; 519 là cuối tuần và phiên đêm, 20 là ngày lễ thật (Tết dương, Giáng sinh,
#: quốc tang 05/12/2018), còn 31 là ngày lẽ ra có phiên. Bản đầu của tệp này khai 32 vì lấy
#: từ một lượt quét chưa lọc — sửa xuống 31 sau khi đọc ra ngày bị loại là ngày nào.
KNOWN_EMPTY_RTH: dict = {"MES": 29, "MNQ": 30, "M2K": 29, "MYM": 31}

#: Không ngày trống nào được phép nằm sau mốc này. Từ đây bộ nạp IBKR tiếp quản và gọi đích
#: danh hợp đồng, nên chuyện "hợp đồng cũ hết hạn mà chưa ai bảo dùng cái nào" không còn.
CLEAN_FROM = dt.date(2024, 12, 1)


def _empty_rth_days(inst: str, path: str) -> list:
    """Những ngày LẼ RA CÓ PHIÊN mà không một bar RTH nào.

    Mẫu số là ngày NYSE mở, không phải mọi ngày có bar: hợp đồng tương lai chạy đêm Chủ nhật
    và xuyên đêm ngày thường, nên hàng trăm ngày có bar mà không có RTH một cách hoàn toàn
    bình thường. Bản đầu của phép kiểm này đếm cả chúng và báo 548 thay vì 29 — một con số to
    và vô nghĩa.
    """
    import logging
    import warnings

    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    try:
        from global_index.track1_live_source import frozen_frame
        from raits.live.trading_calendar import is_trading_day

        idx = frozen_frame(inst, str(REPO / path)).index
    finally:
        logging.disable(logging.NOTSET)

    rth = idx[(idx.time >= RTH_LO) & (idx.time <= RTH_HI)]
    per = pd.Series(1, index=rth).groupby(rth.normalize()).sum()
    have_any = set(idx.normalize().unique())
    out = []
    for day in sorted(have_any):
        d = day.date()
        if not is_trading_day(d):
            continue
        if int(per.get(day, 0)) == 0:
            out.append(d)
    return out


US = ["MES", "MNQ", "M2K", "MYM"]


@pytest.mark.parametrize("inst", US)
def test_no_day_has_bars_but_no_session(inst):
    """Câu đợt rà soát trước không hỏi.

    Một ngày có bar cả ngày mà KHÔNG có bar nào trong 09:30-16:00 là ngày mà mọi sleeve Mỹ
    không thể nhìn — và nó không giống một ngày nghỉ, vì ngày nghỉ thì không có bar nào cả.
    """
    empty = _empty_rth_days(inst, _paths()[inst])
    assert len(empty) == KNOWN_EMPTY_RTH[inst], (
        f"{inst}: {len(empty)} ngày lẽ ra có phiên mà không có bar RTH nào, đã khai "
        f"{KNOWN_EMPTY_RTH[inst]}. Ngày sau mốc sạch: {[d for d in empty if d >= CLEAN_FROM]}")


@pytest.mark.parametrize("inst", US)
def test_nothing_is_missing_after_the_appender_took_over(inst):
    """Đây mới là phép kiểm canh TƯƠNG LAI. Danh sách trên chỉ đóng băng quá khứ."""
    bad = [d for d in _empty_rth_days(inst, _paths()[inst]) if d >= CLEAN_FROM]
    assert not bad, f"{inst}: phiên biến mất sau {CLEAN_FROM}: {bad}"


@pytest.mark.parametrize("inst", US)
def test_every_known_empty_day_is_a_quarterly_expiry(inst):
    """Nếu một ngày trống KHÔNG phải đáo hạn quý thì nó là chuyện khác, và cần đọc lại."""
    from global_index.track1_session_note import is_quarterly_expiry

    empty = _empty_rth_days(inst, _paths()[inst])
    assert empty, f"{inst}: không có ngày trống nào — con số đã khai sai"
    odd = [d for d in empty if not is_quarterly_expiry(d)]
    assert not odd, f"{inst}: ngày trống không phải đáo hạn quý: {odd}"


def test_the_ceiling_is_a_ceiling():
    """Tổng đã khai. Một ngày thứ 32 xuất hiện thì bài trên đỏ; bài này bắt ai đó sửa con số
    mà không đọc lại."""
    assert sum(KNOWN_EMPTY_RTH.values()) == 119, KNOWN_EMPTY_RTH
    assert set(KNOWN_EMPTY_RTH) == set(US)


def test_the_files_checked_are_the_files_the_route_reads():
    """Kiểm một tệp khác với tệp tuyến đọc là một phép kiểm xanh về chuyện không ai quan tâm."""
    p = _paths()
    for inst in US:
        assert inst in p and (REPO / p[inst]).is_file(), (inst, p.get(inst))
    assert "MNKD" in p, "NKD dùng tệp riêng và đồng hồ Tokyo — không nằm trong phép kiểm này"
