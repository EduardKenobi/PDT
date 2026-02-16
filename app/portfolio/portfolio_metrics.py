import pandas as pd
from datetime import datetime
from collections import defaultdict

from utils.data_loader import load_yaml
from config import PRIMARY_CURRENCY, CASH_OPERATIONS_OUTPUT_FILE, IBKR_CASH_BALANCE_OUTPUT_FILE
from utils.exchange_rate import get_rate_from_cache, normalize_currency
from utils.analytics import convert_currency

def calculate_free_cash_by_currency(cash_operations_data: dict) -> dict:
    """
    Calculates the total free cash for XTB for each currency by summing up:
    - Cash operations (deposits, withdrawals, other operations) - excluding transfers and IBKR operations
    - Dividends received
    """
    free_cash = defaultdict(float)

    # Process cash operations
    operations = cash_operations_data.get('other_operations', [])
    for op in operations:
        # Ignore IBKR operations
        if op.get('broker') == 'ibkr':
            continue

        user_category = op.get('user_category', '')
        # We exclude transfers_in from free cash calculation, otherwise they would double count deposits
        if 'transfer_in' in user_category:
            continue

        amount = op.get('amount', 0)
        currency = op.get('currency')
        if currency and amount:
            free_cash[normalize_currency(currency)] += amount

    return dict(free_cash)

def get_ibkr_free_cash() -> dict:
    """
    Loads the IBKR cash balance from the YAML file.
    """
    try:
        cash_balance_data = load_yaml(IBKR_CASH_BALANCE_OUTPUT_FILE)
    except FileNotFoundError:
        print(f"Warning: {IBKR_CASH_BALANCE_OUTPUT_FILE} not found. Cannot load IBKR cash balance.")
        return {}
    
    # Normalize keys
    normalized = {}
    for k, v in cash_balance_data.items():
        normalized[normalize_currency(k)] = v
    return normalized

def get_cash_operations_summary(exchange_rate_cache: dict) -> tuple[float, datetime | None]:
    """
    Calculates net capital contributed and finds the first operation date.
    """
    try:
        cash_operations_data = load_yaml(CASH_OPERATIONS_OUTPUT_FILE)
    except FileNotFoundError:
        print(f"Warning: {CASH_OPERATIONS_OUTPUT_FILE} not found. Cannot calculate net capital.")
        return 0.0, None

    net_capital = 0
    first_date = None
    operations = cash_operations_data.get('other_operations', [])

    for op in operations:
        category = op.get('user_category')
        if category in ['deposit', 'withdrawal']:
            amount = op.get('amount', 0)
            currency = normalize_currency(op.get('currency'))
            date_str = op.get('date')

            if date_str:
                current_date = datetime.strptime(date_str, '%Y-%m-%d')
                if first_date is None or current_date < first_date:
                    first_date = current_date

            if currency == PRIMARY_CURRENCY:
                net_capital += amount
            else:
                if date_str:
                    rate = get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, date_str)
                    if rate:
                        net_capital += amount * rate
                    else:
                        print(f"Warning: Could not find exchange rate for {currency} on {date_str} for a cash operation. Skipping.")
                else:
                    print("Warning: Missing date for a non-primary currency cash operation. Skipping.")

    return net_capital, first_date

def get_other_cash_operations_summary(exchange_rate_cache: dict) -> dict:
    """
    Calculates the sum of amounts for each cash operation type.
    """
    try:
        cash_operations_data = load_yaml(CASH_OPERATIONS_OUTPUT_FILE)
    except FileNotFoundError:
        print(f"Warning: {CASH_OPERATIONS_OUTPUT_FILE} not found. Cannot calculate other operations summary.")
        return {}

    operation_sums = {}
    operations = cash_operations_data.get('other_operations', [])

    for op in operations:
        op_type = op.get('type')
        amount = op.get('amount', 0)
        currency = normalize_currency(op.get('currency'))
        
        if not op_type or not currency or not amount:
            continue

        if op_type not in operation_sums:
            operation_sums[op_type] = {}

        operation_sums[op_type][currency] = operation_sums[op_type].get(currency, 0) + amount

    return operation_sums

def get_portfolio_dividends_per_year(div_df: pd.DataFrame, exchange_rate_cache: dict) -> dict[int, float]:
    """
    Calculates the total portfolio dividends for each year in the primary currency.
    """
    if div_df.empty:
        return {}

    df = div_df.copy()
    df['amount_primary'] = df.apply(
        lambda r: convert_currency(r['amount'], r['currency'], PRIMARY_CURRENCY, r['date'].strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache), 
        axis=1
    )
    df['year'] = df['date'].dt.year
    return df.groupby('year')['amount_primary'].sum().to_dict()

def get_portfolio_dividends_ltm(div_df: pd.DataFrame, exchange_rate_cache: dict) -> float:
    """
    Calculates the portfolio dividends from last twelve months.
    """
    if div_df.empty:
        return 0.0
        
    today = pd.Timestamp.now()
    t12m_start = today - pd.DateOffset(months=12)
    
    mask = (div_df['date'] >= t12m_start) & (div_df['date'] <= today)
    ltm_df = div_df[mask].copy()
    
    if ltm_df.empty:
        return 0.0

    ltm_df['amount_primary'] = ltm_df.apply(
        lambda r: convert_currency(r['amount'], r['currency'], PRIMARY_CURRENCY, r['date'].strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache), 
        axis=1
    )
    return float(ltm_df['amount_primary'].sum())

def get_portfolio_dividends_per_quarter(div_df: pd.DataFrame, exchange_rate_cache: dict) -> dict[tuple[int, int], float]:
    """
    Calculates the total portfolio dividends for each quarter in the primary currency.
    """
    if div_df.empty:
        return {}

    df = div_df.copy()
    df['amount_primary'] = df.apply(
        lambda r: convert_currency(r['amount'], r['currency'], PRIMARY_CURRENCY, r['date'].strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache), 
        axis=1
    )
    df['year'] = df['date'].dt.year
    df['quarter'] = df['date'].dt.quarter
    return df.groupby(['year', 'quarter'])['amount_primary'].sum().to_dict()
