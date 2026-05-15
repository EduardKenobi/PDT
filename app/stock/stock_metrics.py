from logging import warning, error

import pandas as pd
from datetime import datetime, timedelta
from app.portfolio.portfolio_metrics import get_rate_from_cache
from config import PRIMARY_CURRENCY, DIVIDEND_FREQ_MAP
import calendar
from calendar import month_name
from typing import List, Dict, Optional, Tuple
from utils.analytics import calculate_cagr

def get_historical_dividend_dates(ticker: str, all_dividends_data: pd.DataFrame, cached_history: Optional[List[str]] = None) -> List[datetime]:
    """
    Gets a reliable list of historical dividend dates.
    Prioritizes local payment dates. Falls back to cached history.
    """
    # 1. Try local payment dates first (from broker reports)
    if isinstance(all_dividends_data, pd.DataFrame) and not all_dividends_data.empty:
        local_ticker_dividends_df = all_dividends_data[all_dividends_data['ticker'] == ticker]
        if not local_ticker_dividends_df.empty:
            payment_dates = sorted(local_ticker_dividends_df['date'].tolist(), reverse=True)
            if len(payment_dates) >= 2:
                return payment_dates
            
    # Fallback for dict (backward compatibility if needed)
    elif isinstance(all_dividends_data, dict):
        local_ticker_dividends = all_dividends_data.get('companies', {}).get(ticker, {}).get('dividends', [])
        if local_ticker_dividends:
            payment_dates = sorted([pd.to_datetime(div['date']) for div in local_ticker_dividends], reverse=True)
            if len(payment_dates) >= 2:
                return payment_dates

    # 2. Fallback to cached history (from yfinance fetched in update_market_data)
    if cached_history:
        return sorted([pd.to_datetime(date) for date in cached_history], reverse=True)

    # 3. Final fallback
    if isinstance(all_dividends_data, pd.DataFrame) and not all_dividends_data.empty:
        local_ticker_dividends_df = all_dividends_data[all_dividends_data['ticker'] == ticker]
        return sorted(local_ticker_dividends_df['date'].tolist(), reverse=True)
    elif isinstance(all_dividends_data, dict):
        local_ticker_dividends = all_dividends_data.get('companies', {}).get(ticker, {}).get('dividends', [])
        return sorted([pd.to_datetime(div['date']) for div in local_ticker_dividends], reverse=True)
    
    return []


def calculate_average_dividend_yield(ticker, history_df):
    """
    Calculates the average dividend yield over the last 5 full years.
    """
    if history_df.empty:
        return 0.0

    history_df = history_df.copy() # Avoid SettingWithCopyWarning
    
    if 'Dividends' not in history_df.columns or 'Close' not in history_df.columns:
        return 0.0
        
    history_df['Dividends'] = pd.to_numeric(history_df['Dividends'], errors='coerce')
    dividends = history_df['Dividends'][history_df['Dividends'] > 0]
    if dividends.empty:
        return 0.0

    dividends.index = pd.to_datetime(dividends.index)
    if history_df.index.tz is not None:
        history_df.index = history_df.index.tz_localize(None)

    end_year = datetime.now().year - 1
    start_year = end_year - 4

    annual_yields = []
    for year in range(start_year, end_year + 1):
        yearly_dividends = dividends[dividends.index.year == year].sum()
        if yearly_dividends > 0:
            yearly_prices = history_df['Close'][history_df.index.year == year]
            if not yearly_prices.empty:
                price_at_year_end = yearly_prices.asof(datetime(year, 12, 31))
                if pd.notna(price_at_year_end) and price_at_year_end > 0:
                    annual_yield = (yearly_dividends / price_at_year_end)
                    annual_yields.append(annual_yield)

    if not annual_yields:
        return 0.0

    return sum(annual_yields) / len(annual_yields)

def _get_annualized_dividend_at_date(ticker: str, ref_date: datetime, dividends: pd.Series, frequency_type: str, freq: int) -> float:
    """
    Calculates the annualized dividend rate at a specific point in time.
    Consistent with calculate_forward_dividend logic.
    Possible error case: return 0 if company just started payind unregular/semi-annual dividends
    and history is insufficient to annualize (e.g. only 1 payment for quarterly-unregular).
    This is intentional to avoid misleading annualized rates based on very limited data.
    """
    past_divs = dividends[dividends.index <= ref_date].sort_index(ascending=False)
    if past_divs.empty:
        return 0.0

    try:
        if frequency_type in ['Monthly', 'Quarterly-Regulary', 'Quartely-Regulary', 'Quarterly']:
            # Check for NaN/NA first, then for 0
            if pd.isna(past_divs.iloc[0]) or past_divs.iloc[0] == 0:
                warning(f"Dividend amount is zero or NaN for {ticker} at {ref_date}. Cannot annualize.")
                return 0.0
            # Last payment × Frequency
            return float(past_divs.iloc[0]) * freq
        elif frequency_type in ['Quarterly-Unregulary', 'Quartely-Unregulary', 'Semi-Annually']:
            # Sum of payments based on frequency type
            ttm_divs = past_divs.head(freq)
            # If there is a zero, NaN or less than freq payments, we cannot annualize reliably
            if ttm_divs.isna().any() or (ttm_divs == 0).any() or len(ttm_divs) < freq:
                warning(f"Dividend history is insufficient for reliable annualization for {ticker} at {ref_date}. History: {past_divs.tolist()}")
                return 0.0
            return float(ttm_divs.sum())
        elif frequency_type in ['Annually']:
            if pd.isna(past_divs.iloc[0]) or past_divs.iloc[0] == 0:
                warning(f"Dividend amount is zero or NaN for {ticker} at {ref_date}. Cannot annualize.")
                return 0.0
            return float(past_divs.iloc[0])
        else:
            warning(f"Unknown frequency type '{frequency_type}' for {ticker}. Cannot annualize.")
            return 0.0
            
    except (IndexError, TypeError) as e:
        error(f"Error calculating annualized dividend for {ticker} at {ref_date}: {e}")
        return 0.0


def calculate_dividend_growth(ticker: str, dividends_df: pd.DataFrame, div_frequency_str: str, currency: str = '', forward_dividend: float = 0.0) -> Dict[str, Optional[tuple]]:
    """
    Calculates dividend growth for various periods: TTM, and 3, 5, 10-year CAGR.
    Uses frequency-aware annualized rates for robust comparisons.
    """
    growth_metrics = {
        'ttm': None,
        'cagr_3y': None,
        'cagr_5y': None,
        'cagr_10y': None
    }

    if dividends_df.empty:
        return growth_metrics

    # dividends_df is expected to have 'date' (index) and 'amount' columns
    # and already be pre-filtered/cleaned by data_loader
    
    # Handle GBp to GBP conversion if not already handled by loader
    if currency in ['GBp', 'GBP', 'GBX'] and dividends_df['amount'].max() > 10:
        dividends_df = dividends_df.copy()
        dividends_df['amount'] = dividends_df['amount'] / 100.0

    # Get frequency multiplier for annualization
    freq = DIVIDEND_FREQ_MAP.get(div_frequency_str, 4)
    today = datetime.now()

    # Consolidate by date to avoid double counting
    dividends_df = dividends_df.groupby(dividends_df.index).agg({'amount': 'max'}).sort_index()

    # --- Calculation for TTM ---
    div_now_ttm = _get_annualized_dividend_at_date(ticker, today, dividends_df['amount'], div_frequency_str, freq)

    # 1. TTM Growth
    one_year_ago_date = today - pd.DateOffset(years=1)
    div_1y_ago_ttm = _get_annualized_dividend_at_date(ticker, one_year_ago_date, dividends_df['amount'], div_frequency_str, freq)

    if div_1y_ago_ttm > 0:
        growth_amount = div_now_ttm - div_1y_ago_ttm
        growth_percentage = (growth_amount / div_1y_ago_ttm)
        growth_metrics['ttm'] = (growth_amount, growth_percentage)
    elif div_now_ttm > 0:
        growth_metrics['ttm'] = (div_now_ttm, None)

    # --- Calculation for CAGR ---
    # div_now_ttm already calculated above
    div_now_cagr_base = div_now_ttm

    for years in [3, 5, 10]:
        ref_date_then = today - pd.DateOffset(years=years)
        div_then_cagr = _get_annualized_dividend_at_date(ticker, ref_date_then, dividends_df['amount'], div_frequency_str, freq)
        if div_then_cagr > 0 and div_now_cagr_base > 0:
            growth_metrics[f'cagr_{years}y'] = calculate_cagr(div_now_cagr_base, div_then_cagr, years)

    return growth_metrics


def calculate_total_dividends(ticker: str, dividends_df: pd.DataFrame, exchange_rate_cache: dict, primary_currency: str):
    """
    Calculates the total dividends for a given ticker using the centralized DataFrame.
    """
    if dividends_df.empty:
        return 0.0, 0.0

    ticker_divs = dividends_df[dividends_df['ticker'] == ticker]
    if ticker_divs.empty:
        return 0.0, 0.0

    total_dividends = 0.0
    total_tax = 0.0

    for _, div in ticker_divs.iterrows():
        amount = div.get('amount', 0)
        currency = div.get('currency')
        date_str = div['date'].strftime('%Y-%m-%d')
        tax = div.get('withholding_tax', 0)

        if currency == primary_currency:
            total_dividends += amount
            total_tax += tax
        else:
            rate = get_rate_from_cache(exchange_rate_cache, currency, primary_currency, date_str)
            if rate:
                total_dividends += amount * rate
                total_tax += tax * rate

    return total_dividends, total_tax


def get_dividend_payment_months(dividend_dates: List[datetime]) -> List[int]:
    """
    Determines the typical months a stock pays dividends based on historical data.
    Looks at all available history if the recent 2-year window is sparse.
    """
    if not dividend_dates:
        return []

    today = datetime.now()
    # Try last 2 years first
    recent_dividends = [d for d in dividend_dates if d.year >= today.year - 2]
    
    # If less than 2 dividends in 2 years, use all available history to find a pattern
    final_dates = recent_dividends if len(recent_dividends) >= 2 else dividend_dates
    
    if not final_dates:
        return []
    
    payment_months = sorted(list(set([d.month for d in final_dates])))
    return payment_months


def get_realized_gain_and_cost(closed_positions: pd.DataFrame, exchange_rate_cache: dict) -> Tuple[float, float]:
    """
    Calculate total realized gain and cost of closed positions in primary currency for a ticker.
    Args:
        closed_positions (pd.DataFrame): DataFrame of closed positions for a ticker.
        exchange_rate_cache (dict): Cache of exchange rates.
    Returns:
        tuple: (total_realized_gain_primary, total_cost_of_closed_positions_primary)
    """

    total_realized_gain_primary = 0.0
    total_cost_of_closed_positions_primary = 0.0

    if closed_positions.empty:
        return 0.0, 0.0

    for _, closed_pos in closed_positions.iterrows():
        gain = closed_pos.get('gross_pl_amount', 0)
        cost = closed_pos.get('purchase_value', 0)
        currency = closed_pos.get('currency')
        open_date = closed_pos.get('open_date')
        close_date = closed_pos.get('close_date')

        if currency == PRIMARY_CURRENCY:
            total_realized_gain_primary += gain
            total_cost_of_closed_positions_primary += cost
        else:
            rate_gain = get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, close_date)
            rate_cost = get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, open_date)
            if rate_gain:
                total_realized_gain_primary += gain * rate_gain
            if rate_cost:
                total_cost_of_closed_positions_primary += cost * rate_cost

    return total_realized_gain_primary, total_cost_of_closed_positions_primary

def _find_next_month_from_pattern(payment_months: List[int], today: datetime, last_dividend_date: datetime) -> tuple:
    """Finds the next payment month and predicted year based on a pattern of months."""
    current_month = today.month
    predicted_year = today.year
    
    next_payment_month = None
    for month in payment_months:
        if month >= current_month:
            next_payment_month = month
            break
    
    if next_payment_month is None:
        next_payment_month = payment_months[0]
        predicted_year += 1
        
    if next_payment_month == current_month and today.day >= last_dividend_date.day:
        if current_month in payment_months:
            current_index = payment_months.index(current_month)
            next_index = (current_index + 1) % len(payment_months)
            if next_index < current_index: # wrapped around
                predicted_year += 1
            next_payment_month = payment_months[next_index]
            
    return next_payment_month, predicted_year


def predict_next_dividend_month(ticker: str, all_dividends_data: pd.DataFrame, div_frequency: str, dividend_dates: List[datetime], payment_months: List[int] = None) -> str:
    """
    Predicts the month and year of the next dividend payment based on historical data pattern.
    Only uses payment_months to determine the next date.
    """
    if not div_frequency or div_frequency == 'N/A' or not dividend_dates or not payment_months:
        return "N/A"

    today = datetime.now()
    
    # Check for future dividend dates already in data
    future_dividends = [d for d in dividend_dates if d > today]
    if future_dividends:
        next_div_date = min(future_dividends)
        return f"{month_name[next_div_date.month]} {next_div_date.year}"

    last_date = dividend_dates[0]
    month, year = _find_next_month_from_pattern(payment_months, today, last_date)
    return f"{month_name[month]} {year}"


def _predict_dividend_per_share(future_date: datetime, div_frequency: str, sorted_history: List[Dict]) -> Optional[Dict]:
    """
    Predicts the dividend per share amount and currency for a future payment date.
    Returns a dictionary like {'amount': 0.50, 'currency': 'USD'} or None.
    """
    if not sorted_history:
        return None

    latest_dividend = sorted_history[0]

    if div_frequency in ['Monthly', 'Quartely-Regulary']:
        return {'amount': latest_dividend.get('amount_per_share'), 'currency': latest_dividend.get('amount_per_share_currency')}

    if div_frequency in ['Annually', 'Semi-Annually', 'Quartely-Unregulary']:
        target_date_last_year = future_date - pd.DateOffset(years=1)
        
        closest_payment = None
        min_delta = timedelta(days=365)

        for payment in sorted_history:
            payment_date = pd.to_datetime(payment['date'])
            delta = abs(payment_date - target_date_last_year)
            if delta < min_delta:
                min_delta = delta
                closest_payment = payment
        
        if closest_payment and min_delta < timedelta(days=45):
             return {'amount': closest_payment.get('amount_per_share'), 'currency': closest_payment.get('amount_per_share_currency')}

    # Fallback for all cases
    return {'amount': latest_dividend.get('amount_per_share'), 'currency': latest_dividend.get('amount_per_share_currency')}


def predict_dividend_income_calendar(all_tickers_data: Dict, dividends_df: pd.DataFrame, exchange_rate_cache: Dict, timeframe_months: int = 12) -> Dict[str, float]:
    """
    Predicts the dividend income calendar for the next 12 months.
    Uses TickerData metrics (padi, div_frequency) for reliable projections, 
    falling back to historical local data if needed.
    """
    projected_income_calendar = {}
    
    today = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    time_limit = today + pd.DateOffset(months=timeframe_months)

    for ticker, details in all_tickers_data.items():
        if details.current_shares <= 0:
            continue

        div_frequency_str = details.div_frequency
        payment_months = details.dividend_payment_months
        padi = details.padi # Annualized income in PRIMARY_CURRENCY

        if not payment_months or not div_frequency_str or div_frequency_str == 'N/A':
            continue

        freq_multiplier = DIVIDEND_FREQ_MAP.get(div_frequency_str, 4)
        income_per_payment = padi / freq_multiplier if freq_multiplier > 0 else 0

        if income_per_payment <= 0:
            continue

        future_payment_dates = []
        for year_offset in range(2):
            year = today.year + year_offset
            for month in payment_months:
                try:
                    payment_date = datetime(year, month, 1)
                    if payment_date >= today and payment_date < time_limit:
                        future_payment_dates.append(payment_date)
                except ValueError:
                    continue
        
        for payment_date in future_payment_dates:
            month_year_str = f"{month_name[payment_date.month]} {payment_date.year}"
            projected_income_calendar[month_year_str] = projected_income_calendar.get(month_year_str, 0.0) + income_per_payment

    return projected_income_calendar

def is_div_growth_above_inflation(div_growth_metrics: Dict[str, Optional[tuple]], inflation_rate: float) -> bool:
    """
    Determines if the dividend growth is above the inflation rate based on available metrics.
    Prioritizes 5-year CAGR, then 3-year CAGR, then TTM growth percentage.
    """
    cagr_5y = div_growth_metrics.get('cagr_5y')
    cagr_3y = div_growth_metrics.get('cagr_3y')
    ttm_growth = div_growth_metrics.get('ttm')

    if cagr_5y is not None:
        return cagr_5y > inflation_rate
    elif cagr_3y is not None:
        return cagr_3y > inflation_rate
    elif ttm_growth and ttm_growth[1] is not None:
        return ttm_growth[1] > inflation_rate

    return False