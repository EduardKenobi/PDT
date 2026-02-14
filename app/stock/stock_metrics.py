import pandas as pd
from datetime import datetime, timedelta
from app.portfolio.portfolio_metrics import get_rate_from_cache
from config import PRIMARY_CURRENCY, DIVIDEND_FREQ_MAP
from calendar import month_name
from typing import List, Dict, Optional
from utils.analytics import calculate_cagr
def _get_historical_dividend_dates(ticker: str, all_dividends_data: dict, cached_history: Optional[List[str]] = None) -> List[datetime]:
    """
    Gets a reliable list of historical dividend dates.
    Prioritizes local payment dates. Falls back to cached history.
    """
    # 1. Try local payment dates first (from broker reports)
    local_ticker_dividends = all_dividends_data.get('companies', {}).get(ticker, {}).get('dividends', [])
    if local_ticker_dividends:
        payment_dates = sorted([pd.to_datetime(div['date']) for div in local_ticker_dividends], reverse=True)
        if len(payment_dates) >= 2:
            return payment_dates

    # 2. Fallback to cached history (from yfinance fetched in update_market_data)
    if cached_history:
        return sorted([pd.to_datetime(date) for date in cached_history], reverse=True)

    # 3. Return what we have
    if local_ticker_dividends:
        return sorted([pd.to_datetime(div['date']) for div in local_ticker_dividends], reverse=True)
    
    return []

    # 3. Return empty if no source found, but check for any remaining local dates
    if local_ticker_dividends:
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

def _calculate_annualized_dividend_at(ref_date: datetime, dividends: pd.Series, freq: Optional[int]) -> float:
    """
    Calculates the annualized dividend at a specific point in time.
    Uses (last_payment * frequency) if frequency is known, otherwise fallback to trailing 12m sum.
    """
    # Look at dividends strictly BEFORE ref_date
    past_divs = dividends[dividends.index < ref_date]
    if past_divs.empty:
        return 0.0
            
    if freq:
        # Robust method: Last payment * Freq
        return float(past_divs.iloc[-1] * freq)
    else:
        # Fallback: Trailing 12 months sum
        t12m_start = ref_date - pd.DateOffset(months=12)
        return float(past_divs[past_divs.index >= t12m_start].sum())

def calculate_dividend_growth(history_df, div_frequency_str):
    """
    Calculates dividend growth for various periods: TTM, and 3, 5, 10-year CAGR.
    CAGR is the annualized growth rate.
    """
    growth_metrics = {
        'ttm': None,
        '3y': None,
        '5y': None,
        '10y': None
    }

    if history_df.empty:
        return growth_metrics

    history_df = history_df.copy() # Avoid SettingWithCopyWarning
    
    if 'Dividends' not in history_df.columns:
        return growth_metrics
        
    history_df['Dividends'] = pd.to_numeric(history_df['Dividends'], errors='coerce')
    dividends = history_df['Dividends'][history_df['Dividends'] > 0]
    if dividends.empty:
        return growth_metrics

    dividends.index = pd.to_datetime(dividends.index)
    if dividends.index.tz is not None:
        dividends.index = dividends.index.tz_localize(None)

    # Deduplicate by date: if multiple entries exist for the same day (across brokers/accounts), take the max one (usually the base DPS).
    dividends = dividends.groupby(level=0).max()

    freq = DIVIDEND_FREQ_MAP.get(div_frequency_str)
    today = datetime.now()

    # --- Calculation for periods ---
    div_now = _calculate_annualized_dividend_at(today, dividends, freq)
    
    # 1. TTM Growth
    div_1y_ago = _calculate_annualized_dividend_at(today - pd.DateOffset(years=1), dividends, freq)
    if div_1y_ago > 0:
        growth_amount = div_now - div_1y_ago
        growth_percentage = (growth_amount / div_1y_ago)
        growth_metrics['ttm'] = (growth_amount, growth_percentage)
    elif div_now > 0:
        growth_metrics['ttm'] = (div_now, None)

    # 2. CAGR Calculation (3, 5, 10 years)
    for years in [3, 5, 10]:
        div_then = _calculate_annualized_dividend_at(today - pd.DateOffset(years=years), dividends, freq)
        if div_then > 0 and div_now > 0:
            growth_metrics[f'{years}y'] = calculate_cagr(div_now, div_then, years)

    return growth_metrics


def calculate_total_dividends(ticker, all_dividends_data, exchange_rate_cache, primary_currency):
    """
    Calculates the total dividends for a given ticker, converting currencies if necessary.
    """
    total_dividends = 0
    total_tax = 0
    if not all_dividends_data:
        return total_dividends, total_tax

    ticker_dividends = all_dividends_data.get('companies', {}).get(ticker, {}).get('dividends', [])

    for dividend in ticker_dividends:
        amount = dividend.get('amount', 0)
        currency = dividend.get('currency')
        date = dividend.get('date')
        tax = dividend.get('withholding_tax')

        if not currency or not date:
            continue

        if currency == primary_currency:
            total_dividends += amount
            total_tax += tax
        else:
            rate = get_rate_from_cache(exchange_rate_cache, currency, primary_currency, date)
            if rate:
                total_dividends += amount * rate
                total_tax += tax * rate

    return total_dividends, total_tax


def get_dividend_payment_months(ticker: str, all_dividends_data: dict, cached_history: List[str] = None) -> List[int]:
    """
    Determines the typical months a stock pays dividends based on historical data.
    """
    dividend_dates = _get_historical_dividend_dates(ticker, all_dividends_data, cached_history)
    if not dividend_dates:
        return []

    today = datetime.now()
    recent_dividends = [d for d in dividend_dates if d.year >= today.year - 2]
    
    if not recent_dividends:
        return []
    
    payment_months = sorted(list(set([d.month for d in recent_dividends])))
    return payment_months


def get_realized_gain_and_cost(closed_positions: dict, exchange_rate_cache: dict) -> float:
    """
    Calculate total realized gain and cost of closed positions in primary currency for a ticker.
    Args:
        closed_positions (dict): DataFrame of closed positions for a ticker.
        exchange_rate_cache (dict): Cache of exchange rates.
    Returns:
        tuple: (total_realized_gain_primary, total_cost_of_closed_positions_primary)
    """

    total_realized_gain_primary = 0
    total_cost_of_closed_positions_primary = 0

    for _, closed_pos in closed_positions.iterrows():
            gain = closed_pos.get('gross_pl_amount', 0)
            cost = closed_pos.get('purchase_value', 0)
            currency = closed_pos.get('currency')
            open_date = closed_pos.get('open_date')
            close_date = closed_pos.get('close_date')

            if not currency or not close_date or not open_date:
                continue

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

def predict_next_dividend_month(ticker: str, all_dividends_data: dict, div_frequency: str, cached_history: List[str] = None) -> str:
    """
    Predicts the month and year of the next dividend payment based on historical data.
    """
    if not div_frequency or div_frequency == 'N/A':
        return "N/A"

    dividend_dates = _get_historical_dividend_dates(ticker, all_dividends_data, cached_history)

    if not dividend_dates:
        return "N/A"

    today = datetime.now()
    last_dividend_date = dividend_dates[0]

    # Check for future dividend dates already in data
    future_dividends = [d for d in dividend_dates if d > today]
    if future_dividends:
        next_div_date = min(future_dividends)
        return f"{month_name[next_div_date.month]} {next_div_date.year}"

    # --- New logic: Use payment month pattern if enough data ---
    recent_dividends = [d for d in dividend_dates if d > today - pd.DateOffset(years=2)]
    
    freq_map_counts = {
        'Monthly': 10,
        'Quartely-Regulary': 6,
        'Quartely-Unregulary': 4,
        'Semi-Annually': 3,
        'Annually': 2
    }
    
    if len(recent_dividends) >= freq_map_counts.get(div_frequency, 99):
        payment_months = sorted(list(set([d.month for d in recent_dividends])))
        
        current_month = today.month
        predicted_year = today.year
        
        next_payment_month = None
        for month in payment_months:
            if month >= current_month:
                next_payment_month = month
                break
        
        if next_payment_month is None and payment_months:
            next_payment_month = payment_months[0]
            predicted_year += 1
            
        if next_payment_month:
            if last_dividend_date.month == current_month and today.day >= last_dividend_date.day:
                if current_month in payment_months:
                    current_index = payment_months.index(current_month)
                    next_index = (current_index + 1) % len(payment_months)
                    if next_index < current_index: # wrapped around
                        predicted_year += 1
                    next_payment_month = payment_months[next_index]


            return f"{month_name[next_payment_month]} {predicted_year}"

    # --- Fallback to simple interval logic ---
    freq_map_interval = {
        'Monthly': 1,
        'Quartely-Regulary': 3,
        'Quartely-Unregulary': 3,
        'Semi-Annually': 6,
        'Annually': 12
    }
    
    month_interval = freq_map_interval.get(div_frequency)
    
    if not month_interval:
        return "N/A"

    predicted_date = last_dividend_date
    
    while predicted_date <= today:
        predicted_date = predicted_date + pd.DateOffset(months=month_interval)

    return f"{month_name[predicted_date.month]} {predicted_date.year}"


def _predict_dividend_per_share(
    future_date: datetime,
    div_frequency: str,
    sorted_history: List[Dict]
) -> Optional[Dict]:
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


def predict_dividend_income_calendar(
    all_tickers_data: Dict,
    dividends_data: Dict,
    exchange_rate_cache: Dict,
    timeframe_months: int = 12
) -> Dict[str, float]:
    
    projected_income_calendar = {}
    
    today = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    time_limit = today + pd.DateOffset(months=timeframe_months)

    for ticker, details in all_tickers_data.items():
        if details.current_shares <= 0:
            continue

        div_frequency = details.div_frequency
        payment_months = details.dividend_payment_months
        current_shares = details.current_shares

        if not payment_months or not div_frequency:
            continue

        history = dividends_data.get('companies', {}).get(ticker, {}).get('dividends', [])
        if not history:
            continue
        
        history.sort(key=lambda x: pd.to_datetime(x['date']), reverse=True)

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
            predicted_dps = _predict_dividend_per_share(
                payment_date, div_frequency, history
            )

            if not predicted_dps or predicted_dps.get('amount') is None:
                continue

            total_dividend = predicted_dps['amount'] * current_shares
            
            income_primary_currency = total_dividend
            if predicted_dps['currency'] != PRIMARY_CURRENCY:
                rate = get_rate_from_cache(exchange_rate_cache, predicted_dps['currency'], PRIMARY_CURRENCY, today.strftime('%Y-%m-%d'))
                if rate:
                    income_primary_currency *= rate
                else:
                    continue
            
            month_year_str = f"{month_name[payment_date.month]} {payment_date.year}"
            projected_income_calendar[month_year_str] = projected_income_calendar.get(month_year_str, 0.0) + income_primary_currency

    return projected_income_calendar