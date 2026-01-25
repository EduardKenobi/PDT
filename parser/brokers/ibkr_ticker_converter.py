import yfinance as yf
import re
import json
import os

from config import IBKR_TICKER_CACHE_PATH, IBKR_EXCHANGE_MAP, IBKR_SPECIAL_TICKER_MAP

_ticker_cache = None

def get_ticker_cache():
    """Returns the ticker cache, loading it from disk on first call."""
    global _ticker_cache
    if _ticker_cache is None:
        _ticker_cache = load_ticker_cache()
    return _ticker_cache

def load_ticker_cache():
    """Loads the ticker cache from a JSON file."""
    if os.path.exists(IBKR_TICKER_CACHE_PATH):
        with open(IBKR_TICKER_CACHE_PATH, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {IBKR_TICKER_CACHE_PATH}. Starting with an empty cache.")
                return {}
    return {}

def save_ticker_cache(cache):
    """Saves the ticker cache to a JSON file."""
    os.makedirs(os.path.dirname(IBKR_TICKER_CACHE_PATH), exist_ok=True)
    with open(IBKR_TICKER_CACHE_PATH, 'w') as f:
        json.dump(cache, f, indent=4)
    print(f"Ticker cache successfully saved to {IBKR_TICKER_CACHE_PATH}")

def _verify_ticker(yahoo_ticker):
    """Verifies if a ticker exists on Yahoo Finance."""
    try:
        ticker_data = yf.Ticker(yahoo_ticker)
        # .history is a faster way to check for existence than .info
        if not ticker_data.history(period="1d").empty:
            return True
        return False
    except Exception:
        return False

def find_yahoo_ticker(ibkr_ticker, instrument_info_map, cache):
    """
    Finds a corresponding Yahoo Finance ticker for a given IBKR ticker.
    It uses heuristics, verifies with yfinance, and maintains a cache.
    """
    # 1. Check cache
    if ibkr_ticker in cache:
        return cache[ibkr_ticker]

    # Initialize best_unverified_candidate
    best_unverified_candidate = None

    # 2. Check for special, non-stock tickers
    if ibkr_ticker in IBKR_SPECIAL_TICKER_MAP:
        yahoo_ticker = IBKR_SPECIAL_TICKER_MAP[ibkr_ticker]
        print(f"Info: Found special mapping for '{ibkr_ticker}' -> '{yahoo_ticker}'")
        if _verify_ticker(yahoo_ticker):
            cache[ibkr_ticker] = yahoo_ticker
            return yahoo_ticker
        else:
            # This would indicate the special map is wrong
            print(f"Warning: Special mapping for '{ibkr_ticker}' to '{yahoo_ticker}' failed verification.")
            best_unverified_candidate = yahoo_ticker

    # 3. Try the stock heuristic
    exchange = instrument_info_map.get(ibkr_ticker)
    if exchange:
        suffix = IBKR_EXCHANGE_MAP.get(exchange)
        if suffix is not None:
            candidate = f"{ibkr_ticker}{suffix}"
            best_unverified_candidate = candidate
            print(f"Verifying candidate '{candidate}' for IBKR ticker '{ibkr_ticker}'...")
            if _verify_ticker(candidate):
                print(f"Success: Mapped '{ibkr_ticker}' -> '{candidate}'")
                cache[ibkr_ticker] = candidate  # Update cache
                return candidate

    # 4. If all heuristics fail
    print(f"Warning: Could not find a valid Yahoo Finance ticker for '{ibkr_ticker}'.")
    if best_unverified_candidate:
        print(f"Info: Returning best unverified Yahoo format guess: '{best_unverified_candidate}'.")
        cache[ibkr_ticker] = best_unverified_candidate
        return best_unverified_candidate
    else:
        print(f"Warning: Returning original IBKR ticker: '{ibkr_ticker}'. Please verify manually.")
        cache[ibkr_ticker] = ibkr_ticker
        return ibkr_ticker
