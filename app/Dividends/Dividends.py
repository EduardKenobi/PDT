import pandas as pd

class Dividends:
    def __init__(self, proj):
        self.proj = proj
        self.dividend_frequency = None

    def evaluate_dividend_frequency(self, ticker) -> str:
        """
        Evaluates the dividend frequency for a given ticker.
        Looks for count of dividends payments in the previous full year and categorizes into frequency types.
        """
        ticker_data = self.proj.config.get_ticker_data(ticker)
        if not ticker_data:
            self.proj.logger.warning(f"No data found for ticker: {ticker}")
            return 'N/A'
        
        dividends = ticker_data.get('dividends', [])
        if not dividends:
            return 'N/A'
        
        # Count dividends in the last full year
        one_year_ago = pd.Timestamp.now() - pd.DateOffset(years=1)
        recent_dividends = [d for d in dividends if pd.to_datetime(d['date']) > one_year_ago]
        count = len(recent_dividends)
        
        if count == 12:
            return 'Monthly'
        elif count == 4:
            return 'Quarterly'
        elif count == 2:
            return 'Semi-Annually'
        elif count == 1:
            return 'Annually'
        else:
            self.proj.logger.warning(f"Unexpected dividend count for ticker: {ticker}, count: {count}. Unable to categorize frequency.")
            return 'N/A'
        
    def set_frequency_for_all_tickers(self):
        """Sets the dividend frequency for all tickers in the config."""
        for ticker in self.proj.config.get_tickers():
            self.dividend_frequency = self.evaluate_dividend_frequency(ticker)

    def evaluate_fw_dividend(self, ticker) -> float | None:
        """Evaluates the forward dividend for a given ticker."""
        ticker_data = self.proj.config.get_ticker_data(ticker)
        if not ticker_data:
            self.proj.logger.warning(f"No data found for ticker: {ticker}")
            return None
        
        # Example logic to calculate forward dividend
        last_dividend = ticker_data.get('last_dividend', 0)
        div_growth_rate = ticker_data.get('div_growth_rate', 0)
        
        # Simple projection for next year's dividend
        fw_dividend = last_dividend * (1 + div_growth_rate)
        
        self.proj.logger.info(f"Calculated forward dividend for {ticker}: {fw_dividend:.2f}")
        return fw_dividend