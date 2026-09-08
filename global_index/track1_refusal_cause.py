"""global_index/track1_refusal_cause.py — vì sao một slot bị từ chối. TỆP MỚI.

Chỉ đọc. Không cổng nào ở đây, không quyết định nào bị đảo. Nó dịch một lời từ chối đã xảy
ra sang nguyên nhân gốc, và chỉ khi nguyên nhân ấy **đo được**.

Vấn đề nó sinh ra để giải
--------------------------
Ngày 2026-09-07, cả 23 slot của sleeve swing bị từ chối. Bản ghi nói:

    reason  = "gate_refused"
    detail  = "missing_session,stale"

Đúng, và không dùng được. Phải đọc bốn tệp mã, đo lại parquet và đổi múi giờ mới ra được câu
trả lời thật: **CME đóng cửa lúc 13:00 ET vào Labor Day, còn cửa sổ swing là 14:00–15:55**.
Cổng làm đúng việc; thị trường đóng thì không có bar, và từ chối là câu trả lời đúng.

Cùng một cặp mã ấy cũng xuất hiện khi job dữ liệu 13:45 không chạy, và khi nguồn bar hỏng.
Ba chuyện khác hẳn nhau về việc phải làm gì, một chuỗi mã.

Ba nguyên nhân, và một chỗ để nói "không biết"
-----------------------------------------------
    MARKET_CLOSED   cửa sổ của sleeve nằm ngoài giờ phiên. Không phải lỗi, không có ai
                    phải làm gì, và một ngày như thế không nói gì về sức khoẻ của hệ.
    DATA_NOT_YET    dữ liệu chưa tới nơi nhưng còn cơ hội tới. Slot sau có thể chạy được.
    SYSTEM_FAULT    phiên đang mở, dữ liệu đáng lẽ phải có, và nó không có. Cần người.
    UNKNOWN         không đo được. **Không gộp vào ba nhóm trên.**

Nhóm thứ tư là nhóm quan trọng nhất. Kho này đã trả giá cho việc gộp "không đo được" vào
"không có gì": một phép dò tiến trình trả về danh sách rỗng cho ba kiểu trục trặc khác nhau,
rỗng nghĩa là "không có bản sao nào đang chạy", và hai bộ lập lịch đã tranh nhau một client
id làm hỏng sáu slot vào lệnh. Ở đây, đoán bừa `MARKET_CLOSED` khi không có lịch sẽ tha bổng
một ngày hệ thật sự hỏng.

Cái này KHÔNG làm
-----------------
Nó **không tha bổng gì cả**. Nó không sửa verdict, không đổi điều kiện cổng, không làm một
ngày FAIL thành ngày sạch. Bộ chấm điểm đọc nó thì đó là quyết định riêng của bộ chấm, và
quyết định ấy phải được viết ra ở chỗ của nó. Ở đây chỉ có một phép dịch: mã máy -> nguyên
nhân, kèm bằng chứng dẫn tới nguyên nhân đó.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Optional

MARKET_CLOSED = "market_closed"
DATA_NOT_YET = "data_not_yet"
SYSTEM_FAULT = "system_fault"
UNKNOWN = "unknown"

CAUSES: tuple = (MARKET_CLOSED, DATA_NOT_YET, SYSTEM_FAULT, UNKNOWN)

#: Mã từ chối tự nó đã nói "chưa tới lúc". Không cần lịch để biết.
_TIMING_CODES: frozenset = frozenset({"too_early"})

#: Mã nói về hình dạng khung dữ liệu chứ không về sự vắng mặt của nó. Một khung sai múi giờ
#: hay có dấu thời gian trùng là chuyện của hệ, dù thị trường mở hay đóng — nên chúng được
#: xét TRƯỚC lịch, và lịch không cứu được chúng.
_SHAPE_CODES: frozenset = frozenset({
    "tz_mismatch", "duplicate_timestamps", "out_of_order", "not_a_frame", "unknown_sleeve",
})

#: Lời từ chối của tầng NỐI DỮ LIỆU, không phải của cổng độ tươi. Chúng nói rằng dữ liệu đã
#: về nhưng sai — hai nửa bất đồng giá, chuỗi hợp đồng đã roll, bar mang dấu thời gian sau
#: lúc lấy nó. Không có giờ phiên nào giải thích được những chuyện đó.
#:
#: Nhận ra bằng CỤM TỪ trong câu, vì tầng ấy viết câu chứ không phát mã. Nhận bằng chuỗi con
#: là thứ kho này đã bị cắn một lần — một dòng nhận diện job hỏi `"python" in detail` và biến
#: mỗi khung traceback thành một lần khởi chạy, vì đường dẫn trình thông dịch chứa chữ đó.
#: Nên các cụm ở đây được chọn để không xuất hiện trong bất kỳ câu nào khác của tầng cổng:
#: chúng là câu chữ của chính lỗi, không phải một từ thông dụng.
_JOIN_FAULT_PHRASES: tuple = (
    "disagree on",                          # hai nửa bất đồng giá ở phần chồng lấn
    "has rolled its continuous series",      # chuỗi hợp đồng đã roll, sổ chưa neo lại
    "cannot arrive from later than",         # bar mang dấu thời gian sau lúc lấy nó
    "no bar provider",                       # slot chạy mà không ai đưa nguồn bar cho nó
)


@dataclass(frozen=True)
class Cause:
    """Nguyên nhân, và bằng chứng dẫn tới nó.

    `evidence` không phải trang trí: một phân loại không nói được vì sao nó phân loại như
    thế là một phân loại không kiểm lại được, và nó sẽ được tin trong đúng cái ngày nó sai.
    """
    cause: str
    detail: str
    evidence: dict = field(default_factory=dict)

    @property
    def needs_a_person(self) -> bool:
        """UNKNOWN cũng cần người — không biết vì sao hệ từ chối là một trạng thái phải
        có ai đó nhìn, không phải một trạng thái để bỏ qua."""
        return self.cause in (SYSTEM_FAULT, UNKNOWN)


def _session_bounds(day: _dt.date) -> Optional[tuple]:
    """`(mở, đóng)` theo giờ ET của phiên CME kết thúc trong ngày `day`, hoặc None.

    None có hai nghĩa và cả hai đều dẫn tới UNKNOWN ở trên: không có thư viện lịch, hoặc
    lịch không nhận ngày đó là một phiên. Nghĩa thứ hai KHÔNG được đọc thành "thị trường
    đóng" — một ngày lịch không biết và một ngày lịch nói đóng là hai chuyện, và chỉ chuyện
    thứ hai mới là bằng chứng.
    """
    try:
        import exchange_calendars as xc
        import pandas as pd

        cal = xc.get_calendar("CMES")
        ts = pd.Timestamp(day)
        if not cal.is_session(ts):
            return None
        et = "America/New_York"
        return (cal.session_open(ts).tz_convert(et).to_pydatetime().replace(tzinfo=None),
                cal.session_close(ts).tz_convert(et).to_pydatetime().replace(tzinfo=None))
    except Exception:                                            # noqa: BLE001
        return None


def _is_a_session(day: _dt.date) -> Optional[bool]:
    """True/False khi lịch trả lời được, None khi không. Ba kết cục, như mọi phép dò khác
    trong kho này."""
    try:
        import exchange_calendars as xc
        import pandas as pd

        return bool(xc.get_calendar("CMES").is_session(pd.Timestamp(day)))
    except Exception:                                            # noqa: BLE001
        return None


def classify(*, session_day, window_from: str, window_to: str,
             codes, clock: str = "America/New_York") -> Cause:
    """Vì sao slot này bị từ chối.

    `window_from`/`window_to` là cửa sổ của sleeve, "HH:MM". `codes` là các mã cổng đã trả
    về — chuỗi nối bằng dấu phẩy hoặc một dãy.

    Thứ tự xét có chủ đích và không đảo được:

    1. **Hình dạng khung sai** thì lịch không cứu được. Một khung sai múi giờ vẫn sai vào
       ngày lễ, và gọi nó là "thị trường đóng" là giấu một lỗi thật sau một ngày nghỉ.
    2. **Cửa sổ nằm ngoài giờ phiên** -> thị trường đóng. Đây là phép đo, không phải suy
       đoán: giờ đóng đọc từ lịch của chính sàn.
    3. **Chỉ có mã "chưa tới lúc"** -> dữ liệu chưa tới.
    4. **Phiên đang mở mà dữ liệu vắng** -> hệ hỏng.
    5. Còn lại -> không biết, và nói ra.

    Sleeve chạy trên đồng hồ khác — Nikkei đọc giờ Tokyo — thì cửa sổ của nó không so được
    trực tiếp với giờ phiên CME tính bằng ET. Trả UNKNOWN thay vì so nhầm hai đồng hồ; kho
    này đã mất một ngày vì đúng loại nhầm lẫn đó.
    """
    if isinstance(codes, str):
        codes = [c.strip() for c in codes.split(",") if c.strip()]
    codes = [str(c) for c in (codes or [])]
    day = (session_day.date() if isinstance(session_day, _dt.datetime)
           else session_day if isinstance(session_day, _dt.date)
           else _dt.date.fromisoformat(str(session_day)[:10]))
    ev: dict = {"codes": codes, "session_day": day.isoformat(),
                "window": [window_from, window_to], "clock": clock}

    shape = sorted(set(codes) & _SHAPE_CODES)
    if shape:
        return Cause(SYSTEM_FAULT,
                     f"khung dữ liệu sai hình dạng ({', '.join(shape)}); lịch không liên "
                     f"quan tới loại lỗi này", {**ev, "shape_codes": shape})

    # Lỗi của tầng nối dữ liệu. Xét ngay sau hình dạng và TRƯỚC mọi thứ dính tới lịch: dữ
    # liệu đã về nhưng sai thì giờ phiên không nói được gì về nó, và một sleeve chạy trên
    # đồng hồ khác cũng không làm nó bớt sai. Ngày 04/09, mười chín slot Nikkei bị từ chối
    # vì chuỗi hợp đồng đã roll — trước dòng này chúng rơi vào "không biết", chỉ vì cửa sổ
    # của sleeve ấy tính bằng giờ Tokyo.
    blob = " ".join(codes).lower()
    hit = [p for p in _JOIN_FAULT_PHRASES if p in blob]
    if hit:
        return Cause(SYSTEM_FAULT,
                     f"tầng nối dữ liệu từ chối ({hit[0]}); dữ liệu đã về nhưng sai, nên "
                     f"giờ phiên không giải thích được", {**ev, "join_fault": hit})

    if clock != "America/New_York":
        return Cause(UNKNOWN,
                     f"cửa sổ của sleeve tính theo {clock}, còn giờ phiên đọc được là ET; "
                     f"so hai đồng hồ khác nhau ở đây sẽ cho một câu trả lời trông đúng",
                     ev)

    bounds = _session_bounds(day)
    if bounds is None:
        if _is_a_session(day) is False:
            return Cause(MARKET_CLOSED, f"{day} không phải một phiên CME",
                         {**ev, "is_session": False})
        return Cause(UNKNOWN,
                     "không đọc được giờ phiên cho ngày này, nên không nói được thị trường "
                     "có mở trong cửa sổ hay không", ev)

    open_et, close_et = bounds
    lo = _dt.datetime.combine(day, _dt.time(*(int(x) for x in window_from.split(":"))))
    hi = _dt.datetime.combine(day, _dt.time(*(int(x) for x in window_to.split(":"))))
    ev["session"] = [open_et.isoformat(), close_et.isoformat()]

    if lo >= close_et:
        return Cause(MARKET_CLOSED,
                     f"phiên đóng lúc {close_et:%H:%M} ET, còn cửa sổ bắt đầu "
                     f"{window_from} — không bar nào có thể tồn tại trong khung này", ev)
    if hi <= open_et:
        return Cause(MARKET_CLOSED,
                     f"phiên mở lúc {open_et:%H:%M} ET, còn cửa sổ kết thúc {window_to}", ev)
    if lo < close_et < hi:
        return Cause(MARKET_CLOSED,
                     f"phiên đóng lúc {close_et:%H:%M} ET, giữa cửa sổ {window_from}-"
                     f"{window_to} — phần sau giờ đóng không thể có bar",
                     {**ev, "partial": True})

    if codes and set(codes) <= _TIMING_CODES:
        return Cause(DATA_NOT_YET,
                     "cửa sổ chưa tới; slot sau trong cùng cửa sổ vẫn có thể chạy", ev)

    if codes:
        return Cause(SYSTEM_FAULT,
                     f"phiên mở suốt cửa sổ {window_from}-{window_to} nhưng cổng vẫn từ "
                     f"chối ({', '.join(sorted(set(codes)))}) — dữ liệu đáng lẽ phải có", ev)

    return Cause(UNKNOWN, "không có mã từ chối nào để xét", ev)


def classify_slot(record: dict, requirements: "dict | None" = None) -> Cause:
    """Cùng câu hỏi, hỏi thẳng từ một dòng bản ghi tín hiệu.

    Cửa sổ đọc từ bảng yêu cầu của chính cổng, không viết lại ở đây — một bản sao thứ hai
    của cửa sổ là một thứ nữa để trôi khỏi bản gốc.
    """
    sleeve = str(record.get("sleeve") or "")
    if requirements is None:
        try:
            from global_index.track1_intraday import REQUIREMENTS as requirements
        except Exception:                                        # noqa: BLE001
            return Cause(UNKNOWN, "không đọc được bảng yêu cầu của cổng",
                         {"sleeve": sleeve})
    req = (requirements or {}).get(sleeve)
    if req is None:
        return Cause(UNKNOWN, f"cổng không có yêu cầu nào cho sleeve {sleeve!r}",
                     {"sleeve": sleeve})
    return classify(session_day=record.get("session_date"),
                    window_from=req.today_from, window_to=req.today_to,
                    codes=record.get("detail") or "",
                    clock=getattr(req, "clock", "America/New_York"))
