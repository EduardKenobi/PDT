import json
from typing import Dict, List
from datetime import datetime
import inquirer
import os
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich import box 

from config import PRIMARY_CURRENCY, EXIT_CODE_RETURN_TO_MENU, CHOICE_EXIT, CHOICE_STOCK_SUMMARY, CHOICE_PORTFOLIO_SUMMARY, CHOICE_PORTFOLIO_HISTORY, STOCK_ANALYSIS_OUTPUT
from utils.data_loader import load_analysis_output, load_dividends_data
from utils.analytics import calculate_yoy

def _format_free_cash(free_cash_by_currency: Dict) -> str:
    """Formats the free cash dictionary into a string for display."""
    parts = []
    for broker, cash_by_currency in free_cash_by_currency.items():
        broker_parts = []
        if broker == 'IBKR':
            amount = cash_by_currency.get(PRIMARY_CURRENCY, 0)
            broker_parts.append(f"{amount:+.2f} {PRIMARY_CURRENCY}")
        else:
            for currency, amount in cash_by_currency.items():
                broker_parts.append(f"{amount:+.2f} {currency}")
        
        if broker_parts:
            parts.append(f"{broker}: {' / '.join(broker_parts)}")
            
    return ", ".join(parts)

def print_portfolio_summary_rich(console: Console, portfolio_summary: Dict):
    """
    Prints the portfolio summary with Performance and Dividends sections using Rich tables.
    Args:
        portfolio_summary (Dict): The portfolio summary data.
    """
    today = datetime.now()

    # --- Performance Table ---
    perf_table = Table(title="Portfolio Performance", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    perf_table.add_column("Metric", style="cyan", no_wrap=True)
    perf_table.add_column("Value", style="white")

    perf_table.add_row("Total Contribution", f"{portfolio_summary['total_contribution']:.2f} {PRIMARY_CURRENCY}")
    perf_table.add_row("Total Cost", f"{portfolio_summary['portfolio_cost']:.2f} {PRIMARY_CURRENCY}")
    perf_table.add_row("Total Value", f"{portfolio_summary['portfolio_value']:.2f} {PRIMARY_CURRENCY}")
    perf_table.add_row("Total P/L", f"{portfolio_summary['total_portfolio_profit_loss']:+.2f} {PRIMARY_CURRENCY} ({portfolio_summary['total_return_percentage']:+.2%}, p.a. {portfolio_summary['annualized_return_percentage']:+.2%})")
    perf_table.add_row("Free Cash", _format_free_cash(portfolio_summary['free_cash_by_currency']))
    perf_table.add_row("Total Dividends", f"{portfolio_summary['total_dividends']:.2f} {PRIMARY_CURRENCY} (Tax: {portfolio_summary['total_dividend_tax']:.2f} {PRIMARY_CURRENCY})")
    perf_table.add_row("Realized P/L", f"{portfolio_summary['realized_pl']:+.2f} {PRIMARY_CURRENCY} ({portfolio_summary['realized_pl_percentage']:+.2%})")
    perf_table.add_row("Unrealized P/L", f"{portfolio_summary['unrealized_pl']:+.2f} {PRIMARY_CURRENCY} ({portfolio_summary['unrealized_pl_percentage']:+.2%})")

    # --- Dividends Table ---
    div_table = Table(title="Portfolio Dividends Metrics", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    div_table.add_column("Metric", style="cyan", no_wrap=True)
    div_table.add_column("Value", style="white")

    div_table.add_row("PADI", f"{portfolio_summary['padi']:.2f} {PRIMARY_CURRENCY}")
    div_table.add_row(f"Income YTD ({today.year})", f"{portfolio_summary['dividends_ytd']:.2f} {PRIMARY_CURRENCY}")
    div_table.add_row("Income LTM", f"{portfolio_summary['dividends_ltm']:.2f} {PRIMARY_CURRENCY}")
    div_table.add_row("Forward Yield", f"{portfolio_summary['forward_dividend_yield']:+.2%}")
    div_table.add_row("Yield on Cost", f"{portfolio_summary['dividend_yield_on_cost']:+.2%}")
    div_table.add_row("Growth TTM (cost-weighted)", f"{portfolio_summary['portfolio_dividend_growth_ttm_cost_weighted']:+.2%}")
    div_table.add_row("Growth TTM (PADI-weighted)", f"{portfolio_summary['portfolio_dividend_growth_ttm_padi_weighted']:+.2%}")

    console.print(perf_table)
    console.print(div_table)

def print_portfolio_history_rich(console: Console, portfolio_history: List[Dict]):
    """
    Prints the portfolio history table.
    """
    if not portfolio_history:
        console.print("[yellow]No portfolio history data available.[/yellow]")
        return

    table = Table(title="Portfolio History", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Deposit", justify="right", style="white")
    table.add_column("Contributions", justify="right", style="white")
    table.add_column("Dividends", justify="right", style="white")
    table.add_column("PADI", justify="right", style="cyan")
    table.add_column("YoY", justify="right", style="dim white")
    table.add_column("3Y CAGR", justify="right", style="dim white")
    table.add_column("5Y CAGR", justify="right", style="dim white")
    table.add_column("Density", justify="right", style="dim white")
    table.add_column("Invested Amount", justify="right", style="white")
    table.add_column("Unrealized Gain", justify="right")
    table.add_column("Total Gain %", justify="right")
    table.add_column("Total Amount", justify="right", style="bold white")
    table.add_column("YoY", justify="right", style="dim white")
    table.add_column("3Y CAGR", justify="right", style="dim white")
    table.add_column("5Y CAGR", justify="right", style="dim white")
    table.add_column("DEH", justify="right", style="bold white")

    for h in portfolio_history:
        unrealized_gain = h['unrealized_gain']
        unrealized_gain_str = f"{unrealized_gain:+,.2f} {PRIMARY_CURRENCY}"
        unrealized_gain_render = f"[green]{unrealized_gain_str}[/green]" if unrealized_gain > 0 else f"[red]{unrealized_gain_str}[/red]" if unrealized_gain < 0 else unrealized_gain_str
        
        total_gain_perc = h.get('total_gain_perc', 0)
        total_gain_str = f"{total_gain_perc:+.2%}"
        total_gain_render = f"[green]{total_gain_str}[/green]" if total_gain_perc > 0 else f"[red]{total_gain_str}[/red]" if total_gain_perc < 0 else total_gain_str

        padi_yoy = h.get('padi_yoy', 0)
        padi_yoy_render = f"[green]{padi_yoy:+.1%}[/green]" if padi_yoy > 0 else f"[red]{padi_yoy:+.1%}[/red]" if padi_yoy < 0 else f"{padi_yoy:+.1%}"
        
        padi_3y = h.get('padi_cagr_3y', 0)
        padi_3y_render = f"[green]{padi_3y:+.1%}[/green]" if padi_3y > 0 else f"[red]{padi_3y:+.1%}[/red]" if padi_3y < 0 else f"{padi_3y:+.1%}"
        
        padi_5y = h.get('padi_cagr_5y', 0)
        padi_5y_render = f"[green]{padi_5y:+.1%}[/green]" if padi_5y > 0 else f"[red]{padi_5y:+.1%}[/red]" if padi_5y < 0 else f"{padi_5y:+.1%}"

        total_amount_yoy = h.get('total_amount_yoy', 0)
        total_amount_yoy_render = f"[green]{total_amount_yoy:+.1%}[/green]" if total_amount_yoy > 0 else f"[red]{total_amount_yoy:+.1%}[/red]" if total_amount_yoy < 0 else f"{total_amount_yoy:+.1%}"

        total_amount_3y = h.get('total_amount_cagr_3y', 0)
        total_amount_3y_render = f"[green]{total_amount_3y:+.1%}[/green]" if total_amount_3y > 0 else f"[red]{total_amount_3y:+.1%}[/red]" if total_amount_3y < 0 else f"{total_amount_3y:+.1%}"

        total_amount_5y = h.get('total_amount_cagr_5y', 0)
        total_amount_5y_render = f"[green]{total_amount_5y:+.1%}[/green]" if total_amount_5y > 0 else f"[red]{total_amount_5y:+.1%}[/red]" if total_amount_5y < 0 else f"{total_amount_5y:+.1%}"
    
        deh = h.get('div_engine_health', 0)
        deh_render = ""
        if deh != 0:
            deh_render = (
                f"[green]{deh:.2%}[/green]" if deh > 0.07 else
                f"[yellow]{deh:.2%}[/yellow]" if deh >= 0.04 else
                f"[red]{deh:.2%}[/red]"
            )

        table.add_row(
            h['date'],
            f"{h['deposit']:+,.2f} {PRIMARY_CURRENCY}",
            f"{h['total_deposit']:,.2f} {PRIMARY_CURRENCY}",
            f"{h['total_dividends']:,.2f} {PRIMARY_CURRENCY}",
            f"{h.get('padi', 0):,.2f} {PRIMARY_CURRENCY}",
            padi_yoy_render if padi_yoy != 0 else "",
            padi_3y_render if padi_3y != 0 else "",
            padi_5y_render if padi_5y != 0 else "",
            f"{h['padi_total_amount']:+,.2%}",
            f"{h['invested_amount']:,.2f} {PRIMARY_CURRENCY}",
            unrealized_gain_render,
            total_gain_render,
            f"{h['total_amount']:,.2f} {PRIMARY_CURRENCY}",
            total_amount_yoy_render if total_amount_yoy != 0 else "",
            total_amount_3y_render if total_amount_3y != 0 else "",
            total_amount_5y_render if total_amount_5y != 0 else "",
            deh_render
        )

    console.print(table)

def _generate_stock_status_table(details: Dict, price_currency: str) -> Table:
    """
    Generates a formatted stock status table for a ticker.
    """
    if not details:
        return None
    
    current_price = details.get('current_price')
    shares_count = details.get('current_shares')
    
    table = Table(title="Status", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    if details.get('name'):
        table.add_row("Company Name", details['name'])
    if details.get('sector'):
        table.add_row("Sector", details['sector'])
    
    table.add_row("Current Price", f"{current_price:.4f} {price_currency}" if current_price is not None else "N/A")
    table.add_row("Shares", f"{shares_count:.4f}" if shares_count is not None else "N/A")

    return table

def _generate_stock_performance_table(details: Dict) -> Table:
    """
    Generates a formatted stock performance table for a ticker.
    """
    if not details:
        return None
    
    cost_basis = details.get('cost_basis_primary_currency')
    market_value = details.get('market_value_primary')
    unrealized_pl = details.get('unrealized_gain_primary_currency')
    unrealized_pl_perc = details.get('unrealized_gain_percentage')
    realized_pl = details.get('realized_gain_primary_currency')
    realized_pl_perc = details.get('realized_gain_percentage')
    dividends = details.get('total_dividends_received_primary_currency')
    total_pl = details.get('total_profit_loss_primary_currency')
    total_pl_perc = details.get('total_profit_loss_percentage')
    
    table = Table(title="Performance", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Cost Basis", f"{cost_basis:.2f} {PRIMARY_CURRENCY}" if cost_basis is not None else "N/A")
    table.add_row("Market Value", f"{market_value:.2f} {PRIMARY_CURRENCY}" if market_value is not None else "N/A")
    table.add_row("Unrealized P/L", f"{unrealized_pl:+.2f} {PRIMARY_CURRENCY} ({unrealized_pl_perc:+.2%})" if unrealized_pl is not None and unrealized_pl_perc is not None else "N/A")
    table.add_row("Realized P/L", f"{realized_pl:+.2f} {PRIMARY_CURRENCY} ({realized_pl_perc:+.2%})" if realized_pl is not None and realized_pl_perc is not None else "N/A")
    table.add_row("Dividends", f"{dividends:+.2f} {PRIMARY_CURRENCY}" if dividends is not None else "N/A")
    table.add_row("Total P/L", f"{total_pl:+.2f} {PRIMARY_CURRENCY} ({total_pl_perc:+.2%})" if total_pl is not None and total_pl_perc is not None else "N/A")

    return table

def _generate_div_metrics_table(details: Dict, price_currency: str) -> Table:
    """
    Generates a formatted dividend metrics table for a ticker.
    """
    if not details:
        return None
    
    fwd_dividend = details.get('forward_dividend')
    padi = details.get('padi')
    dividend_yield = details.get('dividend_yield')
    avg_div_yield_5y = details.get('average_dividend_yield_5y')
    yield_on_cost = details.get('yield_on_cost')
    next_dividend_month = details.get('next_dividend_month')
    
    table = Table(title="Dividend Metrics", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Forward Dividend", f"{fwd_dividend:.4f} {price_currency}" if fwd_dividend is not None else "N/A")
    table.add_row("Annual Income", f"{padi:.2f} {PRIMARY_CURRENCY}" if padi is not None else "N/A")
    table.add_row("Dividend Yield", f"{dividend_yield:.2%}" if dividend_yield is not None else "N/A")
    table.add_row("5Y Avg. Yield", f"{avg_div_yield_5y:.2%}" if avg_div_yield_5y is not None else "N/A")
    table.add_row("Yield on Cost", f"{yield_on_cost:.2%}" if yield_on_cost is not None else "N/A")
    table.add_row("Next Payment", f"{next_dividend_month}" if next_dividend_month is not None else "N/A")

    return table

def _generate_div_growth_table(details: Dict) -> Table:
    """
    Generates a formatted dividend growth table for a ticker.
    """
    if not details or 'dividend_growth' not in details:
        return None

    div_ttm_growth = details['dividend_growth'].get('ttm')
    div_3y_cagr = details['dividend_growth'].get('cagr_3y')
    div_5y_cagr = details['dividend_growth'].get('cagr_5y')
    div_10y_cagr = details['dividend_growth'].get('cagr_10y')

    div_ttm_growth_str = "N/A"
    if div_ttm_growth:
        div_ttm_growth_str = f"{div_ttm_growth[0]:+.2f} (New)" if len(div_ttm_growth) < 2 or div_ttm_growth[1] is None else f"{div_ttm_growth[0]:+.2f} ({div_ttm_growth[1]:+.2%})"

    table = Table(title="Dividend Growth", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("TTM Growth", div_ttm_growth_str)
    table.add_row("3Y CAGR", f"{f'{div_3y_cagr:+.2%}' if div_3y_cagr is not None else 'N/A'}")
    table.add_row("5Y CAGR", f"{f'{div_5y_cagr:+.2%}' if div_5y_cagr is not None else 'N/A'}")
    table.add_row("10Y CAGR", f"{f'{div_10y_cagr:+.2%}' if div_10y_cagr is not None else 'N/A'}")

    return table

def _generate_ratio_summary_table(details: Dict, portfolio_value: float) -> Table:
    """
    Generates a formatted ratio summary table for a ticker.
    """
    if not details:
        return None

    div_market_value = details.get('market_value_primary')
    div_ratio_on_cost = details.get('ratio_on_cost')
    div_ratio_on_padi = details.get('ratio_on_padi')

    table = Table(title="Ratios", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Value Ratio", f"{details.get('ratio_on_market_value', 0):.2%}")
    table.add_row("Cost Ratio", f"{details.get('ratio_on_cost', 0):.2%}")
    table.add_row("PADI Ratio", f"{details.get('ratio_on_padi', 0):.2%}")

    return table

def _generate_positions_table(details: Dict, price_currency: str) -> Table:
    """
    Generates a formatted open positions table for a ticker.
    """
    open_positions = details.get('open_positions', [])
    if not open_positions:
        return None

    table = Table(title="Open Positions", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Date", style="cyan")
    table.add_column("Shares", justify="right", style="white")
    table.add_column("Price", justify="right", style="white")
    table.add_column("Cost", justify="right", style="white")
    table.add_column("Unrealized Gain", justify="right", style="white")
    table.add_column("Broker", style="magenta")

    for p in open_positions:
        date = p.get('date', 'N/A')
        
        # Robust formatting for shares
        shares_val = p.get('shares')
        broker = p.get('broker', 'N/A')
        try:
            shares_str = f"{float(shares_val):.4f}"
        except (ValueError, TypeError, AttributeError):
            shares_str = str(shares_val) if shares_val is not None else "N/A"

        # Robust formatting for other fields
        price_str = f"{float(p.get('price')):.4f} {price_currency}" if p.get('price') is not None else "N/A"
        cost_str = f"{float(p.get('cost_basis_primary_currency')):.2f} {PRIMARY_CURRENCY}" if p.get('cost_basis_primary_currency') is not None else "N/A"
        
        unrealized_gain = p.get('unrealized_gain_value')
        unrealized_perc = p.get('unrealized_gain_perc')
        unrealized_str = f"{float(unrealized_gain):+.2f} {PRIMARY_CURRENCY} ({float(unrealized_perc):+.2%})" if unrealized_gain is not None and unrealized_perc is not None else "N/A"

        table.add_row(date, shares_str, price_str, cost_str, unrealized_str, broker)

    return table

def _generate_performance_summary_table(details: Dict) -> Table:
    """
    Generates a formatted performance summary table for a ticker.
    """
    if not details:
        return None
    
    realized_gain = details.get('realized_gain_primary_currency')
    realized_gain_perc = details.get('realized_gain_percentage')
    total_dividends = details.get('total_dividends_received_primary_currency')
    total_profit_loss = details.get('total_profit_loss_primary_currency')
    total_profit_loss_perc = details.get('total_profit_loss_percentage')

    table = Table(title="Performance Summary", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    table.add_row("Realized Gain", f"{realized_gain:+.2f} {PRIMARY_CURRENCY} ({realized_gain_perc:+.2%})" if realized_gain is not None and realized_gain_perc is not None else "N/A")
    table.add_row("Total Dividends", f"{total_dividends:+.2f} {PRIMARY_CURRENCY}" if total_dividends is not None else "N/A")
    table.add_row("Total P/L", f"{total_profit_loss:+.2f} {PRIMARY_CURRENCY} ({total_profit_loss_perc:+.2%})" if total_profit_loss is not None and total_profit_loss_perc is not None else "N/A")

    return table

def _generate_closed_positions_table(closed_positions: List[Dict], price_currency: str) -> Table:
    """
    Generates a formatted table for closed positions.
    """
    if not closed_positions:
        return None

    table = Table(title="Closed Positions", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Open / Close Date", style="cyan")
    table.add_column("Shares", justify="right", style="white")
    table.add_column("Open / Close Price", justify="right", style="white")
    table.add_column("Purchase / Sale Value", justify="right", style="white")
    table.add_column("Realized Gain", justify="right", style="white")
    table.add_column("Broker", style="magenta")

    for p in closed_positions:
        open_date = p.get('open_date', 'N/A')
        close_date = p.get('close_date', 'N/A')
        shares = p.get('shares')
        broker = p.get('broker', 'N/A')
        open_price = p.get('open_price')
        close_price = p.get('close_price')
        currency = p.get('currency')
        purchase_value = p.get('purchase_value')
        sale_value = p.get('sale_value')
        realized_pl = p.get('realized_gain_amount')
        realized_pl_perc = p.get('realized_gain_percentage')

        open_close_date_str = f"{open_date} / {close_date}"
        shares_str = f"{shares:.4f}" if shares is not None else "N/A"
        open_price_str = f"{open_price:+.2f} {price_currency}" if open_price is not None else "N/A"
        close_price_str = f"{close_price:+.2f} {price_currency}" if close_price is not None else "N/A"
        open_close_price_str = f"{open_price_str} / {close_price_str}"
        purchase_value_str = f"{purchase_value:+.2f} {currency}" if purchase_value is not None else "N/A"
        sale_value_str = f"{sale_value:+.2f} {currency}" if sale_value is not None else "N/A"
        purchase_sale_value_str = f"{purchase_value_str} / {sale_value_str}"
        realized_gain_str = f"{realized_pl:+.2f} {currency} ({realized_pl_perc:+.2%})" if realized_pl is not None and realized_pl_perc is not None else "N/A"
        
        table.add_row(open_close_date_str, shares_str, open_close_price_str, purchase_sale_value_str, realized_gain_str, broker)

    return table

def _generate_dividends_history_table(ticker_dividends: List[Dict]) -> Table:
    """
    Generates a formatted table for dividend history.
    """
    if not ticker_dividends:
        return None
    
    table = Table(title="Dividends History", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Paid Date", style="cyan")
    table.add_column("Amount per Share", justify="right", style="white")
    table.add_column("Received Amount", justify="right", style="white")
    table.add_column("Withholding Tax", justify="right", style="white")

    for ticker_dividend in ticker_dividends:
        date = ticker_dividend.get('date', 'N/A')
        amount_per_share = ticker_dividend.get('amount_per_share')
        amount_per_share_currency = ticker_dividend.get('amount_per_share_currency')
        amount = ticker_dividend.get('amount')
        currency = ticker_dividend.get('currency', 'N/A')
        withholding_tax = ticker_dividend.get('withholding_tax')
        withholding_tax_rate = ticker_dividend.get('withholding_tax_rate')

        amount_per_share_str = f"{amount_per_share:+.4f} {amount_per_share_currency}" if amount_per_share else "N/A"
        amount_str = f"{amount:+.2f} {currency}" if amount else "N/A"
        tax_str = f"{withholding_tax:+.2f} {currency} / {withholding_tax_rate:+.1f}%" if withholding_tax else "N/A"

        table.add_row(f"{date}", amount_per_share_str, amount_str, tax_str)

    return table

def print_dividend_summary_table_enhanced(console: Console, portfolio_summary: Dict):
    """
    Prints a rich dividend summary calendar based on pre-calculated payment months.
    """
    dividend_calendar = portfolio_summary.get('dividend_calendar', {})
    projected_income = portfolio_summary.get('projected_dividend_income', {})
    
    if not dividend_calendar:
        console.print("[yellow]No upcoming dividends found for owned stocks.[/yellow]")
        return

    # Sort by date
    try:
        sorted_months = sorted(dividend_calendar.keys(), key=lambda x: datetime.strptime(x, '%B %Y'))
    except Exception:
        # Fallback to simple sort if date parsing fails
        sorted_months = sorted(dividend_calendar.keys())
    
    table = Table(title="Dividend Summary", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Month", style="cyan", no_wrap=True)
    table.add_column("Projected Income", justify="right", style="white")
    table.add_column("Tickers", style="dim white")

    for month in sorted_months:
        tickers = ", ".join(sorted(dividend_calendar[month]))
        income = projected_income.get(month, 0.0)
        table.add_row(month, f"{income:,.2f} {PRIMARY_CURRENCY}", tickers)

    console.print(table)


def print_stock_summary_rich(console: Console, all_tickers_data: Dict[str, Dict], portfolio_value: float, dividends_data: Dict[str, List[Dict]], tickers_to_show: List[str] = None):
    """
    Prints the stock summary output to the console using Rich tables.
    Args:
        all_tickers_data (Dict[str, Dict]): The processed data for all tickers.
        portfolio_value (float): The total value of the portfolio.
        dividends_data (Dict[str, List[Dict]]): The dividends history data.
        tickers_to_show (List[str], optional): A list of tickers to show. If None, all are shown. Defaults to None.
    """

    tickers_to_iterate = sorted(all_tickers_data.keys())
    
    if tickers_to_show:
        tickers_to_iterate = tickers_to_show

    displayed_any = False

    for ticker_name in tickers_to_iterate:
        details = all_tickers_data[ticker_name]
        price_currency = details.get('price_currency', '')
        ticker_dividends = dividends_data.get('companies', {}).get(ticker_name, {}).get('dividends', [])
        
        # --- Heading for Ticker ---
        # Determine if owned or sold for header text
        is_owned = details['current_shares'] > 0
        display_name = f" - {details['name']}" if details.get('name') else ""
        header_text = f"{details['ticker']}{display_name} ({'Owned' if is_owned else 'Sold'})"
        
        # Only print header if we are going to print tables
        # But we need to know if we have tables.
        
        tables_to_print = []

        if is_owned:
            # --- Status ---
            status_table = _generate_stock_status_table(details, price_currency)
            if status_table: tables_to_print.append(status_table)

            # --- Performance ---
            perf_table = _generate_stock_performance_table(details)
            if perf_table: tables_to_print.append(perf_table)

            # --- Dividends Metrics ---
            div_table = _generate_div_metrics_table(details, price_currency)
            if div_table: tables_to_print.append(div_table)

            # --- Dividend Growth ---
            div_growth_table = _generate_div_growth_table(details)
            if div_growth_table: tables_to_print.append(div_growth_table)

            # --- Ratios ---
            ratio_table = _generate_ratio_summary_table(details, portfolio_value)
            if ratio_table: tables_to_print.append(ratio_table)

            # --- Open Positions ---
            positions_table = _generate_positions_table(details, price_currency)
            if positions_table: tables_to_print.append(positions_table)

            # --- Closed Positions ---
            closed_positions_table = _generate_closed_positions_table(details['closed_positions'], price_currency)
            if closed_positions_table: tables_to_print.append(closed_positions_table)

            # --- Dividends History ---
            dividends_table = _generate_dividends_history_table(ticker_dividends)
            if dividends_table: tables_to_print.append(dividends_table)

        else:
            if details.get('closed_positions'):
                # --- Performance Summary ---
                performance_summary_table = _generate_performance_summary_table(details)
                if performance_summary_table: tables_to_print.append(performance_summary_table)

                # --- Closed Positions Table ---
                closed_positions_table = _generate_closed_positions_table(details['closed_positions'], price_currency)
                if closed_positions_table: tables_to_print.append(closed_positions_table)

                # --- Dividends History ---
                dividends_table = _generate_dividends_history_table(ticker_dividends)
                if dividends_table: tables_to_print.append(dividends_table)

        if tables_to_print:
            displayed_any = True
            console.rule(f"[bold yellow]{header_text}[/bold yellow]")
            for t in tables_to_print:
                console.print(t)
            console.print("") # spacing

    if not displayed_any:
        console.print("[yellow]No owned or sold tickers to display.[/yellow]")


def print_dividend_history_chart(console: Console, portfolio_summary: Dict):
    """
    Prints a rich horizontal bar chart for quarterly dividends.
    """
    quarterly_divs = portfolio_summary.get('quarterly_dividends', {})
    
    if not quarterly_divs:
        console.print("[yellow]No dividends data available.[/yellow]")
        return

    # Sort quarters: first by year (yy), then by quarter number (x)
    sorted_quarters = sorted(quarterly_divs.keys(), key=lambda x: (int(x.split('/')[1]), int(x[1])))

    max_val = max(quarterly_divs.values()) if quarterly_divs else 0
    max_width_bars = 40 

    table = Table(title="Dividend History (Quarterly)", box=box.SIMPLE, show_header=True, header_style="bold cyan")
    table.add_column("Quarter", style="cyan", no_wrap=True)
    table.add_column("Bar", no_wrap=True)
    table.add_column("Amount", justify="right", style="white")
    table.add_column("Y/Y Change", justify="right")

    for i, quarter_key in enumerate(sorted_quarters):
        amount = quarterly_divs[quarter_key]
        
        # Calculate bar length
        bar_len = int((amount / max_val) * max_width_bars) if max_val > 0 else 0
        bar_str = "█" * bar_len
        bar_render = f"[{'blue' if i % 2 == 0 else 'dodger_blue1'}]{bar_str}[/]"
        
        amount_str = f"{amount:,.2f} {PRIMARY_CURRENCY}"

        change_render = ""
        # Y/Y Start from 5th item
        if i >= 4:
            # quarter_key format: Q1/24
            q, y = quarter_key.split('/')
            prev_year_quarter = f"{q}/{int(y)-1:02d}"
            if prev_year_quarter in quarterly_divs:
                prev_amount = quarterly_divs[prev_year_quarter]
                if prev_amount > 0:
                    change = calculate_yoy(amount, prev_amount)
                    if change > 0:
                        change_render = f"[green]+{change:.2%}[/green]"
                    elif change < 0:
                        change_render = f"[red]{change:.2%}[/red]"
                    else:
                        change_render = "[grey]0.00%[/grey]"
                else:
                     change_render = "[dim]N/A[/dim]"
            else:
                 change_render = "[dim]N/A[/dim]"
        
        table.add_row(quarter_key, bar_render, amount_str, change_render)

    console.print(table)


def main():
    """
    Main function to run the stock reporter.
    """
    console = Console()
    print("--- Starting Stock Reporter ---")

    portfolio_summary, all_tickers_data = load_analysis_output()
    if portfolio_summary is None or all_tickers_data is None:
        return
    
    analysis_data = {}
    if os.path.exists(STOCK_ANALYSIS_OUTPUT):
        with open(STOCK_ANALYSIS_OUTPUT, 'r') as f:
            analysis_data = json.load(f)
    portfolio_history = analysis_data.get('portfolio_history', [])

    dividends_data = load_dividends_data()
    if dividends_data is None:
        return

    main_menu_choices = [
        "Stock Summary", 
        "Portfolio Summary",
        "Portfolio History",
        "Dividend Summary",
        "Dividend History",
        "Exit"
    ]
    
    while True:
        questions = [
            inquirer.List(
                'report',
                message="Select the report you want to see",
                choices=main_menu_choices,
                carousel=True
            ),
        ]
        try:
            answers = inquirer.prompt(questions)
            if not answers: # Ctrl+C
                print("Exiting.")
                break
            
            choice = answers['report']

            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"--- {choice} ---")

            if choice == CHOICE_STOCK_SUMMARY:
                # Categorize tickers based on has_open_position flag
                actual_open = sorted([t for t, data in all_tickers_data.items() if data.get('has_open_position', False)])
                actual_closed = sorted([t for t in all_tickers_data.keys() if t not in actual_open])

                ticker_choices = ["All"]
                if actual_open:
                    ticker_choices.extend(actual_open)
                if actual_closed:
                    ticker_choices.extend(actual_closed)

                ticker_questions = [
                    inquirer.List(
                        'ticker',
                        message="Select a ticker to see the summary for",
                        choices=ticker_choices,
                        carousel=True
                    ),
                ]
                ticker_answers = inquirer.prompt(ticker_questions)
                if not ticker_answers: # Ctrl+C
                    continue

                selected_ticker = ticker_answers['ticker']
                
                tickers_to_print = None
                if selected_ticker != "All":
                    tickers_to_print = [selected_ticker]
                
                print_stock_summary_rich(console, all_tickers_data, portfolio_summary['portfolio_value'], dividends_data, tickers_to_print)

            elif choice == CHOICE_PORTFOLIO_SUMMARY:
                print_portfolio_summary_rich(console, portfolio_summary)

            elif choice == "Dividend Summary":
                print_dividend_summary_table_enhanced(console, portfolio_summary)
            
            elif choice == "Dividend History":
                print_dividend_history_chart(console, portfolio_summary)
            
            elif choice == CHOICE_PORTFOLIO_HISTORY:
                print_portfolio_history_rich(console, portfolio_history)

            elif choice == CHOICE_EXIT:
                print("Exiting reporter.")
                sys.exit(EXIT_CODE_RETURN_TO_MENU)
            
            print(f"--- {choice} Finished ---")
            input("\nPress Enter to return to the menu...")
            os.system('cls' if os.name == 'nt' else 'clear')

        except KeyboardInterrupt:
            print("\nExiting application.")
            break

if __name__ == '__main__':
    main()
