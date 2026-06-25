"""
tests/test_reject_funnel.py
---------------------------
Unit tests for raits.backtest.reject_funnel.

Written BEFORE the implementation (TDD discipline).
Tests define the contract; the module must satisfy it.

Run with:  pytest tests/test_reject_funnel.py -v
"""
import logging
import unittest

# These imports define the contract — they FAIL until reject_funnel.py exists.
from raits.backtest.reject_funnel import (
    RejectFunnelHandler,
    normalise_message,
    classify_reason,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_record(msg: str, level: int = logging.DEBUG) -> logging.LogRecord:
    return logging.LogRecord(
        name="RAITS.backtest", level=level, pathname="", lineno=0,
        msg=msg, args=(), exc_info=None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# normalise_message
# ─────────────────────────────────────────────────────────────────────────────

class TestNormaliseMessage(unittest.TestCase):

    def test_ticker_replaced(self):
        out = normalise_message("ORB skip NVDA: gap too small")
        self.assertNotIn("NVDA", out)
        self.assertIn("<TK>", out)

    def test_lowercase_word_preserved(self):
        out = normalise_message("ORB skip nvda: gap too small")
        # lowercase "nvda" is not a ticker symbol
        self.assertIn("nvda", out)

    def test_number_replaced(self):
        out = normalise_message("gap 0.43% too small")
        self.assertIn("<N>", out)
        self.assertNotIn("0.43", out)

    def test_negative_number_replaced(self):
        out = normalise_message("PE_SHORT skip AAPL: gap -7.2% < -5%")
        self.assertIn("<N>", out)
        self.assertNotIn("-7.2", out)

    def test_multiple_tickers_in_one_message(self):
        out = normalise_message("skip AAPL TSLA: some reason")
        # AAPL and TSLA should both become <TK>
        self.assertEqual(out.count("<TK>"), 2)
        self.assertNotIn("AAPL", out)
        self.assertNotIn("TSLA", out)

    def test_five_char_ticker_replaced(self):
        out = normalise_message("ORB skip GOOGL: condition failed")
        self.assertNotIn("GOOGL", out)
        self.assertIn("<TK>", out)

    def test_long_word_not_replaced(self):
        # 6+ capital letters is NOT a ticker pattern (\b[A-Z]{1,5}\b)
        out = normalise_message("MARKETS data unavailable")
        self.assertIn("MARKETS", out)

    def test_single_letter_ticker_replaced(self):
        # e.g. "V" (Visa) or "A" (Agilent) — valid 1-char tickers
        out = normalise_message("ORB skip V: no prior data")
        self.assertNotIn(" V:", out)

    def test_integer_replaced(self):
        out = normalise_message("top-15 tickers selected")
        self.assertIn("<N>", out)
        self.assertNotIn("15", out)

    def test_strip_leading_trailing_whitespace(self):
        out = normalise_message("  ORB skip NVDA: gap too small  ")
        self.assertEqual(out, out.strip())


# ─────────────────────────────────────────────────────────────────────────────
# classify_reason
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyReason(unittest.TestCase):

    # --- Structural reasons ---

    def test_regime_is_structural(self):
        self.assertEqual(classify_reason("ORB skip <TK>: blocked in regime"), "structural")

    def test_stress_is_structural(self):
        self.assertEqual(classify_reason("TF skip <TK>: LONG blocked in Stress bear trend"), "structural")

    def test_bear_is_structural(self):
        self.assertEqual(classify_reason("ORB skip <TK>: bear trend SMA<N><SMA<N>"), "structural")

    def test_trend_is_structural(self):
        self.assertEqual(classify_reason("TF skip <TK>: signal=SHORT but scanner intent=LONG trend"), "structural")

    def test_gap_is_structural(self):
        self.assertEqual(classify_reason("ORB skip <TK>: gap <N>% too small"), "structural")

    def test_atr_is_structural(self):
        self.assertEqual(classify_reason("STRESS_MID skip <TK>: stop dist <N> exceeds max_atr"), "structural")

    def test_cooldown_is_structural(self):
        self.assertEqual(classify_reason("TF skip <TK> <TK>: cooldown block_stop=<N>"), "structural")

    def test_safety_is_structural(self):
        self.assertEqual(classify_reason("safety mode active, blocking entries"), "structural")

    def test_circuit_is_structural(self):
        self.assertEqual(classify_reason("circuit breaker fired at <N>"), "structural")

    def test_pdt_is_structural(self):
        self.assertEqual(classify_reason("PDT block <TK>: daily trade limit reached"), "structural")

    def test_top_minus_is_structural(self):
        self.assertEqual(classify_reason("scanner top-<N> tickers selected"), "structural")

    # --- MECHANICAL reasons ---

    def test_no_prior_is_mechanical(self):
        self.assertEqual(classify_reason("ORB skip <TK>: no prior day close available"), "MECHANICAL")

    def test_no_or_is_mechanical(self):
        self.assertEqual(classify_reason("ORB skip <TK>: no or range formed"), "MECHANICAL")

    def test_missing_is_mechanical(self):
        self.assertEqual(classify_reason("PE_SHORT skip <TK>: missing earnings date"), "MECHANICAL")

    def test_empty_is_mechanical(self):
        self.assertEqual(classify_reason("PE_SHORT skip <TK>: empty bars today"), "MECHANICAL")

    def test_five_min_is_mechanical(self):
        self.assertEqual(classify_reason("skip <TK>: no 5-min data in market_data"), "MECHANICAL")

    def test_no_data_is_mechanical(self):
        self.assertEqual(classify_reason("skip <TK>: no data available for today"), "MECHANICAL")

    def test_no_range_is_mechanical(self):
        self.assertEqual(classify_reason("ORB skip <TK>: no range formed in opening window"), "MECHANICAL")

    # --- Mechanical takes priority over structural when both keywords present ---

    def test_mechanical_takes_priority_over_structural(self):
        # "missing" (mechanical) beats "gap" (structural)
        self.assertEqual(
            classify_reason("ORB skip <TK>: missing gap data"), "MECHANICAL"
        )

    # --- Unknown defaults structural ---

    def test_unknown_defaults_to_structural(self):
        self.assertEqual(classify_reason("something completely unrelated"), "structural")


# ─────────────────────────────────────────────────────────────────────────────
# RejectFunnelHandler
# ─────────────────────────────────────────────────────────────────────────────

class TestRejectFunnelHandler(unittest.TestCase):

    def setUp(self):
        self.handler = RejectFunnelHandler()

    # --- capture logic ---

    def test_captures_skip_message(self):
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        self.assertEqual(sum(self.handler.counts.values()), 1)

    def test_captures_block_message(self):
        self.handler.emit(_make_record("ORB CONFIRM skip AAPL: LONG blocked in bear trend"))
        self.assertEqual(sum(self.handler.counts.values()), 1)

    def test_captures_reject_word(self):
        self.handler.emit(_make_record("TF reject TSLA: wrong direction"))
        self.assertEqual(sum(self.handler.counts.values()), 1)

    def test_captures_no_prefix(self):
        self.handler.emit(_make_record("PE_SHORT skip TSLA: no 5-min data in market_data"))
        self.assertEqual(sum(self.handler.counts.values()), 1)

    def test_captures_empty_word(self):
        self.handler.emit(_make_record("PE_SHORT skip AMD: empty bars today"))
        self.assertEqual(sum(self.handler.counts.values()), 1)

    def test_captures_missing_word(self):
        self.handler.emit(_make_record("skip AAPL: missing prior close"))
        self.assertEqual(sum(self.handler.counts.values()), 1)

    def test_ignores_normal_eod_message(self):
        self.handler.emit(_make_record("EOD 2020-01-06 | $50,012.34 (+0.02%)"))
        self.assertEqual(sum(self.handler.counts.values()), 0)

    def test_ignores_entry_message(self):
        self.handler.emit(_make_record("ORB PENDING NVDA: LONG @ $120.00"))
        self.assertEqual(sum(self.handler.counts.values()), 0)

    def test_ignores_hmm_trained(self):
        self.handler.emit(_make_record("HMM trained successfully", level=logging.INFO))
        self.assertEqual(sum(self.handler.counts.values()), 0)

    # --- normalisation: same message, different tickers → same bucket ---

    def test_same_pattern_different_tickers_merge_to_one_bucket(self):
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        self.handler.emit(_make_record("ORB skip AAPL: gap 0.4% too small"))
        self.assertEqual(len(self.handler.counts), 1)
        self.assertEqual(sum(self.handler.counts.values()), 2)

    def test_different_messages_produce_different_buckets(self):
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        self.handler.emit(_make_record("PE_SHORT skip AAPL: no 5-min data in market_data"))
        self.assertEqual(len(self.handler.counts), 2)

    def test_counter_accumulates_across_emits(self):
        for _ in range(5):
            self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        self.assertEqual(sum(self.handler.counts.values()), 5)

    # --- mechanical_pct ---

    def test_mechanical_pct_all_mechanical(self):
        self.handler.emit(_make_record("ORB skip NVDA: no prior day close available"))
        self.handler.emit(_make_record("PE_SHORT skip AAPL: no 5-min data in market_data"))
        self.assertAlmostEqual(self.handler.mechanical_pct(), 1.0)

    def test_mechanical_pct_all_structural(self):
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        self.handler.emit(_make_record("TF skip AAPL: LONG blocked in Stress bear trend"))
        self.assertAlmostEqual(self.handler.mechanical_pct(), 0.0)

    def test_mechanical_pct_three_quarters_mechanical(self):
        # 1 structural bucket with count 1
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        # 1 mechanical bucket with count 3
        for _ in range(3):
            self.handler.emit(_make_record("ORB skip AAPL: no prior day close available"))
        # 3/(3+1) = 0.75
        self.assertAlmostEqual(self.handler.mechanical_pct(), 0.75)

    def test_mechanical_pct_empty_returns_zero(self):
        self.assertAlmostEqual(self.handler.mechanical_pct(), 0.0)

    # --- funnel() ---

    def test_funnel_sorted_by_count_desc(self):
        for _ in range(3):
            self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        self.handler.emit(_make_record("ORB skip AAPL: no prior day close available"))
        funnel = self.handler.funnel()
        self.assertGreater(len(funnel), 0)
        self.assertEqual(funnel[0][0], 3)
        self.assertEqual(funnel[1][0], 1)

    def test_funnel_entries_have_count_class_reason(self):
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        funnel = self.handler.funnel()
        self.assertEqual(len(funnel), 1)
        count, cls, reason = funnel[0]
        self.assertIsInstance(count, int)
        self.assertIn(cls, ("structural", "MECHANICAL"))
        self.assertIsInstance(reason, str)

    def test_funnel_structural_classified_correctly(self):
        self.handler.emit(_make_record("ORB skip NVDA: gap 0.3% too small"))
        _, cls, _ = self.handler.funnel()[0]
        self.assertEqual(cls, "structural")

    def test_funnel_mechanical_classified_correctly(self):
        self.handler.emit(_make_record("ORB skip AAPL: no prior day close available"))
        _, cls, _ = self.handler.funnel()[0]
        self.assertEqual(cls, "MECHANICAL")

    def test_funnel_empty_handler_returns_empty_list(self):
        self.assertEqual(self.handler.funnel(), [])


if __name__ == "__main__":
    unittest.main()
