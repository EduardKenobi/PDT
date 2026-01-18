import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import pandas as pd
from datetime import datetime
import json
from tabulate import tabulate
from utils.data_loader import load_yaml, load_nested_yaml_to_dataframe
from config import TRANSACTIONS_OUTPUT_FILE, DIVIDEND_OUTPUT_FILE, TICKER_MAP_FILE, TAX_ANALYSIS_OUTPUT
from app.taxes.tax_config import CZECH_DIVIDEND_TAX_RATE, CZECH_CP_BRUTTO_INCOME_LIMIT, CZECH_INCOME_TAX_RATE, CZECH_FOREIGN_DIVIDEND_INCOME_LIMIT
from utils.data_fetcher import get_batch_historical_rates

def _calculate_yearly_average_rates(rates_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates the average yearly exchange rate from a daily rates DataFrame.

    Args:
        rates_df (pd.DataFrame): DataFrame with a DatetimeIndex and a 'Close' column.

    Returns:
        pd.DataFrame: A DataFrame with 'Year' and 'Rate' columns.
    """
    if rates_df.empty or 'Close' not in rates_df.columns:
        return pd.DataFrame(columns=['Year', 'Rate'])

    rates_df.index = pd.to_datetime(rates_df.index, errors='coerce')
    rates_df = rates_df[rates_df.index.notna()]

    if rates_df.empty:
        return pd.DataFrame(columns=['Year', 'Rate'])

    # Resample by year-end frequency ('YE') to calculate the mean exchange rate.
    yearly_avg = rates_df['Close'].resample('YE').mean()
    result_df = yearly_avg.reset_index()

    if result_df.shape[1] < 2:
        return pd.DataFrame(columns=['Year', 'Rate'])
    
    date_col = result_df.columns[0]
    value_col = result_df.columns[1]
    
    result_df['Year'] = result_df[date_col].dt.year
    result_df.rename(columns={value_col: 'Rate'}, inplace=True)
    
    return result_df[['Year', 'Rate']]

def _prepare_exchange_rate_map(start_year: int) -> pd.DataFrame:
    """
    Fetches and prepares a DataFrame mapping year and currency to its average exchange rate against CZK.

    Args:
        start_year (int): The first year for which to fetch exchange rate data.

    Returns:
        pd.DataFrame: A DataFrame with columns ['Year', 'Currency', 'Rate'].
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = f'{start_year}-01-01'

    # 1. Fetch raw daily rates for major currencies against CZK.
    uscz_rates_raw = get_batch_historical_rates('USD', 'CZK', start_date, end_date)
    eucz_rates_raw = get_batch_historical_rates('EUR', 'CZK', start_date, end_date)

    # 2. Calculate the average rate for each year.
    uscz_yearly = _calculate_yearly_average_rates(uscz_rates_raw)
    if not uscz_yearly.empty:
        uscz_yearly['Currency'] = 'USD'
    
    eucz_yearly = _calculate_yearly_average_rates(eucz_rates_raw)
    if not eucz_yearly.empty:
        eucz_yearly['Currency'] = 'EUR'

    # 3. Combine all currency rates into a single map.
    all_rates = pd.concat([uscz_yearly, eucz_yearly], ignore_index=True)
    
    if all_rates.empty:
        return pd.DataFrame(columns=['Year', 'Currency', 'Rate'])

    # 4. Add CZK itself to the map, as its exchange rate to CZK is always 1.
    years = all_rates['Year'].unique()
    czk_rates_list = [{'Year': int(year), 'Currency': 'CZK', 'Rate': 1.0} for year in years]
    czk_rates = pd.DataFrame(czk_rates_list)
    
    final_map = pd.concat([all_rates, czk_rates], ignore_index=True)
    
    return final_map

def convert_income_to_czk(df: pd.DataFrame) -> pd.DataFrame:
    """
    Converts and aggregates monetary values in a DataFrame to CZK using a vectorized approach.

    This function takes a DataFrame with monetary values in various currencies and
    converts them to CZK using a pre-calculated map of average yearly exchange rates.
    It then aggregates the data by year and any other categorical columns.

    Args:
        df (pd.DataFrame): Input DataFrame with columns like 'Year', 'Currency', and numeric values.

    Returns:
        pd.DataFrame: A new DataFrame with monetary values in CZK, aggregated by year.
    """
    if df.empty:
        return pd.DataFrame()

    df_conv = df.copy()

    year_col = 'Year' if 'Year' in df_conv.columns else 'year'
    currency_col = 'Currency' if 'Currency' in df_conv.columns else 'currency'

    if year_col not in df_conv.columns or currency_col not in df_conv.columns:
        raise ValueError(f"Input DataFrame must contain '{year_col}' and '{currency_col}' columns.")

    # --- 1. Prepare Exchange Rate Map ---
    min_year = int(df_conv[year_col].min())
    rate_map = _prepare_exchange_rate_map(min_year)

    if rate_map.empty:
        print("Warning: Could not create exchange rate map. Returning empty DataFrame.")
        return pd.DataFrame()

    # --- 2. Merge DataFrame with Rate Map ---
    # This adds the correct exchange rate to each row based on its year and currency.
    df_merged = pd.merge(df_conv, rate_map, left_on=[year_col, currency_col], right_on=['Year', 'Currency'], how='left')

    # Handle any currencies for which no exchange rate was found.
    unsupported = df_merged[df_merged['Rate'].isna()]
    if not unsupported.empty:
        for _, row in unsupported.iterrows():
            print(f"Warning: Unsupported currency '{row[currency_col]}' for year {int(row[year_col])}. Row will be skipped.")
    
    df_merged.dropna(subset=['Rate'], inplace=True)
    if df_merged.empty:
        return pd.DataFrame()

    # --- 3. Vectorized Currency Conversion ---
    # Multiply all numeric columns by the exchange rate in their row.
    numeric_cols = df_conv.select_dtypes(include=['number']).columns.tolist()
    if year_col in numeric_cols:
        numeric_cols.remove(year_col)
    
    for col in numeric_cols:
        df_merged[col] = (df_merged[col] * df_merged['Rate']).round(2)

    # --- 4. Aggregate Data ---
    # Group by original categorical columns and sum the newly converted CZK values.
    grouping_cols = [c for c in df_conv.columns if c in df_conv.select_dtypes(exclude=['number']).columns and c != currency_col]
    if year_col not in grouping_cols:
        grouping_cols.insert(0, year_col)
    if not grouping_cols:
        grouping_cols = [year_col]

    df_aggregated = df_merged.groupby(grouping_cols, as_index=False)[numeric_cols].sum()
    df_aggregated[currency_col] = 'CZK'

    # --- 5. Format Output ---
    # Ensure the column order is consistent with the original DataFrame.
    original_cols_order = [c for c in df.columns if c in df_aggregated.columns]
    if currency_col not in original_cols_order:
        original_cols_order.append(currency_col)

    return df_aggregated.reindex(columns=original_cols_order)


def analyze_closed_positions(transactions_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculates and prints a summary of closed positions from a transactions DataFrame.

    Args:
        transactions_df (pd.DataFrame): DataFrame containing transaction data.

    Returns:
        pd.DataFrame: A DataFrame summarizing total sale value and profit by year and currency.
    """
    
    # Filter for transactions that are marked as 'closed'.
    closed_df = transactions_df[
        (transactions_df['type'] == 'closed')
    ].copy()

    if closed_df.empty:
        print("No relevant closed transactions found for tax purposes.")
        return pd.DataFrame()

    # Ensure numeric types for calculation
    closed_df['sale_value'] = pd.to_numeric(closed_df['sale_value'], errors='coerce')
    closed_df['purchase_value'] = pd.to_numeric(closed_df['purchase_value'], errors='coerce')

    # Determine profit for each transaction, prioritizing 'recalculated_profit' for special cases.
    if 'recalculated_profit' in closed_df.columns:
        # Use np.where for efficiency: if 'recalculated_profit' is not NaN, use it, else calculate.
        closed_df['profit'] = closed_df['recalculated_profit'].where(
            pd.notna(closed_df['recalculated_profit']),
            closed_df['sale_value'] - closed_df['purchase_value']
        )
    else:
        closed_df['profit'] = closed_df['sale_value'] - closed_df['purchase_value']
    
    closed_df['profit'] = pd.to_numeric(closed_df['profit'], errors='coerce')
    
    closed_df['close_date'] = pd.to_datetime(closed_df['close_date'])
    closed_df['year'] = closed_df['close_date'].dt.year

    # Group by year and currency to calculate total sales and sum the pre-calculated profits.
    yearly_summary = closed_df.groupby(['year', 'currency']).agg(
        total_sale_value=('sale_value', 'sum'),
        profit=('profit', 'sum')
    ).reset_index()

    # For reporting consistency, calculate the total purchase value from the sale and profit.
    yearly_summary['total_purchase_value'] = yearly_summary['total_sale_value'] - yearly_summary['profit']
    
    yearly_summary.rename(columns={
        'year': 'Year',
        'currency': 'Currency',
        'total_sale_value': 'Total Sale Value',
        'total_purchase_value': 'Total Purchase Value',
        'profit': 'Profit'
    }, inplace=True)

    # Reorder columns for the final report
    final_columns = ['Year', 'Currency', 'Total Sale Value', 'Total Purchase Value', 'Profit']
    yearly_summary = yearly_summary.reindex(columns=final_columns)

    return yearly_summary

def check_income_limit(yearly_summary: pd.DataFrame, limit: float) -> list[int]:
    """
    Checks which years' total gross income from sales exceeds a specified limit.

    Args:
        yearly_summary (pd.DataFrame): DataFrame summarizing transaction data per year.
        limit (float): The income limit in CZK to check against.

    Returns:
        list[int]: A list of years where the total income exceeded the limit.
    """
    if yearly_summary.empty:
        return []

    yearly_summary_czk = convert_income_to_czk(yearly_summary)

    if yearly_summary_czk.empty:
        return []

    # Filter for years where the total sale value is over the statutory limit.
    exceeding_years_df = yearly_summary_czk[yearly_summary_czk['Total Sale Value'] > limit]

    return exceeding_years_df['Year'].tolist()


def _process_gross_analysis(transactions_df: pd.DataFrame):
    """
    Performs a gross analysis of all closed positions to check against income limits,
    disregarding any time tests for tax exemption.

    Args:
        transactions_df (pd.DataFrame): DataFrame containing all transaction data.
    
    Returns:
        dict: A dictionary containing the gross summary DataFrame and a list of years exceeding the income limit.
    """
    gross_yearly_summary = analyze_closed_positions(transactions_df)

    if not gross_yearly_summary.empty:
        summary_with_czk = gross_yearly_summary.copy()
        min_year = summary_with_czk['Year'].min()
        rate_map = _prepare_exchange_rate_map(min_year)
        summary_with_czk = pd.merge(summary_with_czk, rate_map, on=['Year', 'Currency'], how='left')
        summary_with_czk['Rate'] = pd.to_numeric(summary_with_czk['Rate'], errors='coerce')
        summary_with_czk['Total Sale Value (CZK)'] = (summary_with_czk['Total Sale Value'] * summary_with_czk['Rate']).round(2)
        summary_with_czk.drop(columns=['Rate'], inplace=True)
        gross_yearly_summary = summary_with_czk

    print("--- Gross Closed Positions Analysis (Before Time Test) ---")
    print(tabulate(gross_yearly_summary, headers='keys', tablefmt='psql'))

    years_exceeding_limit = []
    if not gross_yearly_summary.empty:
        years_exceeding_limit = check_income_limit(gross_yearly_summary, CZECH_CP_BRUTTO_INCOME_LIMIT)
        print(f"\nYears exceeding income limit of {CZECH_CP_BRUTTO_INCOME_LIMIT:,.0f} CZK: {years_exceeding_limit if years_exceeding_limit else 'None'}")
    
    return {
        "summary": gross_yearly_summary,
        "years_exceeding_limit": years_exceeding_limit
    }


def _process_net_analysis(transactions_df: pd.DataFrame):
    """
    Performs a net analysis of taxable closed positions after filtering out
    transactions that are exempt based on the time test.

    Args:
        transactions_df (pd.DataFrame): DataFrame containing all transaction data.

    Returns:
        dict: A dictionary containing the net summary by currency and the final summary in CZK.
    """
    # Filter out transactions that are exempt from tax due to the time test.
    taxable_transactions_df = transactions_df[transactions_df['time_test_cz'] != True].copy()
    
    net_yearly_summary = analyze_closed_positions(taxable_transactions_df)

    print("\n--- Net Taxable Closed Positions Analysis (After Time Test) ---")
    print(tabulate(net_yearly_summary, headers='keys', tablefmt='psql'))

    net_yearly_summary_czk = pd.DataFrame()
    if not net_yearly_summary.empty:
        print("\n--- Final Taxable Summary (in CZK) ---")
        net_yearly_summary_czk = convert_income_to_czk(net_yearly_summary)

        if 'Profit' in net_yearly_summary_czk.columns:
            # Calculate tax liability only on positive profits (gains).
            # Losses are clipped to zero as they don't result in a tax payment.
            net_yearly_summary_czk['Tax'] = (net_yearly_summary_czk['Profit'].clip(lower=0) * CZECH_INCOME_TAX_RATE).round(2)
            
            # Reorder columns to place 'Tax' right after 'Profit' for readability.
            profit_col_index = net_yearly_summary_czk.columns.get_loc('Profit')
            cols = net_yearly_summary_czk.columns.tolist()
            cols.insert(profit_col_index + 1, cols.pop(cols.index('Tax')))
            net_yearly_summary_czk = net_yearly_summary_czk[cols]

        print(tabulate(net_yearly_summary_czk, headers='keys', tablefmt='psql'))
    
    return {
        "summary_by_currency": net_yearly_summary,
        "summary_czk": net_yearly_summary_czk
    }


def process_capital_income(transactions_df: pd.DataFrame):
    """
    Processes capital income from closed positions for tax purposes.

    This involves a two-pass analysis:
    1. Gross analysis: Checks if total income exceeds the legal limit for reporting.
    2. Net analysis: Calculates the final tax base on taxable positions only.

    Args:
        transactions_df (pd.DataFrame): DataFrame containing all transaction data.
    
    Returns:
        dict: A dictionary containing the results of the gross and net analyses.
    """
    if transactions_df.empty:
        print("No transactions found.")
        return {}

    # --- First Pass: Gross analysis for income limit check ---
    gross_analysis_results = _process_gross_analysis(transactions_df)

    # --- Second Pass: Net analysis for taxation ---
    net_analysis_results = _process_net_analysis(transactions_df)

    return {
        "gross_analysis": gross_analysis_results,
        "net_analysis": net_analysis_results
    }


def _enrich_dividend_data(dividends_df: pd.DataFrame, ticker_map_data: dict) -> pd.DataFrame:
    """
    Enriches the raw dividend DataFrame with all necessary tax-related calculations.

    This includes adding country and treaty information, and calculating various
    tax amounts such as credit, reclaimable tax, and final Czech liability.

    Args:
        dividends_df (pd.DataFrame): The raw dividend DataFrame.
        ticker_map_data (dict): A dictionary containing ticker and country metadata.

    Returns:
        pd.DataFrame: The enriched dividend DataFrame with all calculation columns.
    """
    enriched_df = dividends_df.copy()
    
    ticker_info = ticker_map_data.get('ticker_info', {})
    country_info = ticker_map_data.get('country_info', {})

    enriched_df['country'] = enriched_df['ticker'].map(lambda t: ticker_info.get(t, {}).get('country'))
    enriched_df['treaty_rate'] = enriched_df['country'].map(lambda c: country_info.get(c, {}).get('tax_treaty', 0)) / 100

    enriched_df['gross_dividend'] = enriched_df['amount']
    if 'withholding_tax' not in enriched_df.columns:
        enriched_df['withholding_tax'] = 0
    enriched_df['withholding_tax'] = enriched_df['withholding_tax'].fillna(0)

    # Withholding tax from broker reports is often negative; convert to absolute value for calculations.
    enriched_df['withholding_tax'] = enriched_df['withholding_tax'].abs()

    # --- Tax Calculations ---
    # Max creditable tax is the amount allowed by the double-taxation treaty.
    enriched_df['max_creditable_tax'] = enriched_df['gross_dividend'] * enriched_df['treaty_rate']
    
    # The actual tax credit is the minimum of what was paid and what is allowed.
    enriched_df['tax_credit_cz'] = enriched_df[['withholding_tax', 'max_creditable_tax']].min(axis=1)
    
    # Any tax paid above the treaty rate may be reclaimable from the source country.
    enriched_df['tax_to_reclaim'] = (enriched_df['withholding_tax'] - enriched_df['tax_credit_cz']).clip(lower=0)

    # Final Czech tax is the standard liability minus the credit for foreign tax paid.
    enriched_df['czech_tax_liability'] = enriched_df['gross_dividend'] * CZECH_DIVIDEND_TAX_RATE
    enriched_df['tax_to_pay_cz'] = (enriched_df['czech_tax_liability'] - enriched_df['tax_credit_cz']).clip(lower=0)

    enriched_df['date'] = pd.to_datetime(enriched_df['date'])
    enriched_df['year'] = enriched_df['date'].dt.year
    
    return enriched_df

def _create_summary_by_country(enriched_df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates a dividend summary table grouped by country, year, and currency.

    Args:
        enriched_df (pd.DataFrame): The enriched dividend DataFrame.

    Returns:
        pd.DataFrame: A summary table of dividends and taxes by country, year, and currency.
    """
    summary = enriched_df.groupby(['year', 'country', 'currency']).agg(
        gross_dividend=('gross_dividend', 'sum'),
        withholding_tax_paid=('withholding_tax', 'sum'),
        tax_credit_cz=('tax_credit_cz', 'sum'),
        tax_to_pay_cz=('tax_to_pay_cz', 'sum'),
        tax_to_reclaim=('tax_to_reclaim', 'sum')
    ).reset_index()

    summary.rename(columns={
        'year': 'Year', 'country': 'Country', 'currency': 'Currency',
        'gross_dividend': 'Dividends', 'withholding_tax_paid': 'Withholding Tax Paid',
        'tax_credit_cz': 'Tax Credit CZ', 'tax_to_pay_cz': 'Tax to Pay in CZ',
        'tax_to_reclaim': 'Tax to Reclaim'
    }, inplace=True)
    return summary

def _create_total_summary_czk(enriched_df: pd.DataFrame) -> pd.DataFrame:
    """
    Creates the total dividend summary table by year, converted to CZK.

    Args:
        enriched_df (pd.DataFrame): The enriched dividend DataFrame.

    Returns:
        pd.DataFrame: A summary table of total dividends and taxes in CZK by year.
    """
    df_for_conversion = enriched_df[['year', 'currency', 'gross_dividend', 'tax_to_pay_cz']].copy()
    df_for_conversion.rename(columns={'year': 'Year', 'currency': 'Currency'}, inplace=True)

    summary_czk = convert_income_to_czk(df_for_conversion)

    if not summary_czk.empty:
        summary_czk.rename(columns={
            'gross_dividend': 'Total Gross Dividends (CZK)',
            'tax_to_pay_cz': 'Total Tax to Pay in CZ (CZK)'
        }, inplace=True)
        return summary_czk[['Year', 'Total Gross Dividends (CZK)', 'Total Tax to Pay in CZ (CZK)']]
    return pd.DataFrame()

def process_dividend_income(dividends_df: pd.DataFrame, ticker_map_data: dict):
    """
    Orchestrates the dividend income analysis for tax purposes.

    This function calculates tax liabilities and credits, and prints two summary tables:
    1. A detailed breakdown by country, year, and currency.
    2. A final summary of totals per year in CZK.
    
    Args:
        dividends_df (pd.DataFrame): DataFrame containing raw dividend data.
        ticker_map_data (dict): Dictionary with ticker and country metadata.
        
    Returns:
        dict: A dictionary containing the summary by country and the total summary in CZK.
    """
    if dividends_df.empty:
        print("\nNo dividends found.")
        return {}

    print("\n--- Dividend Tax Analysis ---")

    # 1. Enrich data with all necessary calculations.
    enriched_df = _enrich_dividend_data(dividends_df, ticker_map_data)

    # 2. Create and print summary by country.
    summary_by_country = _create_summary_by_country(enriched_df)
    print("\n--- Dividend Summary by Country, Year, and Currency ---")
    print(tabulate(summary_by_country, headers='keys', tablefmt='psql'))

    # 3. Create and print total summary in CZK.
    total_summary_czk = _create_total_summary_czk(enriched_df)
    if not total_summary_czk.empty:
        print("\n--- Total Dividend Summary by Year (in CZK) ---")
        print(tabulate(total_summary_czk, headers='keys', tablefmt='psql'))
        
    return {
        "summary_by_country": summary_by_country,
        "total_summary_czk": total_summary_czk
    }

def _convert_dfs_to_dict_records(data):
    """Recursively converts DataFrames in a nested structure to lists of records."""
    if isinstance(data, pd.DataFrame):
        return data.to_dict('records')
    if isinstance(data, dict):
        return {k: _convert_dfs_to_dict_records(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_convert_dfs_to_dict_records(v) for v in data]
    return data

def determine_tax_return_obligation(capital_results, dividend_results):
    """
    Determines if there is an obligation to file a tax return in the Czech Republic.

    Args:
        capital_results (dict): Results from process_capital_income().
        dividend_results (dict): Results from process_dividend_income().

    Returns:
        list: A list of dictionaries with tax obligation details for each year.
    """
    obligation_details = []

    capital_summary = capital_results.get('gross_analysis', {}).get('summary', pd.DataFrame())
    dividend_summary = dividend_results.get('total_summary_czk', pd.DataFrame())

    if capital_summary.empty and dividend_summary.empty:
        return []

    # Convert capital income to CZK
    capital_summary_czk = convert_income_to_czk(capital_summary)
    if not capital_summary_czk.empty:
        capital_summary_czk = capital_summary_czk[['Year', 'Total Sale Value']].copy()
        capital_summary_czk.rename(columns={'Total Sale Value': 'capital_income_czk'}, inplace=True)

    # Prepare dividend income
    dividend_summary_czk = pd.DataFrame()
    if not dividend_summary.empty:
        dividend_summary_czk = dividend_summary[['Year', 'Total Gross Dividends (CZK)']].copy()
        dividend_summary_czk.rename(columns={'Total Gross Dividends (CZK)': 'foreign_dividends_czk'}, inplace=True)

    # Merge capital and dividend summaries
    if not capital_summary_czk.empty and not dividend_summary_czk.empty:
        merged_summary = pd.merge(capital_summary_czk, dividend_summary_czk, on='Year', how='outer')
    elif not capital_summary_czk.empty:
        merged_summary = capital_summary_czk
    else:
        merged_summary = dividend_summary_czk

    merged_summary.fillna(0, inplace=True)
    
    if 'capital_income_czk' not in merged_summary.columns:
        merged_summary['capital_income_czk'] = 0
    if 'foreign_dividends_czk' not in merged_summary.columns:
        merged_summary['foreign_dividends_czk'] = 0

    for _, row in merged_summary.iterrows():
        year = int(row['Year'])
        capital_income = row['capital_income_czk']
        dividends = row['foreign_dividends_czk']
        
        obligation = False
        reason = "No obligation"

        if capital_income > CZECH_CP_BRUTTO_INCOME_LIMIT:
            obligation = True
            if dividends > CZECH_FOREIGN_DIVIDEND_INCOME_LIMIT:
                reason = f"Sale of securities and foreign dividends over limits"
            else:
                reason = f"Sale of securities over {CZECH_CP_BRUTTO_INCOME_LIMIT/1000:.0f}k CZK"
        elif dividends > CZECH_FOREIGN_DIVIDEND_INCOME_LIMIT:
            obligation = True
            reason = f"Foreign dividends over {CZECH_FOREIGN_DIVIDEND_INCOME_LIMIT/1000:.0f}k CZK"
        elif 0 < dividends <= CZECH_FOREIGN_DIVIDEND_INCOME_LIMIT and not obligation:
            reason = f"Foreign dividends and sale of securities below limits"

        obligation_details.append({
            "year": year,
            "foreign_dividends_czk": dividends,
            "capital_income_czk": capital_income,
            "obligation": obligation,
            "reason": reason
        })
    
    obligation_df = pd.DataFrame(obligation_details)
    print("\n--- Tax Return Obligation Analysis ---")
    print(tabulate(obligation_df, headers='keys', tablefmt='psql'))

    return obligation_details

def main():
    """
    Main entry point to run the tax analysis for both capital gains and dividends.
    """
    try:
        transactions_df = load_nested_yaml_to_dataframe(TRANSACTIONS_OUTPUT_FILE, 'transactions')
        dividends_df = load_nested_yaml_to_dataframe(DIVIDEND_OUTPUT_FILE, 'dividends')
        ticker_map_data = load_yaml(TICKER_MAP_FILE)

    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return

    # --- Analysis of Closed Positions ---
    capital_income_results = process_capital_income(transactions_df)

    # --- Dividend Tax Analysis ---
    dividend_income_results = process_dividend_income(dividends_df, ticker_map_data)

    # --- Determine Tax Return Obligation ---
    tax_obligation_results = determine_tax_return_obligation(capital_income_results, dividend_income_results)

    output_data = {
        "capital_income_analysis": capital_income_results,
        "dividend_income_analysis": dividend_income_results,
        "tax_return_obligation": tax_obligation_results,
        "last_updated": datetime.now().isoformat()
    }

    # Convert all DataFrames in the nested dictionary to a serializable format
    output_data_serializable = _convert_dfs_to_dict_records(output_data)

    # Ensure the output directory exists
    output_dir = os.path.dirname(TAX_ANALYSIS_OUTPUT)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Write to JSON
    with open(TAX_ANALYSIS_OUTPUT, 'w') as f:
        json.dump(output_data_serializable, f, indent=4)

    print(f"\nTax analysis results saved to {TAX_ANALYSIS_OUTPUT}")


if __name__ == '__main__':
    main()