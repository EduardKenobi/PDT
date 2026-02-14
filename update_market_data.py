import json
import os
import pandas as pd
import warnings
from datetime import datetime
from typing import Dict, Any, List

# Suppress pandas SettingWithCopyWarning for cleaner output
warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)

from config import MARKET_DATA_OUTPUT, PRIMARY_CURRENCY
from utils.exchange_rate import get_all_currency_exchange_rate_caches
from utils.data_fetcher import get_batch_history_data, get_ticker_info_batch
from utils.data_loader import load_all_data
from app.stock_analyzer_config import TICKERS_TO_IGNORE
from app.stock.stock_metrics import calculate_average_dividend_yield, calculate_dividend_growth

def clean_for_json(data):
    if isinstance(data, pd.DataFrame):
        return data.reset_index().to_dict('records')
    if isinstance(data, dict):
        # Convert all keys to strings (handles tuple keys from metrics)
        return {str(k): clean_for_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [clean_for_json(item) for item in data]
    return data

def default_serialize(o):
    if isinstance(o, (datetime, pd.Timestamp)):
        return o.isoformat()
    return str(o)

def process_batch_metrics(symbol: str, ticker_df: pd.DataFrame, freq: str = "Quarterly") -> dict:
    """
    Calculates dynamic metrics from a pre-fetched ticker DataFrame.
    """
    if ticker_df.empty:
        return {"price": None, "avg_yield_5y": 0, "growth": {}, "dividend_dates": [], "monthly_prices": {}}
    
    ticker_df = ticker_df.copy()
    # Ensure numeric types for critical columns
    for col in ['Close', 'Dividends']:
        if col in ticker_df.columns:
            ticker_df[col] = pd.to_numeric(ticker_df[col], errors='coerce')
    try:
        if 'Close' not in ticker_df.columns:
            return {"price": None, "avg_yield_5y": 0, "growth": {}, "dividend_dates": [], "monthly_prices": {}}
        cleaned_close = ticker_df['Close'].dropna()
        current_price = float(cleaned_close.iloc[-1]) if not cleaned_close.empty else None
    except Exception:
        current_price = None

    # Avg Yield & Growth
    avg_yield = calculate_average_dividend_yield(symbol, ticker_df)
    growth = calculate_dividend_growth(ticker_df, freq)
    
    # Dividend Dates (from 'Dividends' column where > 0)
    div_dates = []
    if 'Dividends' in ticker_df.columns:
        try:
            div_payouts = ticker_df[ticker_df['Dividends'] > 0]
            div_dates = [d.strftime('%Y-%m-%d') for d in div_payouts.index]
        except Exception:
            div_dates = []
    
    # Monthly Prices (End of Month)
    monthly_prices = {}
    try:
        # Resample to month end and get the last price of each month
        resampled = ticker_df['Close'].resample('ME').last()
        for date, price in resampled.items():
            if pd.notna(price):
                monthly_prices[date.strftime('%Y-%m-%d')] = float(price)
    except Exception as e:
        print(f"Warning: Could not calculate monthly prices for {symbol}: {e}")

    return {
        "price": current_price,
        "avg_yield_5y": avg_yield,
        "growth": growth,
        "dividend_dates": div_dates,
        "monthly_prices": monthly_prices,
        "last_update": datetime.now().isoformat()
    }

def main():
    print("--- Starting Ultra-Fast Market Data Updater ---")

    # 1. Load context
    transactions_df, dividends_data, ticker_map_data, _ = load_all_data()
    if transactions_df is None:
        print("Error: Could not load data.")
        return

    all_tickers = transactions_df['ticker'].unique()
    api_tickers = [t for t in all_tickers if t not in TICKERS_TO_IGNORE and pd.notna(t)]
    
    # 2. Load existing cache
    cache = {"tickers": {}, "exchange_rate_cache": {}}
    if os.path.exists(MARKET_DATA_OUTPUT):
        try:
            with open(MARKET_DATA_OUTPUT, 'r') as f:
                cache = json.load(f)
        except Exception:
            pass

    if "tickers" not in cache: cache["tickers"] = {}

    # 3. Handle Static Info (Only for new tickers - Slow but once per life)
    new_tickers = [t for t in api_tickers if t not in cache["tickers"] or "static" not in cache["tickers"][t]]
    if new_tickers:
        print(f"New tickers detected: {new_tickers}")
        static_infos = get_ticker_info_batch(new_tickers)
        for t, info in static_infos.items():
            if t not in cache["tickers"]: cache["tickers"][t] = {}
            cache["tickers"][t]["static"] = info

    # 4. Handle Dynamic Data (ALL at once - Super fast)
    print(f"Fetching bulk market data for {len(api_tickers)} tickers...")
    batch_df = get_batch_history_data(api_tickers, period="12y")
    
    print("Processing metrics from batch data...")
    ticker_info = ticker_map_data.get('ticker_info', {})
    for t in api_tickers:
        try:
            if len(api_tickers) > 1:
                # Use .get() or handle KeyError if ticker missing from batch result
                if t in batch_df.columns.levels[0]:
                    ticker_df = batch_df[t]
                else:
                    print(f"  Warning: No data found for {t} in batch download.")
                    ticker_df = pd.DataFrame()
            else:
                ticker_df = batch_df
            
            # Retrieve real frequency
            freq = ticker_info.get(t, {}).get('div_frequency', 'Quarterly')
            dynamic_data = process_batch_metrics(t, ticker_df, freq)
            
            if t not in cache["tickers"]: cache["tickers"][t] = {}
            cache["tickers"][t]["dynamic"] = dynamic_data
        except Exception as e:
            if str(e) == "'Dividends'" or str(e) == "'Close'":
                 print(f"  Note: Could not process metrics for {t} (likely delisted or no data).")
            else:
                 print(f"  Warning: Could not process metrics for {t}: {e}")

    # 5. Handle Exchange Rates
    print("Updating exchange rates for all transactions and dividends...")
    ticker_info = ticker_map_data.get('ticker_info', {})
    country_info = ticker_map_data.get('country_info', {})
    
    exchange_rate_cache = get_all_currency_exchange_rate_caches(
        transactions_df, ticker_info, country_info, dividends_data, api_tickers
    )
    cache["exchange_rate_cache"] = clean_for_json(exchange_rate_cache)

    # 6. Save
    os.makedirs(os.path.dirname(MARKET_DATA_OUTPUT), exist_ok=True)
    # Recursively clean the entire structure to ensure no tuples or DataFrames remain
    final_cache = clean_for_json(cache)
    with open(MARKET_DATA_OUTPUT, 'w') as f:
        json.dump(final_cache, f, indent=4, default=default_serialize)

    print(f"\nOptimization complete. Bulk market data saved to {MARKET_DATA_OUTPUT}")

if __name__ == '__main__':
    main()