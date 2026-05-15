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
CHOICE_PORTFOLIO_HISTORY = 'Portfolio History'
CHOICE_RUN_PARSER = 'Run Parser'
CHOICE_RUN_UPDATER = 'Run Updater'
CHOICE_RUN_ANALYZER = 'Run Analyzer'
CHOICE_RUN_REPORTER = 'Run Reporter'
CHOICE_RUN_TAXER = 'Run Taxer'


# --- Input Files ---
# XTB
EUR_ACCOUNT_FILE = os.path.join(DATA_DIR, 'account_1931741.xlsx')
USD_ACCOUNT_FILE = os.path.join(DATA_DIR, 'account_50557805.xlsx')
XTB_ACCOUNTS = [EUR_ACCOUNT_FILE, USD_ACCOUNT_FILE]

# IBKR (Please update the filename to match your CSV export)
IBKR_ACCOUNT_FILE = os.path.join(DATA_DIR, 'U23432040.csv') 
IBKR_ACCOUNTS = [IBKR_ACCOUNT_FILE]

ACCOUNTS = XTB_ACCOUNTS  # This can be changed to IBKR_ACCOUNTS to switch parsers
TICKER_MAP_FILE = os.path.join(DATA_DIR, 'ticker_map.yaml')

# --- Output File Paths ---
# Used by parser
TRANSACTIONS_OUTPUT_FILE = os.path.join(DATA_DIR, 'transactions_excel.yaml')
DIVIDEND_OUTPUT_FILE = os.path.join(DATA_DIR, 'dividends.yaml')
CASH_OPERATIONS_OUTPUT_FILE = os.path.join(DATA_DIR, 'cash_operations.yaml')
CASH_FLOW_CATEGORIZATION_FILE = os.path.join(DATA_DIR, 'cash_flow_categorization.yaml')
IBKR_CASH_BALANCE_OUTPUT_FILE = os.path.join(DATA_DIR, 'ibkr_cash_balance.yaml')
OPEN_TICKERS_FILE = os.path.join(DATA_DIR, 'open_tickers.json')

# Used by app/run_analyzer.py
STOCK_ANALYSIS_OUTPUT = os.path.join(DATA_DIR, 'stock_analysis_output.json')
TAX_ANALYSIS_OUTPUT = os.path.join(DATA_DIR, 'tax_analysis_output.json')

# Used by update_market_data.py and app/run_analyzer.py
MARKET_DATA_OUTPUT = os.path.join(DATA_DIR, 'market_data.json')

# --- Tickers to Ignore ---
TICKERS_TO_IGNORE = ['SPCE', 'SPCE.US']

# --- Ticker Conversion ---
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

IBKR_TICKER_CACHE_PATH = os.path.join(DATA_DIR, 'ibkr_ticker_cache.json')
IBKR_SPECIAL_TICKER_MAP = {}
IBKR_EXCHANGE_MAP = {
    'NASDAQ': '',
    'NYSE': '',
    'ARCA': '',
    'AMEX': '',
    'LSE': '.L',
    'AEB': '.AS', # Amsterdam
    'SFB': '.ST', # Stockholm
    # Add other exchanges as needed
    # 'FWB': '.F',  # Frankfurt
    # 'XETRA': '.DE',
    # 'TSE': '.TO', # Toronto
}

# --- Dividend Frequencies ---
DIVIDEND_FREQ_MAP = {
    'Monthly': 12,
    'Quarterly': 4,
    'Quarterly-Regulary': 4,
    'Quarterly-Unregulary': 4,
    'Quartely-Regulary': 4, # legacy typo support
    'Quartely-Unregulary': 4, # legacy typo support
    'Semi-Annually': 2,
    'Annually': 1
}

# --- Analysis Tiers ---
TIER1 = 'Tier 1'
TIER2 = 'Tier 2'
TIER3 = 'Tier 3'
TIERG = 'Tier G'
SAFETY_MARGIN = 0.10  # 10% safety margin for all tiers
INFLATION_RATE = 0.035  # Inflation rate for decision engine (3.5%)
PEG_RATIO_THRESHOLD = 1.0  # PEG ratio threshold for growth evaluation

ANALYSIS_MAP = {
    TIER1: {
        'name': 'Tier 1 - Core Holdings',
        'description': 'Your main long-term investments. These are the stocks you plan to hold for several years and are the foundation of your portfolio.',
        'criteria': 'Typically, these are well-established companies with strong fundamentals, consistent dividend payments, and a history of stable growth. They may include blue-chip stocks, dividend aristocrats, or companies in sectors you believe will perform well over the long term.',
        'PADI_target': 0.08,  # Example target PADI for Tier 1 stocks
        'market_value_target': 0.07,  # Example target market value percentage for Tier 1 stocks
    },
    TIER2: {
        'name': 'Tier 2 - Growth Holdings',
        'description': 'These are stocks that you expect to grow faster than your Tier 1 holdings but are not yet core holdings.',
        'criteria': 'Typically, these are growth stocks in emerging sectors or companies with high growth potential but may be more volatile or cyclical than Tier 1 holdings.',
        'PADI_target': 0.05,  # Example target PADI for Tier 2 stocks
        'market_value_target': 0.15,  # Example target market value percentage for Tier 2 stocks
    },
    TIER3: {
        'name': 'Tier 3 - Capped Income',
        'description': 'These are stocks that you want to include in your portfolio for diversification or potential high returns but want to limit their overall impact on your portfolio\'s income and risk profile.',
        'criteria': 'Typically, these are stocks that may have higher risk, lower dividend yields, or are in sectors you want to limit exposure to. You want to ensure that even if these stocks perform poorly or cut dividends, they won\'t significantly impact your overall portfolio income or risk.',
        'PADI_target': 0.04,  # Example target PADI for Tier 3 stocks
        'market_value_target': 0.03,  # Example target market value percentage for Tier 3 stocks
    },
    TIERG: {
        'name': 'Tier G - Growth Only',
        'description': 'These are stocks that you want to include in your portfolio for growth potential but do not want to contribute to your portfolio\'s income.',
        'criteria': 'Typically, these are growth stocks that may have little to no dividend yield but have strong growth potential. You want to ensure that even if these stocks perform well, they won\'t significantly impact your overall portfolio income, as you are not relying on them for dividends.',
        'PADI_target': 0.00,  # Target PADI for Tier G stocks (growth only)
        'market_value_target': 0.10,  # Example target market value percentage for Tier G stocks
    }
}