import os

# --- Base Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')

# --- App-specific Configurations ---
PRIMARY_CURRENCY = 'EUR'
EXIT_CODE_RETURN_TO_MENU = 10
CHOICE_EXIT = 'Exit'
CHOICE_STOCK_SUMMARY = 'Stock Summary'
CHOICE_PORTFOLIO_SUMMARY = 'Portfolio Summary'
CHOICE_RUN_PARSER = 'Run Parser'
CHOICE_RUN_UPDATER = 'Run Updater'
CHOICE_RUN_ANALYZER = 'Run Analyzer'
CHOICE_RUN_REPORTER = 'Run Reporter'
CHOICE_RUN_TAXER = 'Run Taxer'


# --- Input Files ---
EUR_ACCOUNT_FILE = os.path.join(DATA_DIR, 'account_1931741.xlsx')
USD_ACCOUNT_FILE = os.path.join(DATA_DIR, 'account_50557805.xlsx')
ACCOUNTS = [EUR_ACCOUNT_FILE, USD_ACCOUNT_FILE]
TICKER_MAP_FILE = os.path.join(DATA_DIR, 'ticker_map.yaml')

# --- Output File Paths ---
# Used by parser
TRANSACTIONS_OUTPUT_FILE = os.path.join(DATA_DIR, 'transactions_excel.yaml')
DIVIDEND_OUTPUT_FILE = os.path.join(DATA_DIR, 'dividends.yaml')
CASH_OPERATIONS_OUTPUT_FILE = os.path.join(DATA_DIR, 'cash_operations.yaml')

# Used by app/stock_analyzer.py
STOCK_ANALYSIS_OUTPUT = os.path.join(DATA_DIR, 'stock_analysis_output.json')
TAX_ANALYSIS_OUTPUT = os.path.join(DATA_DIR, 'tax_analysis_output.json')

# Used by update_market_data.py and app/stock_analyzer.py
MARKET_DATA_OUTPUT = os.path.join(DATA_DIR, 'market_data.json')