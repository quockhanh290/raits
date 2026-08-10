"""Stop được quy cho VỊ THẾ, không phải cho MÃ.

Trước bản sửa này, cả tầng theo dõi stop đều hỏi *"có stop nào cho mã này không"*. Với một
vị thế mỗi mã thì hai câu hỏi trùng nhau, nên không có gì để lộ ra. Chúng tách đôi ngay khi
sleeve thứ hai chạm cùng hợp đồng — đúng điều STRESS_MID suýt làm (nó dùng đúng bốn mã của
Rổ 4 và luôn SHORT). Xem `docs/futures/OPERATIONS.md`, mục "STRESS_MID: tại sao cron 10:20
bị TẮT".

Bốn hỏng đo được, và mỗi cái là một test ở đây:

  * một STP đánh dấu MỌI vị thế cùng mã là đã bảo vệ (`matching[0]`)
  * stop của vị thế SHORT bị báo HAZARD đối với vị thế LONG cùng mã, dù mỗi bên có stop đúng
  * `{p["inst"]: p}` trong repair_stops làm một vị thế đè vị thế kia, im lặng
  * `p["stop_order_id"] = new_ids[p["inst"]]` đóng CÙNG một order id lên mọi vị thế cùng mã

Cái thứ tư nặng nhất: ba cái trên chỉ bỏ sót, cái này ghi bằng chứng sai vào sổ — và
`cancel_order(p.stop_order_id)`, một trong số ít chỗ vốn ĐÃ đúng theo vị thế, sẽ tin vào nó
rồi huỷ stop của vị thế kia khi đóng vị thế này.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from global_index.check_open_orders import Stop, classify
from global_index.repair_stops import _key, _write_positions, id_corrections

TODAY = "2026-08-11"
OLD = "2026-08-03"          # ngoài cửa sổ hoãn — không dính DEFERRED


def _p(inst, direction, cluster, contracts=1, stop_order_id=None, entry_day=OLD):
    return {"inst": inst, "direction": direction, "cluster": cluster,
            "contracts": contracts, "stop_price": 7000.0,
            "stop_order_id": stop_order_id, "entry_day": entry_day}


def _rows(positions, stops):
    return classify(positions, stops, today=TODAY)


def _verdict_for(rows, inst, cluster):
    return [r[0] for r in rows if r[4] is not None and _key(r[4]) == (inst, cluster)]


# ── một stop không được phủ hai vị thế ────────────────────────────────────────

def test_one_stop_does_not_protect_two_positions():
    """Hỏng cốt lõi. `matching[0]` cũ trả OK cho cả hai; một hợp đồng trần vĩnh viễn,
    không guard nào kêu."""
    positions = [_p("MES", "LONG", "roska4_swing"),
                 _p("MES", "LONG", "roska4_stress")]
    rows = _rows(positions, {"MES": [Stop("SELL", 12, 6900.0, 1)]})
    assert _verdict_for(rows, "MES", "roska4_swing") == ["OK"]
    assert _verdict_for(rows, "MES", "roska4_stress") == ["NAKED"]


def test_two_stops_protect_two_positions():
    """Mặt còn lại: đủ stop thì cả hai phải OK, và mỗi bên nhận MỘT order id khác nhau."""
    positions = [_p("MES", "LONG", "roska4_swing"),
                 _p("MES", "LONG", "roska4_stress")]
    stops = {"MES": [Stop("SELL", 12, 6900.0, 1), Stop("SELL", 13, 6800.0, 1)]}
    rows = _rows(positions, stops)
    ok = [r for r in rows if r[0] == "OK"]
    assert len(ok) == 2
    assert {r[3].order_id for r in ok} == {12, 13}, "hai vi the nhan cung mot order id"


def test_opposite_directions_each_keep_their_own_stop():
    """Swing LONG + stress SHORT cùng mã, mỗi bên có stop đúng chiều.

    Bản cũ gọi stop BUY (của SHORT) là HAZARD đối với vị thế LONG và ngược lại — hai cảnh
    báo giả mỗi ngày, đúng loại làm người vận hành quen bỏ qua chữ HAZARD."""
    positions = [_p("MES", "LONG", "roska4_swing"),
                 _p("MES", "SHORT", "roska4_stress")]
    stops = {"MES": [Stop("SELL", 12, 6900.0, 1), Stop("BUY", 13, 7100.0, 1)]}
    rows = _rows(positions, stops)
    assert _verdict_for(rows, "MES", "roska4_swing") == ["OK"]
    assert _verdict_for(rows, "MES", "roska4_stress") == ["OK"]
    assert not [r for r in rows if r[0] in ("HAZARD", "ORPHAN")]


# ── "có stop" khác "đủ stop" ─────────────────────────────────────────────────

def test_a_stop_smaller_than_the_position_is_partial_not_ok():
    """Sự tồn tại không phải là độ phủ. Một STP 1 hợp đồng dưới vị thế 2 hợp đồng từng
    thoả mãn phép kiểm cũ."""
    rows = _rows([_p("MES", "LONG", "roska4_swing", contracts=2)],
                 {"MES": [Stop("SELL", 12, 6900.0, 1)]})
    assert [r[0] for r in rows] == ["PARTIAL"]
    _mine, got, need = rows[0][3]
    assert (got, need) == (1, 2)


def test_missing_size_still_reads_OK():
    """File vị thế không ghi `contracts` thì không kết luận được độ phủ. Giữ nguyên hành vi
    cũ (OK) — báo PARTIAL vì thiếu metadata là cảnh báo giả, và cảnh báo giả hằng ngày là
    cách một cảnh báo thật bị bỏ qua."""
    p = _p("MES", "LONG", "roska4_swing")
    p.pop("contracts")
    assert [r[0] for r in _rows([p], {"MES": [Stop("SELL", 12, 6900.0, 3)]})] == ["OK"]


def test_a_surplus_correct_side_stop_is_reported():
    """Stop thừa đúng chiều: khớp thì đóng phần không ai yêu cầu đóng rồi MỞ chiều ngược.
    Bản cũ chỉ coi stop SAI chiều là HAZARD nên cái này vô hình."""
    rows = _rows([_p("MES", "LONG", "roska4_swing")],
                 {"MES": [Stop("SELL", 12, 6900.0, 1), Stop("SELL", 13, 6800.0, 1)]})
    assert [r[0] for r in rows] == ["OK", "HAZARD"]
    assert rows[1][3].order_id == 13


# ── sổ sách: id ghi theo vị thế ──────────────────────────────────────────────

def test_id_corrections_are_keyed_by_position():
    positions = [_p("MES", "LONG", "roska4_swing"),
                 _p("MES", "LONG", "roska4_stress")]
    stops = {"MES": [Stop("SELL", 12, 6900.0, 1), Stop("SELL", 13, 6800.0, 1)]}
    drift = id_corrections(positions, stops, today=TODAY)
    assert set(drift) == {("MES", "roska4_swing"), ("MES", "roska4_stress")}
    assert len(set(drift.values())) == 2, "hai vi the nhan cung mot order id"


def test_an_unprotected_position_gets_no_id():
    """Chỉ vị thế OK mới được ghi id. Bản cũ đọc thẳng `stops.get(inst)` nên vị thế thứ hai
    — vốn trần — vẫn được đóng dấu id của vị thế thứ nhất."""
    positions = [_p("MES", "LONG", "roska4_swing"),
                 _p("MES", "LONG", "roska4_stress")]
    drift = id_corrections(positions, {"MES": [Stop("SELL", 12, 6900.0, 1)]}, today=TODAY)
    assert set(drift) == {("MES", "roska4_swing")}


def test_write_positions_stamps_only_the_right_position(tmp_path):
    """Hỏng nặng nhất trong cả bốn: vòng lặp cũ đóng một id lên MỌI vị thế cùng mã, tức là
    GHI bằng chứng sai vào sổ. `cancel_order(p.stop_order_id)` vốn đã đúng theo vị thế sẽ
    tin vào nó và huỷ stop của vị thế kia."""
    path = tmp_path / "live_positions.json"
    path.write_text(json.dumps({"positions": [
        _p("MES", "LONG", "roska4_swing"),
        _p("MES", "LONG", "roska4_stress"),
    ]}), encoding="utf-8")

    _write_positions(path, {("MES", "roska4_swing"): "99"})

    after = {p["cluster"]: p["stop_order_id"]
             for p in json.loads(path.read_text(encoding="utf-8"))["positions"]}
    assert after["roska4_swing"] == "99"
    assert after["roska4_stress"] is None, "id cua vi the nay bi dong sang vi the kia"


def test_write_positions_keeps_a_backup(tmp_path):
    path = tmp_path / "live_positions.json"
    path.write_text(json.dumps({"positions": [_p("MES", "LONG", "roska4_swing")]}),
                    encoding="utf-8")
    _write_positions(path, {("MES", "roska4_swing"): "7"})
    assert path.with_suffix(".json.bak").exists()


# ── không hồi quy về hành vi một-vị-thế-một-mã ───────────────────────────────

def test_a_lone_orphan_is_still_an_orphan():
    rows = _rows([], {"MES": [Stop("SELL", 12, 6900.0, 1)]})
    assert [r[0] for r in rows] == ["ORPHAN"]


def test_a_lone_wrong_way_is_still_wrong_way():
    rows = _rows([_p("MES", "SHORT", "roska4_swing")],
                 {"MES": [Stop("SELL", 12, 6900.0, 1)]})
    assert [r[0] for r in rows] == ["WRONG-WAY"]


def test_wrong_way_stops_are_not_reported_twice():
    """Nhánh WRONG-WAY tiêu thụ các lệnh nó tố cáo; nếu không, lượt quét cuối sẽ kể lại
    chính chúng dưới tên HAZARD và repair_stops huỷ hai lần."""
    rows = _rows([_p("MES", "SHORT", "roska4_swing")],
                 {"MES": [Stop("SELL", 12, 6900.0, 1), Stop("SELL", 13, 6800.0, 1)]})
    assert [r[0] for r in rows] == ["WRONG-WAY"]
    assert len(rows[0][3]) == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
