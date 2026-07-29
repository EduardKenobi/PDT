import pandas as pd
import openpyxl
from .xtb_ticker_converter import find_yahoo_ticker, get_ticker_cache
from .xtb_config import (
    OPND_POSITION_SHEET,
    OUT_OF_RANGE,
    FULL_YEAR,
    THREE_YEARS
)

def parse_excel(input_path, sheet_name):
    """
    Reads an Excel file and returns a DataFrame for the specified sheet.

    Args:
        input_path (str): Path to the Excel file.
        sheet_name (str): Name of the sheet to read.
    Returns:
        pd.DataFrame: DataFrame containing the data from the specified sheet.
    Raises:
        FileNotFoundError: If the input file does not exist.
        ValueError: If the specified sheet does not exist in the Excel file or another parsing error occurs.
    """
    try:
        # Use openpyxl to find the true number of rows
        workbook = openpyxl.load_workbook(input_path, read_only=True)
        if sheet_name not in workbook.sheetnames:
            workbook.close()
            raise ValueError(f"Sheet '{sheet_name}' not found in the Excel file.")
        
        sheet = workbook[sheet_name]
        max_row = sheet.max_row
        workbook.close()

        # Now, use pandas to read the exact number of rows
        # In new XTB reports, max_row can return 1 due to dimension issues in openpyxl read-only mode.
        # If max_row is None or <= 1, we read the entire sheet without nrows constraint.
        if max_row is not None and max_row > 1:
            df = pd.read_excel(input_path, sheet_name=sheet_name, header=None, nrows=max_row)
        else:
            df = pd.read_excel(input_path, sheet_name=sheet_name, header=None)
        return df

    except FileNotFoundError:
        # Re-raise to be handled by the caller
        raise
    except Exception as e:
        # Catch other potential pandas errors
        raise ValueError(f"Failed to parse Excel file: {e}") from e
    

def convert_ticker(ticker):
    """
    Converts an XTB ticker to a Yahoo Finance ticker using an automatic
    finder with a caching mechanism.
    Args:
        ticker (str): The XTB ticker symbol to convert (e.g., 'TSLA.US').
    Returns:
        str: The converted Yahoo Finance ticker symbol.
    """
    # Use the automatic finder which handles its own lazy-loading cache.
    return find_yahoo_ticker(ticker, get_ticker_cache())
    

def get_currency(df, row_index, col_index):
    """
    Extracts the currency from cell L7 of the DataFrame.
    Args:
        df (pd.DataFrame): DataFrame containing the Excel data.
    Returns:
        str: The currency found in cell L7, or 'N/A' if not found
    Raises:
        IndexError: If the DataFrame does not have enough rows or columns to access cell L
    """
    try:
        # Currency is expected to be in given row and column indices
        currency = df.iloc[row_index, col_index]
        if pd.isna(currency):
            print("Warning: Currency cell L7 is empty or not found. Please check the Excel file.")
            currency = None # Fallback currency
        return currency
    except IndexError:
        print("Error: Could not read currency from cell L7. The sheet structure may be incorrect.")
        return None
    
    
def find_header_row(df, first_col_name='Position', second_col_name='Symbol', third_col_name='Open time'):
    """
    Finds the header row in the DataFrame by looking for specific column names.
    Args:
        df (pd.DataFrame): DataFrame containing the Excel data.
    Returns:
        int: The index of the header row, or -1 if not found.
    """
    for i, row in df.iterrows():

        # Identify header row by checking for key column names
        if first_col_name in row.values and second_col_name in row.values and third_col_name in row.values:
            return i
        
    return OUT_OF_RANGE # Return -1 if no header row is found


def calculate_time_test(open_date, close_date):
    """
    Calculates the time test for capital gains based on the holding period.
    Args:
        open_date (pd.Timestamp): The date when the position was opened.
        close_date (pd.Timestamp): The date when the position was closed.
    Returns:
        tuple: A tuple containing two boolean values:
            - time_test_cz: True if the position was held for more than 3 years
            - time_test_sk: True if the position was held for more than 1 year
    """
    time_test_cz = False
    time_test_sk = False
    days_held = 0

    # Calculate the number of days held
    days_held = (close_date - open_date).days

    # Ensure that the position was held for a positive number of days
    if days_held >= 0:
        # Determine if the position meets the time test criteria
        if days_held >= FULL_YEAR:
            time_test_sk = True
            if days_held >= THREE_YEARS:
                time_test_cz = True
    else:
        print(f"Warning: Position held for {days_held} days, which is not valid. Open date: {open_date}, Close date: {close_date}")

    return time_test_cz, time_test_sk
    

def handle_possible_split(ticker, position, purchase_value, sale_value, gross_pl_amount, shares):
    """
    Checks for a possible stock split or data issue and adjusts purchase value if necessary.
    Args:
        ticker (str): Ticker symbol of the stock.
        position (str): Position identifier.
        purchase_value (float): Purchase value of the stock.
        sale_value (float): Sale value of the stock.
        gross_pl_amount (float): Gross profit/loss amount.
        shares (int): Number of shares involved in the transaction.
    Returns:
        float: Adjusted purchase value if a split is detected, otherwise the original purchase value.
    """
    # Check if any of the values are None or NaN
    if purchase_value is not None and sale_value is not None and gross_pl_amount is not None:
        calculated_pl = sale_value - purchase_value # Calculate the profit/loss from sale and purchase values

        # Check if the calculated profit/loss deviates significantly from the gross profit/loss amount
        if abs(calculated_pl - gross_pl_amount) > max(1, abs(gross_pl_amount) * 0.01):
            print(f"Warning: Possible split or data issue for {ticker} on position {position}. "
                  f"Gross P/L ({gross_pl_amount}) != Sale - Purchase ({calculated_pl})")
            return round(purchase_value / shares if shares else None, 2) # Adjust purchase value based on shares if a split is detected
    
    return purchase_value


def find_open_position_sheet(input_path):
    """
    Finds the 'OPEN POSITION' sheet by looking for a sheet name with the correct prefix.
    Args:
        input_path (str): Path to the Excel file.
    Returns:
        str: The name of the sheet, or None if not found.
    """
    try:
        xls = pd.ExcelFile(input_path)
        for sheet_name in xls.sheet_names:
            if sheet_name.startswith(OPND_POSITION_SHEET):
                return sheet_name
        return None
    except FileNotFoundError:
        return None


def merge_data(base_data, new_data, attribute='transactions'):
    """
    Merges two data dictionaries.
    Args:
        base_data (dict): The base data dictionary to merge into.
        new_data (dict): The new data dictionary to merge.
    Returns:
        dict: The merged data dictionary.
    """
    for ticker, data in new_data['companies'].items():
        if ticker in base_data['companies']:
            base_data['companies'][ticker][attribute].extend(data[attribute])
        else:
            base_data['companies'][ticker] = data
    
    return base_data
