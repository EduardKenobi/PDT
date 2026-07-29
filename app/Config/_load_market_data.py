import json
import os
from config import MARKET_DATA_OUTPUT

def load_market_data():
    """
    Loads data from the market_data.json file.
    Returns a dictionary of market data or an empty dict if not found.
    """
    if not os.path.exists(MARKET_DATA_OUTPUT):
        print(f"Warning: {MARKET_DATA_OUTPUT} not found.")
        return {}
        
    try:
        with open(MARKET_DATA_OUTPUT, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to decode JSON from {MARKET_DATA_OUTPUT}: {e}")
        return {}
    except Exception as e:
        print(f"Error: An unexpected error occurred while loading {MARKET_DATA_OUTPUT}: {e}")
        return {}
