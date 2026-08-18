"""Công cụ phải tự từ chối bị dùng theo cách đã làm IBKR khoá truy vấn.

Đêm 2026-08-18 tôi dựng một vòng dò 20 phút/lần để đo độ trễ công bố sổ của IBKR. Tám
lần hỏng liên tiếp và dịch vụ đổi từ `code=1004` ("chưa chốt sổ") sang `code=1025 Too
many failed attempts` — khoá lại, và có nguy cơ làm hỏng cả job thật lúc 22:20 ET dù
token lẫn khoảng ngày đều đã đúng.

Sai ở chỗ đo nhầm giới hạn. Runbook ghi nhịp *1 lần/giây, 10 lần/phút*; tôi tính 20
phút/lần là an toàn thừa rồi dừng. Nhịp không phải ràng buộc bị vi phạm — số lần hỏng
liên tiếp mới là. Kiểm đúng cái giới hạn mình tìm thấy, và không hỏi còn giới hạn nào
khác.

Ngưỡng chọn theo hậu quả, không theo cảm giác: job đêm chạy MỘT lần mỗi ngày nên không
bao giờ chạm tới; thử tay hai lần cũng không; một vòng lặp thì dừng ở lần thứ ba.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from monitor import flex_pull as fp  # noqa: E402

NOW = 1_000_000.0


def _log(tmp_path: Path, ages_min: list[float]) -> Path:
    p = tmp_path / ".send_failures.json"
    p.write_text(json.dumps([NOW - m * 60 for m in ages_min]), encoding="utf-8")
    return p


def test_the_nightly_job_is_never_blocked_by_yesterdays_failure(tmp_path):
    """Nửa quan trọng nhất. Một guard chặn cả job đêm sẽ biến việc hỏng một hôm thành
    hỏng vĩnh viễn — tệ hơn hẳn thứ nó định ngăn."""
    old = _log(tmp_path, [24 * 60, 48 * 60, 72 * 60])   # ba lần hỏng, mỗi ngày một lần
    fp._refuse_if_hammering(old, NOW)                    # không được ném


def test_two_manual_retries_are_allowed(tmp_path):
    fp._refuse_if_hammering(_log(tmp_path, [5, 20]), NOW)


def test_a_third_failure_inside_the_hour_stops_the_loop(tmp_path):
    with pytest.raises(SystemExit) as exc:
        fp._refuse_if_hammering(_log(tmp_path, [5, 20, 45]), NOW)
    assert "1025" in str(exc.value), "loi phai noi ro hau qua, khong chi 'refusing'"


def test_no_log_means_no_refusal(tmp_path):
    fp._refuse_if_hammering(tmp_path / "khong-ton-tai.json", NOW)


def test_a_corrupt_counter_never_blocks_the_pull(tmp_path):
    """Sổ đếm hỏng không được làm hỏng việc chính — nó là thứ phụ trợ."""
    p = tmp_path / ".send_failures.json"
    p.write_text("{ khong phai json", encoding="utf-8")
    fp._refuse_if_hammering(p, NOW)


def test_a_failure_is_recorded_and_a_success_clears_the_slate(tmp_path):
    """Hai nửa của vòng đời. Không ghi thì bộ đếm mãi rỗng và guard không bao giờ đếm
    tới; không xoá thì ba lần hỏng rải rác sẽ chặn một lần kéo hoàn toàn hợp lệ."""
    p = tmp_path / ".send_failures.json"
    for _ in range(3):
        fp._record_failure(p, NOW)
    assert len(fp._recent_failures(p, NOW)) == 3
    with pytest.raises(SystemExit):
        fp._refuse_if_hammering(p, NOW)

    fp._clear_failures(p)
    assert fp._recent_failures(p, NOW) == []
    fp._refuse_if_hammering(p, NOW)


def test_the_counter_lives_beside_the_output_so_a_test_cannot_lock_the_live_path(tmp_path):
    """`--out-dir` khác thì sổ đếm khác. Một phép kiểm hay một lần thử trong thư mục tạm
    không bao giờ được khoá đường chạy thật — đúng bài học của chính đêm nay."""
    assert fp._attempt_log(tmp_path) == tmp_path / ".send_failures.json"
    assert fp._attempt_log(fp.DEFAULT_OUT_DIR) != fp._attempt_log(tmp_path)


def test_the_1025_answer_says_it_is_not_a_configuration_problem(monkeypatch):
    """Chữ của IBKR là "Please review your configuration", và nó chỉ sai hướng: cấu hình
    không đổi, cái đổi là đã hỏng quá nhiều lần. Đọc theo chữ thì người ta đi lục Client
    Portal thay vì chỉ cần dừng lại và chờ.

    Kiểm hành vi chứ không kiểm văn bản mã nguồn: bản đầu của phép kiểm này tìm chuỗi
    trong file và đỏ vì chuỗi bị ngắt dòng — nó đo cách xuống dòng, không đo điều được
    nói ra.
    """
    xml = (b"<FlexStatementResponse><Status>Warn</Status><ErrorCode>1025</ErrorCode>"
           b"<ErrorMessage>Too many failed attempts. Please review your configuration."
           b"</ErrorMessage></FlexStatementResponse>")
    monkeypatch.setattr(fp, "_get", lambda _url: xml)
    with pytest.raises(SystemExit) as exc:
        fp._send_request("t", "q", None, None)
    said = str(exc.value)
    assert "1025" in said
    assert "KHONG phai loi cau hinh" in said, f"khong noi ro day khong phai cau hinh: {said}"
    assert "DUNG thu lai" in said, f"khong bao nguoi doc dung lai: {said}"


def test_an_ordinary_failure_keeps_its_plain_message(monkeypatch):
    """Nửa còn lại: chỉ 1025 mới được diễn giải. Một lỗi khác bị nhét vào cùng lời
    khuyên sẽ dẫn người đọc đi sai hướng theo chiều ngược lại."""
    xml = (b"<FlexStatementResponse><Status>Fail</Status><ErrorCode>1004</ErrorCode>"
           b"<ErrorMessage>Statement is incomplete at this time.</ErrorMessage>"
           b"</FlexStatementResponse>")
    monkeypatch.setattr(fp, "_get", lambda _url: xml)
    with pytest.raises(SystemExit) as exc:
        fp._send_request("t", "q", None, None)
    said = str(exc.value)
    assert "1004" in said and "KHONG phai loi cau hinh" not in said


_FAIL_XML = (b"<FlexStatementResponse><Status>Fail</Status><ErrorCode>1004</ErrorCode>"
             b"<ErrorMessage>Statement is incomplete at this time.</ErrorMessage>"
             b"</FlexStatementResponse>")


def _main_with(monkeypatch, tmp_path, get):
    """Chạy main() thật, nhưng mọi đường ra ngoài đều bị bịt.

    Gọi main() trong một phép kiểm chính là thứ đã chặn ba slot NKD đêm nay, nên nói rõ
    vì sao lần này an toàn: `_get` bị thay nên không có mạng, `--out-dir` trỏ vào thư
    mục tạm nên sổ đếm nằm trong đó, và đường này không chạm tới khoá, sổ vị thế hay
    broker. Dây bẫy trong conftest.py sẽ kêu nếu tôi sai.
    """
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "t")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "q")
    monkeypatch.setattr(fp, "_get", get)
    monkeypatch.setattr(sys, "argv", ["flex_pull", "--out-dir", str(tmp_path)])
    return fp.main()


def test_main_actually_counts_its_failures_and_then_stops(monkeypatch, tmp_path):
    """Phép kiểm về việc GUARD ĐƯỢC CẮM VÀO, không phải về guard.

    Chín phép kiểm trên gọi thẳng các hàm, nên gỡ `_record_failure` khỏi main() vẫn
    xanh cả chín — đo bằng mutation. Sổ đếm mãi rỗng thì guard không bao giờ đếm tới,
    và cả bản vá thành vô nghĩa.
    """
    for _ in range(fp._ATTEMPT_LIMIT):
        with pytest.raises(SystemExit) as exc:
            _main_with(monkeypatch, tmp_path, lambda _u: _FAIL_XML)
        assert "1004" in str(exc.value)

    with pytest.raises(SystemExit) as exc:
        _main_with(monkeypatch, tmp_path, lambda _u: _FAIL_XML)
    assert "Refusing to send" in str(exc.value), (
        f"lan thu {fp._ATTEMPT_LIMIT + 1} van gui di — guard chua duoc cam vao main: {exc.value}")


def test_a_successful_pull_wipes_the_counter(monkeypatch, tmp_path):
    """Nửa còn lại. Không xoá thì ba lần hỏng rải rác trong một tiếng sẽ chặn một lần
    kéo hoàn toàn hợp lệ ngay sau đó."""
    for _ in range(fp._ATTEMPT_LIMIT - 1):
        with pytest.raises(SystemExit):
            _main_with(monkeypatch, tmp_path, lambda _u: _FAIL_XML)
    assert fp._recent_failures(fp._attempt_log(tmp_path), NOW := __import__("time").time())

    ok = (b"<FlexStatementResponse><Status>Success</Status>"
          b"<ReferenceCode>123</ReferenceCode></FlexStatementResponse>")
    monkeypatch.setattr(fp, "_get_statement", lambda *_a, **_k: b"col1,col2\n1,2\n")
    monkeypatch.setattr(sys, "argv", ["flex_pull", "--out-dir", str(tmp_path), "--sleep", "0"])
    assert _main_with(monkeypatch, tmp_path, lambda _u: ok) == 0
    assert fp._recent_failures(fp._attempt_log(tmp_path), NOW) == [], "so dem khong duoc xoa"
