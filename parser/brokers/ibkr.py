import pandas as pd
import csv
from io import StringIO
from datetime import datetime
from config import IBKR_EXCHANGE_MAP
from .ibkr_ticker_converter import find_yahoo_ticker, get_ticker_cache, save_ticker_cache

def _parse_deposits_withdrawals(csv_content: str) -> list[dict]:
    """
    Parses the 'Deposits & Withdrawals' section from IBKR CSV content.
    """
    transactions = []
    csv_file = StringIO(csv_content)
    reader = csv.reader(csv_file)
    header_found = False
    
    for row in reader:
        if len(row) > 2 and row[0].strip() == 'Deposits & Withdrawals' and row[1].strip() == 'Header':
            header_found = True
            continue
        
        if header_found and len(row) > 5 and row[0].strip() == 'Deposits & Withdrawals' and row[1].strip() == 'Data':
            currency, settle_date_str, description, amount_str = row[2].strip(), row[3].strip(), row[4].strip(), row[5].strip()
            if currency == 'Total':
                continue
            try:
                amount = float(amount_str)
                op_type = 'deposit' if amount > 0 else 'withdrawal'
                transactions.append({
                    'type': op_type, 'date': settle_date_str, 'amount': amount,
                    'currency': currency, 'comment': description, 'user_category': op_type,
                    'broker': 'ibkr'
                })
            except ValueError:
                print(f"Warning: Could not parse amount '{amount_str}' for deposit/withdrawal. Skipping.")
        
        if header_found and row[0].strip() != 'Deposits & Withdrawals':
            break
            
    return transactions

def _get_instrument_info(csv_content: str) -> dict:
    """
    Parses the 'Financial Instrument Information' section to map symbols to their listing exchange.
    Returns a dict like {'GOOGL': 'NASDAQ', 'ULVR': 'LSE'}.
    """
    instrument_map = {}
    csv_file = StringIO(csv_content)
    reader = csv.reader(csv_file)
    header_found = False
    
    for row in reader:
        if len(row) > 2 and row[0].strip() == 'Financial Instrument Information' and row[1].strip() == 'Header':
            header_found = True
            continue
        
        if header_found and len(row) > 8 and row[0].strip() == 'Financial Instrument Information' and row[1].strip() == 'Data':
            asset_category, symbol, listing_exch = row[2].strip(), row[3].strip(), row[8].strip()
            if asset_category == 'Stocks':
                instrument_map[symbol] = listing_exch
        
        if header_found and row[0].strip() != 'Financial Instrument Information':
            break
            
    return instrument_map

def _parse_trades(csv_content: str, instrument_info_map: dict, ticker_cache: dict) -> dict:
    """
    Parses the 'Trades' section from IBKR CSV content.
    """
    companies = {}
    csv_file = StringIO(csv_content)
    reader = csv.reader(csv_file)
    header_found = False
    
    for row in reader:
        if len(row) > 2 and row[0].strip() == 'Trades' and row[1].strip() == 'Header':
            header_found = True
            continue
        
        if header_found and len(row) > 11 and row[0].strip() == 'Trades' and row[1].strip() == 'Data' and row[2].strip() == 'Order':
            asset_category = row[3].strip()
            if asset_category != 'Stocks':
                continue
            
            try:
                currency, raw_ticker, date_time_str, quantity_str, t_price_str, proceeds_str, comm_fee_str = \
                    row[4].strip(), row[5].strip(), row[6].strip(), row[7].strip(), row[8].strip(), row[10].strip(), row[11].strip()
                
                quantity = int(quantity_str)
                proceeds = float(proceeds_str)
                
                # Determine position status type: 'open' for buys, 'closed' for sells
                position_status_type = 'open' if proceeds < 0 else 'closed'
                
                ticker = find_yahoo_ticker(raw_ticker, instrument_info_map, ticker_cache)
                
                transaction = {
                    'type': position_status_type, 
                    'shares': quantity,
                    'open_date': datetime.strptime(date_time_str, '%Y-%m-%d, %H:%M:%S').strftime('%Y-%m-%d') if position_status_type == 'open' else None,
                    'close_date': datetime.strptime(date_time_str, '%Y-%m-%d, %H:%M:%S').strftime('%Y-%m-%d') if position_status_type == 'closed' else None,
                    'open_price': float(t_price_str) if position_status_type == 'open' else None,
                    'close_price': float(t_price_str) if position_status_type == 'closed' else None,
                    'purchase_value': abs(proceeds)+abs(float(comm_fee_str)) if position_status_type == 'open' else None,
                    'sale_value': abs(proceeds) if position_status_type == 'closed' else None,
                    'currency': currency, 'commission': float(comm_fee_str), 'position': None,
                    'broker': 'ibkr'
                }
                
                if ticker not in companies:
                    companies[ticker] = {'transactions': []}
                companies[ticker]['transactions'].append(transaction)

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse trade row: {row}. Error: {e}. Skipping.")
            
        if header_found and row[0].strip() != 'Trades':
            break
            
    return {'companies': companies}

def _parse_dividends_and_withholding(csv_content: str) -> list[dict]:
    """
    Parses the 'Dividends' and 'Withholding Tax' sections from IBKR CSV content.
    """
    transactions = []
    csv_file = StringIO(csv_content)
    reader = csv.reader(csv_file)
    
    for row in reader:
        if len(row) > 0 and row[0].strip() in ['Dividends', 'Withholding Tax']:
            if len(row) > 5 and row[1].strip() == 'Data':
                op_type = 'Dividend' if row[0].strip() == 'Dividends' else 'Withholding Tax'
                currency, date_str, description, amount_str = row[2].strip(), row[3].strip(), row[4].strip(), row[5].strip()
                try:
                    amount = float(amount_str)
                    transactions.append({
                        'type': op_type,
                        'date': date_str,
                        'amount': amount,
                        'currency': currency,
                        'comment': description,
                        'user_category': op_type,
                        'broker': 'ibkr'
                    })
                except ValueError:
                    print(f"Warning: Could not parse amount '{amount_str}' for {op_type}. Skipping.")
    return transactions

def get_cash_operations_from_csv_files(file_paths: list[str]) -> tuple[dict, dict]:
    """
    Reads and merges cash operations from multiple IBKR CSV files.
    """
    all_cash_operations = []
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                csv_content = f.read()
            all_cash_operations.extend(_parse_deposits_withdrawals(csv_content))
            all_cash_operations.extend(_parse_dividends_and_withholding(csv_content))
        except FileNotFoundError:
            print(f"Error: IBKR CSV file not found at {file_path}")
        except Exception as e:
            print(f"Error parsing IBKR cash ops from {file_path}: {e}")
            
    return {'companies': {}}, {'other_operations': all_cash_operations}

def get_transactions_from_csv_files(file_paths: list[str]) -> dict:
    """
    Parses trade transactions from multiple IBKR CSV files.
    """
    merged_companies_data = {}
    ticker_cache = get_ticker_cache()
    
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                csv_content = f.read()
            
            instrument_info_map = _get_instrument_info(csv_content)
            trades_data = _parse_trades(csv_content, instrument_info_map, ticker_cache)
            
            for ticker, data in trades_data.get('companies', {}).items():
                if ticker not in merged_companies_data:
                    merged_companies_data[ticker] = {'transactions': []}
                merged_companies_data[ticker]['transactions'].extend(data['transactions'])
                
        except FileNotFoundError:
            print(f"Error: IBKR CSV file not found at {file_path}")
        except Exception as e:
            print(f"Error parsing IBKR trades from {file_path}: {e}")
            
    save_ticker_cache(ticker_cache)
    return {'companies': merged_companies_data}

def get_ending_cash_balance_from_csv_files(file_paths: list[str]) -> dict:
    """
    Parses the 'Cash Report' section from IBKR CSV content to extract ending cash balances.
    """
    cash_balances = {}
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                csv_content = f.read()
            csv_file = StringIO(csv_content)
            reader = csv.reader(csv_file)
            header_found = False

            for row in reader:
                if len(row) > 2 and row[0].strip() == 'Cash Report' and row[1].strip() == 'Header':
                    header_found = True
                    continue

                if header_found and len(row) > 4 and row[0].strip() == 'Cash Report' and row[1].strip() == 'Data':
                    report_type, currency, amount_str = row[2].strip(), row[3].strip(), row[4].strip()
                    if report_type == 'Ending Cash':
                        try:
                            amount = float(amount_str)
                            cash_balances[currency] = amount
                        except ValueError:
                            print(f"Warning: Could not parse amount '{amount_str}' for ending cash in {currency}. Skipping.")
                
                if header_found and row[0].strip() != 'Cash Report':
                    break # Stop reading after the cash report section
        except FileNotFoundError:
            print(f"Error: IBKR CSV file not found at {file_path}")
        except Exception as e:
            print(f"Error parsing IBKR cash balance from {file_path}: {e}")
    return cash_balances