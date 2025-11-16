
import pandas as pd
from datetime import datetime
from dataclasses import asdict, is_dataclass
from typing import Optional, Dict, List, Any, Tuple

from app.models import DividendGrowthMetrics, TickerData, PortfolioSummary, PositionData, ClosedPositionData
from config import PRIMARY_CURRENCY
from utils.stock_calculator import sum_shares, calculate_cost_per_currency
from utils.data_fetcher import get_forward_dividend_from_yfinance, get_ticker_history
from app.stock.stock_metrics import (
    calculate_average_dividend_yield, calculate_dividend_growth, 
    calculate_total_dividends, predict_next_dividend_month, 
    get_dividend_payment_months, predict_dividend_income_calendar
)
from app.portfolio.portfolio_metrics import (
    calculate_free_cash_by_currency, get_rate_from_cache, 
    get_cash_operations_summary, get_other_cash_operations_summary, get_portfolio_dividends_per_year, 
    get_portfolio_dividends_ltm
)
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
    Process closed positions to calculate realized gains and prepare details.
    """
    closed_positions_details: List[ClosedPositionData] = []
    ticker_realized_gain = 0
    ticker_cost_of_closed = 0

    for _, pos in closed_positions.iterrows():
        rate_open = 1 if pos['currency'] == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, pos['currency'], PRIMARY_CURRENCY, pos['open_date'])
        rate_close = 1 if pos['currency'] == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, pos['currency'], PRIMARY_CURRENCY, pos['close_date'])

        purchase_value_primary = pos['purchase_value'] * rate_open if rate_open else 0
        realized_gain_lot_local = pos['gross_pl_amount']
        realized_gain_lot_perc = pos['gross_pl_percent']
        realized_gain_lot_primary = realized_gain_lot_local * rate_close if rate_close else 0

        ticker_realized_gain += realized_gain_lot_primary
        ticker_cost_of_closed += purchase_value_primary

        closed_positions_details.append(
            ClosedPositionData(
                open_date=pos['open_date'],
                close_date=pos['close_date'],
                shares=pos['shares'],
                open_price=pos['open_price'],
                close_price=pos['close_price'],
                currency=pos['currency'],
                purchase_value=pos['purchase_value'],
                sale_value=pos['sale_value'],
                realized_gain_amount=realized_gain_lot_primary,
                realized_gain_percentage=realized_gain_lot_perc
            )
        )

    return closed_positions_details, ticker_realized_gain, ticker_cost_of_closed

def process_open_positions(open_positions: pd.DataFrame, current_price: float, price_currency: str, exchange_rate_cache: Dict) -> Tuple[List[PositionData], float, float, float, Dict]:
    """
    Process open positions to calculate unrealized gains and prepare details.
    """
    open_positions_details: List[PositionData] = []
    gain_amount = 0
    total_cost_primary = 0
    market_value_primary = 0
    cost_by_currency = calculate_cost_per_currency(open_positions)

    for _, pos in open_positions.iterrows():
        rate = 1 if pos['currency'] == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, pos['currency'], PRIMARY_CURRENCY, pos['open_date'])
        cost_basis_lot_primary = pos['purchase_value'] * rate if rate else 0
        total_cost_primary += cost_basis_lot_primary

        current_lot_value_primary = 0
        if current_price and price_currency:
            rate_now = 1 if price_currency == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, price_currency, PRIMARY_CURRENCY, datetime.now().strftime('%Y-%m-%d'))
            if rate_now:
                current_lot_value_primary = (pos['shares'] * current_price) * rate_now
        
        unrealized_gain_lot = current_lot_value_primary - cost_basis_lot_primary
        gain_amount += unrealized_gain_lot
        unrealized_gain_lot_perc = (unrealized_gain_lot / cost_basis_lot_primary) if cost_basis_lot_primary > 0 else 0

        open_positions_details.append(
            PositionData(
                date=pos['open_date'],
                shares=pos['shares'],
                price=pos['open_price'],
                value=pos['purchase_value'],
                currency=pos['currency'],
                cost_basis_primary_currency=cost_basis_lot_primary,
                unrealized_gain_perc=unrealized_gain_lot_perc,
                unrealized_gain_value=unrealized_gain_lot
            )
        )

    if current_price and price_currency:
        rate_now = 1 if price_currency == PRIMARY_CURRENCY else get_rate_from_cache(exchange_rate_cache, price_currency, PRIMARY_CURRENCY, datetime.now().strftime('%Y-%m-%d'))
        if rate_now:
            current_shares = sum_shares(open_positions)
            market_value_primary = (current_shares * current_price) * rate_now

    return open_positions_details, gain_amount, total_cost_primary, market_value_primary, cost_by_currency

def calculate_ticker_metrics(ticker, transactions_df, dividends_data, ticker_info, country_info, current_prices, exchange_rate_cache) -> Optional[TickerData]:
    """
    Calculate all relevant metrics for a single ticker.
    """
    ticker_transactions = transactions_df[transactions_df['ticker'] == ticker]
    open_positions = ticker_transactions[ticker_transactions['type'] == 'open']
    closed_positions = ticker_transactions[ticker_transactions['type'] == 'closed']

    if open_positions.empty and closed_positions.empty:
        return None

    country = ticker_info.get(ticker, {}).get('country')
    price_currency = country_info.get(country, {}).get('currency', '')
    current_shares = sum_shares(open_positions)

    closed_positions_details, ticker_realized_gain, ticker_cost_of_closed = process_closed_positions(closed_positions, exchange_rate_cache, price_currency)
    total_dividends_received_ticker, total_tax_paid_ticker = calculate_total_dividends(ticker, dividends_data, exchange_rate_cache, PRIMARY_CURRENCY)

    forward_dividend, current_price, history_df = 0, None, pd.DataFrame()
    if current_shares > 0 and ticker not in TICKERS_TO_IGNORE:
        forward_dividend = get_forward_dividend_from_yfinance(ticker) if ticker else 0
        current_price = current_prices.get(ticker)
        history_df = get_ticker_history(ticker) if current_price else pd.DataFrame()

    if current_price and ticker.endswith('.L'):
        current_price /= 100

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
    avg_div_yield = calculate_average_dividend_yield(ticker, history_df)
    ticker_specific_info = ticker_info.get(ticker, {})
    div_frequency_str = ticker_specific_info.get('div_frequency', 'N/A')
    div_growth_metrics_dict = calculate_dividend_growth(history_df, div_frequency_str)
    div_growth_metrics = DividendGrowthMetrics(
        ttm=div_growth_metrics_dict.get('ttm'),
        cagr_3y=div_growth_metrics_dict.get('3y'),
        cagr_5y=div_growth_metrics_dict.get('5y'),
        cagr_10y=div_growth_metrics_dict.get('10y')
    )

    padi = forward_dividend * current_shares
    if price_currency and price_currency != PRIMARY_CURRENCY:
        rate = get_rate_from_cache(exchange_rate_cache, price_currency, PRIMARY_CURRENCY, datetime.now().strftime('%Y-%m-%d'))
        if rate:
            padi *= rate
    yield_on_cost = (padi / total_cost_primary) if total_cost_primary > 0 else 0
    next_dividend_month = predict_next_dividend_month(ticker, dividends_data, div_frequency_str)
    dividend_payment_months = get_dividend_payment_months(ticker, dividends_data)

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
        div_frequency=div_frequency_str
    )

def process_all_tickers(transactions_df, dividends_data, ticker_map_data, all_tickers, current_prices, exchange_rate_cache) -> Dict[str, TickerData]:
    """
    Process all tickers to calculate their metrics.
    """
    print("\n--- Portfolio Analysis ---")
    all_tickers_data = {}
    ticker_info = ticker_map_data.get('ticker_info', {})
    country_info = ticker_map_data.get('country_info', {})
    for ticker in all_tickers:
        ticker_data = calculate_ticker_metrics(ticker, transactions_df, dividends_data, ticker_info, country_info, current_prices, exchange_rate_cache)
        if ticker_data:
            all_tickers_data[ticker] = ticker_data

    return all_tickers_data

def calculate_portfolio_summary(all_tickers_data: Dict[str, TickerData], transactions_df, dividends_data, cash_operations_data, exchange_rate_cache) -> PortfolioSummary:
    """
    Calculate overall portfolio summary metrics.
    """
    today = datetime.now()

    padi = sum(d.padi for d in all_tickers_data.values())
    unrealized_pl = sum(d.unrealized_gain_primary_currency for d in all_tickers_data.values())
    portfolio_cost = sum(d.cost_basis_primary_currency for d in all_tickers_data.values())
    total_dividends = sum(d.total_dividends_received_primary_currency for d in all_tickers_data.values())
    total_dividend_tax = sum(d.total_dividend_tax_primary_currency for d in all_tickers_data.values())
    realized_pl = sum(d.realized_gain_primary_currency for d in all_tickers_data.values())
    cost_of_closed_positions = sum(d.cost_of_closed_positions for d in all_tickers_data.values())

    free_cash_by_currency = calculate_free_cash_by_currency(dividends_data, cash_operations_data)
    total_free_cash_primary = 0.0
    for currency, amount in free_cash_by_currency.items():
        if currency == PRIMARY_CURRENCY:
            total_free_cash_primary += amount
        else:
            rate = get_rate_from_cache(exchange_rate_cache, currency, PRIMARY_CURRENCY, today.strftime('%Y-%m-%d'))
            if rate:
                total_free_cash_primary += amount * rate

    portfolio_value = portfolio_cost + unrealized_pl + total_free_cash_primary
    net_capital_contributed, first_cash_op_date = get_cash_operations_summary(exchange_rate_cache)
    total_portfolio_profit_loss = portfolio_value - net_capital_contributed

    first_transaction_date = transactions_df['open_date_dt'].min()
    investment_start_date = min(d for d in [first_transaction_date, first_cash_op_date] if pd.notna(d))

    years_invested = (today - investment_start_date).days / 365.25 if pd.notna(investment_start_date) else 0

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
        investment_start_date=investment_start_date.strftime('%Y-%m-%d') if pd.notna(investment_start_date) else None,
        years_invested=years_invested,
        other_operations_summary=get_other_cash_operations_summary(exchange_rate_cache),
        portfolio_dividends_per_year=portfolio_dividends_per_year,
        free_cash_by_currency=free_cash_by_currency,
        total_free_cash_primary_currency=total_free_cash_primary,
        projected_dividend_income=projected_dividend_income
    )

def enrich_ticker_data(all_tickers_data: Dict[str, TickerData], portfolio_summary: PortfolioSummary) -> Dict[str, TickerData]:
    """
    Enrich each ticker's data with its ratio of cost and PADI to the overall portfolio.
    """
    total_cost = portfolio_summary.portfolio_cost
    total_padi = portfolio_summary.padi
    for data in all_tickers_data.values():
        data.ratio_on_cost = (data.cost_basis_primary_currency / total_cost) if total_cost > 0 else 0
        data.ratio_on_padi = (data.padi / total_padi) if total_padi > 0 else 0

    return all_tickers_data
