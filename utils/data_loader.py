import yaml
import pandas as pd
import json
import ast
import os
from app.history.history_helpers import _get_month_ends
from utils.exchange_rate import normalize_currency
from config import (
    TRANSACTIONS_OUTPUT_FILE, 
    DIVIDEND_OUTPUT_FILE, 
    TICKER_MAP_FILE, 
    MARKET_DATA_OUTPUT,
    CASH_FLOW_CATEGORIZATION_FILE,
    STOCK_ANALYSIS_OUTPUT,
    PRIMARY_CURRENCY,
    CASH_OPERATIONS_OUTPUT_FILE
)

def convert_df_columns_to_numeric(df, columns):
    """
    Converts specified columns of a DataFrame to numeric, coercing errors."""
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors='coerce')
    return df

def load_yaml(file_path):
    """
    Loads a YAML file and returns its content.
    Args:
        file_path (str): The path to the YAML file.
    Returns:
        dict: The content of the YAML file, or None if an error occurs.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as stream:
            return yaml.safe_load(stream)
    except FileNotFoundError:
        # This is expected on the first run, so just return None.
        return None
    except yaml.YAMLError as exc:
        print(f"Error parsing YAML file: {exc}")
        return None

def load_categorizations():
    """
    Loads cash flow categorizations from the YAML file.
    Returns a dictionary of categorizations or an empty dict if not found.
    """
    categorizations = load_yaml(CASH_FLOW_CATEGORIZATION_FILE)
    return categorizations if categorizations is not None else {}


def load_nested_yaml_to_dataframe(yaml_path: str, list_key: str) -> pd.DataFrame:
    """
    Loads and flattens data from a nested YAML file into a pandas DataFrame.
    It expects a structure like: companies -> ticker -> list_of_records.

    Args:
        yaml_path (str): The absolute path to the input YAML file.
        list_key (str): The key for the list of records (e.g., 'transactions' or 'dividends').

    Returns:
        pd.DataFrame: A flattened DataFrame with a 'ticker' column.
    """
    data = load_yaml(yaml_path)
    if data is None:
        return pd.DataFrame()

    all_records = []
    companies_data = data.get('companies', {})

    for ticker, company_info in companies_data.items():
        records = company_info.get(list_key, [])
        for record in records:
            record['ticker'] = ticker
            all_records.append(record)

    return pd.DataFrame(all_records)

def load_flat_yaml_to_dataframe(yaml_path: str, list_key: str) -> pd.DataFrame:
    """
    Loads data from a YAML file with a flat list structure into a pandas DataFrame.
    It expects a structure like: list_of_records.

    Args:
        yaml_path (str): The absolute path to the input YAML file.
        list_key (str): The key for the list of records (e.g., 'other_operations').

    Returns:
        pd.DataFrame: A DataFrame containing the records.
    """
    data = load_yaml(yaml_path)
    if data is None:
        return pd.DataFrame()

    records = data.get(list_key, [])

    return pd.DataFrame(records)

def prepare_data(transactions_df):
    """
    Prepare and filter data for analysis.
    """
    transactions_df['open_date_dt'] = pd.to_datetime(transactions_df['open_date'])
    transactions_df['close_date_dt'] = pd.to_datetime(transactions_df['close_date'])
    all_tickers = transactions_df['ticker'].unique()
    return all_tickers

def load_all_data():
    """
    Load all necessary data files with error handling and return as DataFrames.
    """
    try:
        # 1. Transactions
        transactions_df = load_nested_yaml_to_dataframe(TRANSACTIONS_OUTPUT_FILE, 'transactions')
        numeric_columns = ['shares', 'open_price', 'close_price', 'purchase_value', 'sale_value', 'gross_pl_amount', 'gross_pl_percent']
        transactions_df = convert_df_columns_to_numeric(transactions_df, numeric_columns)
        transactions_df['open_date_dt'] = pd.to_datetime(transactions_df['open_date'])
        transactions_df['close_date_dt'] = pd.to_datetime(transactions_df['close_date'])
        
        # 2. Dividends
        dividends_raw = load_yaml(DIVIDEND_OUTPUT_FILE)
        div_df = _prepare_dividend_history_df(dividends_raw)
        
        # 3. Ticker Map
        ticker_map_data = load_yaml(TICKER_MAP_FILE)
        
        # 4. Cash Operations
        cash_ops_raw = load_yaml(CASH_OPERATIONS_OUTPUT_FILE)
        other_ops_df = pd.DataFrame(cash_ops_raw.get('other_operations', []))
        if not other_ops_df.empty:
            other_ops_df['date_dt'] = pd.to_datetime(other_ops_df['date'])
            # Convert currency to standard format
            if 'currency' in other_ops_df.columns:
                other_ops_df['currency'] = other_ops_df['currency'].str.upper().replace('GBX', 'GBP').replace('GBP', 'GBP') # GBp/GBX handling
        
        all_tickers = transactions_df['ticker'].unique() if not transactions_df.empty else []
        month_ends = _get_month_ends()
        
        return transactions_df, dividends_raw, ticker_map_data, cash_ops_raw, all_tickers, month_ends, div_df, other_ops_df
    except (FileNotFoundError, ValueError, Exception) as e:
        print(f"Error loading source data: {e}")
        return None, None, None, None, None, None, None, None

def rehydrate_data(data):
    """
    Recursively rehydrates a data structure from a JSON-like format.
    - Converts stringified tuple keys back to tuples.
    - Converts lists of dicts representing DataFrames back to DataFrames.
    """
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            try:
                # Safely evaluate the key to see if it's a stringified tuple
                evaluated_key = ast.literal_eval(k)
                if isinstance(evaluated_key, tuple):
                    new_dict[evaluated_key] = rehydrate_data(v)
                else:
                    new_dict[k] = rehydrate_data(v)
            except (ValueError, SyntaxError):
                # The key is just a normal string
                new_dict[k] = rehydrate_data(v)
        return new_dict
    if isinstance(data, list):
        # Heuristic: if a list contains dicts with 'Date'/'index' and 'Close'/'Rate', assume it's a DataFrame
        if data and all(isinstance(i, dict) for i in data):
            keys = data[0].keys()
            has_date = 'Date' in keys or 'index' in keys
            has_value = any(k in keys for k in ['Rate', 'Close', 'Adj Close'])
            if has_date and has_value:
                return pd.DataFrame(data)
        return [rehydrate_data(item) for item in data]
    return data

def load_market_data() -> dict:
    """Loads and rehydrates the market data cache from JSON."""
    if not os.path.exists(MARKET_DATA_OUTPUT):
        print(f"Warning: {MARKET_DATA_OUTPUT} not found. Run 'update_market_data.py' first.")
        return {}
    
    try:
        with open(MARKET_DATA_OUTPUT, 'r') as f:
            data = json.load(f)
        return rehydrate_data(data)
    except Exception as e:
        print(f"Error loading market data: {e}")
        return {}

def load_analysis_output():
    """
    Load the analysis output from the JSON file.
    """
    try:
        with open(STOCK_ANALYSIS_OUTPUT, 'r') as f:
            analysis_data = json.load(f)
        print("Analysis data loaded successfully.")
        return analysis_data.get('portfolio_summary'), analysis_data.get('tickers')

    except FileNotFoundError:
        print(f"Error: Analysis file not found at {STOCK_ANALYSIS_OUTPUT}.")
        print("Please run the 'Run Analyzer' option from the main menu first.")
        return None, None

    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {STOCK_ANALYSIS_OUTPUT}.")
        return None, None

def load_dividends_data():

    """

    Load dividends data from the YAML file.

    """

    return load_yaml(DIVIDEND_OUTPUT_FILE)

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
                    'amount_per_share_currency': normalize_currency(div.get('amount_per_share_currency')),
                    'withholding_tax': div.get('withholding_tax', 0)
                })
    div_df = pd.DataFrame(all_dividends)
    if not div_df.empty:
        div_df['date'] = pd.to_datetime(div_df['date'])
        div_df = div_df.sort_values('date').set_index('date', drop=False)
        div_df.index.name = None
    return div_df