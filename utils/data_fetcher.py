import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def get_current_prices(tickers: list) -> dict:
    """
    Fetches the current market price for a list of tickers.

    Args:
        tickers (list): A list of ticker symbols.

    Returns:
        dict: A dictionary mapping each ticker to its current price.
              If a price is not found for a ticker, it will not be included in the dictionary.
    """
    prices = {}
    for ticker_symbol in tickers:
        try:
            ticker = yf.Ticker(ticker_symbol)
            price = ticker.fast_info.get("last_price")
            if price is None:
                price = ticker.info.get("regularMarketPrice")
            
            if price:
                prices[ticker_symbol] = price
            else:
                print(f"Warning: Could not find a price for {ticker_symbol}")

        except Exception as e:
            print(f"Error fetching price for {ticker_symbol}: {e}")

    return prices

def get_batch_historical_rates(from_currency: str, to_currency: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetches a DataFrame of historical exchange rates for a given period.

    Args:
        from_currency (str): The currency to convert from.
        to_currency (str): The currency to convert to.
        start_date (str): The start date in 'YYYY-MM-DD' format.
        end_date (str): The end date in 'YYYY-MM-DD' format.

    Returns:
        pd.DataFrame: A DataFrame with the historical exchange rates, or an empty DataFrame if not found.
    """
    if from_currency == to_currency:
        # Return a DataFrame with a constant rate of 1.0 for same currency conversion
        dates = pd.to_datetime([start_date, end_date])
        date_range = pd.date_range(start=dates[0], end=dates[1], freq='D')
        return pd.DataFrame({'Close': 1.0}, index=date_range)

    ticker_symbol = f"{from_currency}{to_currency}=X"
    
    try:
        data = yf.download(
            ticker_symbol,
            start=start_date,
            end=end_date,
            progress=False,
            auto_adjust=True,
            group_by='ticker'
        )
        
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(0)
        
        if 'Close' in data.columns:
            data['Close'] = pd.to_numeric(data['Close'], errors='coerce')
            
        return data
    except Exception as e:
        print(f"Error fetching batch historical rates for {ticker_symbol}: {e}")
        return pd.DataFrame()

def get_forward_dividend_from_yfinance(ticker: str) -> float:
    """
    Gets the forward dividend rate from yfinance for a given ticker.

    Args:
        ticker (str): The ticker symbol.

    Returns:
        float: The forward dividend rate, or 0.0 if not available.
    """
    try:
        stock = yf.Ticker(ticker)
        dividend_rate = stock.info.get('dividendRate')
        if dividend_rate:
            return dividend_rate
        
        # Fallback to forwardAnnualDividendRate if dividendRate is not available
        dividend_rate = stock.info.get('forwardAnnualDividendRate')
        if dividend_rate:
            return dividend_rate
            
        return 0.0
    except Exception as e:
        print(f"Error fetching forward dividend for {ticker}: {e}")
        return 0.0

def get_ticker_history(ticker: str, period: str = "max") -> pd.DataFrame:
    """
    Gets historical market data from yfinance for a given ticker.

    Args:
        ticker (str): The ticker symbol.
        period (str): The period to fetch data for (e.g., "1y", "5y", "max").

    Returns:
        pd.DataFrame: A pandas DataFrame with historical data, or an empty DataFrame if not available.
    """
    try:
        stock = yf.Ticker(ticker)
        history = stock.history(period=period)
        return history
    except Exception as e:
        print(f"Error fetching historical data for {ticker}: {e}")
        return pd.DataFrame()

