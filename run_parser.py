from collections import defaultdict
import hashlib
import json
from parser import get_parser_functions
from utils.data_loader import load_yaml, load_categorizations
from utils.output_writer import save_data_to_yaml, save_categorizations
from parser.brokers.xtb_ticker_converter import get_ticker_cache, save_ticker_cache
from config import (
    XTB_ACCOUNTS,
    IBKR_ACCOUNTS,
    TRANSACTIONS_OUTPUT_FILE,
    DIVIDEND_OUTPUT_FILE,
    CASH_OPERATIONS_OUTPUT_FILE,
    IBKR_CASH_BALANCE_OUTPUT_FILE
)

def generate_transaction_id(transaction):
    """
    Generates a unique and deterministic identifier for a cash flow transaction
    by creating a SHA256 hash from its key properties.
    """
    unique_parts = (
        transaction.get('date'),
        str(transaction.get('amount')),
        transaction.get('currency'),
        transaction.get('type'),
        transaction.get('comment', '')
    )
    encoded_parts = json.dumps(unique_parts, sort_keys=True).encode('utf-8')
    hasher = hashlib.sha256()
    hasher.update(encoded_parts)
    return hasher.hexdigest()

def run_single_parser(broker_name: str) -> tuple[dict, dict, dict, dict | None]:
    """
    Runs the parser for a single specified broker and returns the parsed data.
    """
    cash_balance = None
    if broker_name == 'xtb':
        accounts_to_parse = XTB_ACCOUNTS
    elif broker_name == 'ibkr':
        accounts_to_parse = IBKR_ACCOUNTS
        from parser.brokers.ibkr import get_ending_cash_balance_from_csv_files
        print("Parsing cash balance...")
        cash_balance = get_ending_cash_balance_from_csv_files(accounts_to_parse)
    else:
        raise ValueError(f"Broker '{broker_name}' is not configured.")

    print(f"\n--- Running parser for broker: {broker_name} ---")
    parser_funcs = get_parser_functions(broker_name)
    
    print("Parsing transactions...")
    transactions_data = parser_funcs["get_transactions"](accounts_to_parse)
    
    print("Parsing cash operations and dividends...")
    dividends_data, other_cash_ops = parser_funcs["get_cash_operations"](accounts_to_parse)

    # Specific handling for XTB ticker cache
    if broker_name == 'xtb':
        final_cache = get_ticker_cache()
        if final_cache:
            save_ticker_cache(final_cache)
            
    return transactions_data, dividends_data, other_cash_ops, cash_balance

def merge_data(base_data: dict, new_data: dict, list_key: str):
    """
    Merges 'new_data' into 'base_data' for dictionaries structured with a 'companies' key.
    """
    for ticker, data in new_data.get('companies', {}).items():
        if ticker not in base_data['companies']:
            base_data['companies'][ticker] = {list_key: []}
        
        if list_key not in base_data['companies'][ticker]:
             base_data['companies'][ticker][list_key] = []
             
        base_data['companies'][ticker][list_key].extend(data.get(list_key, []))

def main():
    """
    Main function to run all parsers.
    """
    brokers_to_run = ['xtb', 'ibkr']
    
    # Initialize final data structures
    final_transactions = {'companies': {}}
    final_dividends = {'companies': {}}
    final_cash_ops = {'other_operations': []}
    ibkr_cash_balance = {}

    for broker in brokers_to_run:
        try:
            trans_data, div_data, cash_ops_data, cash_balance = run_single_parser(broker)
            
            # Merge data
            merge_data(final_transactions, trans_data, 'transactions')
            merge_data(final_dividends, div_data, 'dividends')
            final_cash_ops['other_operations'].extend(cash_ops_data.get('other_operations', []))
            if cash_balance:
                ibkr_cash_balance.update(cash_balance)

        except ValueError as e:
            print(f"Error: {e}")
            continue
    
    # --- Interactive Cash Flow Categorization on merged data ---
    if final_cash_ops.get('other_operations'):
        print("\n--- Starting Interactive Cash Flow Categorization ---")
        categorizations = load_categorizations()
        needs_saving = False
        
        for op in final_cash_ops['other_operations']:
            op_type = op.get('type')
            if not op_type or op_type.lower() not in ['deposit', 'withdrawal']:
                continue

            op_id = generate_transaction_id(op)
            if op_id not in categorizations:
                print("\n" + "="*50)
                print(f"New uncategorized transaction found:")
                print(f"  Type:    {op.get('type')}")
                print(f"  Date:    {op.get('date')}")
                print(f"  Amount:  {op.get('amount')} {op.get('currency')}")
                print(f"  Comment: {op.get('comment')}")
                print("="*50)
                
                prompt_map = {
                    'deposit': ("Is this [1] New Capital or [2] a Transfer from another broker? ", {'1': 'deposit', '2': 'transfer_in'}),
                    'withdrawal': ("Is this [1] Leaving Portfolio or [2] a Transfer to another broker? ", {'1': 'withdrawal', '2': 'transfer_out'})
                }
                prompt, choices = prompt_map[op_type.lower()]
                
                user_choice = ''
                while user_choice not in choices:
                    user_choice = input(prompt)

                new_category = choices[user_choice]
                op['user_category'] = new_category
                categorizations[op_id] = new_category
                needs_saving = True
                print(f"-> Categorized as: {new_category}")
            else:
                op['user_category'] = categorizations[op_id]

        if needs_saving:
            save_categorizations(categorizations)
            print("\n--- Saved new cash flow categorizations. ---")
        else:
            print("--- No new cash flow transactions to categorize. ---")
    
    # --- Save final merged data ---
    save_data_to_yaml(final_transactions, TRANSACTIONS_OUTPUT_FILE)
    print(f"Transactions saved to {TRANSACTIONS_OUTPUT_FILE}")
    
    save_data_to_yaml(final_dividends, DIVIDEND_OUTPUT_FILE)
    print(f"Dividends saved to {DIVIDEND_OUTPUT_FILE}")
    
    save_data_to_yaml(final_cash_ops, CASH_OPERATIONS_OUTPUT_FILE)
    print(f"Cash operations saved to {CASH_OPERATIONS_OUTPUT_FILE}")
    
    if ibkr_cash_balance:
        save_data_to_yaml(ibkr_cash_balance, IBKR_CASH_BALANCE_OUTPUT_FILE)
        print(f"IBKR cash balance saved to {IBKR_CASH_BALANCE_OUTPUT_FILE}")
    
    print("\nData parsing complete.")


if __name__ == '__main__':
    main()