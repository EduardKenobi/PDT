from ._load_market_data import load_market_data
from ._load_analysis_data import load_analysis_data

class Config:
    """
    Config class that loads and holds data from external sources.
    This serves as the data container for the Project.
    """
    def __init__(self, proj=None):
        self.proj = proj
        # Load data from different sources using standalone functions
        self.market_data = load_market_data()
        self.analysis_data = load_analysis_data()
        
        # 1. Consolidate Tickers from both sources
        self.tickers = self._consolidate_tickers()
        
        # 2. Easily accessible attributes for other data
        self.exchange_rates = self.market_data.get('exchange_rate_cache', {})
        self.portfolio_summary = self.analysis_data.get('portfolio_summary', {})
        self.portfolio_history = self.analysis_data.get('portfolio_history', [])

    def _consolidate_tickers(self):
        """
        Merges ticker data from market_data and analysis_data.
        Analysis data takes precedence for shared keys, or they are merged.
        """
        market_tickers = self.market_data.get('tickers', {})
        analysis_tickers = self.analysis_data.get('tickers', {})
        
        # Start with all tickers found in market data
        consolidated = {ticker: data.copy() for ticker, data in market_tickers.items()}
        
        # Update or add with analysis data
        for ticker, data in analysis_tickers.items():
            if ticker in consolidated:
                # Merge dictionaries if ticker exists in both
                consolidated[ticker].update(data)
            else:
                # Add new ticker from analysis data
                consolidated[ticker] = data.copy()
                
        return consolidated

    def get_ticker_data(self, ticker):
        """Helper method to get analysis data for a specific ticker."""
        return self.tickers.get(ticker, {})

    def get_exchange_rate(self, from_currency, to_currency):
        """Helper method to get exchange rate from cache."""
        key = f"{from_currency}_{to_currency}"
        return self.exchange_rates.get(key, None)
