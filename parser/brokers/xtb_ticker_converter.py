import yfinance as yf
import re
import json
import os

from config import XTB_TICKER_CACHE_PATH, XTB_MARKET_MAP, XTB_SPECIAL_TICKER_MAP

_ticker_cache = None

def get_ticker_cache():
    """Returns the ticker cache, loading it from disk on first call."""
    global _ticker_cache
    if _ticker_cache is None:
        _ticker_cache = load_ticker_cache()
    return _ticker_cache

def load_ticker_cache():
    """Loads the ticker cache from a JSON file."""
    if os.path.exists(XTB_TICKER_CACHE_PATH):
        with open(XTB_TICKER_CACHE_PATH, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {XTB_TICKER_CACHE_PATH}. Starting with an empty cache.")
                return {}
    return {}

def save_ticker_cache(cache):
    """Saves the ticker cache to a JSON file."""
    os.makedirs(os.path.dirname(XTB_TICKER_CACHE_PATH), exist_ok=True)
    with open(XTB_TICKER_CACHE_PATH, 'w') as f:
        json.dump(cache, f, indent=4)
    print(f"Ticker cache successfully saved to {XTB_TICKER_CACHE_PATH}")

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

def find_yahoo_ticker(xtb_ticker, cache):
    """
    Finds a corresponding Yahoo Finance ticker for a given XTB ticker.
    It uses heuristics, verifies with yfinance, and maintains a cache.
    """
    # 1. Check cache
    if xtb_ticker in cache:
        return cache[xtb_ticker]

    # Initialize best_unverified_candidate
    best_unverified_candidate = None

    # 2. Check for special, non-stock tickers
    if xtb_ticker in XTB_SPECIAL_TICKER_MAP:
        yahoo_ticker = XTB_SPECIAL_TICKER_MAP[xtb_ticker]
        print(f"Info: Found special mapping for '{xtb_ticker}' -> '{yahoo_ticker}'")
        if _verify_ticker(yahoo_ticker):
            cache[xtb_ticker] = yahoo_ticker
            return yahoo_ticker
        else:
            # This would indicate the special map is wrong
            print(f"Warning: Special mapping for '{xtb_ticker}' to '{yahoo_ticker}' failed verification.")
            # If special map is wrong, we still want to try other heuristics
            best_unverified_candidate = yahoo_ticker # Still a guess, but from special map

    # 3. Try the stock heuristic (BASE.MARKET)
    match = re.match(r'^(?P<base>.+?)\.(?P<market>[A-Z]{2,})$', xtb_ticker)
    if match:
        parts = match.groupdict()
        base_ticker = parts['base']
        market_code = parts['market']

        if market_code not in XTB_MARKET_MAP:
            print(f"Warning: Unknown market code '{market_code}' for XTB ticker '{xtb_ticker}'. Please update XTB_MARKET_MAP in config.py with this new market.")
        else:
            # Heuristic 2: Construct candidate tickers
            yahoo_suffix = XTB_MARKET_MAP[market_code]
            primary_candidate = f"{base_ticker}{yahoo_suffix}"
            best_unverified_candidate = primary_candidate # Update with the best guess from stock heuristic

            candidates = [primary_candidate]

            # Add secondary heuristic for hyphenation if applicable
            if len(base_ticker) > 1 and base_ticker[-1].isalpha() and base_ticker[-1].isupper():
                secondary_base_ticker = f"{base_ticker[:-1]}-{base_ticker[-1]}"
                secondary_candidate = f"{secondary_base_ticker}{yahoo_suffix}"
                candidates.append(secondary_candidate)

            # Heuristic 3: Verify candidates
            for candidate in candidates:
                print(f"Verifying candidate '{candidate}' for XTB ticker '{xtb_ticker}'...")
                if _verify_ticker(candidate):
                    print(f"Success: Mapped '{xtb_ticker}' -> '{candidate}'")
                    cache[xtb_ticker] = candidate  # Update cache
                    return candidate

    # 4. If all heuristics fail
    print(f"Warning: Could not find a valid Yahoo Finance ticker for '{xtb_ticker}'.")
    if best_unverified_candidate:
        print(f"Info: Returning best unverified Yahoo format guess: '{best_unverified_candidate}'.")
        cache[xtb_ticker] = best_unverified_candidate
        return best_unverified_candidate
    else:
        print(f"Warning: Returning original XTB ticker: '{xtb_ticker}'. Please verify manually.")
        cache[xtb_ticker] = xtb_ticker
        return xtb_ticker
