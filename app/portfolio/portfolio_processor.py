import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional

from app.models import TickerData, PortfolioSummary, TiersPadi
from config import PRIMARY_CURRENCY
from app.portfolio.portfolio_metrics import (
    calculate_free_cash_by_currency, get_ibkr_free_cash, 
    get_cash_operations_summary, get_other_cash_operations_summary, 
    get_portfolio_dividends_per_year, get_portfolio_dividends_ltm,
    get_portfolio_dividends_per_quarter, get_portfolio_dividend_calendar,
    check_portfolio_history_consistency, get_portfolio_tier_padi_ratio,
    validate_padi_tier_ratios
)
from utils.exchange_rate import normalize_currency, get_rate_from_cache
from app.stock.stock_metrics import predict_dividend_income_calendar
from app.history.history_helpers import (
    _get_month_ends, 
    _prepare_monthly_portfolio_metrics, _aggregate_ticker_data_by_date, 
    _create_history_entry
)

def calculate_portfolio_summary(all_tickers_data: Dict[str, TickerData], transactions_df: pd.DataFrame, dividends_df: pd.DataFrame, cash_operations_data: dict, exchange_rate_cache: dict, div_df: pd.DataFrame = None, other_ops_df: pd.DataFrame = None) -> PortfolioSummary:
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

    if div_df is None:
        div_df = dividends_df

    portfolio_dividends_per_year = get_portfolio_dividends_per_year(div_df, exchange_rate_cache)
    
    # Debug
    # for ticker, data in all_tickers_data.items():
    #     if data.has_open_position and data.dividend_growth.ttm and data.dividend_growth.ttm[1] is not None:
    #         print(f"Ticker: {ticker}, TTM Growth: {data.dividend_growth.ttm[1]:.2%}, Cost: {data.cost_basis_primary_currency:.2f}, PADI: {data.padi:.2f}")

    div_growth_cost_weighted, div_growth_padi_weighted = 0, 0
    cost_sum, padi_sum = 0, 0
    for data in all_tickers_data.values():
        if data.has_open_position and data.dividend_growth.ttm and data.dividend_growth.ttm[1] is not None:
            cost, p = data.cost_basis_primary_currency, data.padi
            if cost > 0:
                div_growth_cost_weighted += data.dividend_growth.ttm[1] * cost
                cost_sum += cost
            if p > 0:
                div_growth_padi_weighted += data.dividend_growth.ttm[1] * p
                padi_sum += p

    div_growth_cost_weighted_5yr, div_growth_padi_weighted_5yr = 0, 0
    cost_sum_5yr, padi_sum_5yr = 0, 0
    for data in all_tickers_data.values():
        if data.has_open_position and data.dividend_growth.cagr_5y is not None:
            cost, p = data.cost_basis_primary_currency, data.padi
            if cost > 0:
                div_growth_cost_weighted_5yr += data.dividend_growth.cagr_5y * cost
                cost_sum_5yr += cost
            if p > 0:
                div_growth_padi_weighted_5yr += data.dividend_growth.cagr_5y * p
                padi_sum_5yr += p
    
    projected_dividend_income = predict_dividend_income_calendar(all_tickers_data, dividends_df, exchange_rate_cache)

    # Calculate dividend calendar for next 12 months
    dividend_calendar = get_portfolio_dividend_calendar(all_tickers_data, today)

    # Pre-calculate Quarterly Dividends for Reporter
    q_divs_raw = get_portfolio_dividends_per_quarter(div_df, exchange_rate_cache)
    # Convert tuple keys to string keys for JSON serialization
    quarterly_dividends = {f"Q{q}/{str(y)[-2:]}": amt for (y, q), amt in q_divs_raw.items()}

    # Tiers PADI Calculation
    tiers_padi = get_portfolio_tier_padi_ratio(all_tickers_data)

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
        dividends_ltm=get_portfolio_dividends_ltm(div_df, exchange_rate_cache),
        portfolio_dividend_growth_ttm_cost_weighted=div_growth_cost_weighted / cost_sum if cost_sum > 0 else 0,
        portfolio_dividend_growth_ttm_padi_weighted=div_growth_padi_weighted / padi_sum if padi_sum > 0 else 0,
        portfolio_dividend_growth_5y_cost_weighted=div_growth_cost_weighted_5yr / cost_sum_5yr if cost_sum_5yr > 0 else 0,
        portfolio_dividend_growth_5y_padi_weighted=div_growth_padi_weighted_5yr / padi_sum_5yr if padi_sum_5yr > 0 else 0,
        primary_currency=PRIMARY_CURRENCY,
        investment_start_date=investment_start_date.strftime('%Y-%m-%d') if investment_start_date else None,
        years_invested=years_invested,
        other_operations_summary=get_other_cash_operations_summary(exchange_rate_cache),
        portfolio_dividends_per_year=portfolio_dividends_per_year,
        free_cash_by_currency=free_cash_by_currency,
        total_free_cash_primary_currency=total_free_cash_primary,
        projected_dividend_income=projected_dividend_income,
        dividend_calendar=dividend_calendar,
        quarterly_dividends=quarterly_dividends,
        tiers_padi=tiers_padi
    )

def calculate_portfolio_history(transactions_df: pd.DataFrame, dividends_df: pd.DataFrame, cash_operations_data: dict, market_data: dict, ticker_map_data: dict, all_tickers_data: Dict[str, TickerData], cached_history: List[Dict] = None, div_df: pd.DataFrame = None, month_ends: pd.DatetimeIndex = None, monthly_metrics: Dict = None, other_ops_df: pd.DataFrame = None) -> List[Dict]:
    """
    Calculates the portfolio state at the end of each month.
    Aggregates per-ticker histories and adds portfolio-level metrics (cash, deposits).
    Supports incremental updates to skip already calculated months.
    """
    history = []
    if month_ends is None:
        month_ends = _get_month_ends()
    
    exchange_rate_cache = market_data.get('exchange_rate_cache', {})
    ibkr_cash_primary = get_ibkr_free_cash().get(PRIMARY_CURRENCY, 0)
    
    if other_ops_df is None:
        other_ops_df = pd.DataFrame(cash_operations_data.get('other_operations', []))
        if not other_ops_df.empty:
            other_ops_df['date_dt'] = pd.to_datetime(other_ops_df['date'])
    
    transactions_df = transactions_df.copy()
    ibkr_trades = transactions_df[transactions_df['broker'] == 'ibkr']
    first_ibkr_date = ibkr_trades['open_date_dt'].min() if not ibkr_trades.empty else None

    # 0. Incremental Update Logic: If cached history exists, check for consistency and resume from last month if possible
    if cached_history:
        # If consistent, history will contain all cached months except the last one (which is the running month).
        # If not consistent, history will be empty and we will recalculate from scratch.
        history = check_portfolio_history_consistency(month_ends, monthly_metrics, cached_history)

    # 1. Aggregating Invested, Market Value and PADI from tickers (fast aggregation)
    ticker_histories_by_date = _aggregate_ticker_data_by_date(all_tickers_data)

    # 2. Pre-calculation for Portfolio-Level metrics (Cash, Dividends, Deposits)
    if not monthly_metrics:
        # Fallback to internal calculation if not provided (keeping backward compatibility)
        monthly_metrics = _prepare_monthly_portfolio_metrics(
            month_ends, div_df, other_ops_df, exchange_rate_cache, ibkr_cash_primary, first_ibkr_date
        )

    # 3. Final Loop - Now O(N) due to pre-calculations
    for i, me in enumerate(month_ends):
        me_str = me.strftime('%m/%y')
        
        # Skip if already in history (from cache)
        if any(h['date'] == me_str for h in history):
            continue

        # Create history entry using helper
        entry_ticker_metrics = ticker_histories_by_date.get(me_str, {'invested': 0, 'market_value': 0, 'padi': 0})
        entry_cum_metrics = {
            'cash': monthly_metrics['cumulative_cash'].get(me_str, 0),
            'total_deposit': monthly_metrics['cumulative_deposits'].get(me_str, 0),
            'monthly_deposit': monthly_metrics['monthly_deposits'].get(me_str, 0),
            'total_dividends': monthly_metrics['cumulative_dividends'].get(me_str, 0)
        }
        
        history.append(_create_history_entry(me_str, entry_ticker_metrics, entry_cum_metrics, history))
        
    return history

def enrich_ticker_data(all_tickers_data: Dict[str, TickerData], portfolio_summary: PortfolioSummary) -> Dict[str, TickerData]:
    """
    Enrich each ticker's data with portfolio ratios and decision engine flags.
    """
    total_cost = portfolio_summary.portfolio_cost
    total_padi = portfolio_summary.padi
    total_market_value = portfolio_summary.portfolio_value
    for data in all_tickers_data.values():
        data.ratio_on_cost = (data.cost_basis_primary_currency / total_cost) if total_cost > 0 else 0
        data.ratio_on_padi = (data.padi / total_padi) if total_padi > 0 else 0
        data.ratio_on_market_value = (data.market_value_primary / total_market_value) if total_market_value > 0 else 0

    # 2. PADI Ratio within Tier Group validation
    tier_status = validate_padi_tier_ratios(all_tickers_data)
    for data in all_tickers_data.values():
        if data.has_open_position:
            data.is_padi_ratio_within_tier_ok = tier_status.get(data.tier_group, True)

    return all_tickers_data
