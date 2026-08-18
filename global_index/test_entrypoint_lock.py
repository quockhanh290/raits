"""Ba entry point chạm IBKR phải cùng đứng sau một khoá liên-tiến-trình.

Sự cố 2026-08-13 07:31:00: hai scheduler cùng sống nên slot MAX_HOLD bị bắn HAI LẦN
trong cùng một giây — hai dòng lệnh y hệt nhau trong scheduler_0813.log. Cả hai tiến
trình `run_maxhold_exit` lao vào clientId 1; một cái chiếm được, cái kia chết vì
`TimeoutError` ở tầng ib_insync sau 5 giây, không nói được gì về nguyên nhân.

Mutex trong run_scheduler KHÔNG cứu được và không bao giờ cứu được: nó là
`threading.Lock`, chỉ thấy các slot trong CÙNG một tiến trình. Guard E1 — khoá tệp PID,
vốn có sẵn và tự khai là "prevents duplicate runner instances from submitting double
orders" — thì thấy, nhưng trước bản vá này chỉ `run_live_day` dùng nó. Đúng hai entry
point còn lại là hai cái đã va nhau.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pytest.importorskip("pandas")

from global_index import run_maxhold_exit as mh          # noqa: E402
from global_index import run_stop_repair as sr           # noqa: E402
from global_index import runner as rn                    # noqa: E402


def _defaults(module) -> dict:
    """Giá trị mặc định argparse của module, đọc mà KHÔNG chạy main().

    Bản đầu của hàm này gọi `module.main()` với argv rỗng để parser tự chạy. Nó chạy
    thật: tìm thấy `live_positions.json` trong thư mục làm việc, giành khoá ở đường dẫn
    MẶC ĐỊNH `runner.pid` — tức tệp khoá của hệ thật — rồi mới chết khi thử nối IBKR.
    Tệp khoá ở lại, mang PID của tiến trình pytest còn sống, nên `_pid_alive` trả True
    và MỌI slot NKD sau đó bị từ chối.

    Đo được 2026-08-18: runner.pid ghi lúc 00:38:39 mang PID 43756 (chính pytest), rồi
    hai slot 02:40 và 02:45 ET đều "no-op (previous run still in flight)" và chạy 10
    giây thay vì 77. Phép kiểm dựng ra để bảo vệ đường đặt lệnh đã tự chặn nó.

    Nên: chỉ dựng parser, không chạy thân hàm. Bắt SystemExit của `--help` là đủ để
    thu mọi default mà không chạm vào bất cứ thứ gì.
    """
    import argparse
    seen = {}
    real = argparse.ArgumentParser.add_argument

    def spy(self, *args, **kw):
        for name in args:
            if isinstance(name, str) and name.startswith("--"):
                seen[name] = kw.get("default")
        return real(self, *args, **kw)

    argparse.ArgumentParser.add_argument = spy
    try:
        # --help: parser dựng xong thì argparse thoát ngay, trước mọi dòng thân hàm.
        sys.argv = ["x", "--help"]
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                module.main()
            except SystemExit:
                pass
    finally:
        argparse.ArgumentParser.add_argument = real
    assert seen, f"khong doc duoc default nao tu {module.__name__}"
    return seen


def test_all_three_entry_points_share_one_lock_file():
    """Ba tệp khoá riêng thì mỗi tiến trình tự khoá mình và không cái nào thấy cái kia —
    đúng bằng không có khoá, nhưng trông như đã có."""
    from global_index import run_live_day as ld
    paths = {
        "run_live_day": _defaults(ld).get("--lock-path"),
        "run_maxhold_exit": _defaults(mh).get("--lock-path"),
        "run_stop_repair": _defaults(sr).get("--lock-path"),
    }
    assert all(paths.values()), f"co entry point khong khai bao --lock-path: {paths}"
    assert len(set(paths.values())) == 1, (
        f"ba entry point khoa vao ba tep khac nhau, tuc khong khoa gi ca: {paths}")


@pytest.mark.parametrize("module, taken_before_connect", [(mh, True), (sr, True)])
def test_the_lock_is_taken_before_the_broker_connection(module, taken_before_connect):
    """Thứ tự là toàn bộ ý nghĩa.

    run_live_day đã học điều này rồi và ghi lại: giành khoá SAU khi nối thì tiến trình
    thừa đã kịp chiếm clientId và va vào lượt đang chạy, rồi mới chết vì khoá. Giành
    trước thì nó thoát mà chưa đụng tới IBKR.
    """
    src = Path(module.__file__).read_text(encoding="utf-8")
    lock_at = src.index("_acquire_lock(Path(a.lock_path))")
    connect_at = src.index("IBKRBroker(host=")
    assert lock_at < connect_at, (
        f"{module.__name__}: giành khoá SAU khi nối broker — tiến trình thừa vẫn kịp "
        f"chiếm clientId trước khi nó biết mình là thừa")


class _NeverConnected(RuntimeError):
    pass


def _run_with_lock_held(module, monkeypatch, tmp_path, held: bool):
    """Chạy main() với tệp khoá do một PID CÒN SỐNG khác giữ (hoặc không giữ)."""
    lock = tmp_path / "runner.pid"
    positions = tmp_path / "live_positions.json"
    positions.write_text("[]", encoding="utf-8")
    if held:
        lock.write_text("424242", encoding="utf-8")
        monkeypatch.setattr(rn, "_pid_alive", lambda _pid: True)

    # Nếu khoá không chặn thì main() sẽ đi tiếp và nối broker. Không cho nó nối: ném ra
    # một ngoại lệ nhận dạng được, để phân biệt "đã đi qua cửa khoá" với "bị khoá chặn".
    def _boom(*_a, **_k):
        raise _NeverConnected()
    monkeypatch.setattr(module, "IBKRBroker", _boom)
    monkeypatch.setattr(sys, "argv", [
        "x", "--positions-path", str(positions), "--lock-path", str(lock)])
    return module.main()


def test_maxhold_refuses_loudly_when_another_process_holds_the_lock(monkeypatch, tmp_path):
    """Thoát khác 0, không phải im lặng.

    Khác run_live_day: slot kia 5 phút một lần nên bỏ qua là vô hại và nó thoát 0. Job
    này chạy một lần một ngày; thoát 0 sẽ được scheduler đọc thành "completed OK" đúng
    cái ngày MAX_HOLD không chạy, và bảng sẽ không hiện gì cả.
    """
    assert _run_with_lock_held(mh, monkeypatch, tmp_path, held=True) == 1


def test_stop_repair_skips_quietly_when_another_process_holds_the_lock(monkeypatch, tmp_path):
    """Ngược lại ở đây: quét sửa là idempotent và lượt sau cách 2 tiếng sẽ làm, đúng lý
    lẽ `_run_guarded` vẫn dùng để bỏ qua chính job này. Bỏ qua, không phải lỗi."""
    assert _run_with_lock_held(sr, monkeypatch, tmp_path, held=True) == 0


@pytest.mark.parametrize("module", [mh, sr])
def test_an_unheld_lock_does_not_block_anything(module, monkeypatch, tmp_path):
    """Nửa còn lại. Nếu khoá chặn cả khi không ai giữ thì bản vá này biến hai job thành
    không bao giờ chạy — và cả hai phép kiểm trên vẫn xanh."""
    with pytest.raises(_NeverConnected):
        _run_with_lock_held(module, monkeypatch, tmp_path, held=False)
