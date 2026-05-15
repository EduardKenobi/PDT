import pandas as pd
import pytest
from datetime import datetime
from app.stock.stock_metrics import _get_annualized_dividend_at_date

TEST_TICKER = 'TEST'

# --- Existing Tests ---
def test_get_annualized_dividend_semiannual():
    dividends = pd.Series([1.5, 0.93], index=pd.to_datetime(['2025-08-26', '2025-05-19']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 5, 23), dividends, 'Semi-Annually', 2)
    assert result == 2.43

def test_get_annualized_dividend_regular():
    dividends = pd.Series([1.0, 1.0, 1.0, 1.0], index=pd.to_datetime(['2026-01-01', '2025-10-01', '2025-07-01', '2025-04-01']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly', 4)
    assert result == 4.0

def test_get_annualized_dividend_irregular_ttm():
    dividends = pd.Series([1.0, 1.0, 1.0, 1.0], index=pd.to_datetime(['2026-01-01', '2025-10-01', '2025-07-01', '2025-04-01']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly-Unregulary', 4)
    assert result == 4.0

def test_get_annualized_dividend_irregular_timing_shift():
    dividends = pd.Series([1.0, 1.0, 1.0, 1.0, 1.0], index=pd.to_datetime(['2026-01-01', '2025-12-01', '2025-10-01', '2025-07-01', '2025-04-01']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly-Unregulary', 4)
    # The implementation sums the *latest* `freq` payments.
    # Sorted descending: [1.0, 1.0, 1.0, 1.0, 1.0]
    # Sum of top 4: 4.0
    assert result == 4.0

# --- New Edge Case Tests ---

def test_get_annualized_dividend_empty_series():
    dividends = pd.Series([], dtype=float)
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly', 4)
    assert result == 0.0

def test_get_annualized_dividend_insufficient_history():
    dividends = pd.Series([1.0], index=pd.to_datetime(['2025-01-01']))
    # Need 4 for quarterly, have 1
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly-Unregulary', 4)
    assert result == 0.0

def test_get_annualized_dividend_zero_amount():
    dividends = pd.Series([0.0, 1.0], index=pd.to_datetime(['2026-01-01', '2025-10-01']))
    # For regular, checks only latest
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly', 4)
    assert result == 0.0

def test_get_annualized_dividend_nan_amount():
    dividends = pd.Series([pd.NA, 1.0], index=pd.to_datetime(['2026-01-01', '2025-10-01']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly', 4)
    assert result == 0.0

def test_get_annualized_dividend_date_before_any_payments():
    dividends = pd.Series([1.0], index=pd.to_datetime(['2026-06-01']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Quarterly', 4)
    assert result == 0.0

def test_get_annualized_dividend_annually():
    dividends = pd.Series([5.0, 4.0], index=pd.to_datetime(['2026-01-01', '2025-01-01']))
    result = _get_annualized_dividend_at_date(TEST_TICKER, datetime(2026, 1, 1), dividends, 'Annually', 1)
    assert result == 5.0
