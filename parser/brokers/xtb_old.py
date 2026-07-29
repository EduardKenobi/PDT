import pandas as pd
import re
from .xtb_helpers import (
    parse_excel,
    get_currency,
    find_header_row,
    handle_possible_split,
    calculate_time_test,
    merge_data,
    find_open_position_sheet,
    convert_ticker
)
from .xtb_config import (
    CLSD_POSITION_SHEET,
    CLSD_COLUMNS_MANDATORY,
    OPN_COLUMNS_MANDATORY,
    OUT_OF_RANGE,
    CLSD_ROW_INDEX_CURRENCY,
    CLSD_COL_INDEX_CURRENCY,
    OPN_ROW_INDEX_CURRENCY,
    OPN_COL_INDEX_CURRENCY,
    CASH_OPERATION_SHEET,
    CASH_OPERATION_ROW_INDEX_CURRENCY,
    CASH_OPERATION_COL_INDEX_CURRENCY,
    CASH_OPERATION_COLUMNS_MANDATORY,
    WITHHOLDING_TAX_ATTRIBUTE,
    DIVIDENDS_ATTRIBUTE,
    IGNORE_TYPES
)

def _parse_withholding_tax_rate(comment):
    """
    Parses the withholding tax rate from the comment string.
    """
    if not isinstance(comment, str):
        return None
    match = re.search(r'WHT\s(\d+)%', comment)
    if match:
        return float(match.group(1))
    return None

def _parse_dividend_per_share(comment):
    """
    Parses the dividend per share value and currency from the comment string.
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

def _process_row_to_transaction(ticker, row, currency, position_type):
    """
    Processes a row from the DataFrame to create a transaction dictionary.
    """
    purchase_value = float(row.get('Purchase value')) if not pd.isna(row.get('Purchase value')) else None
    gross = float(row.get('Gross P/L')) if not pd.isna(row.get('Gross P/L')) else None
    if pd.isna(purchase_value):
        purchase_value = float(row.get('Margin')) if not pd.isna(row.get('Margin')) else None
        
    transaction = {
        'position': int(row.get('Position')) if not pd.isna(row.get('Position')) else None,
        'type': position_type,
        'shares': float(row.get('Volume')) if not pd.isna(row.get('Volume')) else None,
        'open_date': pd.to_datetime(row.get('Open time')).strftime('%Y-%m-%d'),
        'open_price': float(row.get('Open price')) if not pd.isna(row.get('Open price')) else None,
        'purchase_value': None if pd.isna(purchase_value) else purchase_value,
        'currency': currency,
        'broker': 'xtb',
    }

    if position_type == 'closed':
        sale_value = (
            float(row.get('Sale value')) if not pd.isna(row.get('Sale value')) else (None if pd.isna(row.get('Margin')) or pd.isna(row.get('Gross P/L')) else float(row.get('Margin') + row.get('Gross P/L')))
        )
        gross_pl_amount = float(row.get('Gross P/L')) if not pd.isna(row.get('Gross P/L')) else None

        comment = row.get('Close origin')
        
        is_correction = False
        recalculated_profit = None
        if gross_pl_amount == 0.0:
            if isinstance(comment, str) and 'correction' in comment.lower():
                is_correction = True
                recalculated_profit = sale_value - purchase_value
                print(f"Warning: Detected broker correction for position {transaction['position']} of ticker {ticker}. A recalculated profit of {recalculated_profit:.2f} will be used for tax calculation.")
                
        if not is_correction:
            purchase_value = handle_possible_split(ticker, row.get('Position'), transaction['purchase_value'], sale_value, gross_pl_amount, transaction['shares'])

        transaction.update({
            'purchase_value': purchase_value,
        })
        transaction.update({
            'close_date': pd.to_datetime(row.get('Close time')).strftime('%Y-%m-%d'),
            'close_price': float(row.get('Close price')) if not pd.isna(row.get('Close price')) else None,
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

def _setup_df_and_currency(input_path, sheet_name, currency_row, currency_col, header_columns):
    """
    Sets up the DataFrame and extracts the currency from a given Excel sheet.
    """
    try:
        df = parse_excel(input_path, sheet_name)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return None, None
    
    if df.empty:
        print(f"Error: The sheet '{sheet_name}' is empty or not found in the file '{input_path}'.")
        return None, None
    
    try:
        currency = get_currency(df, currency_row, currency_col)
    except IndexError as e:
        print(f"Error: {e}")
        return None, None
    
    if currency is None:
        print(f"Error: Could not determine the currency from the sheet.")
        return None, None
    
    header_row_index = find_header_row(df, *header_columns)
    if header_row_index == OUT_OF_RANGE:
        print(f"Error: Could not find the header row in the sheet '{sheet_name}'.")
        return None, None
    
    df.columns = df.iloc[header_row_index]
    df = df.iloc[header_row_index + 1:].reset_index(drop=True)
    
    return df, currency

def _parse_positions(input_path, sheet_name, mandatory_columns, currency_row, currency_col, position_type):
    """
    Parses the specified sheet from an Excel file and extracts transaction data.
    """
    df, currency = _setup_df_and_currency(input_path, sheet_name, currency_row, currency_col, ())
    if df is None or currency is None:
        return None
    df.dropna(subset=mandatory_columns, inplace=True)

    companies = {}
    for _, row in df.iterrows():
        original_ticker = row.get('Symbol')
        if not original_ticker or pd.isna(original_ticker):
            continue

        ticker = convert_ticker(original_ticker)
        transaction = _process_row_to_transaction(ticker, row, currency, position_type)

        if ticker not in companies:
            companies[ticker] = {'transactions': []}
        companies[ticker]['transactions'].append(transaction)

    return {'companies': companies}

def get_transactions_from_excel_files(accounts):
    """
    Reads and merges transactions from multiple Excel files.
    """
    merged_data = {'companies': {}}
    for account in accounts:
        sheet_name = find_open_position_sheet(account)
        if sheet_name:
            open_data = _parse_positions(account, sheet_name, OPN_COLUMNS_MANDATORY, OPN_ROW_INDEX_CURRENCY, OPN_COL_INDEX_CURRENCY, 'open')
            if open_data:
                merged_data = merge_data(merged_data, open_data)

        closed_data = _parse_positions(account, CLSD_POSITION_SHEET, CLSD_COLUMNS_MANDATORY, CLSD_ROW_INDEX_CURRENCY, CLSD_COL_INDEX_CURRENCY, 'closed')
        if closed_data:
            merged_data = merge_data(merged_data, closed_data)

    # Handle positions that are both open and closed in the same report
    for ticker, company_data in merged_data['companies'].items():
        if 'transactions' not in company_data:
            continue

        transactions = company_data['transactions']
        closed_position_ids = {t['position'] for t in transactions if t['type'] == 'closed'}
        
        final_transactions = []
        for t in transactions:
            is_open = t['type'] == 'open'
            position_id = t['position']
            
            if is_open and position_id in closed_position_ids:
                print(f"Warning: Position {position_id} for ticker {ticker} is closed in the same report. Removing the open position entry.")
                continue
            
            final_transactions.append(t)
        
        company_data['transactions'] = final_transactions

    for ticker in merged_data['companies']:
        if 'transactions' in merged_data['companies'][ticker]:
            merged_data['companies'][ticker]['transactions'].sort(key=lambda x: x.get('close_date') or x.get('open_date'))

    return merged_data

def _process_dividend_row(df, df_iter, index, row, currency):
    """
    Processes a row from the DataFrame to create a dividend transaction dictionary.
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
        next_type = next_row_df.get('Type', '').strip()

        if next_type == WITHHOLDING_TAX_ATTRIBUTE:
            dividend_transaction['withholding_tax'] = float(next_row_df.get('Amount')) if not pd.isna(next_row_df.get('Amount')) else None
            dividend_transaction['withholding_tax_rate'] = _parse_withholding_tax_rate(next_row_df.get('Comment'))
            next(df_iter, None)

    except (IndexError, StopIteration):
        pass

    return dividend_transaction

def _parse_cash_operations(input_path, sheet_name, mandatory_columns):
    """ 
    Parses cash operations from the specified sheet in an Excel file.
    """ 
    header_columns = ('Type', 'Symbol', 'Time')
    df, currency = _setup_df_and_currency(input_path, sheet_name, CASH_OPERATION_ROW_INDEX_CURRENCY, CASH_OPERATION_COL_INDEX_CURRENCY, header_columns)
    if df is None or currency is None:
        return None

    df.dropna(subset=['Type'], inplace=True)

    companies = {}
    other_operations = []
    
    df_iter = df.iterrows()
    while True:
        try:
            index, row = next(df_iter)
            current_type = str(row.get('Type', '')).strip()

            # if not current_type or current_type in IGNORE_TYPES:
            #     continue

            if current_type == DIVIDENDS_ATTRIBUTE:
                if row[mandatory_columns].isnull().any():
                    print(f"Warning: Skipping dividend row at index {index} due to missing mandatory data.")
                    continue
                
                original_ticker = row.get('Symbol')
                if not original_ticker or pd.isna(original_ticker):
                    continue

                ticker = convert_ticker(original_ticker)
                dividend_transaction = _process_dividend_row(df, df_iter, index, row, currency)

                if ticker not in companies:
                    companies[ticker] = {}
                if 'dividends' not in companies[ticker]:
                    companies[ticker]['dividends'] = []
                companies[ticker]['dividends'].append(dividend_transaction)

            else:
                date_val = pd.to_datetime(row.get('Time'))
                operation = {
                    'type': current_type,
                    'date': date_val.strftime('%Y-%m-%d') if pd.notna(date_val) else None,
                    'amount': float(row.get('Amount')) if not pd.isna(row.get('Amount')) else None,
                    'currency': currency,
                    'comment': row.get('Comment'),
                    'user_category': current_type,
                    'broker': 'xtb'
                }
                other_operations.append(operation)

        except StopIteration:
            break

    return {'companies': companies, 'other_operations': other_operations}

def get_cash_operations_from_excel_files(accounts):
    """
    Reads and merges cash operations from multiple Excel files.
    """
    merged_data = {'companies': {}, 'other_operations': []}
    for account in accounts:
        cash_op_data = _parse_cash_operations(account, CASH_OPERATION_SHEET, CASH_OPERATION_COLUMNS_MANDATORY)

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
