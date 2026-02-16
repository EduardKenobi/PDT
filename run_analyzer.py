import pandas as pd
import os
import json
import time
from datetime import datetime

from utils.data_loader import load_all_data, load_market_data
from config import STOCK_ANALYSIS_OUTPUT, PRIMARY_CURRENCY
from app.portfolio.portfolio_metrics import get_ibkr_free_cash
from utils.json_utils import clean_for_json, default_serialize
from app.stock.stock_processor import process_all_tickers
from app.portfolio.portfolio_processor import (
    calculate_portfolio_summary, 
    enrich_ticker_data, 
    calculate_portfolio_history
)
from app.history.history_helpers import (
    _prepare_dividend_history_df,
    _get_month_ends,
    _prepare_monthly_portfolio_metrics
)

def save_analysis_to_json(output_data, filename):
    """
    Save the analysis results to a JSON file.
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    cleaned_data = clean_for_json(output_data)
    with open(filename, 'w') as f:
        json.dump(cleaned_data, f, indent=4, default=default_serialize)
    print(f"\nAnalysis results saved to {filename}")

def get_data_for_analyzer():
    """
    Prepare and filter data for analysis.
    """
    transactions_df, dividends_data, ticker_map_data, cash_operations_data, all_tickers, month_ends, div_df = load_all_data()
    if transactions_df is None:
        print("Could not load data. Exiting.")
        return

    market_data = load_market_data()
    if not market_data:
        print("Error: Market data cache is empty. Please run Updater first.")
        return
    
    return transactions_df, dividends_data, ticker_map_data, cash_operations_data, all_tickers, month_ends, div_df, market_data

def get_stock_analysis_output_data_by_attribute(attribute):
    """
    Get existing analysis data for a specific attribute.
    """
    existing_attribute_data = {}
    if os.path.exists(STOCK_ANALYSIS_OUTPUT):
        try:
            with open(STOCK_ANALYSIS_OUTPUT, 'r') as f:
                existing_data = json.load(f)
                existing_attribute_data = existing_data.get(attribute, {})
        except Exception as e:
            print(f"      Warning: Could not load existing analysis for {attribute}: {e}")
    return existing_attribute_data

def main():
    total_start_time = time.time()
    print("\n" + "="*40)
    print("      STOCK ANALYZER - PROGRESS      ")
    print("="*40)

    # 1. Load Data
    print("\n[1/7] Loading data and market data...")
    start_time = time.time()
    transactions_df, dividends_data, ticker_map_data, cash_operations_data, all_tickers, month_ends, div_df, market_data = get_data_for_analyzer()
    print(f"      Finished in {time.time() - start_time:.2f}s")

    # 2. Prepare Monthly Portfolio Metrics (Cash, Deposits, Dividends)
    print("\n[2/7] Preparing monthly portfolio metrics...")
    start_time = time.time()
    exchange_rate_cache = market_data.get('exchange_rate_cache', {})
    ibkr_cash_primary = market_data.get('ibkr_cash_primary', 0) # Use from cache or calculate
    # Note: ibkr_cash_primary in analyzer_engine is fetched via get_ibkr_free_cash().
    # Let's align with analyzer_engine's logic.
    ibkr_cash_primary_val = get_ibkr_free_cash().get(PRIMARY_CURRENCY, 0)
    
    other_ops = pd.DataFrame(cash_operations_data.get('other_operations', []))
    if not other_ops.empty:
        other_ops['date_dt'] = pd.to_datetime(other_ops['date'])
    
    # Need first_ibkr_date
    ibkr_trades = transactions_df[transactions_df['broker'] == 'ibkr']
    first_ibkr_date = ibkr_trades['open_date_dt'].min() if not ibkr_trades.empty else None

    monthly_metrics = _prepare_monthly_portfolio_metrics(month_ends, div_df, other_ops, exchange_rate_cache, ibkr_cash_primary_val, first_ibkr_date)
    print(f"      Finished in {time.time() - start_time:.2f}s")
    
    # 3. Process Tickers
    print(f"\n[3/7] Processing {len(all_tickers)} tickers (Incremental)...")
    start_time = time.time()
    existing_tickers_data = get_stock_analysis_output_data_by_attribute('tickers')
    all_tickers_data = process_all_tickers(transactions_df, dividends_data, ticker_map_data, all_tickers, market_data, existing_tickers_data, div_df, month_ends)
    print(f"      Finished in {time.time() - start_time:.2f}s")

    # 4. Portfolio Summary
    print("\n[4/7] Calculating portfolio summary...")
    start_time = time.time()
    portfolio_summary = calculate_portfolio_summary(all_tickers_data, transactions_df, dividends_data, cash_operations_data, market_data.get('exchange_rate_cache', {}), div_df)
    print(f"      Finished in {time.time() - start_time:.2f}s")

    # 5. Enrich Tickers
    print("\n[5/7] Enrichening ticker data...")
    start_time = time.time()
    all_tickers_data = enrich_ticker_data(all_tickers_data, portfolio_summary)
    print(f"      Finished in {time.time() - start_time:.2f}s")

    # 6. Portfolio History
    print("\n[6/7] Generating portfolio history...")
    start_time = time.time()
    existing_history = get_stock_analysis_output_data_by_attribute('portfolio_history')
    portfolio_history = calculate_portfolio_history(transactions_df, dividends_data, cash_operations_data, market_data, ticker_map_data, all_tickers_data, existing_history, div_df, month_ends, monthly_metrics)
    print(f"      Finished in {time.time() - start_time:.2f}s")

    # 7. Save Results
    print("\n[7/7] Saving analysis output...")
    start_time = time.time()
    output_data = {
        'portfolio_summary': portfolio_summary, 
        'tickers': all_tickers_data,
        'portfolio_history': portfolio_history
    }
    save_analysis_to_json(output_data, STOCK_ANALYSIS_OUTPUT)
    print(f"      Finished in {time.time() - start_time:.2f}s")

    print("\n" + "="*40)
    print(f"   ANALYSIS COMPLETE - Total time: {time.time() - total_start_time:.2f}s")
    print("="*40 + "\n")

if __name__ == '__main__':
    main()
