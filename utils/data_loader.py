import yaml
import pandas as pd
import json
import ast
from config import (
    TRANSACTIONS_OUTPUT_FILE, 
    DIVIDEND_OUTPUT_FILE, 
    TICKER_MAP_FILE, 
    CASH_OPERATIONS_OUTPUT_FILE,
    MARKET_DATA_OUTPUT,
    CASH_FLOW_CATEGORIZATION_FILE
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

def load_all_data():
    """
    Load all necessary data files with error handling.
    """
    try:
        transactions_df = load_nested_yaml_to_dataframe(TRANSACTIONS_OUTPUT_FILE, 'transactions')
        # Define numeric columns that should be numeric
        numeric_columns = ['shares', 'open_price', 'close_price', 'purchase_value', 'sale_value', 'gross_pl_amount', 'gross_pl_percent']
        transactions_df = convert_df_columns_to_numeric(transactions_df, numeric_columns)
        dividends_data = load_yaml(DIVIDEND_OUTPUT_FILE)
        ticker_map_data = load_yaml(TICKER_MAP_FILE)
        cash_operations_data = load_yaml(CASH_OPERATIONS_OUTPUT_FILE)
        print("All source data loaded successfully.")
        return transactions_df, dividends_data, ticker_map_data, cash_operations_data
    except (FileNotFoundError, ValueError) as e:
        print(f"Error loading source data: {e}")
        return None, None, None, None

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
        # Heuristic: if a list contains dicts with 'Date' and 'Rate', assume it's a currency DataFrame
        if data and all(isinstance(i, dict) for i in data) and 'Date' in data[0] and 'Rate' in data[0]:
            return pd.DataFrame(data)
        return [rehydrate_data(item) for item in data]
    return data

def load_market_data():

    """

    Load pre-fetched market data from JSON file, converting rate data back to DataFrames.

    """

    try:

        with open(MARKET_DATA_OUTPUT, 'r') as f:

            market_data = json.load(f)

        print("Market data loaded successfully.")



        # Recursively rehydrate the entire data structure

        rehydrated_data = rehydrate_data(market_data)



        return rehydrated_data.get('current_prices', {}), rehydrated_data.get('exchange_rate_cache', {})

    except FileNotFoundError:

        print(f"Error: Market data file not found at {MARKET_DATA_OUTPUT}.")

        print("Please run the 'Update Market Data' option from the main menu first.")

        return None, None

    except json.JSONDecodeError:

        print(f"Error: Could not decode JSON from {MARKET_DATA_OUTPUT}.")

        return None, None



def load_analysis_output():

    """

    Load the analysis output from the JSON file.

    """

    from config import STOCK_ANALYSIS_OUTPUT

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