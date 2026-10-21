from global_index.track1_report import _headline, _headline_detail


def test_unreconciled_pnl_copy_names_system_book_and_missing_broker_evidence():
    broker = {
        "reasons": ["broker_statement_unavailable"],
        "reading": "no broker evidence can confirm Track 1 trading: statement unavailable",
    }
    headline = _headline({}, {}, {}, broker, {})
    detail = _headline_detail(
        {"state": "available", "rows": 2},
        {"state": "available"},
        {"state": "available", "rows": 2},
        broker,
        {"status": "PASS"},
    )

    assert "P&L comes from the system book" in headline
    assert "IBKR statement reconciliation is still unavailable" in headline
    assert "broker evidence:" in detail
    assert "statement unavailable" in detail
