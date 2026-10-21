from pathlib import Path

from monitor.backend.track1_runtime_reader import _book


ROOT = Path(__file__).resolve().parents[1]


def test_track1_book_publishes_50k_risk_base(tmp_path):
    (tmp_path / "live_positions.track1.json").write_text(
        '{"equity":49956,"peak_equity":50000,"broker_equity":251213.8,"positions":[]}',
        encoding="utf-8",
    )

    book = _book(tmp_path)

    assert book["account_base"] == 50_000.0
    assert book["currency"] == "USD"
    assert book["payload"]["equity"] == 49_956
    assert book["payload"]["peak_equity"] == 50_000
    assert "broker equity is reference context only" in book["equity_semantics"]


def test_realtime_uses_book_for_equity_peak_and_50k_base():
    js = (ROOT / "global_index/dash/realtime/realtime.js").read_text(encoding="utf-8")
    html = (ROOT / "global_index/dash/realtime/index.html").read_text(encoding="utf-8")

    assert "setMetric('metricEquity', `${esc(t1currency)} ${money0(t1equity)}`" in js
    assert "state.track1?.book?.account_base" in js
    assert "Number.isFinite(t1peak) && t1peak > 0 ? dollars(t1peak)" in js
    assert "Broker reference" in js
    assert "not the risk denominator" in html
