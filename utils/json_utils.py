import pandas as pd
from dataclasses import asdict, is_dataclass
from datetime import datetime

def clean_for_json(data):
    """
    Recursively clean data for JSON serialization.
    Handles Dataclasses, DataFrames, Infinity, NaN, Dates/Timestamps, 
    and stringifies dict keys.
    """
    if is_dataclass(data):
        data = asdict(data)
    
    if isinstance(data, pd.DataFrame):
        return data.reset_index().to_dict('records')
        
    if isinstance(data, dict):
        # Convert all keys to strings (handles tuple keys from groupby results)
        return {str(k): clean_for_json(v) for k, v in data.items()}
        
    if isinstance(data, (list, tuple)):
        return [clean_for_json(v) for v in data]
        
    if isinstance(data, (datetime, pd.Timestamp)):
        return data.isoformat()
        
    # Handle Numeric edge cases
    if isinstance(data, float):
        if data == float('inf') or data == float('-inf'):
            return str(data)
        if pd.isna(data):
            return None
            
    return data

def default_serialize(o):
    """
    Default serializer for json.dump to handle types not handled by clean_for_json
    or as a fallback.
    """
    if isinstance(o, (datetime, pd.Timestamp)):
        return o.isoformat()
    return str(o)
