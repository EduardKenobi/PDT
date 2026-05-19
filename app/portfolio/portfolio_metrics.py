import pandas as pd
from datetime import datetime
from collections import defaultdict
from calendar import month_name

from app.models import TiersPadi
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

def get_portfolio_dividend_calendar(all_tickers_data: dict, today: pd.Timestamp) -> dict[str, list[str]]:
    """
    Creates a dividend calendar mapping each month to the list of tickers paying dividends in that month.
    """
    # Pre-calculate Dividend Calendar for Reporter
    dividend_calendar = {}
    timeframe_months = 12
    # Reset to the beginning of the current day/month (00:00:00) so we capture everything from today onwards
    cal_today = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    time_limit = cal_today + pd.DateOffset(months=timeframe_months)

    for ticker, data in all_tickers_data.items():
        if data.current_shares > 0:
            payment_months = data.dividend_payment_months
            if not payment_months:
                continue

            # Project payments for the next years
            for year_offset in range(2):  # Check current and next year
                year = cal_today.year + year_offset
                for month in payment_months:
                    try:
                        payment_date = datetime(year, month, 1)
                    except ValueError:
                        continue 

                    if payment_date >= cal_today and payment_date < time_limit:
                        month_year_str = f"{month_name[month]} {year}"
                        if month_year_str not in dividend_calendar:
                            dividend_calendar[month_year_str] = []
                        if ticker not in dividend_calendar[month_year_str]:
                            dividend_calendar[month_year_str].append(ticker)
    return dividend_calendar

def check_portfolio_history_consistency(month_ends: list[pd.Timestamp], monthly_metrics: dict, cached_history: list[dict]) -> list[dict]:
    """
    Checks if the cached historical portfolio metrics are consistent with the newly calculated monthly metrics.
    If consistent, returns the cached history up to the last month. If not, returns an empty list to recalculate from scratch.
    Consistency is checked by comparing the total dividends and total deposits for the last cached month with
    the corresponding values in the newly calculated monthly metrics. If there is a significant difference (greater than 0.01), it is considered inconsistent.
    """
    history = []
    current_me_str = month_ends[-1].strftime('%m/%y')
        
    # Check for consistency: if last cached month's total dividends match fresh calculation
    last_cached_entry = cached_history[-1] if cached_history[-1]['date'] != current_me_str else (cached_history[-2] if len(cached_history) > 1 else None)
    
    is_consistent = True
    if last_cached_entry:
        last_date_str = last_cached_entry['date']
        fresh_total_div = monthly_metrics['cumulative_dividends'].get(last_date_str, 0)
        fresh_total_dep = monthly_metrics['cumulative_deposits'].get(last_date_str, 0)
        
        # Use a small epsilon for float comparison
        div_diff = abs(last_cached_entry['total_dividends'] - fresh_total_div)
        dep_diff = abs(last_cached_entry['total_deposit'] - fresh_total_dep)
        
        if div_diff > 0.01 or dep_diff > 0.01:
            reason = "dividends" if div_diff > 0.01 else "deposits"
            print(f"      Historical data change detected in {reason} for {last_date_str}. Recalculating full history.")
            is_consistent = False
    
    if is_consistent:
        for entry in cached_history:
            if entry['date'] != current_me_str:
                history.append(entry)
            else:
                break
        if history:
            print(f"      Resuming portfolio history from {history[-1]['date']}. Skipped {len(history)} months.")
        else:
            print("     Resuming portfolio history from the beginning. No cached months added.")
    else:
        print("      Inconsistent historical data. Starting portfolio history from scratch.")
    return history

def get_portfolio_tier_padi_ratio(all_tickers_data: dict) -> TiersPadi:
    """
    Determines the portfolio tier PADI ratio based on the total PADI.
    Returns a TiersPadi object containing total PADI and ratio for each tier.
    
    Args:
        all_tickers_data (dict): The dictionary containing ticker data.
    Returns:
        TiersPadi: A TiersPadi object with metrics for each tier.
    """
    total_padi = sum(data.padi for data in all_tickers_data.values())
    
    tier_1_padi = sum(
        data.padi for data in all_tickers_data.values() 
        if data.tier_group == 'Tier 1'
    ) 

    tier_2_padi = sum(
        data.padi for data in all_tickers_data.values() 
        if data.tier_group == 'Tier 2'
    )

    tier_3_padi = sum(
        data.padi for data in all_tickers_data.values() 
        if data.tier_group == 'Tier 3'
    )

    tier_g_padi = sum(
        data.padi for data in all_tickers_data.values() 
        if data.tier_group == 'Tier G'
    )

    other_padi = sum(
        data.padi for data in all_tickers_data.values() 
        if data.tier_group not in ['Tier 1', 'Tier 2', 'Tier 3', 'Tier G']
    )

    if total_padi == 0:
        return TiersPadi(
            tier_1=(0.0, 0.0),
            tier_2=(0.0, 0.0),
            tier_3=(0.0, 0.0),
            tier_g=(0.0, 0.0),
            other=(0.0, 0.0)
        )
        
    return TiersPadi(
        tier_1=(tier_1_padi, tier_1_padi / total_padi),
        tier_2=(tier_2_padi, tier_2_padi / total_padi),
        tier_3=(tier_3_padi, tier_3_padi / total_padi),
        tier_g=(tier_g_padi, tier_g_padi / total_padi),
        other=(other_padi, other_padi / total_padi)
    )

def validate_padi_tier_ratios(all_tickers_data: dict) -> dict[str, bool]:
    """
    Validates if any ticker's PADI ratio within its tier group exceeds the defined threshold.
    Returns a dictionary mapping tier names to a boolean (True if all tickers in that tier are within limits).
    """
    from config import PADI_TIER_THRESHOLDS

    # Calculate total PADI per tier group
    tier_totals = defaultdict(float)
    for data in all_tickers_data.values():
        if data.has_open_position:
            tier_totals[data.tier_group] += data.padi

    # Check thresholds
    tier_status = {tier: True for tier in PADI_TIER_THRESHOLDS.keys()}
    for data in all_tickers_data.values():
        if data.has_open_position and data.tier_group in PADI_TIER_THRESHOLDS:
            tier = data.tier_group
            tier_total = tier_totals[tier]
            if tier_total > 0:
                ratio_within_tier = data.padi / tier_total
                if ratio_within_tier > PADI_TIER_THRESHOLDS[tier]:
                    tier_status[tier] = False

    return tier_status