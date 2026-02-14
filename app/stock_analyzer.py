import pandas as pd
import os
import json

from utils.data_loader import load_all_data, load_market_data
from config import STOCK_ANALYSIS_OUTPUT
from app.analyzer_engine import (
    clean_for_json,
    process_all_tickers,
    calculate_portfolio_summary,
    enrich_ticker_data,
    calculate_portfolio_history
)

def prepare_data(transactions_df):
    """
    Prepare and filter data for analysis.
    """
    transactions_df['open_date_dt'] = pd.to_datetime(transactions_df['open_date'])
    all_tickers = transactions_df['ticker'].unique()
    return all_tickers

def save_analysis_to_json(output_data, filename):
    """
    Save the analysis results to a JSON file.
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    cleaned_data = clean_for_json(output_data)
    with open(filename, 'w') as f:
        json.dump(cleaned_data, f, indent=4, default=str)
    print(f"\nAnalysis results saved to {filename}")

def main():
    print("--- Starting Stock Analyzer ---")
    transactions_df, dividends_data, ticker_map_data, cash_operations_data = load_all_data()
    if transactions_df is None:
        print("Could not load data. Exiting.")
        return

    market_data = load_market_data()
    if not market_data:
        print("Error: Market data cache is empty. Please run Updater first.")
        return

    all_tickers = prepare_data(transactions_df)
    
    # Process using cache
    all_tickers_data = process_all_tickers(transactions_df, dividends_data, ticker_map_data, all_tickers, market_data)

    portfolio_summary = calculate_portfolio_summary(all_tickers_data, transactions_df, dividends_data, cash_operations_data, market_data.get('exchange_rate_cache', {}))

    all_tickers_data = enrich_ticker_data(all_tickers_data, portfolio_summary)

    # Calculate portfolio history
    portfolio_history = calculate_portfolio_history(transactions_df, dividends_data, cash_operations_data, market_data, ticker_map_data)

    output_data = {
        'portfolio_summary': portfolio_summary, 
        'tickers': all_tickers_data,
        'portfolio_history': portfolio_history
    }
    save_analysis_to_json(output_data, STOCK_ANALYSIS_OUTPUT)

if __name__ == '__main__':
    main()
