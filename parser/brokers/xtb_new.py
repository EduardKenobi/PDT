import pandas as pd
import re
import os
from .xtb_helpers import (
    parse_excel,
    find_header_row,
    handle_possible_split,
    calculate_time_test,
    convert_ticker,
    merge_data
)

# Casing/spelling mapping to match the output of the old parser
TYPE_MAPPING = {
    'SEC fee': 'Sec Fee',
    'Withdrawal': 'withdrawal',
    'Transfer': 'transfer',
    'Stock sell': 'Stock sale',
    'Withholding tax': 'Withholding Tax',
    'Dividend': 'Dividend',
    'Deposit': 'deposit',
    'Free funds interest': 'Free-funds Interest',
    'Free funds interest tax': 'Free-funds Interest Tax',
    'Tax IFTT': 'tax IFTT',
    'Stamp duty': 'Stamp Duty',
    'Close trade': 'close trade',
    'Commission': 'commission',
    'Swap': 'swap',
    'Fractional shares': 'fractional shares',
    'Correction': 'correction',
    'Rollover': 'rollover',
    'Stock purchase': 'Stock purchase'
}

def detect_currency(filepath, df_closed=None):
    """
    Detects the currency from the filename or account ID.
    """
    basename = os.path.basename(filepath).upper()
    if 'EUR' in basename:
        return 'EUR'
    if 'USD' in basename:
        return 'USD'
    
    if df_closed is not None and not df_closed.empty:
        try:
            account_id = str(df_closed.iloc[0, 1]).strip()
            if account_id == '1931741':
                return 'EUR'
            if account_id == '50557805':
                return 'USD'
        except Exception:
            pass
            
    return 'EUR'

def _parse_comment_shares_price(comment):
    """
    Parses shares and price from comments like "OPEN BUY 2 @ 57.46" or "CLOSE BUY 1 @ 65.18".
    """
    if not isinstance(comment, str):
        return None, None
    match = re.search(r'(?:OPEN|CLOSE)\s+BUY\s+([\d\.]+)\s+@\s+([\d\.]+)', comment)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None

def _parse_withholding_tax_rate(comment):
    """
    Parses withholding tax rate from comment like "ADC.US USD WHT 15%"
    """
    if not isinstance(comment, str):
        return None
    match = re.search(r'WHT\s(\d+)%', comment)
    if match:
        return float(match.group(1))
    return None

def _parse_dividend_per_share(comment):
    """
    Parses dividend per share amount and currency from comment like "ADC.US USD 0.2670/ SHR"
    """
    if not isinstance(comment, str):
        return None
    match = re.search(r'\s([A-Z]{3})\s(\d+\.\d+)/\s*SHR', comment)
    if match:
        return {'currency': match.group(1), 'amount': float(match.group(2))}
    match = re.search(r'(\d+\.\d+)/\s*SHR', comment)
    if match:
        return {'currency': None, 'amount': float(match.group(1))}
    return None

def _process_closed_row_to_transaction(ticker, row, currency):
    """
    Processes a row from Closed Positions to a transaction dict.
    """
    purchase_value = float(row.get('Purchase Value')) if not pd.isna(row.get('Purchase Value')) else None
    gross_pl_amount = float(row.get('Gross Profit')) if not pd.isna(row.get('Gross Profit')) else None
    if pd.isna(purchase_value):
        purchase_value = float(row.get('Margin')) if not pd.isna(row.get('Margin')) else None

    transaction = {
        'position': int(row.get('Position ID')) if not pd.isna(row.get('Position ID')) else None,
        'type': 'closed',
        'shares': float(row.get('Volume')) if not pd.isna(row.get('Volume')) else None,
        'open_date': pd.to_datetime(row.get('Open Time (UTC)')).strftime('%Y-%m-%d'),
        'open_price': float(row.get('Open Price')) if not pd.isna(row.get('Open Price')) else None,
        'purchase_value': None if pd.isna(purchase_value) else purchase_value,
        'currency': currency,
        'broker': 'xtb',
    }

    sale_value = float(row.get('Sale Value')) if not pd.isna(row.get('Sale Value')) else None
    if pd.isna(sale_value):
        margin_val = float(row.get('Margin')) if not pd.isna(row.get('Margin')) else None
        if margin_val is not None and gross_pl_amount is not None:
            sale_value = margin_val + gross_pl_amount

    comment = row.get('Close Origin')
    is_correction = False
    recalculated_profit = None
    if gross_pl_amount == 0.0:
        if isinstance(comment, str) and 'correction' in comment.lower():
            is_correction = True
            # Recalculate true sale value for broker corrections in the new layout
            # actual_sale_value = Volume * Close Price * Close Conversion Rate
            close_conv = float(row.get('Close Conversion Rate')) if not pd.isna(row.get('Close Conversion Rate')) else 1.0
            actual_sale_value = float(row.get('Volume')) * float(row.get('Close Price')) * close_conv
            sale_value = round(actual_sale_value, 2)
            recalculated_profit = round(sale_value - purchase_value, 2)
            print(f"Warning: Detected broker correction for position {transaction['position']} of ticker {ticker}. A recalculated profit of {recalculated_profit:.2f} will be used for tax calculation.")

    if not is_correction:
        purchase_value = handle_possible_split(ticker, str(row.get('Position ID')), transaction['purchase_value'], sale_value, gross_pl_amount, transaction['shares'])

    transaction.update({
        'purchase_value': purchase_value,
    })
    
    transaction.update({
        'close_date': pd.to_datetime(row.get('Close Time (UTC)')).strftime('%Y-%m-%d'),
        'close_price': float(row.get('Close Price')) if not pd.isna(row.get('Close Price')) else None,
        'sale_value': sale_value,
        'gross_pl_amount': gross_pl_amount,
        'recalculated_profit': recalculated_profit,
        'gross_pl_percent': (
            gross_pl_amount / purchase_value
            if purchase_value is not None and purchase_value != 0 and not pd.isna(gross_pl_amount)
            else None
        ),
    })

    time_test_cz, time_test_sk = calculate_time_test(
        pd.to_datetime(transaction['open_date']),
        pd.to_datetime(transaction['close_date'])
    )
    transaction.update({
        'time_test_sk': time_test_sk,
        'time_test_cz': time_test_cz,
    })

    return transaction

def get_transactions_from_excel_files(accounts):
    """
    Reads and merges transactions from multiple Excel files (new format).
    """
    merged_data = {'companies': {}}
    for account in accounts:
        # Load Closed Positions sheet
        try:
            df_closed_raw = parse_excel(account, 'Closed Positions')
        except Exception as e:
            print(f"Error loading Closed Positions from {account}: {e}")
            continue

        if df_closed_raw.empty:
            continue

        # Load Cash Operations sheet
        try:
            df_cash_raw = parse_excel(account, 'Cash Operations')
        except Exception as e:
            print(f"Error loading Cash Operations from {account}: {e}")
            continue

        # Detect currency
        currency = detect_currency(account, df_closed_raw)

        # Set up Closed Positions DataFrame
        header_row_clsd = find_header_row(df_closed_raw, 'Position ID', 'Ticker', 'Open Price')
        if header_row_clsd == -1:
            header_row_clsd = 4 # default fallback
        
        df_closed = df_closed_raw.copy()
        df_closed.columns = df_closed.iloc[header_row_clsd]
        df_closed = df_closed.iloc[header_row_clsd + 1:].reset_index(drop=True)
        # Drop summary rows at the bottom (e.g. 'Profit/loss' or rows without Position ID)
        df_closed = df_closed.dropna(subset=['Position ID'])

        # Sort Closed Positions chronologically by Close Time (UTC) and then Position ID
        df_closed['Close Time (UTC)_dt'] = pd.to_datetime(df_closed['Close Time (UTC)'])
        df_closed = df_closed.sort_values(by=['Close Time (UTC)_dt', 'Position ID'], ascending=True).reset_index(drop=True)
        df_closed = df_closed.drop(columns=['Close Time (UTC)_dt'])

        # Set up Cash Operations DataFrame
        header_row_cash = find_header_row(df_cash_raw, 'Type', 'Ticker', 'Time')
        if header_row_cash == -1:
            header_row_cash = 4 # default fallback

        df_cash = df_cash_raw.copy()
        df_cash.columns = df_cash.iloc[header_row_cash]
        df_cash = df_cash.iloc[header_row_cash + 1:].reset_index(drop=True)
        df_cash = df_cash.dropna(subset=['Type', 'Time'])
        # Sort Cash Operations in ascending order (oldest first)
        df_cash = df_cash.sort_values(by=['Time', 'ID'], ascending=True).reset_index(drop=True)

        # 1. Process all closed transactions
        closed_transactions = []
        for _, row in df_closed.iterrows():
            original_ticker = row.get('Ticker')
            if not original_ticker or pd.isna(original_ticker):
                continue
            ticker = convert_ticker(original_ticker)
            tx = _process_closed_row_to_transaction(ticker, row, currency)
            closed_transactions.append((ticker, tx))

        # 2. Reconstruct open positions from Stock purchase cash operations
        # Filter for Stock purchase cash operations
        purchases = []
        for idx, row in df_cash.iterrows():
            if row.get('Type') == 'Stock purchase':
                original_ticker = row.get('Ticker')
                if not original_ticker or pd.isna(original_ticker):
                    continue
                ticker = convert_ticker(original_ticker)
                comment = row.get('Comment')
                shares, price = _parse_comment_shares_price(comment)
                amount = float(row.get('Amount')) if not pd.isna(row.get('Amount')) else 0.0
                
                if shares is not None:
                    purchases.append({
                        'position': int(row.get('ID')),
                        'ticker': ticker,
                        'original_shares': shares,
                        'remaining_shares': shares,
                        'open_date': pd.to_datetime(row.get('Time')).strftime('%Y-%m-%d'),
                        'open_price': price,
                        'original_purchase_value': -amount,
                        'purchase_value': -amount,
                        'currency': currency,
                        'broker': 'xtb',
                        'type': 'open',
                        'time': pd.to_datetime(row.get('Time'))
                    })

        # Match closed positions against the purchases to find leftover open shares
        # For each closed transaction, we find the matching purchases and subtract the shares
        for ticker, clsd_tx in closed_transactions:
            # We only match stock closed positions (CFDs are not in purchases)
            c_shares = clsd_tx['shares']
            c_price = clsd_tx['open_price']
            c_time = pd.to_datetime(clsd_tx['open_date'])

            # 1st attempt: match ticker, exact price, remaining_shares > 0
            candidates = [p for p in purchases if p['ticker'] == ticker and p['remaining_shares'] > 0 and abs(p['open_price'] - c_price) < 0.001]
            
            # Sort candidates by time difference
            candidates.sort(key=lambda p: abs((p['time'] - c_time).total_seconds()))

            for cand in candidates:
                if c_shares <= 0:
                    break
                deduct = min(c_shares, cand['remaining_shares'])
                cand['remaining_shares'] -= deduct
                c_shares -= deduct

            # 2nd attempt fallback: match ticker (price-independent, e.g. due to split adjustments) and remaining_shares > 0
            if c_shares > 0:
                candidates_fallback = [p for p in purchases if p['ticker'] == ticker and p['remaining_shares'] > 0]
                candidates_fallback.sort(key=lambda p: abs((p['time'] - c_time).total_seconds()))
                for cand in candidates_fallback:
                    if c_shares <= 0:
                        break
                    deduct = min(c_shares, cand['remaining_shares'])
                    cand['remaining_shares'] -= deduct
                    c_shares -= deduct

        # Any purchases with remaining shares are currently open positions
        open_transactions = []
        for p in purchases:
            if p['remaining_shares'] > 0.0001:
                # Pro-rate the purchase value based on remaining shares
                shares_ratio = p['remaining_shares'] / p['original_shares']
                p['shares'] = p['remaining_shares']
                p['purchase_value'] = round(p['original_purchase_value'] * shares_ratio, 2)
                # Clean up keys not needed in transaction dict
                tx_clean = {
                    'position': p['position'],
                    'type': 'open',
                    'shares': p['shares'],
                    'open_date': p['open_date'],
                    'open_price': p['open_price'],
                    'purchase_value': p['purchase_value'],
                    'currency': p['currency'],
                    'broker': p['broker']
                }
                open_transactions.append((p['ticker'], tx_clean))

        # 3. Merge open and closed into final structures
        account_data = {'companies': {}}
        for ticker, tx in open_transactions:
            if ticker not in account_data['companies']:
                account_data['companies'][ticker] = {'transactions': []}
            account_data['companies'][ticker]['transactions'].append(tx)

        for ticker, tx in closed_transactions:
            if ticker not in account_data['companies']:
                account_data['companies'][ticker] = {'transactions': []}
            account_data['companies'][ticker]['transactions'].append(tx)

        # Merge with overall merged_data
        merged_data = merge_data(merged_data, account_data)

    # Sort each company's transactions by date
    for ticker in merged_data['companies']:
        if 'transactions' in merged_data['companies'][ticker]:
            merged_data['companies'][ticker]['transactions'].sort(key=lambda x: x.get('close_date') or x.get('open_date'))

    return merged_data

def _process_dividend_row(df, df_iter, index, row, currency):
    """
    Processes a dividend row and potential withholding tax row immediately following it.
    """
    dividend_per_share_data = _parse_dividend_per_share(row.get('Comment'))
    dividend_transaction = {
        'amount': float(row.get('Amount')) if not pd.isna(row.get('Amount')) else None,
        'date': pd.to_datetime(row.get('Time')).strftime('%Y-%m-%d'),
        'currency': currency,
        'withholding_tax': 0,
        'withholding_tax_rate': 0,
        'amount_per_share': dividend_per_share_data['amount'] if dividend_per_share_data else None,
        'amount_per_share_currency': dividend_per_share_data['currency'] if dividend_per_share_data else None,
        'broker': 'xtb'
    }

    try:
        next_row_df = df.iloc[index + 1]
        next_type = str(next_row_df.get('Type', '')).strip()

        if next_type == 'Withholding tax':
            dividend_transaction['withholding_tax'] = float(next_row_df.get('Amount')) if not pd.isna(next_row_df.get('Amount')) else None
            dividend_transaction['withholding_tax_rate'] = _parse_withholding_tax_rate(next_row_df.get('Comment'))
            next(df_iter, None) # skip withholding tax row
    except (IndexError, StopIteration):
        pass

    return dividend_transaction

def _parse_cash_operations(input_path, sheet_name):
    """
    Parses cash operations and dividends from sheet in Excel.
    """
    try:
        df_raw = parse_excel(input_path, sheet_name)
    except Exception as e:
        print(f"Error loading {sheet_name} from {input_path}: {e}")
        return None

    if df_raw.empty:
        return None

    # Detect currency
    currency = detect_currency(input_path, df_raw)

    # Find header row
    header_row = find_header_row(df_raw, 'Type', 'Ticker', 'Time')
    if header_row == -1:
        header_row = 4

    df = df_raw.copy()
    df.columns = df.iloc[header_row]
    df = df.iloc[header_row + 1:].reset_index(drop=True)
    df = df.dropna(subset=['Type'])
    df = df[df['Type'].str.strip() != 'Total']

    # Sort Cash Operations in ascending order (oldest first) so index+1 references next chronological event
    df = df.sort_values(by=['Time', 'ID'], ascending=True).reset_index(drop=True)

    companies = {}
    other_operations = []

    df_iter = df.iterrows()
    while True:
        try:
            index, row = next(df_iter)
            current_type = str(row.get('Type', '')).strip()

            if current_type == 'Dividend':
                original_ticker = row.get('Ticker')
                if not original_ticker or pd.isna(original_ticker):
                    continue
                ticker = convert_ticker(original_ticker)

                dividend_transaction = _process_dividend_row(df, df_iter, index, row, currency)

                if ticker not in companies:
                    companies[ticker] = {}
                if 'dividends' not in companies[ticker]:
                    companies[ticker]['dividends'] = []
                companies[ticker]['dividends'].append(dividend_transaction)

            elif current_type == 'Withholding tax':
                # Orphan Withholding tax row (not matched by previous Dividend check)
                date_val = pd.to_datetime(row.get('Time'))
                mapped_type = TYPE_MAPPING.get(current_type, current_type)
                operation = {
                    'type': mapped_type,
                    'date': date_val.strftime('%Y-%m-%d') if pd.notna(date_val) else None,
                    'amount': float(row.get('Amount')) if not pd.isna(row.get('Amount')) else None,
                    'currency': currency,
                    'comment': row.get('Comment'),
                    'user_category': mapped_type,
                    'broker': 'xtb'
                }
                other_operations.append(operation)

            else:
                date_val = pd.to_datetime(row.get('Time'))
                mapped_type = TYPE_MAPPING.get(current_type, current_type)
                operation = {
                    'type': mapped_type,
                    'date': date_val.strftime('%Y-%m-%d') if pd.notna(date_val) else None,
                    'amount': float(row.get('Amount')) if not pd.isna(row.get('Amount')) else None,
                    'currency': currency,
                    'comment': row.get('Comment'),
                    'user_category': mapped_type,
                    'broker': 'xtb'
                }
                other_operations.append(operation)

        except StopIteration:
            break

    return {'companies': companies, 'other_operations': other_operations}

def get_cash_operations_from_excel_files(accounts):
    """
    Reads and merges cash operations from multiple Excel files (new format).
    """
    merged_data = {'companies': {}, 'other_operations': []}
    for account in accounts:
        cash_op_data = _parse_cash_operations(account, 'Cash Operations')

        if cash_op_data:
            for ticker, data in cash_op_data['companies'].items():
                if ticker not in merged_data['companies']:
                    merged_data['companies'][ticker] = {}
                for op_type, op_list in data.items():
                    if op_type not in merged_data['companies'][ticker]:
                        merged_data['companies'][ticker][op_type] = []
                    merged_data['companies'][ticker][op_type].extend(op_list)

            if 'other_operations' in cash_op_data:
                merged_data['other_operations'].extend(cash_op_data['other_operations'])

    dividends_data = {'companies': {}}
    other_cash_operations = {'other_operations': []}

    for ticker, data in merged_data['companies'].items():
        if 'dividends' in data:
            if ticker not in dividends_data['companies']:
                dividends_data['companies'][ticker] = {}
            dividends_data['companies'][ticker]['dividends'] = data['dividends']

    other_cash_operations['other_operations'] = merged_data['other_operations']

    for ticker, data in dividends_data['companies'].items():
        if 'dividends' in data:
            for dividend in data['dividends']:
                other_cash_operations['other_operations'].append({
                    'type': 'Dividend',
                    'date': dividend.get('date'),
                    'amount': dividend.get('amount'),
                    'currency': dividend.get('currency'),
                    'comment': f"Dividend for {ticker}",
                    'broker': 'xtb'
                })
                if dividend.get('withholding_tax', 0) != 0:
                    other_cash_operations['other_operations'].append({
                        'type': 'Withholding Tax',
                        'date': dividend.get('date'),
                        'amount': dividend.get('withholding_tax'),
                        'currency': dividend.get('currency'),
                        'comment': f"Withholding tax for {ticker} dividend",
                        'broker': 'xtb'
                    })

    for ticker in dividends_data['companies']:
        dividends_data['companies'][ticker]['dividends'].sort(key=lambda x: x.get('date'))

    other_cash_operations['other_operations'].sort(key=lambda x: (x.get('date') is None, x.get('date')))

    return dividends_data, other_cash_operations
