import pandas as pd
from datetime import datetime

from utils.data_fetcher import get_batch_historical_rates
from config import PRIMARY_CURRENCY

def get_rate_from_cache(cache: dict, from_currency: str, to_currency: str, date_str: str) -> float:
    """Looks up an exchange rate from a local cache for a specific date."""
    rate_data = cache.get(f"{from_currency}{to_currency}")
    if rate_data is None:
        return None

    rate_df = pd.DataFrame(rate_data)
    if rate_df.empty:
        return None

    rate_df['Date'] = pd.to_datetime(rate_df['Date'])
    rate_df.set_index('Date', inplace=True)

    try:
        target_date = pd.to_datetime(date_str)
        idx = rate_df.index.get_indexer([target_date], method='nearest')[0]
        # The column name is now dynamic, so we need to find it
        close_col = [col for col in rate_df.columns if 'Close' in col][0]
        rate_value = rate_df[close_col].iloc[idx]
        return rate_value.item()
    except Exception:
        return None

def get_all_currency_exchange_rate_caches(open_positions_df: pd.DataFrame, ticker_info: dict, country_info: dict, dividends_data: dict, tickers_with_open_positions: list) -> dict:
    
    exchange_rate_cache = {}
    purchase_currencies = open_positions_df[open_positions_df['currency'] != PRIMARY_CURRENCY]['currency'].unique()
    price_currencies = set()
    for ticker in tickers_with_open_positions:
        country = ticker_info.get(ticker, {}).get('country')
        price_currency = country_info.get(country, {}).get('currency')
        if price_currency and price_currency != PRIMARY_CURRENCY:
            price_currencies.add(price_currency)

    dividend_currencies = set()
    if dividends_data:
        for company, data in dividends_data.get('companies', {}).items():
            for dividend in data.get('dividends', []):
                currency = dividend.get('currency')
                if currency and currency != PRIMARY_CURRENCY:
                    dividend_currencies.add(currency)

    all_currencies_to_convert = set(purchase_currencies) | price_currencies | dividend_currencies

    if all_currencies_to_convert and not open_positions_df.empty:
        min_date = open_positions_df['open_date_dt'].min().strftime('%Y-%m-%d')
        max_date = datetime.now().strftime('%Y-%m-%d')
        for currency in all_currencies_to_convert:
            print(f"Fetching rates for {currency} to {PRIMARY_CURRENCY}...")
            rates_df = get_batch_historical_rates(currency, PRIMARY_CURRENCY, min_date, max_date)
            exchange_rate_cache[f"{currency}{PRIMARY_CURRENCY}"] = rates_df

    return exchange_rate_cache
