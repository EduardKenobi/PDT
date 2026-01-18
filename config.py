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
CASH_FLOW_CATEGORIZATION_FILE = os.path.join(DATA_DIR, 'cash_flow_categorization.yaml')

# Used by app/stock_analyzer.py
STOCK_ANALYSIS_OUTPUT = os.path.join(DATA_DIR, 'stock_analysis_output.json')
TAX_ANALYSIS_OUTPUT = os.path.join(DATA_DIR, 'tax_analysis_output.json')

# Used by update_market_data.py and app/stock_analyzer.py
MARKET_DATA_OUTPUT = os.path.join(DATA_DIR, 'market_data.json')


# --- Ticker Conversion (XTB) ---
XTB_TICKER_CACHE_PATH = os.path.join(DATA_DIR, 'xtb_ticker_cache.json')
XTB_MARKET_MAP = {
    'US': '',    # US stocks often have no suffix
    'DE': '.DE', # Germany (XETRA)
    'UK': '.L',  # London Stock Exchange
    'FR': '.PA', # Paris
    'NL': '.AS', # Amsterdam
    'DK': '.CO', # Copenhagen
    'SE': '.ST', # Stockholm
    'ES': '.MC', # Madrid
    'PT': '.LS', # Lisbon
    'CH': '.SW', # Swiss Exchange
    'IT': '.MI', # Milan
    'BE': '.BR', # Brussels
    'FI': '.HE', # Helsinki
    'NO': '.OL', # Oslo
    'CZ': '.PR', # Prague
    'PL': '.WA', # Warsaw
}
XTB_SPECIAL_TICKER_MAP = {
    'GOLD': 'GC=F',
    'EU50': '^STOXX50E',
}