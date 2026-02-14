from datetime import datetime
from typing import Optional, Dict
from utils.exchange_rate import normalize_currency
from config import PRIMARY_CURRENCY

def calculate_cagr(end_value: float, start_value: float, years: float) -> float:
    """Calculates the Compound Annual Growth Rate."""
    if start_value <= 0 or end_value <= 0 or years <= 0:
        return 0.0
    return (end_value / start_value) ** (1 / years) - 1

def calculate_yoy(current_value: float, previous_value: float) -> float:
    """Calculates the Year-over-Year growth rate."""
    if previous_value <= 0:
        return 0.0
    return (current_value / previous_value) - 1

def normalize_price(price: float, ticker: str) -> float:
    """Handles ticker-specific price normalization (e.g., LSE pence to pounds)."""
    if price is not None and ticker.upper().endswith('.L'):
        return price / 100
    return price

def convert_currency(amount: float, from_currency: str, to_currency: str, date: str, exchange_rate_cache: Dict, get_rate_func) -> float:
    """
    Unified currency conversion utility.
    Requires get_rate_func (usually get_rate_from_cache) to be passed in to avoid circular imports.
    """
    if amount == 0:
        return 0.0
        
    from_curr = normalize_currency(from_currency)
    to_curr = normalize_currency(to_currency)
    
    if from_curr == to_curr:
        return amount
        
    rate = get_rate_func(exchange_rate_cache, from_curr, to_curr, date)
    if rate:
        return amount * rate
    return 0.0 # Or potentially return amount as fallback if preferred, but 0 is safer for totals
