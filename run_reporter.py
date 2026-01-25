import json
import pandas as pd
from typing import Dict, List
from tabulate import tabulate
from datetime import datetime
import inquirer
import os
import sys
from calendar import month_name

from config import PRIMARY_CURRENCY, EXIT_CODE_RETURN_TO_MENU, CHOICE_EXIT, CHOICE_STOCK_SUMMARY, CHOICE_PORTFOLIO_SUMMARY
from utils.data_loader import load_analysis_output, load_dividends_data

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

def generate_portfolio_summary_table(portfolio_summary: Dict) -> List[List]:
    """
    Generates the portfolio summary table with Performance and Dividends sections.
    Args:
        portfolio_summary (Dict): The portfolio summary data.
    Returns:
        List[List]: A list containing two sublists for Performance and Dividends tables.
    """

    today = datetime.now()

    # Performance Data
    perf_data = [
        ["Total Contribution:", f"{portfolio_summary['total_contribution']:.2f} {PRIMARY_CURRENCY}"],
        ["Total Cost:", f"{portfolio_summary['portfolio_cost']:.2f} {PRIMARY_CURRENCY}"],
        ["Total Value:", f"{portfolio_summary['portfolio_value']:.2f} {PRIMARY_CURRENCY}"],
        ["Total P/L:", f"{portfolio_summary['total_portfolio_profit_loss']:+.2f} {PRIMARY_CURRENCY} ({portfolio_summary['total_return_percentage']:+.2%}, p.a. {portfolio_summary['annualized_return_percentage']:+.2%})"],
        ["Free Cash:", _format_free_cash(portfolio_summary['free_cash_by_currency'])],
        ["Total Dividends:", f"{portfolio_summary['total_dividends']:.2f} {PRIMARY_CURRENCY} (Tax: {portfolio_summary['total_dividend_tax']:.2f} {PRIMARY_CURRENCY})"],
        ["Realized P/L:", f"{portfolio_summary['realized_pl']:+.2f} {PRIMARY_CURRENCY} ({portfolio_summary['realized_pl_percentage']:+.2%})"],
        ["Unrealized P/L:", f"{portfolio_summary['unrealized_pl']:+.2f} {PRIMARY_CURRENCY} ({portfolio_summary['unrealized_pl_percentage']:+.2%})"]
    ]
    
    # Dividends Data
    div_data = [
        ["PADI:", f"{portfolio_summary['padi']:.2f} {PRIMARY_CURRENCY}"],
        [f"Income YTD ({today.year}):", f"{portfolio_summary['dividends_ytd']:.2f} {PRIMARY_CURRENCY}"],
        ["Income LTM:", f"{portfolio_summary['dividends_ltm']:.2f} {PRIMARY_CURRENCY}"],
        ["Forward Yield:", f"{portfolio_summary['forward_dividend_yield']:+.2%}"],
        ["Yield on Cost:", f"{portfolio_summary['dividend_yield_on_cost']:+.2%}"],
        ["Growth TTM (cost-weighted):", f"{portfolio_summary['portfolio_dividend_growth_ttm_cost_weighted']:+.2%}"],
        ["Growth TTM (PADI-weighted):", f"{portfolio_summary['portfolio_dividend_growth_ttm_padi_weighted']:+.2%}"]
    ]

    perf_table_str = tabulate(perf_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)
    div_table_str = tabulate(div_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

    main_table_data = [
        ["Performance", perf_table_str],
        ["Dividends", div_table_str]
    ]

    return main_table_data

def _generate_stock_status_table(details: Dict, price_currency: str) -> str:
    """
    Generates a formatted stock status table for a ticker.
    Args:
        details (Dict): The ticker details dictionary with current price information and current shares count.
        price_currency (str): The currency of the listed ticker.
    Returns:
        str: The formatted table with Metrics and Values columns as a string for outputting stock status.
    """
    
    if not details:
        return ""
    
    current_price = details.get('current_price')
    shares_count = details.get('current_shares')
    
    status_data = [
        [f"Current Price:", f"{current_price:.4f} {price_currency}" if current_price is not None else "N/A"],
        [f"Shares:", f"{shares_count:.4f}" if shares_count is not None else "N/A"]   # Display up to 4 decimal places for shares due to fractional shares
    ]

    return tabulate(status_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

def _generate_stock_performance_table(details: Dict) -> str:
    """
    Generates a formatted stock performance table for a ticker.
    Args:
        details (Dict): The ticker details dictionary.
    Returns:
        str: The formatted table with Metrics and Values columns as a string for outputting stock performance.
    """

    if not details:
        return ""
    
    cost_basis = details.get('cost_basis_primary_currency')
    market_value = details.get('market_value_primary')
    unrealized_pl = details.get('unrealized_gain_primary_currency')
    unrealized_pl_perc = details.get('unrealized_gain_percentage')
    realized_pl = details.get('realized_gain_primary_currency')
    realized_pl_perc = details.get('realized_gain_percentage')
    dividends = details.get('total_dividends_received_primary_currency')
    total_pl = details.get('total_profit_loss_primary_currency')
    total_pl_perc = details.get('total_profit_loss_percentage')
    
    perf_data = [
        [f"Cost Basis:", f"{cost_basis:.2f} {PRIMARY_CURRENCY}" if cost_basis is not None else "N/A"],
        [f"Market Value:", f"{market_value:.2f} {PRIMARY_CURRENCY}" if market_value is not None else "N/A"],
        [f"Unrealized P/L:", f"{unrealized_pl:+.2f} {PRIMARY_CURRENCY} ({unrealized_pl_perc:+.2%})" if unrealized_pl is not None and unrealized_pl_perc is not None else "N/A"],
        [f"Realized P/L:", f"{realized_pl:+.2f} {PRIMARY_CURRENCY} ({realized_pl_perc:+.2%})" if realized_pl is not None and realized_pl_perc is not None else "N/A"],
        [f"Dividends:", f"{dividends:+.2f} {PRIMARY_CURRENCY}" if dividends is not None else "N/A"],
        [f"Total P/L:", f"{total_pl:+.2f} {PRIMARY_CURRENCY} ({total_pl_perc:+.2%})" if total_pl is not None and total_pl_perc is not None else "N/A"]
    ]

    return tabulate(perf_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

def _generate_div_metrics_table(details: Dict, price_currency: str) -> str:
    """
    Generates a formatted dividend metrics table for a ticker.
    Args:
        details (Dict): The ticker details dictionary.
        price_currency (str): The currency of the listed ticker.
    Returns:
        str: The formatted table with Metrics and Values columns as a string for outputting dividend metrics.
    """

    if not details:
        return ""
    
    fwd_dividend = details.get('forward_dividend')
    padi = details.get('padi')
    dividend_yield = details.get('dividend_yield')
    avg_div_yield_5y = details.get('average_dividend_yield_5y')
    yield_on_cost = details.get('yield_on_cost')
    next_dividend_month = details.get('next_dividend_month')
    
    div_data = [
        [f"Forward Dividend:", f"{fwd_dividend:.4f} {price_currency}" if fwd_dividend is not None else "N/A"],
        [f"Annual Income:", f"{padi:.2f} {PRIMARY_CURRENCY}" if padi is not None else "N/A"],
        [f"Dividend Yield:", f"{dividend_yield:.2%}" if dividend_yield is not None else "N/A"],
        [f"5Y Avg. Yield:", f"{avg_div_yield_5y:.2%}" if avg_div_yield_5y is not None else "N/A"],
        [f"Yield on Cost:", f"{yield_on_cost:.2%}" if yield_on_cost is not None else "N/A"],
        [f"Next Payment:", f"{next_dividend_month}" if next_dividend_month is not None else "N/A"]
    ]

    return tabulate(div_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

def _generate_div_growth_table(details: Dict) -> str:
    """
    Generates a formatted dividend growth table for a ticker.
    Args:
        details (Dict): The ticker details dictionary.
    Returns:
        str: The formatted table with Metrics and Values columns as a string for outputting dividend growth.
    """

    if not details or 'dividend_growth' not in details:
        return ""

    div_ttm_growth = details['dividend_growth'].get('ttm')
    div_3y_cagr = details['dividend_growth'].get('cagr_3y')
    div_5y_cagr = details['dividend_growth'].get('cagr_5y')
    div_10y_cagr = details['dividend_growth'].get('cagr_10y')

    div_ttm_growth_str = "N/A"
    if div_ttm_growth:
        div_ttm_growth_str = f"{div_ttm_growth[0]:+.2f} (New)" if len(div_ttm_growth) < 2 or div_ttm_growth[1] is None else f"{div_ttm_growth[0]:+.2f} ({div_ttm_growth[1]:+.2%})"

    div_growth_data = [
        [f"TTM Growth:", div_ttm_growth_str],
        [f"3Y CAGR:", f"{f'{div_3y_cagr:+.2%}' if div_3y_cagr is not None else 'N/A'}"],
        [f"5Y CAGR:", f"{f'{div_5y_cagr:+.2%}' if div_5y_cagr is not None else 'N/A'}"],
        [f"10Y CAGR:", f"{f'{div_10y_cagr:+.2%}' if div_10y_cagr is not None else 'N/A'}"]
    ]

    return tabulate(div_growth_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

def _generate_ratio_summary_table(details: Dict, portfolio_value: float) -> str:
    """
    Generates a formatted ratio summary table for a ticker.
    Args:
        details (Dict): The ticker details dictionary.
        portfolio_value (float): The total value of the portfolio.
    Returns:
        str: The formatted table with Metrics and Values columns as a string for outputting ratio summary.
    """

    if not details:
        return ""

    div_market_value = details.get('market_value_primary')
    div_ratio_on_cost = details.get('ratio_on_cost')
    div_ratio_on_padi = details.get('ratio_on_padi')

    ratio_data = [
        [f"Value Ratio:", f"{(div_market_value / portfolio_value):.2%}" if portfolio_value > 0 else "N/A"],
        [f"Cost Ratio:", f"{div_ratio_on_cost:.2%}"],
        [f"PADI Ratio:", f"{div_ratio_on_padi:.2%}"]
    ]

    return tabulate(ratio_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

def _generate_positions_table(details: Dict, price_currency: str) -> str:
    """
    Generates a formatted open positions table for a ticker.
    Args:
        details (Dict): The ticker details dictionary.
        price_currency (str): The currency of the listed ticker.
    Returns:
        str: The formatted table with detailed information of open positions as a string for outputting results.
    """
    open_positions = details.get('open_positions', [])
    if not open_positions:
        return ""

    headers = ['Date', 'Shares', 'Price', f'Cost', f'Unrealized Gain', 'Broker']
    positions_data = []
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

        positions_data.append([
            date,
            shares_str,
            price_str,
            cost_str,
            unrealized_str,
            broker
        ])

    return tabulate(positions_data, headers=headers, tablefmt="grid", disable_numparse=True)

def _generate_performance_summary_table(details: Dict) -> str:
    """
    Generates a formatted performance summary table for a ticker.
    Args:
        details (Dict): The ticker details dictionary.
    Returns:
        str: The formatted table with Metrics and Values columns as a string for outputting performance summary.
    """

    if not details:
        return ""
    
    realized_gain = details.get('realized_gain_primary_currency')
    realized_gain_perc = details.get('realized_gain_percentage')
    total_dividends = details.get('total_dividends_received_primary_currency')
    total_profit_loss = details.get('total_profit_loss_primary_currency')
    total_profit_loss_perc = details.get('total_profit_loss_percentage')

    perf_data = [
        [f"Realized Gain:", f"{realized_gain:+.2f} {PRIMARY_CURRENCY} ({realized_gain_perc:+.2%})" if realized_gain is not None and realized_gain_perc is not None else "N/A"],
        [f"Total Dividends:", f"{total_dividends:+.2f} {PRIMARY_CURRENCY}" if total_dividends is not None else "N/A"],
        [f"Total P/L:", f"{total_profit_loss:+.2f} {PRIMARY_CURRENCY} ({total_profit_loss_perc:+.2%})" if total_profit_loss is not None and total_profit_loss_perc is not None else "N/A"]
    ]

    return tabulate(perf_data, headers=["Metric", "Value"], tablefmt="grid", disable_numparse=True)

def _generate_closed_positions_table(closed_positions: List[Dict], price_currency: str) -> str:
    """
    Generates a formatted table for closed positions.
    Args:
        closed_positions (List[Dict]): List of closed position dictionaries per ticker.
        price_currency (str): The currency of the listed ticker.
    Returns:
        str: The formatted table with detailed information of closed positions as a string for outputting results.
    """

    if not closed_positions:
        return ""

    headers = ['Open / Close Date', 'Shares', 'Open / Close Price', 'Purchase / Sale Value', 'Realized Gain', 'Broker']
    closed_data = []

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
        shares_str = f"{shares:.4f}" if shares is not None else "N/A"  # Display up to 4 decimal places for shares due to fractional shares
        open_price_str = f"{open_price:+.2f} {price_currency}" if open_price is not None else "N/A"
        close_price_str = f"{close_price:+.2f} {price_currency}" if close_price is not None else "N/A"
        open_close_price_str = f"{open_price_str} / {close_price_str}"
        purchase_value_str = f"{purchase_value:+.2f} {currency}" if purchase_value is not None else "N/A"
        sale_value_str = f"{sale_value:+.2f} {currency}" if sale_value is not None else "N/A"
        purchase_sale_value_str = f"{purchase_value_str} / {sale_value_str}"
        realized_gain_str = f"{realized_pl:+.2f} {currency} ({realized_pl_perc:+.2%})" if realized_pl is not None and realized_pl_perc is not None else "N/A"
        closed_data.append([
            open_close_date_str,
            shares_str,
            open_close_price_str,
            purchase_sale_value_str,
            realized_gain_str,
            broker
        ])

    return tabulate(closed_data, headers=headers, tablefmt="grid", disable_numparse=True)

def _generate_dividends_history_table(ticker_dividends: List[Dict]) -> str:
    """
    Generates a formatted table for dividend history.
    Args:
        ticker_dividends (List[Dict]): List of dividend dictionaries per ticker.
    Returns:
        str: The formatted table with detailed information of dividend history as a string for outputting results.
    """

    if not ticker_dividends:
        return ""
    
    headers = ["Paid Date", "Amount per Share", "Received Amount", "Withholding Tax"]
    div_history_data = []
    for ticker_dividend in ticker_dividends:
        date = ticker_dividend.get('date', 'N/A')
        amount_per_share = ticker_dividend.get('amount_per_share')
        amount_per_share_currency = ticker_dividend.get('amount_per_share_currency')
        amount = ticker_dividend.get('amount')
        currency = ticker_dividend.get('currency', 'N/A')
        withholding_tax = ticker_dividend.get('withholding_tax')
        withholding_tax_rate = ticker_dividend.get('withholding_tax_rate')

        div_history_data.append(
            [
                f"{date}",
                f"{amount_per_share:+.4f} {amount_per_share_currency}" if amount_per_share else "N/A",
                f"{amount:+.2f} {currency}" if amount else "N/A",
                f"{withholding_tax:+.2f} {currency} / {withholding_tax_rate:+.1f}%" if withholding_tax else "N/A",
            ]
        )

    return tabulate(div_history_data, headers=headers, tablefmt="grid", disable_numparse=True)

def generate_dividend_summary_table(all_tickers_data: Dict[str, Dict], portfolio_summary: Dict, timeframe_months: int = 12) -> str:
    """
    Generates a dividend summary calendar based on pre-calculated payment months.
    """
    dividend_calendar = {}  # { 'Month Year': [Tickers] }
    projected_income = portfolio_summary.get('projected_dividend_income', {})
    today = datetime.now()
    # Set day to 1 to avoid issues with month-end calculations
    today = today.replace(day=1)
    time_limit = today + pd.DateOffset(months=timeframe_months)

    for ticker, details in all_tickers_data.items():
        if details.get('current_shares', 0) > 0:
            payment_months = details.get('dividend_payment_months')
            if not payment_months:
                continue

            # Project payments for the next years
            for year_offset in range(2):  # Check current and next year
                year = today.year + year_offset
                for month in payment_months:
                    # Create a representative date for that month/year
                    try:
                        payment_date = datetime(year, month, 1)
                    except ValueError:
                        continue # Invalid date, e.g., month 0

                    # Check if this date is in the future and within our timeframe
                    if payment_date >= today and payment_date < time_limit:
                        month_year_str = f"{month_name[month]} {year}"
                        if month_year_str not in dividend_calendar:
                            dividend_calendar[month_year_str] = []
                        if ticker not in dividend_calendar[month_year_str]:
                            dividend_calendar[month_year_str].append(ticker)

    if not dividend_calendar:
        return "No upcoming dividends found for owned stocks."

    # Sort by date and format for tabulate
    sorted_months = sorted(dividend_calendar.keys(), key=lambda x: datetime.strptime(x, '%B %Y'))
    
    table_data = []
    for month in sorted_months:
        tickers = ", ".join(sorted(dividend_calendar[month]))
        income = projected_income.get(month, 0.0)
        table_data.append([month, f"{income:,.2f} {PRIMARY_CURRENCY}", tickers])

    return tabulate(table_data, headers=["Month", "Projected Income", "Tickers"], tablefmt="grid", disable_numparse=True)


def generate_stock_summary_output(all_tickers_data: Dict[str, Dict], portfolio_value: float, dividends_data: Dict[str, List[Dict]], tickers_to_show: List[str] = None) -> str:
    """
    Generates and prints the stock summary output to the console.
    Args:
        all_tickers_data (Dict[str, Dict]): The processed data for all tickers.
        portfolio_value (float): The total value of the portfolio.
        dividends_data (Dict[str, List[Dict]]): The dividends history data.
        tickers_to_show (List[str], optional): A list of tickers to show. If None, all are shown. Defaults to None.
    Returns:
        str: The formatted stock summary report.
    """

    owned_tickers_output, sold_tickers_output = [], []

    tickers_to_iterate = sorted(all_tickers_data.keys())
    
    if tickers_to_show:
        tickers_to_iterate = tickers_to_show

    for ticker_name in tickers_to_iterate:
        details = all_tickers_data[ticker_name]
        price_currency = details.get('price_currency', '')
        ticker_dividends = dividends_data.get('companies', {}).get(ticker_name, {}).get('dividends', [])
        
        if details['current_shares'] > 0:
            table_data = []

            # --- Status ---
            status_table = _generate_stock_status_table(details, price_currency)
            if status_table:
                table_data.append(["Status", status_table])

            # --- Performance ---
            perf_table = _generate_stock_performance_table(details)
            if perf_table:
                table_data.append(["Performance", perf_table])

            # --- Dividends Metrics ---
            div_table = _generate_div_metrics_table(details, price_currency)
            if div_table:
                table_data.append(["Dividends", div_table])

            # --- Dividend Growth ---
            div_growth_table = _generate_div_growth_table(details)
            if div_growth_table:
                table_data.append(["Div. Growth", div_growth_table])

            # --- Ratios ---
            ratio_table = _generate_ratio_summary_table(details, portfolio_value)
            if ratio_table:
                table_data.append(["Ratios", ratio_table])

            # --- Open Positions ---
            positions_table = _generate_positions_table(details, price_currency)
            if positions_table:
                table_data.append(["Open Positions", positions_table])

            # --- Closed Positions ---
            closed_positions_table = _generate_closed_positions_table(details['closed_positions'], price_currency)
            if closed_positions_table:
                table_data.append(["Closed Positions", closed_positions_table])

            # --- Dividends History ---
            dividends_table = _generate_dividends_history_table(ticker_dividends)
            if dividends_table:
                table_data.append(["Dividends History", dividends_table])

            owned_tickers_output.append(tabulate(table_data, headers=[f"{details['ticker']} (Owned)", "Metrics"], tablefmt="grid", disable_numparse=True))

        else:
            if details.get('closed_positions'):
                table_data = []
                
                # --- Performance Summary ---
                performance_summary_table = _generate_performance_summary_table(details)
                if performance_summary_table:
                    table_data.append(["Performance Summary", performance_summary_table])

                # --- Closed Positions Table ---
                closed_positions_table = _generate_closed_positions_table(details['closed_positions'], price_currency)
                if closed_positions_table:
                    table_data.append(["Closed Positions", closed_positions_table])

                # --- Dividends History ---
                dividends_table = _generate_dividends_history_table(ticker_dividends)
                if dividends_table:
                    table_data.append(["Dividends History", dividends_table])

                output_table = tabulate(table_data, headers=[f"{details['ticker']} (Sold)", "Metrics"], tablefmt="grid", disable_numparse=True)
                sold_tickers_output.append(output_table)

    output_blocks = []
    if owned_tickers_output:
        output_blocks.append("\n".join(owned_tickers_output))
        
    if sold_tickers_output:
            output_blocks.append("\n".join(sold_tickers_output))

    if not output_blocks:
            return "No owned or sold tickers to display."

    return "\n\n".join(output_blocks)


def main():
    """
    Main function to run the stock reporter.
    """
    print("--- Starting Stock Reporter ---")

    portfolio_summary, all_tickers_data = load_analysis_output()
    if portfolio_summary is None or all_tickers_data is None:
        return

    dividends_data = load_dividends_data()
    if dividends_data is None:
        return

    main_menu_choices = [
        "Stock Summary", 
        "Portfolio Summary",
        "Dividend Summary",
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
                ticker_choices = ["All"] + sorted(list(all_tickers_data.keys()))
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
                
                stock_summary_output = generate_stock_summary_output(all_tickers_data, portfolio_summary['portfolio_value'], dividends_data, tickers_to_print)
                print(stock_summary_output)

            elif choice == CHOICE_PORTFOLIO_SUMMARY:
                portfolio_summary_table = generate_portfolio_summary_table(portfolio_summary)
                print(tabulate(portfolio_summary_table, headers=["Portfolio Summary", ""], tablefmt="grid", disable_numparse=True))

            elif choice == "Dividend Summary":
                dividend_summary_output = generate_dividend_summary_table(all_tickers_data, portfolio_summary)
                print(dividend_summary_output)

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
