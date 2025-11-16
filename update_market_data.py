import json
import os
import pandas as pd
import ast
from datetime import datetime

from app.portfolio.portfolio_metrics import get_all_currency_exchange_rate_caches
from config import MARKET_DATA_OUTPUT
from utils.data_fetcher import get_current_prices
from utils.data_loader import load_all_data
from app.stock_analyzer_config import TICKERS_TO_IGNORE

def prepare_data_for_updater(transactions_df):
    """
    Prepare and filter data to find tickers requiring market data updates.
    """
    transactions_df['open_date_dt'] = pd.to_datetime(transactions_df['open_date'])
    open_positions_df = transactions_df[transactions_df['type'] == 'open'].copy()
    tickers_with_open_positions = open_positions_df['ticker'].unique()
    api_tickers = [t for t in tickers_with_open_positions if t not in TICKERS_TO_IGNORE]
    return open_positions_df, api_tickers

def clean_for_json(data):
    """
    Recursively clean a data structure for JSON serialization.
    - Converts pandas DataFrames to a list of dictionaries.
    - Forcefully converts all dictionary keys to strings.
    """
    if isinstance(data, pd.DataFrame):
        return data.reset_index().to_dict('records')
    if isinstance(data, dict):
        return {str(k): clean_for_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [clean_for_json(item) for item in data]
    return data

def default(o):
    if isinstance(o, (datetime, pd.Timestamp)):
        return o.isoformat()
    raise TypeError(f'Object of type {o.__class__.__name__} is not JSON serializable')

def main():
    """
    Fetches the latest market data (stock prices and exchange rates) and saves it to a JSON file.
    """
    print("--- Starting Market Data Updater ---")

    transactions_df, dividends_data, ticker_map_data, _ = load_all_data()
    if transactions_df is None:
        print("Could not load transaction data. Exiting.")
        return

    open_positions_df, api_tickers = prepare_data_for_updater(transactions_df)
    ticker_info = ticker_map_data.get('ticker_info', {})
    country_info = ticker_map_data.get('country_info', {})

    print("\nFetching current market prices...")
    current_prices = get_current_prices(api_tickers)
    print("Finished fetching prices.")

    print("\nFetching all required exchange rates...")
    tickers_with_open_positions = open_positions_df['ticker'].unique()
    api_tickers_with_open_positions = [t for t in tickers_with_open_positions if t not in ticker_info.get('ignore', [])]
    exchange_rate_cache = get_all_currency_exchange_rate_caches(open_positions_df, ticker_info, country_info, dividends_data, api_tickers_with_open_positions)
    print("Finished fetching exchange rates.")

    output_data = {
        'current_prices': current_prices,
        'exchange_rate_cache': exchange_rate_cache
    }

    # Recursively clean the entire data structure before saving
    cleaned_output = clean_for_json(output_data)

    os.makedirs(os.path.dirname(MARKET_DATA_OUTPUT), exist_ok=True)
    with open(MARKET_DATA_OUTPUT, 'w') as f:
        json.dump(cleaned_output, f, indent=4, default=default)

    print(f"\nMarket data saved to {MARKET_DATA_OUTPUT}")


if __name__ == '__main__':
    main()