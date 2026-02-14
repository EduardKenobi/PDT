import pandas as pd
from datetime import datetime
from dataclasses import asdict, is_dataclass
from typing import Optional, Dict, List, Any, Tuple
from collections import defaultdict

from app.models import DividendGrowthMetrics, TickerData, PortfolioSummary, PositionData, ClosedPositionData
from config import PRIMARY_CURRENCY, DIVIDEND_FREQ_MAP
from utils.stock_calculator import sum_shares, calculate_cost_per_currency, calculate_padi_value
from utils.analytics import calculate_cagr, calculate_yoy, normalize_price, convert_currency
from app.stock.stock_metrics import (
    calculate_average_dividend_yield, calculate_dividend_growth, 
    calculate_total_dividends, predict_next_dividend_month, 
    get_dividend_payment_months, predict_dividend_income_calendar
)
from app.portfolio.portfolio_metrics import (
    calculate_free_cash_by_currency, get_ibkr_free_cash, get_rate_from_cache, 
    get_cash_operations_summary, get_other_cash_operations_summary, get_portfolio_dividends_per_year, 
    get_portfolio_dividends_ltm
)
from utils.exchange_rate import normalize_currency
from app.stock_analyzer_config import TICKERS_TO_IGNORE

def clean_for_json(data):
    """
    Recursively clean data for JSON serialization.
    """
    if is_dataclass(data):
        data = asdict(data)
    if isinstance(data, dict):
        return {k: clean_for_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [clean_for_json(v) for v in data]
    if isinstance(data, tuple):
        return [clean_for_json(v) for v in data]
    if data == float('inf') or data == float('-inf'):
        return str(data)
    if pd.isna(data):
        return None
    return data

def process_closed_positions(closed_positions: pd.DataFrame, exchange_rate_cache: Dict, price_currency: str) -> Tuple[List[ClosedPositionData], float, float]:
    """
    Process closed positions using cached exchange rates.
    """
    closed_positions_details: List[ClosedPositionData] = []
    ticker_realized_gain = 0
    ticker_cost_of_closed = 0

    for _, pos in closed_positions.iterrows():
        currency = normalize_currency(pos['currency'])
        rate_open = 1 if currency == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, pos['open_date'])
        rate_close = 1 if currency == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, pos['close_date'])

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
        rate = 1 if currency == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, pos['open_date'])
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

def calculate_ticker_metrics(ticker, transactions_df, dividends_data, ticker_map_data, market_data) -> Optional[TickerData]:
    """
    Calculate all metrics using 100% cached data.
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
    closed_positions_details, ticker_realized_gain, ticker_cost_of_closed = process_closed_positions(closed_positions, exchange_rate_cache, price_currency)
    total_dividends_received_ticker, total_tax_paid_ticker = calculate_total_dividends(ticker, dividends_data, exchange_rate_cache, PRIMARY_CURRENCY)

    # Dynamic metrics from cache
    current_price = normalize_price(dynamic_data.get('price'), ticker)
    # Use info from static if available (fallback) or dynamic
    forward_dividend = static_info.get('forward_dividend', 0.0)

    open_positions_details, gain_amount, total_cost_primary, market_value_primary, cost_by_currency = ([], 0, 0, 0, {})
    if current_shares > 0:
        open_positions_details, gain_amount, total_cost_primary, market_value_primary, cost_by_currency = \
            process_open_positions(open_positions, current_price, price_currency, exchange_rate_cache)

    gain_perc = (gain_amount / total_cost_primary) if total_cost_primary > 0 else 0
    ticker_realized_gain_perc = (ticker_realized_gain / ticker_cost_of_closed) if ticker_cost_of_closed > 0 else 0
    total_cost_of_all_positions = total_cost_primary + ticker_cost_of_closed
    total_profit_loss = ticker_realized_gain + gain_amount + total_dividends_received_ticker - total_tax_paid_ticker
    total_pl_perc = (total_profit_loss / total_cost_of_all_positions) if total_cost_of_all_positions > 0 else 0

    div_yield = (forward_dividend / current_price) if current_price and current_price > 0 else 0
    
    # Use cached metrics
    avg_div_yield = dynamic_data.get('avg_yield_5y', 0.0)
    div_growth_dict = dynamic_data.get('growth', {})
    div_growth_metrics = DividendGrowthMetrics(
        ttm=div_growth_dict.get('ttm'),
        cagr_3y=div_growth_dict.get('3y'),
        cagr_5y=div_growth_dict.get('5y'),
        cagr_10y=div_growth_dict.get('10y')
    )

    padi = calculate_padi_value(current_shares, forward_dividend, 1) # forward_dividend is already annualized
    padi = convert_currency(padi, price_currency, PRIMARY_CURRENCY, datetime.now().strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache)
    yield_on_cost = (padi / total_cost_primary) if total_cost_primary > 0 else 0
    
    div_frequency_str = ticker_map_data.get('ticker_info', {}).get(ticker, {}).get('div_frequency', 'N/A')
    cached_history = dynamic_data.get('dividend_dates', [])
    
    next_dividend_month = predict_next_dividend_month(ticker, dividends_data, div_frequency_str, cached_history)
    dividend_payment_months = get_dividend_payment_months(ticker, dividends_data, cached_history)

    return TickerData(
        ticker=ticker, current_shares=current_shares, market_value_primary=market_value_primary,
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
        yield_on_cost=yield_on_cost, average_dividend_yield_5y=avg_div_yield,
        dividend_growth=div_growth_metrics,
        open_positions=open_positions_details,
        closed_positions=closed_positions_details,
        next_dividend_month=next_dividend_month,
        dividend_payment_months=dividend_payment_months,
        div_frequency=div_frequency_str,
        name=static_info.get('name'),
        sector=static_info.get('sector')
    )

def process_all_tickers(transactions_df, dividends_data, ticker_map_data, all_tickers, market_data) -> Dict[str, TickerData]:
    """
    Process all tickers using cached market data.
    """
    print("\n--- Offline Portfolio Analysis ---")
    all_tickers_data = {}
    for ticker in all_tickers:
        ticker_data = calculate_ticker_metrics(ticker, transactions_df, dividends_data, ticker_map_data, market_data)
        if ticker_data:
            all_tickers_data[ticker] = ticker_data

    return all_tickers_data

def calculate_portfolio_summary(all_tickers_data: Dict[str, TickerData], transactions_df, dividends_data, cash_operations_data, exchange_rate_cache) -> PortfolioSummary:
    """
    Calculate overall portfolio summary metrics using cached exchange rates.
    """
    today = datetime.now()

    padi = sum(d.padi for d in all_tickers_data.values())
    unrealized_pl = sum(d.unrealized_gain_primary_currency for d in all_tickers_data.values())
    portfolio_cost = sum(d.cost_basis_primary_currency for d in all_tickers_data.values())
    total_dividends = sum(d.total_dividends_received_primary_currency for d in all_tickers_data.values())
    total_dividend_tax = sum(d.total_dividend_tax_primary_currency for d in all_tickers_data.values())
    realized_pl = sum(d.realized_gain_primary_currency for d in all_tickers_data.values())
    cost_of_closed_positions = sum(d.cost_of_closed_positions for d in all_tickers_data.values())

    xtb_free_cash = calculate_free_cash_by_currency(cash_operations_data)
    ibkr_free_cash = get_ibkr_free_cash()
    free_cash_by_currency = {
        'XTB': xtb_free_cash,
        'IBKR': ibkr_free_cash
    }

    total_free_cash_primary = 0.0
    today_str = today.strftime('%Y-%m-%d')
    for broker, cash_by_currency in free_cash_by_currency.items():
        for currency, amount in cash_by_currency.items():
            norm_curr = normalize_currency(currency)
            if norm_curr == PRIMARY_CURRENCY:
                total_free_cash_primary += amount
            else:
                rate = get_rate_from_cache(exchange_rate_cache, norm_curr, PRIMARY_CURRENCY, today_str)
                if rate:
                    total_free_cash_primary += amount * rate

    portfolio_value = portfolio_cost + unrealized_pl + total_free_cash_primary
    net_capital_contributed, first_cash_op_date = get_cash_operations_summary(exchange_rate_cache)
    total_portfolio_profit_loss = portfolio_value - net_capital_contributed

    # Filter out NaT from open_date_dt
    valid_dates = transactions_df['open_date_dt'].dropna()
    first_transaction_date = valid_dates.min() if not valid_dates.empty else None
    
    start_dates = [d for d in [first_transaction_date, first_cash_op_date] if d is not None and pd.notna(d)]
    investment_start_date = min(start_dates) if start_dates else None

    years_invested = (today - investment_start_date).days / 365.25 if investment_start_date else 0

    unrealized_pl_percentage = unrealized_pl / portfolio_cost if portfolio_cost > 0 else 0
    total_return_percentage = total_portfolio_profit_loss / net_capital_contributed if net_capital_contributed != 0 else 0
    annualized_return_percentage = total_return_percentage / years_invested if years_invested > 0 else 0
    forward_dividend_yield = padi / portfolio_cost if portfolio_cost > 0 else 0
    dividend_yield_on_cost = padi / net_capital_contributed if net_capital_contributed > 0 else 0
    realized_pl_percentage = realized_pl / cost_of_closed_positions if cost_of_closed_positions > 0 else 0

    portfolio_dividends_per_year = get_portfolio_dividends_per_year(dividends_data, exchange_rate_cache, PRIMARY_CURRENCY)
    
    div_growth_cost_weighted, div_growth_padi_weighted = 0, 0
    cost_sum, padi_sum = 0, 0
    for data in all_tickers_data.values():
        if data.current_shares > 0 and data.dividend_growth.ttm and data.dividend_growth.ttm[1] is not None:
            cost, p = data.cost_basis_primary_currency, data.padi
            if cost > 0:
                div_growth_cost_weighted += data.dividend_growth.ttm[1] * cost
                cost_sum += cost
            if p > 0:
                div_growth_padi_weighted += data.dividend_growth.ttm[1] * p
                padi_sum += p
    
    projected_dividend_income = predict_dividend_income_calendar(all_tickers_data, dividends_data, exchange_rate_cache)

    return PortfolioSummary(
        total_contribution=net_capital_contributed,
        total_portfolio_profit_loss=total_portfolio_profit_loss,
        total_return_percentage=total_return_percentage,
        annualized_return_percentage=annualized_return_percentage,
        portfolio_cost=portfolio_cost,
        unrealized_pl=unrealized_pl,
        unrealized_pl_percentage=unrealized_pl_percentage,
        realized_pl=realized_pl,
        realized_pl_percentage=realized_pl_percentage,
        portfolio_value=portfolio_value,
        total_dividends=total_dividends,
        total_dividend_tax=total_dividend_tax,
        padi=padi,
        dividends_ytd=portfolio_dividends_per_year.get(today.year, 0.0),
        forward_dividend_yield=forward_dividend_yield,
        dividend_yield_on_cost=dividend_yield_on_cost,
        dividends_ltm=get_portfolio_dividends_ltm(dividends_data, exchange_rate_cache, PRIMARY_CURRENCY),
        portfolio_dividend_growth_ttm_cost_weighted=div_growth_cost_weighted / cost_sum if cost_sum > 0 else 0,
        portfolio_dividend_growth_ttm_padi_weighted=div_growth_padi_weighted / padi_sum if padi_sum > 0 else 0,
        primary_currency=PRIMARY_CURRENCY,
        investment_start_date=investment_start_date.strftime('%Y-%m-%d') if investment_start_date else None,
        years_invested=years_invested,
        other_operations_summary=get_other_cash_operations_summary(exchange_rate_cache),
        portfolio_dividends_per_year=portfolio_dividends_per_year,
        free_cash_by_currency=free_cash_by_currency,
        total_free_cash_primary_currency=total_free_cash_primary,
        projected_dividend_income=projected_dividend_income
    )

def enrich_ticker_data(all_tickers_data: Dict[str, TickerData], portfolio_summary: PortfolioSummary) -> Dict[str, TickerData]:
    """
    Enrich each ticker's data with portfolio ratios.
    """
    total_cost = portfolio_summary.portfolio_cost
    total_padi = portfolio_summary.padi
    for data in all_tickers_data.values():
        data.ratio_on_cost = (data.cost_basis_primary_currency / total_cost) if total_cost > 0 else 0
        data.ratio_on_padi = (data.padi / total_padi) if total_padi > 0 else 0

    return all_tickers_data

def _prepare_dividend_history_df(dividends_data: dict) -> pd.DataFrame:
    """Preprocesses dividend data into a sorted DataFrame."""
    all_dividends = []
    for ticker, company_data in dividends_data.get('companies', {}).items():
        for div in company_data.get('dividends', []):
            if div.get('date') and div.get('amount'):
                all_dividends.append({
                    'ticker': ticker,
                    'date': pd.Timestamp(div.get('date')),
                    'amount': div.get('amount', 0),
                    'currency': normalize_currency(div.get('currency')),
                    'amount_per_share': div.get('amount_per_share'),
                    'amount_per_share_currency': normalize_currency(div.get('amount_per_share_currency'))
                })
    div_df = pd.DataFrame(all_dividends)
    if not div_df.empty:
        div_df = div_df.sort_values('date')
    return div_df

def _get_history_metrics_at_date(date: pd.Timestamp, ref_str: str, transactions_df: pd.DataFrame, div_df: pd.DataFrame, market_data: dict, ticker_map_data: dict, exchange_rate_cache: dict, is_recent_me: bool) -> Tuple[float, float, float]:
    """Calculates invested_amount, market_value, and padi for a specific date."""
    open_at_date = transactions_df[
        (transactions_df['open_date_dt'] <= date) & 
        ((transactions_df['close_date_dt'].isna()) | (transactions_df['close_date_dt'] > date))
    ]
    
    invested_amount = 0
    market_value = 0
    padi_at_date = 0
    current_holdings = defaultdict(float)
    
    for _, pos in open_at_date.iterrows():
        currency = normalize_currency(pos['currency'])
        invested_amount += convert_currency(pos['purchase_value'], currency, PRIMARY_CURRENCY, pos['open_date'], exchange_rate_cache, get_rate_from_cache)
        current_holdings[pos['ticker']] += pos['shares']
        
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

        forward_dividend = static_info.get('forward_dividend', 0.0)
        
        if is_recent_me and forward_dividend > 0:
            padi_ticker = calculate_padi_value(shares, forward_dividend, 1)
            padi_at_date += convert_currency(padi_ticker, price_currency, PRIMARY_CURRENCY, ref_str, exchange_rate_cache, get_rate_from_cache)
        else:
            if not div_df.empty:
                ticker_divs = div_df[div_df['ticker'] == ticker]
                divs_before_date = ticker_divs[ticker_divs['date'] <= date]
                if not divs_before_date.empty:
                    latest_div = divs_before_date.iloc[-1]
                    div_freq_str = ticker_map_data.get('ticker_info', {}).get(ticker, {}).get('div_frequency', 'N/A')
                    freq = DIVIDEND_FREQ_MAP.get(div_freq_str, 0)
                    
                    padi_hist = calculate_padi_value(shares, latest_div['amount_per_share'], freq)
                    padi_at_date += convert_currency(padi_hist, latest_div['amount_per_share_currency'], PRIMARY_CURRENCY, ref_str, exchange_rate_cache, get_rate_from_cache)

    return invested_amount, market_value, padi_at_date

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

def calculate_portfolio_history(transactions_df: pd.DataFrame, dividends_data: dict, cash_operations_data: dict, market_data: dict, ticker_map_data: dict) -> List[Dict]:
    """
    Calculates the portfolio state at the end of each month from 2021-06 to today.
    Uses the Balance Sheet approach: Total Amount = Market Value + Total Cash.
    """
    history = []
    start_date = pd.Timestamp('2021-06-30')
    end_date = pd.Timestamp.now().to_period('M').to_timestamp('M')
    month_ends = pd.date_range(start=start_date, end=end_date, freq='ME')
    
    exchange_rate_cache = market_data.get('exchange_rate_cache', {})
    
    # Pre-process static data
    ibkr_cash_primary = get_ibkr_free_cash().get(PRIMARY_CURRENCY, 0)
    
    other_ops = pd.DataFrame(cash_operations_data.get('other_operations', []))
    if not other_ops.empty:
        other_ops['date_dt'] = pd.to_datetime(other_ops['date'])
    
    transactions_df = transactions_df.copy()
    transactions_df['open_date_dt'] = pd.to_datetime(transactions_df['open_date'])
    transactions_df['close_date_dt'] = pd.to_datetime(transactions_df['close_date'])

    ibkr_trades = transactions_df[transactions_df['broker'] == 'ibkr']
    first_ibkr_date = ibkr_trades['open_date_dt'].min() if not ibkr_trades.empty else None

    div_df = _prepare_dividend_history_df(dividends_data)

    for i, me in enumerate(month_ends):
        # 1. Setup reference dates
        is_running_month = (i == len(month_ends) - 1)
        ref_date = pd.Timestamp.now() if is_running_month else me
        ref_str = ref_date.strftime('%Y-%m-%d')
        is_recent_me = me >= (pd.Timestamp.now() - pd.DateOffset(days=45))

        # 2. Calculate Invested, Market Value and PADI
        invested_amount, market_value, padi_at_me = _get_history_metrics_at_date(
            me, ref_str, transactions_df, div_df, market_data, ticker_map_data, exchange_rate_cache, is_recent_me
        )

        # 3. Calculate Cash and Deposits
        total_cash, total_deposit, monthly_deposit = _get_cash_and_deposits_at_date(
            me, other_ops, exchange_rate_cache, ibkr_cash_primary, first_ibkr_date
        )

        # 4. Final aggregation
        total_amount = market_value + total_cash
        unrealized_gain = market_value - invested_amount
        
        total_dividends = 0
        if not div_df.empty:
            div_up_to_me = div_df[div_df['date'] <= me]
            for _, div in div_up_to_me.iterrows():
                total_dividends += convert_currency(div['amount'], div['currency'], PRIMARY_CURRENCY, div['date'].strftime('%Y-%m-%d'), exchange_rate_cache, get_rate_from_cache)

        total_gain_perc = (total_amount / total_deposit - 1) if total_deposit > 0 else 0
        
        # 5. Calculate Growth Metrics (YoY, CAGR)
        padi_yoy = calculate_yoy(padi_at_me, history[-12]['padi']) if len(history) >= 12 else 0
        padi_3y = calculate_cagr(padi_at_me, history[-36]['padi'], 3) if len(history) >= 36 else 0
        padi_5y = calculate_cagr(padi_at_me, history[-60]['padi'], 5) if len(history) >= 60 else 0

        total_amount_yoy = calculate_yoy(total_amount, history[-12]['total_amount']) if len(history) >= 12 else 0
        total_amount_3y = calculate_cagr(total_amount, history[-36]['total_amount'], 3) if len(history) >= 36 else 0
        total_amount_5y = calculate_cagr(total_amount, history[-60]['total_amount'], 5) if len(history) >= 60 else 0

        history.append({
            'date': me.strftime('%m/%y'),
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
        })
        
    return history
