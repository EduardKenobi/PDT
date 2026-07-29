import json
import os
from config import STOCK_ANALYSIS_OUTPUT

def load_analysis_data():
    """
    Loads data from the stock_analysis_output.json file.
    Returns a dictionary of analysis data or an empty dict if not found.
    """
    if not os.path.exists(STOCK_ANALYSIS_OUTPUT):
        print(f"Warning: {STOCK_ANALYSIS_OUTPUT} not found.")
        return {}
        
    try:
        with open(STOCK_ANALYSIS_OUTPUT, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to decode JSON from {STOCK_ANALYSIS_OUTPUT}: {e}")
        return {}
    except Exception as e:
        print(f"Error: An unexpected error occurred while loading {STOCK_ANALYSIS_OUTPUT}: {e}")
        return {}
