from collections import defaultdict
from parser import get_parser_functions
from utils.data_loader import load_yaml
from utils.output_writer import save_data_to_yaml
from config import (
    ACCOUNTS,
    TICKER_MAP_FILE,
    TRANSACTIONS_OUTPUT_FILE,
    DIVIDEND_OUTPUT_FILE,
    CASH_OPERATIONS_OUTPUT_FILE
)

def main():
    """
    Main function to orchestrate the parsing of broker data.
    """
    # This could be made dynamic, e.g., via command-line arguments.
    broker_name = 'xtb' 
    print(f"--- Running parser for broker: {broker_name} ---")
    
    try:
        parser_funcs = get_parser_functions(broker_name)
    except ValueError as e:
        print(f"Error: {e}")
        return

    ticker_map_data = load_yaml(TICKER_MAP_FILE)
    if not ticker_map_data:
        print("Could not load ticker map. Aborting.")
        return
    ticker_map = ticker_map_data.get('ticker_rename', {})

    # 1. Get transactions and save
    print("Parsing transactions...")
    transactions_data = parser_funcs["get_transactions"](ACCOUNTS, ticker_map)
    save_data_to_yaml(transactions_data, TRANSACTIONS_OUTPUT_FILE)
    print(f"Transactions saved to {TRANSACTIONS_OUTPUT_FILE}")

    # 2. Get cash operations and dividends and save
    print("Parsing cash operations and dividends...")
    dividends_data, other_cash_ops = parser_funcs["get_cash_operations"](ACCOUNTS, ticker_map)
    save_data_to_yaml(dividends_data, DIVIDEND_OUTPUT_FILE)
    print(f"Dividends saved to {DIVIDEND_OUTPUT_FILE}")
    save_data_to_yaml(other_cash_ops, CASH_OPERATIONS_OUTPUT_FILE)
    print(f"Cash operations saved to {CASH_OPERATIONS_OUTPUT_FILE}")
    
    print(f"\nData parsing complete for broker: {broker_name}")

if __name__ == '__main__':
    main()