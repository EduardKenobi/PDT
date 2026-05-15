import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

def get_batch_stock_data(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetches market data for multiple tickers in batch.
    Includes current price and basic info.
    """
    if not tickers:
        return {}
    
    results = {}
    # Use Tickers object for consolidated access
    # Note: price fetching is often faster via download for bulk
    # but info requires Ticker objects.
    
    print(f"DEBUG: Batch fetching prices for {len(tickers)} tickers...")
    try:
        # Download latest 1d data to get exact last prices reliably
        data = yf.download(tickers, period="1d", interval="1m", progress=False, group_by='ticker')
        
        for symbol in tickers:
            symbol_data = {"price": None}
            try:
                if len(tickers) > 1:
                    ticker_df = data[symbol]
                else:
                    ticker_df = data
                
                if not ticker_df.empty:
                    # Get last Close price
                    symbol_data["price"] = float(ticker_df['Close'].iloc[-1])
            except Exception as e:
                print(f"Warning: Could not get price for {symbol}: {e}")
            
            results[symbol] = symbol_data
            
    except Exception as e:
        print(f"Error in batch price download: {e}")
        # Fallback to empty prices
        for s in tickers: results[s] = {"price": None}

    return results

def get_ticker_info_batch(tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetches static info (name, sector, currency, forward dividend) for tickers.
    Warning: .info is slow in yfinance as it makes a web request per ticker.
    """
    info_results = {}
    if not tickers:
        return info_results

    print(f"DEBUG: Fetching detailed info for {len(tickers)} tickers (this may take a while)...")
    ticker_objs = yf.Tickers(" ".join(tickers))
    
    for symbol in tickers:
        try:
            t = ticker_objs.tickers[symbol]
            info = t.info
            info_results[symbol] = {
                "name": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "currency": info.get("currency"),
                "forward_dividend": info.get("dividendRate") or info.get("forwardAnnualDividendRate") or 0.0,
                "peg_ratio": info.get("pegRatio") or info.get("trailingPegRatio") or info.get("trailingPeg")
            }
        except Exception as e:
            print(f"Warning: Could not fetch info for {symbol}: {e}")
            info_results[symbol] = {}
            
    return info_results

def get_batch_historical_rates(from_currency: str, to_currency: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Fetches historical exchange rates.
    """
    if from_currency == to_currency:
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        return pd.DataFrame({'Close': 1.0}, index=dates)

    ticker_symbol = f"{from_currency}{to_currency}=X"
    try:
        data = yf.download(ticker_symbol, start=start_date, end=end_date, progress=False, auto_adjust=True)
        return data
    except Exception as e:
        print(f"Error fetching rates for {ticker_symbol}: {e}")
        return pd.DataFrame()

def get_ticker_financials_batch(tickers: List[str]) -> Dict[str, pd.DataFrame]:
    """
    Fetches financials (income statement) for tickers.
    Warning: .financials is slow in yfinance.
    """
    financials_results = {}
    if not tickers:
        return financials_results

    print(f"DEBUG: Fetching financials for {len(tickers)} tickers (this may take a while)...")
    ticker_objs = yf.Tickers(" ".join(tickers))
    
    for symbol in tickers:
        try:
            t = ticker_objs.tickers[symbol]
            financials_results[symbol] = t.financials
        except Exception as e:
            print(f"Warning: Could not fetch financials for {symbol}: {e}")
            financials_results[symbol] = pd.DataFrame()
            
    return financials_results

def get_batch_history_data(tickers: List[str], period: str = "5y", start: str = None) -> pd.DataFrame:
    """
    Fetches historical data (Prices, Dividends, Splits) for multiple tickers in ONE call.
    Args:
        tickers: List of ticker symbols
        period: Relative period (e.g., "5y") - used if start is not provided
        start: Fixed start date (e.g., "2021-01-01") - takes precedence over period
    """
    if not tickers:
        return pd.DataFrame()
    
    try:
        if start:
            print(f"DEBUG: Batch fetching history from {start} for {len(tickers)} tickers...")
            data = yf.download(
                tickers, 
                start=start, 
                actions=True, 
                progress=False, 
                group_by='ticker',
                auto_adjust=False
            )
        else:
            print(f"DEBUG: Batch fetching {period} history for {len(tickers)} tickers...")
            data = yf.download(
                tickers, 
                period=period, 
                actions=True, 
                progress=False, 
                group_by='ticker',
                auto_adjust=False
            )
        
        # Ensure we return a format that the caller expects even if some tickers failed
        if len(tickers) == 1:
            return data
            
        return data
    except Exception as e:
        print(f"Error in batch history download: {e}")
        return pd.DataFrame()

def get_ticker_history_and_obj(ticker: str) -> Any:
    """
    Returns the yfinance Ticker object.
    """
    return yf.Ticker(ticker)

def get_ticker_history(ticker: str, period: str = "5y") -> pd.DataFrame:
    """
    Gets historical market data.
    """
    try:
        stock = yf.Ticker(ticker)
        return stock.history(period=period)
    except Exception as e:
        print(f"Error fetching history for {ticker}: {e}")
        return pd.DataFrame()
