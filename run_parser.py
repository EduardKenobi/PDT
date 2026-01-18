from collections import defaultdict
import hashlib
import json
from parser import get_parser_functions
from utils.data_loader import load_yaml, load_categorizations
from utils.output_writer import save_data_to_yaml, save_categorizations
from parser.brokers.xtb_ticker_converter import get_ticker_cache, save_ticker_cache
from config import (
    ACCOUNTS,
    TRANSACTIONS_OUTPUT_FILE,
    DIVIDEND_OUTPUT_FILE,
    CASH_OPERATIONS_OUTPUT_FILE
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
    # Use json to create a canonical string representation, then encode to bytes
    encoded_parts = json.dumps(unique_parts, sort_keys=True).encode('utf-8')
    
    # Create a sha256 hash
    hasher = hashlib.sha256()
    hasher.update(encoded_parts)
    
    # Return the hex digest, which is a stable string
    return hasher.hexdigest()

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

    # 1. Get transactions and save
    print("Parsing transactions...")
    transactions_data = parser_funcs["get_transactions"](ACCOUNTS)
    save_data_to_yaml(transactions_data, TRANSACTIONS_OUTPUT_FILE)
    print(f"Transactions saved to {TRANSACTIONS_OUTPUT_FILE}")

    # 2. Get cash operations and dividends
    print("Parsing cash operations and dividends...")
    dividends_data, other_cash_ops = parser_funcs["get_cash_operations"](ACCOUNTS)

    # 3. Interactive Cash Flow Categorization
    print("\n--- Starting Interactive Cash Flow Categorization ---")
    categorizations = load_categorizations()
    needs_saving = False
    
    operations_to_process = other_cash_ops.get('other_operations', [])

    for op in operations_to_process:
        op_type = op.get('type')
        if not op_type or op_type.lower() not in ['deposit', 'withdrawal']:
            continue

        op_id = generate_transaction_id(op)

        if op_id in categorizations:
            op['user_category'] = categorizations[op_id]
        else:
            print("\n" + "="*50)
            print(f"New uncategorized transaction found:")
            print(f"  Type:    {op.get('type')}")
            print(f"  Date:    {op.get('date')}")
            print(f"  Amount:  {op.get('amount')} {op.get('currency')}")
            print(f"  Comment: {op.get('comment')}")
            print("="*50)
            
            if op_type.lower() == 'deposit':
                prompt = "Is this [1] New Capital or [2] a Transfer from another broker? "
                choices = {'1': 'deposit', '2': 'transfer_in'}
            else:  # Withdrawal
                prompt = "Is this [1] Leaving Portfolio or [2] a Transfer to another broker? "
                choices = {'1': 'withdrawal', '2': 'transfer_out'}
            
            user_choice = ''
            while user_choice not in choices:
                user_choice = input(prompt)

            new_category = choices[user_choice]
            op['user_category'] = new_category
            categorizations[op_id] = new_category
            needs_saving = True
            print(f"-> Categorized as: {new_category}")

    if needs_saving:
        save_categorizations(categorizations)
        print("\n--- Saved new cash flow categorizations. ---")
    else:
        print("--- No new cash flow transactions to categorize. ---")

    # 4. Save final data
    save_data_to_yaml(dividends_data, DIVIDEND_OUTPUT_FILE)
    print(f"Dividends saved to {DIVIDEND_OUTPUT_FILE}")
    save_data_to_yaml(other_cash_ops, CASH_OPERATIONS_OUTPUT_FILE)
    print(f"Cash operations saved to {CASH_OPERATIONS_OUTPUT_FILE}")
    
    # Save the updated ticker cache once at the end
    final_cache = get_ticker_cache()
    if final_cache:
        save_ticker_cache(final_cache)
    
    print(f"\nData parsing complete for broker: {broker_name}")

if __name__ == '__main__':
    main()