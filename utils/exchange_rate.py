import pandas as pd
from datetime import datetime

from utils.data_fetcher import get_batch_historical_rates
from config import PRIMARY_CURRENCY

def normalize_currency(currency: str) -> str:
    """Standardizes currency codes (e.g., GBp -> GBP)."""
    if not currency:
        return currency
    c = currency.upper()
    if c in ['GBP', 'GBX', 'GBP']: # GBp is sometimes reported as GBX or GBP
        return 'GBP'
    if c == 'GBp': # yfinance case
        return 'GBP'
    return c

def get_rate_from_cache(cache: dict, from_currency: str, to_currency: str, date_str: str) -> float:
    """Looks up an exchange rate from a local cache for a specific date."""
    from_currency = normalize_currency(from_currency)
    to_currency = normalize_currency(to_currency)
    
    rate_data = cache.get(f"{from_currency}{to_currency}")
    if rate_data is None:
        return None

    # If it's already a DataFrame (thanks to rehydrate_data), great. Otherwise convert it.
    if not isinstance(rate_data, pd.DataFrame):
        rate_df = pd.DataFrame(rate_data)
    else:
        rate_df = rate_data.copy()

    if rate_df.empty:
        return None

    # Identify date column and set as index if needed
    # Yahoo download with multi-index can result in weird column names like "('Date', '')"
    date_col = next((c for c in rate_df.columns if 'Date' in str(c)), None)
    if date_col:
        rate_df[date_col] = pd.to_datetime(rate_df[date_col])
        rate_df.set_index(date_col, inplace=True)
    
    if not isinstance(rate_df.index, pd.DatetimeIndex):
        try:
            # Maybe the index itself is date-like strings
            rate_df.index = pd.to_datetime(rate_df.index)
        except Exception:
            # If still not DatetimeIndex, this cache entry is unusable
            return None

    # CRITICAL: Index must be sorted for get_indexer with method='nearest'
    rate_df = rate_df.sort_index()

    try:
        target_date = pd.to_datetime(date_str)
        # Handle cases with non-unique index
        if not rate_df.index.is_unique:
             rate_df = rate_df[~rate_df.index.duplicated(keep='last')]
             
        idx = rate_df.index.get_indexer([target_date], method='nearest')[0]
        if idx == -1:
            return None
        
        # Identify value column (Rate, Close, or Adj Close)
        rate_col = next((c for c in ['Rate', 'Close', 'Adj Close'] if c in rate_df.columns), None)
        
        if not rate_col:
            # Fallback to any column that contains 'Close' (handles tuple strings like "('Close', 'USD...=X')")
            rate_col = next((c for c in rate_df.columns if 'Close' in str(c)), None)
            
        if not rate_col:
            return None

        rate_value = rate_df[rate_col].iloc[idx]
        return float(rate_value)
    except Exception:
        return None

def get_all_currency_exchange_rate_caches(transactions_df: pd.DataFrame, ticker_info: dict, country_info: dict, dividends_data: dict, api_tickers: list) -> dict:
    
    exchange_rate_cache = {}
    
    # 1. Determine all required currencies
    currencies = set()
    if not transactions_df.empty:
        currencies.update(transactions_df['currency'].dropna().unique())
    
    # Add currencies from country info for tickers
    for ticker in api_tickers:
        country = ticker_info.get(ticker, {}).get('country')
        price_currency = country_info.get(country, {}).get('currency')
        if price_currency:
            currencies.add(normalize_currency(price_currency))

    # Add currencies from dividends
    if dividends_data:
        for company, data in dividends_data.get('companies', {}).items():
            for dividend in data.get('dividends', []):
                if dividend.get('currency'):
                    currencies.add(normalize_currency(dividend['currency']))
                if dividend.get('amount_per_share_currency'):
                    currencies.add(normalize_currency(dividend['amount_per_share_currency']))

    all_currencies_to_convert = {c for c in currencies if c and c != PRIMARY_CURRENCY}

    # 2. Determine required date range
    all_dates = []
    if not transactions_df.empty:
        all_dates.extend(pd.to_datetime(transactions_df['open_date']).dropna().tolist())
        if 'close_date' in transactions_df.columns:
            all_dates.extend(pd.to_datetime(transactions_df['close_date']).dropna().tolist())
    
    if dividends_data:
        for company in dividends_data.get('companies', {}).values():
            for dividend in company.get('dividends', []):
                if dividend.get('date'):
                    all_dates.append(pd.to_datetime(dividend['date']))

    if not all_dates:
        all_dates = [datetime.now()]

    # Start date is the earliest recorded event minus 30 days for safety
    start_date = (min(all_dates) - pd.Timedelta(days=30)).strftime('%Y-%m-%d')
    end_date = (datetime.now() + pd.Timedelta(days=1)).strftime('%Y-%m-%d')

    # 3. Fetch rates
    if all_currencies_to_convert:
        for currency in sorted(list(all_currencies_to_convert)):
            print(f"Fetching rates for {currency} to {PRIMARY_CURRENCY} ({start_date} to {end_date})...")
            rates_df = get_batch_historical_rates(currency, PRIMARY_CURRENCY, start_date, end_date)
            if not rates_df.empty:
                exchange_rate_cache[f"{currency}{PRIMARY_CURRENCY}"] = rates_df

    return exchange_rate_cache
