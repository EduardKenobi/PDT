import pandas as pd
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from collections import defaultdict

from app.models import TickerData
from config import PRIMARY_CURRENCY, DIVIDEND_FREQ_MAP
from utils.exchange_rate import normalize_currency, get_rate_from_cache
from utils.analytics import convert_currency, normalize_price, calculate_cagr, calculate_yoy
from utils.stock_calculator import calculate_padi_value, calculate_forward_dividend



def _get_history_metrics_at_date(date: pd.Timestamp, ref_str: str, transactions_df: pd.DataFrame, div_df: pd.DataFrame, market_data: dict, ticker_map_data: dict, exchange_rate_cache: dict, is_recent_me: bool) -> Tuple[float, float, float]:
    """Calculates invested_amount, market_value, and padi for a specific date using DataFrames."""

    # 1. Filter transactions open at date
    open_at_date = transactions_df[
        (transactions_df['open_date_dt'] <= date) & 
        ((transactions_df['close_date_dt'].isna()) | (transactions_df['close_date_dt'] > date))
    ]
    
    if open_at_date.empty:
        return 0.0, 0.0, 0.0

    # 2. Calculate invested amount (vectorized for same currency, otherwise loop)
    # Simple loop for conversion since it depends on individual dates/currencies
    invested_amount = 0.0
    current_holdings = defaultdict(float)
    
    for _, pos in open_at_date.iterrows():
        currency = normalize_currency(pos['currency'])
        invested_amount += convert_currency(pos['purchase_value'], currency, PRIMARY_CURRENCY, pos['open_date'], exchange_rate_cache, get_rate_from_cache)
        current_holdings[pos['ticker']] += pos['shares']
        
    # 3. Calculate market value and PADI
    market_value = 0.0
    padi_at_date = 0.0
    
    for ticker, shares in current_holdings.items():
        ticker_cache = market_data.get('tickers', {}).get(ticker, {})
        static_info = ticker_cache.get('static', {})
        dynamic_data = ticker_cache.get('dynamic', {})
        
        price_currency = normalize_currency(static_info.get('currency') or PRIMARY_CURRENCY)
        historical_prices = dynamic_data.get('monthly_prices', {})
        
        # Determine price based on whether it's the running month or historical
        is_running_month = (date >= pd.Timestamp.now().to_period('M').to_timestamp())
        if is_running_month:
            price = dynamic_data.get('price')
        else:
            price = historical_prices.get(ref_str)
        
        if price is None and historical_prices:
            price_dates = sorted([d for d in historical_prices.keys() if d <= ref_str])
            if price_dates:
                price = historical_prices[price_dates[-1]]
            elif is_running_month:
                price_dates = sorted(historical_prices.keys())
                if price_dates:
                    price = historical_prices[price_dates[-1]]
        
        price = normalize_price(price, ticker)
        if price is not None:
            market_value += convert_currency(shares * price, price_currency, PRIMARY_CURRENCY, ref_str, exchange_rate_cache, get_rate_from_cache)

        # Calculate forward dividend from official historical data (Yahoo)
        div_frequency_str = ticker_map_data.get('ticker_info', {}).get(ticker, {}).get('div_frequency', 'N/A')
        dividends_history = dynamic_data.get('dividends', [])
        
        # Filter official dividends up to the historical date
        hist_dividends_data = [
            div for div in dividends_history 
            if 'date' in div and pd.to_datetime(div['date']) <= date
        ]

        if hist_dividends_data:
            try:
                forward_dividend_hist = calculate_forward_dividend(
                    ticker=ticker,
                    frequency_type=div_frequency_str,
                    dividends_history=hist_dividends_data,
                    currency=price_currency,
                    reference_date=date # Key fix: make staleness check relative to historical point
                )
                
                is_div_suspended = False
                div_suspended_val = ticker_map_data.get('ticker_info', {}).get(ticker, {}).get('div_suspended', False)
                if isinstance(div_suspended_val, str):
                    ref_ts = pd.to_datetime(date).tz_localize(None)
                    is_div_suspended = (ref_ts >= pd.to_datetime(div_suspended_val).tz_localize(None))
                elif isinstance(div_suspended_val, bool):
                    is_div_suspended = div_suspended_val
                
                if is_div_suspended:
                    forward_dividend_hist = 0.0

                if forward_dividend_hist > 0:
                    padi_hist = calculate_padi_value(shares, forward_dividend_hist)
                    padi_at_date += convert_currency(padi_hist, price_currency, PRIMARY_CURRENCY, ref_str, exchange_rate_cache, get_rate_from_cache)

            except Exception as e:
                logging.warning(f"Could not calculate historical forward dividend for {ticker} at {date}: {e}")

    return invested_amount, market_value, padi_at_date

def _get_month_ends() -> pd.DatetimeIndex:
    """Centralized logic for defining the range of month ends for history."""
    start_date = pd.Timestamp('2021-06-30')
    end_date = pd.Timestamp.now().to_period('M').to_timestamp('M')
    return pd.date_range(start=start_date, end=end_date, freq='ME')

def _calculate_cumulative_dividends_history(month_ends: pd.DatetimeIndex, div_df: pd.DataFrame, exchange_rate_cache: dict) -> Dict[str, float]:
    """Pre-calculates cumulative dividends for all month ends."""
    cumulative_dividends = {}
    if div_df.empty:
        return {me.strftime('%m/%y'): 0 for me in month_ends}
        
    total_div = 0
    sorted_divs = div_df.sort_values('date')
    div_idx = 0
    for me in month_ends:
        while div_idx < len(sorted_divs) and sorted_divs.iloc[div_idx]['date'] <= me:
            div = sorted_divs.iloc[div_idx]
            total_div += convert_currency(div['amount'], div['currency'], PRIMARY_CURRENCY, div['date'].strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache)
            div_idx += 1
        cumulative_dividends[me.strftime('%m/%y')] = total_div
    return cumulative_dividends

def _calculate_cumulative_cash_history(month_ends: pd.DatetimeIndex, other_ops: pd.DataFrame, exchange_rate_cache: dict, ibkr_cash_primary: float, first_ibkr_date: pd.Timestamp) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    """Pre-calculates cumulative cash and deposits for all month ends."""
    history_metrics = {
        'cumulative_cash': {},
        'cumulative_deposits': {},
        'monthly_deposits': {}
    }
    
    if other_ops.empty:
        empty_map = {me.strftime('%m/%y'): 0 for me in month_ends}
        return empty_map, empty_map, empty_map

    xtb_cash = 0
    total_dep = 0
    cash_ops = other_ops[
        (other_ops['broker'] != 'ibkr') & 
        (~other_ops['user_category'].str.contains('transfer_in', na=False))
    ].sort_values('date_dt')
    deposit_ops = other_ops[other_ops['user_category'].isin(['deposit', 'withdrawal'])].sort_values('date_dt')
    
    cash_idx = 0
    dep_idx = 0
    
    for me in month_ends:
        me_str = me.strftime('%m/%y')
        # XTB Cash
        while cash_idx < len(cash_ops) and cash_ops.iloc[cash_idx]['date_dt'] <= me:
            op = cash_ops.iloc[cash_idx]
            xtb_cash += convert_currency(op['amount'], normalize_currency(op['currency']), PRIMARY_CURRENCY, op['date'], exchange_rate_cache, get_rate_from_cache)
            cash_idx += 1
        
        # IBKR Cash
        current_ibkr_cash = ibkr_cash_primary if first_ibkr_date and me >= first_ibkr_date else 0
        history_metrics['cumulative_cash'][me_str] = xtb_cash + current_ibkr_cash
        
        # Deposits
        month_dep = 0
        month_start = me - pd.DateOffset(months=1)
        while dep_idx < len(deposit_ops) and deposit_ops.iloc[dep_idx]['date_dt'] <= me:
            op = deposit_ops.iloc[dep_idx]
            amt = convert_currency(op['amount'], normalize_currency(op['currency']), PRIMARY_CURRENCY, op['date'], exchange_rate_cache, get_rate_from_cache)
            total_dep += amt
            if month_start < op['date_dt'] <= me:
                month_dep += amt
            dep_idx += 1
        
        history_metrics['cumulative_deposits'][me_str] = total_dep
        history_metrics['monthly_deposits'][me_str] = month_dep

    return history_metrics['cumulative_cash'], history_metrics['cumulative_deposits'], history_metrics['monthly_deposits']

def _prepare_monthly_portfolio_metrics(month_ends: pd.DatetimeIndex, div_df: pd.DataFrame, other_ops: pd.DataFrame, exchange_rate_cache: dict, ibkr_cash_primary: float, first_ibkr_date: pd.Timestamp) -> Dict[str, Dict]:
    """Orchestrates pre-calculation of cumulative dividends, cash, and deposits."""
    cum_divs = _calculate_cumulative_dividends_history(month_ends, div_df, exchange_rate_cache)
    cum_cash, cum_deps, mon_deps = _calculate_cumulative_cash_history(month_ends, other_ops, exchange_rate_cache, ibkr_cash_primary, first_ibkr_date)
    
    return {
        'cumulative_dividends': cum_divs,
        'cumulative_cash': cum_cash,
        'cumulative_deposits': cum_deps,
        'monthly_deposits': mon_deps
    }

def _get_cash_and_deposits_at_date(date: pd.Timestamp, other_ops: pd.DataFrame, exchange_rate_cache: dict, ibkr_cash_primary: float, first_ibkr_date: Optional[pd.Timestamp]) -> Tuple[float, float, float]:
    """Calculates cash balance and cumulative/monthly deposits for a specific date."""
    xtb_cash = 0
    total_deposit = 0
    monthly_deposit = 0
    
    if not other_ops.empty:
        # Cash calculation
        ops_up_to_date = other_ops[
            (other_ops['date_dt'] <= date) & 
            (other_ops['broker'] != 'ibkr') & 
            (~other_ops['user_category'].str.contains('transfer_in', na=False))
        ]
        for _, op in ops_up_to_date.iterrows():
            currency = normalize_currency(op['currency'])
            xtb_cash += convert_currency(op['amount'], currency, PRIMARY_CURRENCY, op['date'], exchange_rate_cache, get_rate_from_cache)

        # Deposit calculation
        deposit_ops = other_ops[other_ops['user_category'].isin(['deposit', 'withdrawal'])]
        deposits_up_to_date = deposit_ops[deposit_ops['date_dt'] <= date]
        for _, op in deposits_up_to_date.iterrows():
            currency = normalize_currency(op['currency'])
            amount_primary = convert_currency(op['amount'], currency, PRIMARY_CURRENCY, op['date'], exchange_rate_cache, get_rate_from_cache)
            total_deposit += amount_primary
            
            if date - pd.DateOffset(months=1) < op['date_dt'] <= date:
                monthly_deposit += amount_primary

    current_ibkr_cash = ibkr_cash_primary if first_ibkr_date and date >= first_ibkr_date else 0
    total_cash = xtb_cash + current_ibkr_cash
    
    return total_cash, total_deposit, monthly_deposit

def _aggregate_ticker_data_by_date(all_tickers_data: Dict[str, TickerData]) -> Dict[str, Dict]:
    """Aggregates invested, market value, and padi from all tickers by date."""
    ticker_histories_by_date = defaultdict(lambda: {'invested': 0, 'market_value': 0, 'padi': 0})
    for ticker, data in all_tickers_data.items():
        for entry in data.history:
            d = entry['date']
            ticker_histories_by_date[d]['invested'] += entry['invested_amount']
            ticker_histories_by_date[d]['market_value'] += entry['market_value']
            ticker_histories_by_date[d]['padi'] += entry['padi']
    return ticker_histories_by_date

def _create_history_entry(me_str: str, ticker_metrics: dict, cum_metrics: dict, history: List[Dict]) -> Dict:
    """Creates a single portfolio history entry with growth and health metrics."""
    invested_amount = ticker_metrics['invested']
    market_value = ticker_metrics['market_value']
    padi_at_me = ticker_metrics['padi']
    
    total_cash = cum_metrics['cash']
    total_deposit = cum_metrics['total_deposit']
    monthly_deposit = cum_metrics['monthly_deposit']
    total_dividends = cum_metrics['total_dividends']

    total_amount = market_value + total_cash
    unrealized_gain = market_value - invested_amount
    total_gain_perc = (total_amount / total_deposit - 1) if total_deposit > 0 else 0
    
    # Calculate Growth Metrics (YoY, CAGR)
    padi_yoy = calculate_yoy(padi_at_me, history[-12]['padi']) if len(history) >= 12 else 0
    padi_3y = calculate_cagr(padi_at_me, history[-36]['padi'], 3) if len(history) >= 36 else 0
    padi_5y = calculate_cagr(padi_at_me, history[-60]['padi'], 5) if len(history) >= 60 else 0

    total_amount_yoy = calculate_yoy(total_amount, history[-12]['total_amount']) if len(history) >= 12 else 0
    total_amount_3y = calculate_cagr(total_amount, history[-36]['total_amount'], 3) if len(history) >= 36 else 0
    total_amount_5y = calculate_cagr(total_amount, history[-60]['total_amount'], 5) if len(history) >= 60 else 0

    return {
        'date': me_str,
        'deposit': monthly_deposit,
        'total_deposit': total_deposit,
        'total_dividends': total_dividends,
        'padi': padi_at_me,
        'padi_yoy': padi_yoy,
        'padi_cagr_3y': padi_3y,
        'padi_cagr_5y': padi_5y,
        'invested_amount': invested_amount,
        'unrealized_gain': unrealized_gain,
        'total_amount': total_amount,
        'total_gain_perc': total_gain_perc,
        'total_amount_yoy': total_amount_yoy,
        'total_amount_cagr_3y': total_amount_3y,
        'total_amount_cagr_5y': total_amount_5y,
        'padi_total_amount': padi_at_me / total_amount if total_amount > 0 else 0,
        'div_engine_health': 0.6 * padi_3y + 0.4 * padi_5y
    }
