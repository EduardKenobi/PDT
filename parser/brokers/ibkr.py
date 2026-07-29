import pandas as pd
import csv
import re
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

def _extract_ticker_from_description(description: str) -> str | None:
    """
    Extracts the ticker symbol from IBKR dividend descriptions.
    Example: 'O(US7561091049) Cash Dividend...' -> 'O'
    """
    if not isinstance(description, str):
        return None
    match = re.search(r'^([A-Z0-9\s\.]+?)\(', description)
    if match:
        return match.group(1).strip()
    return None

def _extract_dividend_per_share(description: str) -> tuple[float | None, str | None]:
    """
    Extracts dividend per share amount and currency from IBKR descriptions.
    Example: '... USD 0.27 per Share ...' -> (0.27, 'USD')
    """
    if not isinstance(description, str):
        return None, None
    match = re.search(r'([A-Z]{3})\s+([0-9.]+)\s+per Share', description)
    if match:
        try:
            return float(match.group(2)), match.group(1)
        except ValueError:
            pass
    return None, None

def _parse_dividends_and_withholding(csv_content: str, instrument_info_map: dict, ticker_cache: dict) -> tuple[list[dict], dict]:
    """
    Parses the 'Dividends' and 'Withholding Tax' sections from IBKR CSV content.
    Returns a tuple of (flat_list_of_operations, structured_companies_dict).
    """
    all_ops = []
    companies = {}
    csv_file = StringIO(csv_content)
    rows = list(csv.reader(csv_file))
    
    # Map section headers to find column indices (especially 'Code')
    section_headers = {}
    for row in rows:
        if len(row) > 1 and row[1].strip() == 'Header':
            section_headers[row[0].strip()] = [col.strip() for col in row]

    for i, row in enumerate(rows):
        if len(row) > 5 and row[1].strip() == 'Data':
            section = row[0].strip()
            if section in ['Dividends', 'Withholding Tax']:
                currency, date_str, description, amount_str = row[2].strip(), row[3].strip(), row[4].strip(), row[5].strip()
                
                if currency == 'Total':
                    continue
                
                # Check for accrual codes if 'Code' column exists
                headers = section_headers.get(section, [])
                if 'Code' in headers:
                    code_idx = headers.index('Code')
                    if code_idx < len(row):
                        code = row[code_idx].strip()
                        # 'Po' = Posting, 'Re' = Reversal (accrual related)
                        if 'Po' in code or 'Re' in code:
                            continue

                try:
                    amount = float(amount_str)
                    op_type = 'Dividend' if section == 'Dividends' else 'Withholding Tax'
                    all_ops.append({
                        'type': op_type, 'date': date_str, 'amount': amount,
                        'currency': currency, 'comment': description, 'user_category': op_type,
                        'broker': 'ibkr'
                    })
                    
                    if section == 'Dividends':
                        raw_ticker = _extract_ticker_from_description(description)
                        if raw_ticker:
                            ticker = find_yahoo_ticker(raw_ticker, instrument_info_map, ticker_cache)
                            if ticker not in companies:
                                companies[ticker] = {'dividends': []}
                            
                            amount_per_share, amount_per_share_currency = _extract_dividend_per_share(description)
                            
                            dividend_entry = {
                                'amount': amount,
                                'date': date_str,
                                'currency': currency,
                                'withholding_tax': 0,
                                'amount_per_share': amount_per_share,
                                'amount_per_share_currency': amount_per_share_currency,
                                'broker': 'ibkr'
                            }
                            
                            # Peek for withholding tax matching this dividend
                            for j in range(i + 1, len(rows)):
                                next_row = rows[j]
                                if len(next_row) > 5 and next_row[0].strip() == 'Withholding Tax' and next_row[1].strip() == 'Data':
                                    # Ensure next_row is not an accrual or total
                                    next_currency = next_row[2].strip()
                                    if next_currency == 'Total':
                                        continue
                                        
                                    next_headers = section_headers.get('Withholding Tax', [])
                                    if 'Code' in next_headers:
                                        next_code_idx = next_headers.index('Code')
                                        if next_code_idx < len(next_row):
                                            next_code = next_row[next_code_idx].strip()
                                            if 'Po' in next_code or 'Re' in next_code:
                                                continue

                                    next_desc = next_row[4].strip()
                                    if raw_ticker in next_desc and next_row[3].strip() == date_str:
                                        try:
                                            wt = float(next_row[5].strip())
                                            dividend_entry['withholding_tax'] = wt
                                            if amount != 0:
                                                dividend_entry['withholding_tax_rate'] = round(abs(wt) / amount * 100)
                                        except ValueError:
                                            pass
                                        break
                            
                            companies[ticker]['dividends'].append(dividend_entry)
                except ValueError:
                    continue
    return all_ops, companies

def get_cash_operations_from_csv_files(file_paths: list[str]) -> tuple[dict, dict]:
    """
    Reads and merges cash operations from multiple IBKR CSV files.
    """
    all_cash_operations = []
    merged_companies_dividends = {}
    ticker_cache = get_ticker_cache()

    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                csv_content = f.read()
            
            instrument_info_map = _get_instrument_info(csv_content)
            
            # Parse deposits and withdrawals
            all_cash_operations.extend(_parse_deposits_withdrawals(csv_content))
            
            # Parse dividends and withholding tax (returns both flat and structured data)
            div_ops, comp_divs = _parse_dividends_and_withholding(csv_content, instrument_info_map, ticker_cache)
            all_cash_operations.extend(div_ops)
            
            # Merge company-specific dividend data
            for ticker, data in comp_divs.items():
                if ticker not in merged_companies_dividends:
                    merged_companies_dividends[ticker] = {'dividends': []}
                merged_companies_dividends[ticker]['dividends'].extend(data['dividends'])

        except FileNotFoundError:
            print(f"Error: IBKR CSV file not found at {file_path}")
        except Exception as e:
            print(f"Error parsing IBKR cash ops from {file_path}: {e}")
            
    return {'companies': merged_companies_dividends}, {'other_operations': all_cash_operations}

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

def _get_account_info(csv_content: str) -> dict:
    """
    Parses the 'Account Information' section to get base currency and other details.
    """
    info = {}
    csv_file = StringIO(csv_content)
    reader = csv.reader(csv_file)
    header_found = False
    headers = []
    for row in reader:
        if len(row) > 1 and row[0].strip() == 'Account Information' and row[1].strip() == 'Header':
            header_found = True
            headers = [c.strip() for c in row]
            continue
        if header_found and len(row) > 1 and row[0].strip() == 'Account Information' and row[1].strip() == 'Data':
            try:
                name_idx = headers.index('Field Name')
                val_idx = headers.index('Field Value')
                info[row[name_idx].strip()] = row[val_idx].strip()
            except (ValueError, IndexError):
                pass
        if header_found and row[0].strip() != 'Account Information':
            break
    return info

def get_ending_cash_balance_from_csv_files(file_paths: list[str]) -> dict:
    """
    Parses IBKR CSV content to extract ending cash balances.
    Prioritizes total cash values converted to base currency to avoid double-counting.
    """
    from utils.exchange_rate import normalize_currency
    cash_balances = {}
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                csv_content = f.read()
            
            # 1. Get base currency
            account_info = _get_account_info(csv_content)
            base_currency = normalize_currency(account_info.get('Base Currency', 'EUR'))

            csv_file = StringIO(csv_content)
            reader = csv.reader(csv_file)
            
            file_currency_balances = {}
            total_cash_from_summary = None
            current_section = None
            current_headers = []

            for row in reader:
                if len(row) < 2:
                    continue
                
                section = row[0].strip()
                record_type = row[1].strip()
                
                if record_type == 'Header':
                    current_section = section
                    current_headers = [c.strip() for c in row]
                    continue
                
                if record_type == 'Data':
                    if current_section == 'Net Asset Value':
                        try:
                            asset_class_idx = current_headers.index('Asset Class')
                            total_idx = current_headers.index('Current Total')
                            asset_class = row[asset_class_idx].strip()
                            # 'Cash' row in NAV section is the total cash across all currencies in base currency
                            if asset_class == 'Cash':
                                total_cash_from_summary = float(row[total_idx].strip())
                        except (ValueError, IndexError):
                            pass
                    
                    elif current_section == 'Cash Report':
                        if len(row) > 4:
                            report_type = row[2].strip()
                            currency = row[3].strip()
                            amount_str = row[4].strip()
                            
                            if report_type == 'Ending Cash':
                                try:
                                    amount = float(amount_str)
                                    if currency == 'Base Currency Summary':
                                        if total_cash_from_summary is None:
                                            total_cash_from_summary = amount
                                    else:
                                        file_currency_balances[normalize_currency(currency)] = amount
                                except ValueError:
                                    pass
            
            # If we found a total cash summary (e.g. from 'Base Currency Summary'), it ALREADY includes
            # all individual currency balances converted to base currency.
            # To avoid double-counting in the portfolio processor (which sums all dict keys),
            # we should ONLY return the total in the base currency key.
            if total_cash_from_summary is not None:
                # We overwrite the base currency key with the total and REMOVE others
                # this ensures that the portfolio value calculation (which sums all currencies)
                # correctly reflects the total liquidity.
                file_currency_balances = {base_currency: total_cash_from_summary}
            
            # Merge this file's balances into the overall result
            cash_balances.update(file_currency_balances)

        except FileNotFoundError:
            print(f"Error: IBKR CSV file not found at {file_path}")
        except Exception as e:
            print(f"Error parsing IBKR cash balance from {file_path}: {e}")
            
    return cash_balances

def _parse_open_positions(csv_content: str, instrument_info_map: dict, ticker_cache: dict) -> dict:
    """
    Parses the 'Open Positions' section to get current holdings.
    Returns a dict like {'WKL.AS': {'shares': 4, 'cost_basis': 333.34, 'currency': 'EUR'}}.
    """
    positions = {}
    csv_file = StringIO(csv_content)
    reader = csv.reader(csv_file)
    header_found = False
    headers = []
    
    for row in reader:
        if len(row) > 2 and row[0].strip() == 'Open Positions' and row[1].strip() == 'Header':
            header_found = True
            headers = [c.strip() for c in row]
            continue
        
        if header_found and len(row) > 10 and row[0].strip() == 'Open Positions' and row[1].strip() == 'Data' and row[2].strip() == 'Summary':
            try:
                asset_category = row[headers.index('Asset Category')].strip()
                if asset_category != 'Stocks':
                    continue
                
                currency = row[headers.index('Currency')].strip()
                raw_ticker = row[headers.index('Symbol')].strip()
                quantity = float(row[headers.index('Quantity')].strip())
                cost_basis = float(row[headers.index('Cost Basis')].strip())
                
                ticker = find_yahoo_ticker(raw_ticker, instrument_info_map, ticker_cache)
                positions[ticker] = {
                    'shares': quantity,
                    'cost_basis': cost_basis,
                    'currency': currency
                }
            except (ValueError, IndexError):
                pass
        
        if header_found and row[0].strip() != 'Open Positions':
            break
            
    return positions
