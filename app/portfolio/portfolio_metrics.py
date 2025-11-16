import pandas as pd
from datetime import datetime
from collections import defaultdict

from utils.data_loader import load_yaml
from utils.data_fetcher import get_batch_historical_rates
from config import PRIMARY_CURRENCY, CASH_OPERATIONS_OUTPUT_FILE

def calculate_free_cash_by_currency(dividends_data: dict, cash_operations_data: dict) -> dict:
    """
    Calculates the total free cash for each currency by summing up:
    - Cash operations (deposits, withdrawals, other operations)
    - Dividends received
    """
    free_cash = defaultdict(float)

    # Process cash operations
    operations = cash_operations_data.get('other_operations', [])
    for op in operations:
        amount = op.get('amount', 0)
        currency = op.get('currency')
        if currency and amount:
            free_cash[currency] += amount

    return dict(free_cash)

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

def get_cash_operations_summary(exchange_rate_cache: dict) -> tuple[float, datetime | None]:
    """
    Calculates net capital contributed and finds the first operation date.
    """
    try:
        cash_operations_data = load_yaml(CASH_OPERATIONS_OUTPUT_FILE)
    except FileNotFoundError:
        print(f"Warning: {CASH_OPERATIONS_OUTPUT_FILE} not found. Cannot calculate net capital.")
        return 0.0, None

    net_capital = 0
    first_date = None
    operations = cash_operations_data.get('other_operations', [])

    for op in operations:
        op_type = op.get('type')
        if op_type in ['deposit', 'withdrawal']:
            amount = op.get('amount', 0)
            currency = op.get('currency')
            date_str = op.get('date')

            if date_str:
                current_date = datetime.strptime(date_str, '%Y-%m-%d')
                if first_date is None or current_date < first_date:
                    first_date = current_date

            if currency == PRIMARY_CURRENCY:
                net_capital += amount
            else:
                if date_str:
                    rate = get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, date_str)
                    if rate:
                        net_capital += amount * rate
                    else:
                        print(f"Warning: Could not find exchange rate for {currency} on {date_str} for a cash operation. Skipping.")
                else:
                    print("Warning: Missing date for a non-primary currency cash operation. Skipping.")

    return net_capital, first_date

def get_other_cash_operations_summary(exchange_rate_cache: dict) -> dict:
    """
    Calculates the sum of amounts for each cash operation type.
    """
    try:
        cash_operations_data = load_yaml(CASH_OPERATIONS_OUTPUT_FILE)
    except FileNotFoundError:
        print(f"Warning: {CASH_OPERATIONS_OUTPUT_FILE} not found. Cannot calculate other operations summary.")
        return {}

    operation_sums = {}
    operations = cash_operations_data.get('other_operations', [])

    for op in operations:
        op_type = op.get('type')
        amount = op.get('amount', 0)
        currency = op.get('currency')
        
        if not op_type or not currency or not amount:
            continue

        if op_type not in operation_sums:
            operation_sums[op_type] = {}

        operation_sums[op_type][currency] = operation_sums[op_type].get(currency, 0) + amount

    return operation_sums

def get_portfolio_dividends_per_year(all_dividends_data: dict, exchange_rate_cache: dict, primary_currency: str) -> dict[int, float]:
    """
    Calculates the total portfolio dividends for each year in the primary currency.
    """
    portfolio_dividends_by_year = {}

    if not all_dividends_data:
        return portfolio_dividends_by_year

    for ticker, company_data in all_dividends_data.get('companies', {}).items():
        for dividend in company_data.get('dividends', []):
            amount = dividend.get('amount', 0)
            currency = dividend.get('currency')
            date_str = dividend.get('date')

            if not currency or not date_str or not amount:
                continue

            try:
                dividend_date = datetime.strptime(date_str, '%Y-%m-%d')
                year = dividend_date.year
            except ValueError:
                print(f"Warning: Could not parse date '{date_str}' for a dividend from {ticker}. Skipping.")
                continue

            converted_amount = amount
            if currency != primary_currency:
                rate = get_rate_from_cache(exchange_rate_cache, currency, primary_currency, date_str)
                if rate:
                    converted_amount *= rate
                else:
                    print(f"Warning: Could not find exchange rate for {currency} on {date_str} for a dividend. Skipping.")
                    continue
            
            portfolio_dividends_by_year[year] = portfolio_dividends_by_year.get(year, 0) + converted_amount

    return portfolio_dividends_by_year

def get_portfolio_dividends_ltm(all_dividends_data: dict, exchange_rate_cache: dict, primary_currency: str) -> float:
    """
    Calculates the portfolio dividends from last twelve months.
    """

    portfolio_dividends_ltm = 0

    today = datetime.now()
    t12m_start = today - pd.DateOffset(months=12)

    if not all_dividends_data:
        return portfolio_dividends_ltm
    
    for ticker, company_data in all_dividends_data.get('companies', {}).items():
        for dividend in company_data.get('dividends', []):
            amount = dividend.get('amount', 0)
            currency = dividend.get('currency')
            date_str = dividend.get('date')

            if not currency or not date_str or not amount:
                continue
            
            try:
                  dividend_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                  # This warning can be noisy, you might want to remove it if dates are often invalid
                  print(f"Warning: Could not parse date '{date_str}' for a dividend from {ticker}. Skipping.")
                  continue
            
            if t12m_start <= dividend_date <= today:
                converted_amount = amount
                if currency != primary_currency:
                    rate = get_rate_from_cache(exchange_rate_cache, currency, primary_currency, date_str)
                    if rate:
                        converted_amount *= rate
                    else:
                        print(f"Warning: Could not find exchange rate for {currency} on {date_str} for a dividend. Skipping.")
                        continue
                
                portfolio_dividends_ltm += converted_amount

    return portfolio_dividends_ltm