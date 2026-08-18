"""Chạy suite không được để lại dấu vết trên trạng thái của hệ thật.

Đêm 2026-08-18 một phép kiểm mới — viết ra để BẢO VỆ đường đặt lệnh — đã tự chặn nó.
Hàm đọc giá trị mặc định của argparse trong đó gọi thẳng `module.main()`; `main()` chạy
thật, giành khoá ở đường dẫn mặc định `runner.pid` là tệp khoá của hệ thật, rồi mới chết
khi thử nối IBKR. Tệp khoá ở lại mang PID của pytest, và **ba slot NKD liên tiếp không
làm gì** — 02:40, 02:45, 02:50 ET.

Không cảnh báo nào bắt được: một lượt bị khoá chặn vẫn thoát 0, nên scheduler ghi
"completed OK". Chủ dự án phát hiện bằng một tín hiệu ÂM TÍNH — dòng lỗi HMM biến mất,
vì slot chạy 10 giây thay vì 77 nên chưa chạm tới guard.

Quét tĩnh không thay được cái này: tìm `write_text` ngoài `tmp_path` ra 86 dòng, và hai
dòng đáng ngờ nhất khi soi kỹ đều là nhiễu — biến dựng từ `tmp_path` ở dòng trước, hoặc
đường dẫn đã bị `monkeypatch.setattr` đổi hướng trong fixture. Không nhìn từng dòng mà
biết được.

Và so dấu vân tay trước/sau cũng không đủ: bản đầu của canh gác này làm thế, rồi phép tự
kiểm bác ngay — một probe tạo `runner.pid` rồi xoá đi thì trước và sau giống hệt nhau,
mà cú chạm thoáng qua ấy vẫn đủ chặn một slot đang chạy. Nên phải nghe từng thao tác lúc
nó xảy ra, bằng audit hook.
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent

# Những tệp mà một lần chạy suite KHÔNG BAO GIỜ được động tới. Danh sách theo hậu quả,
# không theo thư mục: sổ vị thế, nhật ký lệnh, khoá chống trùng, công tắc dừng, trạng
# thái đã-chạy-hay-chưa của các job, và tham số đã niêm phong.
GUARDED = (
    "live_positions.json",
    "trade_log.jsonl",
    "runner.pid",
    "stop.flag",
    "global_index/live_state_data.js",
    "global_index/paper_history.json",
    "global_index/preflight_state.json",
    "global_index/maxhold_state.json",
    "global_index/replay_checkpoint.json",
    "monitor/paper_inputs.json",
    "configs/final_params.yaml",
)

_WATCHED = {str((ROOT / rel).resolve()).lower(): rel for rel in GUARDED}
_NAMES = {Path(rel).name.lower() for rel in GUARDED}   # cửa hẹp: loại nhanh gần hết
_TOUCHED: dict[str, str] = {}

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | getattr(os, "O_TRUNC", 0)
_DESTRUCTIVE = ("os.remove", "os.unlink", "os.rename", "os.replace", "shutil.move")


def _audit(event: str, args) -> None:
    """Nghe từng thao tác ghi/xoá, và chỉ quan tâm các tệp trong GUARDED."""
    if event == "open":
        if len(args) < 3 or not isinstance(args[2], int) or not (args[2] & _WRITE_FLAGS):
            return
        target = args[0]
    elif event in _DESTRUCTIVE:
        target = args[0] if args else None
    else:
        return
    if not isinstance(target, (str, bytes, os.PathLike)):
        return
    try:
        text = os.fsdecode(target)
    except (TypeError, ValueError):
        return
    if os.path.basename(text).lower() not in _NAMES:
        return
    try:
        full = str(Path(text).resolve()).lower()
    except OSError:
        return
    rel = _WATCHED.get(full)
    if rel:
        _TOUCHED.setdefault(rel, event)


sys.addaudithook(_audit)


def _fingerprint() -> dict[str, str | None]:
    """Nội dung, không phải mtime: ghi lại đúng nội dung cũ là vô hại, ghi khác thì không."""
    out: dict[str, str | None] = {}
    for rel in GUARDED:
        path = ROOT / rel
        try:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
        except OSError as exc:
            out[rel] = f"unreadable: {exc}"
    return out


@pytest.fixture(scope="session", autouse=True)
def _live_state_is_left_alone():
    """Cảnh báo khi suite chạm vào trạng thái của hệ thật.

    Cảnh báo chứ không làm đỏ suite: hỏng ở đây là hỏng của bộ kiểm chứ không phải của
    mã sản xuất, và biến nó thành lỗi sẽ che mất kết quả thật khi cả hai cùng xảy ra.
    Dòng cảnh báo nêu tên tệp, thao tác, và việc dấu vết có ở lại hay không.
    """
    before = _fingerprint()
    yield
    after = _fingerprint()
    changed = {rel for rel in GUARDED if before[rel] != after[rel]}
    if not (changed or _TOUCHED):
        return
    lines = []
    for rel in sorted(set(_TOUCHED) | changed):
        how = _TOUCHED.get(rel, "noi dung doi")
        lasting = "con lai sau khi chay" if rel in changed else "thoang qua"
        lines.append("  {}: {} ({})".format(rel, how, lasting))
    banner = "!! SUITE DA CHAM VAO TRANG THAI HE THAT:"
    hint = ("   Mot phep kiem dang ghi ra ngoai hop cat. Xem conftest.py de biet vi sao "
            "dieu nay tung vo hieu hoa ba slot NKD lien tiep.")
    print("\n\n" + banner + "\n" + "\n".join(lines) + "\n" + hint + "\n")
