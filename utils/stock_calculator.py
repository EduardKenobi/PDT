import pandas as pd
from typing import Optional

def sum_shares(positions_df: pd.DataFrame) -> float:
    """Sums the 'shares' column of a given DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing position data with a 'shares' column.

    Returns:
        float: The total sum of shares, or 0.0 if the DataFrame is empty.
    """
    if positions_df.empty or 'shares' not in positions_df.columns:
        return 0.0
    return positions_df['shares'].sum()

def calculate_cost_per_currency(positions_df: pd.DataFrame) -> dict:
    """
    Calculates the total purchase value for each currency in a DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing position data
                                      with 'currency' and 'purchase_value' columns.

    Returns:
        dict: A dictionary where keys are currencies and values are the total cost for that currency.
    """
    if positions_df.empty or 'currency' not in positions_df.columns or 'purchase_value' not in positions_df.columns:
        return {}

    # Group by currency and sum the purchase_value
    cost_per_currency = positions_df.groupby('currency')['purchase_value'].sum()
    
    # Convert the result to a dictionary
    return cost_per_currency.to_dict()

def calculate_unrealized_gain(total_cost: float, current_shares: float, current_price: float) -> tuple:
    """
    Calculates the unrealized gain and loss for a position.

    Args:
        total_cost (float): The total cost of the position.
        current_shares (float): The number of shares held.
        current_price (float): The current market price per share.

    Returns:
        tuple: A tuple containing the unrealized gain amount and percentage.
               Returns (0.0, 0.0) if inputs are invalid.
    """
    if total_cost <= 0 or current_shares <= 0 or current_price <= 0:
        return 0.0, 0.0

    market_value = current_shares * current_price
    unrealized_gain_amount = market_value - total_cost
    unrealized_gain_perc = unrealized_gain_amount / total_cost

    return unrealized_gain_amount, unrealized_gain_perc

def sum_realized_gains_per_currency(positions_df: pd.DataFrame) -> dict:
    """
    Calculates the total realized gain for each currency in a DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing closed position data
                                      with 'currency' and 'gross_pl_amount' columns.

    Returns:
        dict: A dictionary where keys are currencies and values are the total realized gain for that currency.
    """
    if positions_df.empty or 'currency' not in positions_df.columns or 'gross_pl_amount' not in positions_df.columns:
        return {}

    # Group by currency and sum the gross_pl_amount
    gains_per_currency = positions_df.groupby('currency')['gross_pl_amount'].sum()
    
    # Convert the result to a dictionary
    return gains_per_currency.to_dict()

def calculate_padi_value(shares: float, amount_per_share: Optional[float]) -> float:
    """Calculates the Projected Annual Dividend Income for a holding."""
    if shares > 0 and amount_per_share > 0:
        return shares * amount_per_share
    return 0.0

def calculate_forward_dividend(ticker: str, frequency_type: str, dividends_history: list, currency: str = '') -> float:
    """
    Calculates the forward dividend based on frequency type and historical dividend data.
    
    Args:
        ticker (str): The ticker symbol (for logging purposes).
        frequency_type (str): The dividend frequency type from ticker_map.yaml
                             (e.g., 'Monthly', 'Quarterly-Regulary', 'Quarterly-Unregulary', 
                              'Semi-Annually', 'Annually').
        dividends_history (list): List of dividend payment dictionaries with 'date' and 'amount' keys.
                                 Expected format: [{"date": "2024-01-15", "amount": 0.50}, ...]
        currency (str): The currency of the stock (e.g. 'USD', 'EUR', 'GBp'). 
                       Used to convert GBp (pence) to GBP (pounds) if necessary.
    
    Returns:
        float: The calculated forward dividend, or 0.0 if calculation fails.
    
    Logic:
        - Monthly & Quarterly-Regular: Last payment × Frequency
        - Quarterly-Unregular & Semi-Annually: Sum of all payments in the last 365 days (TTM).
          This is robust against timing shifts and merged payments. 
          Falls back to last payment annualized if no payments in the last year.
        - Annually: Last annual payment
    """
    from config import DIVIDEND_FREQ_MAP
    import logging
    from datetime import datetime
    import pandas as pd
    
    # Validate inputs
    if not frequency_type or frequency_type == 'N/A':
        return 0.0
    
    if not dividends_history or len(dividends_history) == 0:
        logging.warning(f"{ticker}: No dividend history available.")
        return 0.0
    
    # Get frequency multiplier
    frequency = DIVIDEND_FREQ_MAP.get(frequency_type)
    if frequency is None:
        logging.warning(f"{ticker}: Unknown frequency type '{frequency_type}'.")
        return 0.0
    
    # Sort and consolidate dividends by date
    try:
        # Consolidation: handle duplicates for the same date
        consolidated = {}
        for d in dividends_history:
            dt = d['date']
            amt = d['amount']
            if dt not in consolidated or amt > consolidated[dt]:
                consolidated[dt] = amt
        
        consolidated_history = [{"date": dt, "amount": amt} for dt, amt in consolidated.items()]
        # Sort descending by date
        sorted_dividends = sorted(consolidated_history, key=lambda x: x['date'], reverse=True)
    except (KeyError, TypeError) as e:
        logging.error(f"{ticker}: Invalid dividend history format: {e}")
        return 0.0
    
    # Calculate based on frequency type
    forward_div = 0.0
    try:
        if frequency_type in ['Monthly', 'Quarterly-Regulary', 'Quartely-Regulary', 'Quarterly']:
            # Monthly & Quarterly-Regular: Last payment × Frequency
            last_payment = sorted_dividends[0]['amount']
            forward_div = last_payment * frequency
        
        elif frequency_type in ['Quarterly-Unregulary', 'Quartely-Unregulary', 'Semi-Annually']:
            # Sum of all payments in the last 365 days (TTM)
            today = datetime.now()
            one_year_ago = today - pd.DateOffset(days=365)
            
            ttm_sum = 0.0
            payments_found = 0
            for div in sorted_dividends:
                div_date = pd.to_datetime(div['date'])
                if div_date > one_year_ago and div_date <= today:
                    ttm_sum += div['amount']
                    payments_found += 1
            
            if payments_found >= 1:
                forward_div = ttm_sum
            else:
                # Fallback: annualize the most recent payment
                logging.warning(f"{ticker}: No payments in last 365 days. Annualizing last payment.")
                last_payment = sorted_dividends[0]['amount']
                forward_div = last_payment * frequency
        
        elif frequency_type == 'Annually':
            # Annually: Last annual payment
            last_payment = sorted_dividends[0]['amount']
            forward_div = last_payment
        
        else:
            logging.warning(f"{ticker}: Unhandled frequency type '{frequency_type}'.")
            return 0.0
        
        # Handle GBp to GBP conversion
        # Check for GBp/GBP/GBX and if value is likely in pence (> 50 is a safe heuristic for dividend amount)
        if currency in ['GBp', 'GBP', 'GBX'] and forward_div > 50:
            forward_div = forward_div / 100.0
            
        return forward_div
            
    except (KeyError, IndexError, TypeError) as e:
        logging.error(f"{ticker}: Error calculating forward dividend: {e}")
        return 0.0
    
def above_safety_margin(value: float, target: float, margin: float) -> bool:
    """Checks if a value is above a target considering a safety margin."""
    return value > (target * (1 - margin))

