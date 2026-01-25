from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any

@dataclass
class DividendGrowthMetrics:
    ttm: Optional[tuple[float, Optional[float]]] = None
    cagr_3y: Optional[float] = None
    cagr_5y: Optional[float] = None
    cagr_10y: Optional[float] = None

@dataclass
class PositionData:
    date: str
    shares: float
    price: float
    value: float
    currency: str
    cost_basis_primary_currency: float
    unrealized_gain_perc: float
    unrealized_gain_value: float
    broker: str

@dataclass
class ClosedPositionData:
    open_date: str
    close_date: str
    shares: float
    open_price: float
    close_price: float
    currency: str
    purchase_value: float
    sale_value: float
    realized_gain_amount: float
    realized_gain_percentage: float
    broker: str

@dataclass
class TickerData:
    ticker: str
    current_shares: float
    market_value_primary: float
    cost_basis_primary_currency: float
    cost_basis_per_currency: Dict[str, float]
    unrealized_gain_primary_currency: float
    unrealized_gain_percentage: float
    realized_gain_primary_currency: float
    realized_gain_percentage: float
    cost_of_closed_positions: float
    total_dividends_received_primary_currency: float
    total_dividend_tax_primary_currency: float
    total_profit_loss_primary_currency: float
    total_profit_loss_percentage: float
    padi: float
    forward_dividend: float
    current_price: Optional[float]
    price_currency: Optional[str]
    country: Optional[str]
    dividend_yield: float
    yield_on_cost: float
    average_dividend_yield_5y: float
    dividend_growth: DividendGrowthMetrics
    open_positions: List[PositionData]
    closed_positions: List[ClosedPositionData] = field(default_factory=list)
    ratio_on_cost: float = 0.0
    ratio_on_padi: float = 0.0
    next_dividend_month: Optional[str] = None
    dividend_payment_months: Optional[List[int]] = None
    div_frequency: Optional[str] = None

@dataclass
class PortfolioSummary:
    total_contribution: float
    total_portfolio_profit_loss: float
    total_return_percentage: float
    annualized_return_percentage: float
    portfolio_cost: float
    unrealized_pl: float
    unrealized_pl_percentage: float
    realized_pl: float
    realized_pl_percentage: float
    portfolio_value: float
    total_dividends: float
    total_dividend_tax: float
    padi: float
    dividends_ytd: float
    forward_dividend_yield: float
    dividend_yield_on_cost: float
    dividends_ltm: float
    portfolio_dividend_growth_ttm_cost_weighted: float
    portfolio_dividend_growth_ttm_padi_weighted: float
    primary_currency: str
    investment_start_date: Optional[str]
    years_invested: float
    other_operations_summary: Dict[str, Any]
    portfolio_dividends_per_year: Dict[int, float]
    free_cash_by_currency: Dict[str, float]
    total_free_cash_primary_currency: float
    projected_dividend_income: Optional[Dict[str, float]] = None