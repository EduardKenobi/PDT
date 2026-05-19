import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from app.models import TickerData, DividendGrowthMetrics, PositionData, ClosedPositionData
from config import PRIMARY_CURRENCY, DIVIDEND_FREQ_MAP, ANALYSIS_MAP, SAFETY_MARGIN, TIER1, TIER2, TIER3, TIERG, INFLATION_RATE, PEG_RATIO_THRESHOLD
from utils.stock_calculator import sum_shares, calculate_cost_per_currency, calculate_padi_value, calculate_forward_dividend, above_safety_margin
from utils.analytics import calculate_cagr, calculate_yoy, normalize_price, convert_currency
from app.stock.stock_metrics import (
    calculate_total_dividends, predict_next_dividend_month, 
    get_dividend_payment_months, get_historical_dividend_dates, calculate_dividend_growth, is_div_growth_above_inflation
)
from utils.exchange_rate import normalize_currency, get_rate_from_cache
from app.history.history_helpers import _get_month_ends, _get_history_metrics_at_date

def process_closed_positions(closed_positions: pd.DataFrame, exchange_rate_cache: Dict, price_currency: str) -> Tuple[List[ClosedPositionData], float, float]:
    """
    Process closed positions using cached exchange rates.
    """
    closed_positions_details: List[ClosedPositionData] = []
    ticker_realized_gain = 0
    ticker_cost_of_closed = 0

    for _, pos in closed_positions.iterrows():
        currency = normalize_currency(pos['currency'])
        purchase_value_primary = convert_currency(pos['purchase_value'], currency, PRIMARY_CURRENCY, pos['open_date'], exchange_rate_cache, get_rate_from_cache)
        realized_gain_lot_local = pos['gross_pl_amount']
        realized_gain_lot_perc = pos['gross_pl_percent']
        realized_gain_lot_primary = convert_currency(realized_gain_lot_local, currency, PRIMARY_CURRENCY, pos['close_date'], exchange_rate_cache, get_rate_from_cache)

        ticker_realized_gain += realized_gain_lot_primary
        ticker_cost_of_closed += purchase_value_primary

        closed_positions_details.append(
            ClosedPositionData(
                open_date=pos['open_date'],
                close_date=pos['close_date'],
                shares=pos['shares'],
                open_price=pos['open_price'],
                close_price=pos['close_price'],
                currency=currency,
                broker=pos['broker'],
                purchase_value=pos['purchase_value'],
                sale_value=pos['sale_value'],
                realized_gain_amount=realized_gain_lot_primary,
                realized_gain_percentage=realized_gain_lot_perc
            )
        )

    return closed_positions_details, ticker_realized_gain, ticker_cost_of_closed

def process_open_positions(open_positions: pd.DataFrame, current_price: float, price_currency: str, exchange_rate_cache: Dict) -> Tuple[List[PositionData], float, float, float, Dict]:
    """
    Process open positions using cached price and exchange rates.
    """
    open_positions_details: List[PositionData] = []
    gain_amount = 0
    total_cost_primary = 0
    market_value_primary = 0
    cost_by_currency = calculate_cost_per_currency(open_positions)

    today_str = datetime.now().strftime('%Y-%m-%d')
    price_currency = normalize_currency(price_currency)

    for _, pos in open_positions.iterrows():
        currency = normalize_currency(pos['currency'])
        cost_basis_lot_primary = convert_currency(pos['purchase_value'], currency, PRIMARY_CURRENCY, pos['open_date'], exchange_rate_cache, get_rate_from_cache)
        total_cost_primary += cost_basis_lot_primary

        current_lot_value_primary = 0
        if current_price and price_currency:
            current_lot_value_primary = convert_currency(pos['shares'] * current_price, price_currency, PRIMARY_CURRENCY, today_str, exchange_rate_cache, get_rate_from_cache)
            if not current_lot_value_primary and price_currency != PRIMARY_CURRENCY:
                # If conversion fails, keep cost basis to avoid zeroing out value if just currency rate is missing
                current_lot_value_primary = cost_basis_lot_primary
        
        unrealized_gain_lot = current_lot_value_primary - cost_basis_lot_primary
        gain_amount += unrealized_gain_lot
        unrealized_gain_lot_perc = (unrealized_gain_lot / cost_basis_lot_primary) if cost_basis_lot_primary > 0 else 0

        open_positions_details.append(
            PositionData(
                date=pos['open_date'],
                broker=pos['broker'],
                shares=pos['shares'],
                price=pos['open_price'],
                value=pos['purchase_value'],
                currency=currency,
                cost_basis_primary_currency=cost_basis_lot_primary,
                unrealized_gain_perc=unrealized_gain_lot_perc,
                unrealized_gain_value=unrealized_gain_lot
            )
        )

    if current_price and price_currency:
        current_shares = sum_shares(open_positions)
        market_value_primary = convert_currency(current_shares * current_price, price_currency, PRIMARY_CURRENCY, today_str, exchange_rate_cache, get_rate_from_cache)
        if not market_value_primary:
            market_value_primary = total_cost_primary # Fallback

    return open_positions_details, gain_amount, total_cost_primary, market_value_primary, cost_by_currency

def calculate_ticker_history(ticker: str, transactions_df: pd.DataFrame, div_df: pd.DataFrame, market_data: dict, ticker_map_data: dict, exchange_rate_cache: dict, cached_history: List[Dict] = None, month_ends: pd.DatetimeIndex = None, current_metrics: Dict = None) -> List[Dict]:
    """
    Calculates the historical performance for a single ticker.
    """
    history = []
    if month_ends is None:
        month_ends = _get_month_ends()

    # Reuse cache up to the month BEFORE the current month
    if cached_history:
        current_me_str = month_ends[-1].strftime('%m/%y')
        for entry in cached_history:
            if entry['date'] != current_me_str:
                history.append(entry)
            else:
                break

    ticker_transactions = transactions_df[transactions_df['ticker'] == ticker]
    if ticker_transactions.empty:
        return history

    for i, me in enumerate(month_ends):
        me_str = me.strftime('%m/%y')
        if any(h['date'] == me_str for h in history):
            continue

        is_running_month = (i == len(month_ends) - 1)
        
        if is_running_month and current_metrics:
            # For the running month, use the accurately calculated current metrics to ensure consistency with summary
            invested = current_metrics.get('invested', 0)
            value = current_metrics.get('value', 0)
            padi = current_metrics.get('padi', 0)
        else:
            ref_date = me
            ref_str = ref_date.strftime('%Y-%m-%d')
            is_recent_me = me >= (pd.Timestamp.now() - pd.DateOffset(days=45))

            invested, value, padi = _get_history_metrics_at_date(
                me, ref_str, ticker_transactions, div_df, market_data, ticker_map_data, exchange_rate_cache, is_recent_me
            )

        history.append({
            'date': me_str,
            'invested_amount': invested,
            'market_value': value,
            'padi': padi
        })
    
    return history

def _set_tier_group_for_ticker(ticker: str, tier_group: str) -> str:
    """Sets the tier group for a ticker in the existing tickers data, if not already set."""

    # Prompt user for Tier Group if not already set
    if tier_group is None:
        tier_map = {
            '1': TIER1,
            '2': TIER2,
            '3': TIER3,
            '4': TIERG
        }
        while True:
            print(f"Ticker: {ticker}")
            print(f"\nPlease select a Tier Group for {ticker} (Open Positions):")
            print(f"  (1) {TIER1}")
            print(f"  (2) {TIER2}")
            print(f"  (3) {TIER3}")
            print(f"  (4) {TIERG}")
            choice = input("Enter your choice (1-4): ")
            if choice in tier_map:
                tier_group = tier_map[choice]
                break
            else:
                print("Invalid choice. Please try again.")
    return tier_group

def calculate_ticker_metrics(ticker, transactions_df, dividends_df: pd.DataFrame, ticker_map_data, market_data, div_df: pd.DataFrame, cached_ticker_data: Dict = None, month_ends: pd.DatetimeIndex = None) -> Optional[TickerData]:
    """
    Calculate all metrics using 100% cached data where possible.
    """
    ticker_transactions = transactions_df[transactions_df['ticker'] == ticker]
    open_positions = ticker_transactions[ticker_transactions['type'] == 'open']
    closed_positions = ticker_transactions[ticker_transactions['type'] == 'closed']

    if open_positions.empty and closed_positions.empty:
        return None

    # Get cached data
    ticker_cache = market_data.get('tickers', {}).get(ticker, {})
    static_info = ticker_cache.get('static', {})
    dynamic_data = ticker_cache.get('dynamic', {})
    exchange_rate_cache = market_data.get('exchange_rate_cache', {})

    # Ticker Metadata
    country = static_info.get('country') 
    price_currency = static_info.get('currency') or ticker_map_data.get('country_info', {}).get(country, {}).get('currency', '')
    price_currency = normalize_currency(price_currency)
    
    current_shares = sum_shares(open_positions)
    # Determine if ticker has open positions
    has_open_position = current_shares > 0

    # Get tier_group from cache
    tier_group = cached_ticker_data.get('tier_group') if cached_ticker_data else None
    
    # Optimize closed positions processing: if number of closed matches cache, reuse details
    cached_closed_details = cached_ticker_data.get('closed_positions', []) if cached_ticker_data else []
    if len(cached_closed_details) == len(closed_positions):
        # This is a bit naive but likely correct for this app's workflow
        closed_positions_details = [ClosedPositionData(**cp) if isinstance(cp, dict) else cp for cp in cached_closed_details]
        ticker_realized_gain = sum(cp.realized_gain_amount for cp in closed_positions_details)
        ticker_cost_of_closed = sum(convert_currency(cp.purchase_value, cp.currency, PRIMARY_CURRENCY, cp.open_date, exchange_rate_cache, get_rate_from_cache) for cp in closed_positions_details)
    else:
        closed_positions_details, ticker_realized_gain, ticker_cost_of_closed = process_closed_positions(closed_positions, exchange_rate_cache, price_currency)
    
    total_dividends_received_ticker, total_tax_paid_ticker = calculate_total_dividends(ticker, dividends_df, exchange_rate_cache, PRIMARY_CURRENCY)

    # Initialize open positions details and gain metrics; will be calculated if there are open positions
    open_positions_details, gain_amount, total_cost_primary, market_value_primary, cost_by_currency, gain_perc = ([], 0, 0, 0, {}, 0)
    dividend_dates, dividend_payment_months, next_dividend_month, div_frequency_str = ([], [], "N/A", "N/A")
    padi, div_yield, forward_dividend, current_price, yield_on_cost, avg_div_yield, div_growth_metrics = (0, 0, 0, 0, 0, 0, DividendGrowthMetrics())
    dividend_payment_months, next_dividend_month = ([], "N/A")
    has_div_yield_above_5y_avg = False
    yield_below_avg, pe_below_avg, div_growth_above_inflation = (False, False, False)
    peg_ratio = None

    # Process attributes necessary for tickers with open positions
    if has_open_position:
        # Dynamic metrics from cache
        current_price = normalize_price(dynamic_data.get('price'), ticker)
        pe_actual = dynamic_data.get('pe_actual')
        pe_avg_10y = dynamic_data.get('pe_avg_10y')
        peg_ratio = dynamic_data.get('peg_ratio')
    
        # Calculate forward dividend from historical data
        div_frequency_str = ticker_map_data.get('ticker_info', {}).get(ticker, {}).get('div_frequency', 'N/A')
        dividends_history = dynamic_data.get('dividends', [])
    
        # Use our custom calculation based on frequency type
        forward_dividend = calculate_forward_dividend(
            ticker=ticker,
            frequency_type=div_frequency_str,
            dividends_history=dividends_history,
            currency=price_currency
        )

        # Process open positions with caching where possible
        open_positions_details, gain_amount, total_cost_primary, market_value_primary, cost_by_currency = \
            process_open_positions(open_positions, current_price, price_currency, exchange_rate_cache)
        gain_perc = (gain_amount / total_cost_primary)

        div_yield = (forward_dividend / current_price) if current_price and current_price > 0 else 0

        # Use cached metrics
        avg_div_yield = dynamic_data.get('avg_yield_5y', 0.0)
        
        tier_group = _set_tier_group_for_ticker(ticker, tier_group)
                    
        # Calculate dividend growth metrics using official per-share history
        ticker_divs_official = dynamic_data.get('dividends', [])
        if ticker_divs_official:
            ticker_divs_df = pd.DataFrame(ticker_divs_official)
            ticker_divs_df['date'] = pd.to_datetime(ticker_divs_df['date'])
            ticker_divs_df.set_index('date', inplace=True)
            ticker_divs_df.sort_index(inplace=True)
        else:
            ticker_divs_df = pd.DataFrame(columns=['amount'])
            
        calculated_growth_metrics = calculate_dividend_growth(
            ticker,
            ticker_divs_df,
            div_frequency_str,
            price_currency,
            forward_dividend
        )
        div_growth_metrics = DividendGrowthMetrics(
            ttm=calculated_growth_metrics.get('ttm'),
            cagr_3y=calculated_growth_metrics.get('cagr_3y'),
            cagr_5y=calculated_growth_metrics.get('cagr_5y'),
            cagr_10y=calculated_growth_metrics.get('cagr_10y')
        )

        has_div_yield_above_5y_avg = above_safety_margin(div_yield, avg_div_yield, margin=SAFETY_MARGIN) if avg_div_yield > 0 else False

        # Decision Engine Flags
        # True only if current value is below average minus 10% safety margin
        yield_below_avg = div_yield > (avg_div_yield * (1 + SAFETY_MARGIN)) if avg_div_yield > 0 else False
        
        # Debugging the PE calculation
        pe_below_avg = pe_actual < (pe_avg_10y * (1 - SAFETY_MARGIN)) if pe_actual is not None and pe_avg_10y is not None else False
        if ticker in ['ASML', 'ASML.AS', 'MSFT', 'AAPL']: # Add tickers as needed to check
            print(f"DEBUG: {ticker} | pe_actual: {pe_actual} | pe_avg_10y: {pe_avg_10y} | SAFETY_MARGIN: {SAFETY_MARGIN} | pe_below_avg: {pe_below_avg}")
            
        peg_below_threshold = peg_ratio < PEG_RATIO_THRESHOLD if peg_ratio is not None else False
        div_growth_above_inflation = is_div_growth_above_inflation(calculated_growth_metrics, INFLATION_RATE)

        padi = calculate_padi_value(current_shares, forward_dividend) # forward_dividend is already annualized
        padi = convert_currency(padi, price_currency, PRIMARY_CURRENCY, datetime.now().strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache)
        yield_on_cost = (padi / total_cost_primary) if total_cost_primary > 0 else 0

        # Fetch dividend dates once
        # For dates, we can still use the raw list if preferred, but let's stay consistent
        div_dates_list = ticker_divs_df.index.tolist()
        dividend_dates = get_historical_dividend_dates(ticker, dividends_df, div_dates_list)
        dividend_payment_months = get_dividend_payment_months(dividend_dates)
        next_dividend_month = predict_next_dividend_month(ticker, dividends_df, div_frequency_str, dividend_dates, payment_months=dividend_payment_months)

    has_paying_dividend = False
    if forward_dividend:
        has_paying_dividend = True

    ticker_realized_gain_perc = (ticker_realized_gain / ticker_cost_of_closed) if ticker_cost_of_closed > 0 else 0
    total_cost_of_all_positions = total_cost_primary + ticker_cost_of_closed
    total_profit_loss = ticker_realized_gain + gain_amount + total_dividends_received_ticker - total_tax_paid_ticker
    total_pl_perc = (total_profit_loss / total_cost_of_all_positions) if total_cost_of_all_positions > 0 else 0
    
    # Calculate ticker history
    cached_history = cached_ticker_data.get('history', []) if cached_ticker_data else []
    
    # Pass current metrics to ensure history's running month matches summary
    current_metrics = {
        'invested': total_cost_primary,
        'value': market_value_primary,
        'padi': padi
    }
    ticker_history = calculate_ticker_history(
        ticker, transactions_df, div_df, market_data, ticker_map_data, 
        exchange_rate_cache, cached_history, month_ends, current_metrics
    )

    return TickerData(
        ticker=ticker, current_shares=current_shares, has_open_position=has_open_position, market_value_primary=market_value_primary,
        cost_basis_primary_currency=total_cost_primary, cost_basis_per_currency=cost_by_currency,
        unrealized_gain_primary_currency=gain_amount, unrealized_gain_percentage=gain_perc,
        realized_gain_primary_currency=ticker_realized_gain, realized_gain_percentage=ticker_realized_gain_perc,
        cost_of_closed_positions=ticker_cost_of_closed,
        total_dividends_received_primary_currency=total_dividends_received_ticker, 
        total_dividend_tax_primary_currency=total_tax_paid_ticker,
        total_profit_loss_primary_currency=total_profit_loss, 
        total_profit_loss_percentage=total_pl_perc,
        padi=padi, forward_dividend=forward_dividend, current_price=current_price, 
        price_currency=price_currency, country=country, dividend_yield=div_yield, 
        yield_on_cost=yield_on_cost, has_paying_dividend=has_paying_dividend, average_dividend_yield_5y=avg_div_yield, has_div_yield_above_5y_avg=has_div_yield_above_5y_avg,
        dividend_growth=div_growth_metrics,
        open_positions=open_positions_details,
        closed_positions=closed_positions_details,
        pe_actual=pe_actual if has_open_position else None,
        pe_avg_10y=pe_avg_10y if has_open_position else None,
        peg_ratio=peg_ratio if has_open_position else None,
        yield_below_avg=yield_below_avg,
        pe_below_avg=pe_below_avg,
        peg_below_threshold=peg_below_threshold if has_open_position else False,
        div_growth_above_inflation=div_growth_above_inflation,
        next_dividend_month=next_dividend_month,
        dividend_payment_months=dividend_payment_months,
        div_frequency=div_frequency_str,
        name=static_info.get('name'),
        sector=static_info.get('sector'),
        tier_group=tier_group,
        history=ticker_history
    )

def process_all_tickers(transactions_df, dividends_df: pd.DataFrame, ticker_map_data, all_tickers, market_data, existing_tickers_data=None, div_df: pd.DataFrame = None, month_ends: pd.DatetimeIndex = None) -> Dict[str, TickerData]:
    """
    Process all tickers using cached market data and existing ticker info.
    """
    if div_df is None:
        div_df = dividends_df # Unified
    if month_ends is None:
        month_ends = _get_month_ends()
    all_tickers_data = {}
    for ticker in all_tickers:
        cached_ticker = existing_tickers_data.get(ticker, {}) if existing_tickers_data else {}
        ticker_data = calculate_ticker_metrics(ticker, transactions_df, dividends_df, ticker_map_data, market_data, div_df, cached_ticker, month_ends)
        if ticker_data:
            all_tickers_data[ticker] = ticker_data

    return all_tickers_data
