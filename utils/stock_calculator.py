import pandas as pd

def sum_shares(positions_df: pd.DataFrame) -> float:
    """Sums the 'shares' column of a given DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing position data with a 'shares' column.

    Returns:
        float: The total sum of shares, or 0.0 if the DataFrame is empty.
    """
    if positions_df.empty:
        return 0.0
    return positions_df['shares'].sum()

def calculate_cost_per_currency(positions_df: pd.DataFrame) -> dict:
    """
    Calculates the total purchase value for each currency in a DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing position data
                                      with 'currency' and 'purchase_value' columns.

    Returns:
        dict: A dictionary where keys are currencies and values are the total cost for that currency.
    """
    if positions_df.empty:
        return {}

    # Group by currency and sum the purchase_value
    cost_per_currency = positions_df.groupby('currency')['purchase_value'].sum()
    
    # Convert the result to a dictionary
    return cost_per_currency.to_dict()


def calculate_unrealized_gain(total_cost: float, current_shares: float, current_price: float) -> tuple:
    """
    Calculates the unrealized gain and loss for a position.

    Args:
        total_cost (float): The total cost of the position.
        current_shares (float): The number of shares held.
        current_price (float): The current market price per share.

    Returns:
        tuple: A tuple containing the unrealized gain amount and percentage.
               Returns (0.0, 0.0) if inputs are invalid.
    """
    if total_cost <= 0 or current_shares <= 0 or current_price <= 0:
        return 0.0, 0.0

    market_value = current_shares * current_price
    unrealized_gain_amount = market_value - total_cost
    unrealized_gain_perc = unrealized_gain_amount / total_cost

    return unrealized_gain_amount, unrealized_gain_perc

def sum_realized_gains_per_currency(positions_df: pd.DataFrame) -> dict:
    """
    Calculates the total realized gain for each currency in a DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing closed position data
                                      with 'currency' and 'gross_pl_amount' columns.

    Returns:
        dict: A dictionary where keys are currencies and values are the total realized gain for that currency.
    """
    if positions_df.empty:
        return {}

    # Group by currency and sum the gross_pl_amount
    gains_per_currency = positions_df.groupby('currency')['gross_pl_amount'].sum()
    
    # Convert the result to a dictionary
    return gains_per_currency.to_dict()

import pandas as pd

def sum_shares(positions_df: pd.DataFrame) -> float:
    """Sums the 'shares' column of a given DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing position data with a 'shares' column.

    Returns:
        float: The total sum of shares, or 0.0 if the DataFrame is empty.
    """
    if positions_df.empty:
        return 0.0
    return positions_df['shares'].sum()

def calculate_cost_per_currency(positions_df: pd.DataFrame) -> dict:
    """
    Calculates the total purchase value for each currency in a DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing position data
                                      with 'currency' and 'purchase_value' columns.

    Returns:
        dict: A dictionary where keys are currencies and values are the total cost for that currency.
    """
    if positions_df.empty:
        return {}

    # Group by currency and sum the purchase_value
    cost_per_currency = positions_df.groupby('currency')['purchase_value'].sum()
    
    # Convert the result to a dictionary
    return cost_per_currency.to_dict()


def calculate_unrealized_gain(total_cost: float, current_shares: float, current_price: float) -> tuple:
    """
    Calculates the unrealized gain and loss for a position.

    Args:
        total_cost (float): The total cost of the position.
        current_shares (float): The number of shares held.
        current_price (float): The current market price per share.

    Returns:
        tuple: A tuple containing the unrealized gain amount and percentage.
               Returns (0.0, 0.0) if inputs are invalid.
    """
    if total_cost <= 0 or current_shares <= 0 or current_price <= 0:
        return 0.0, 0.0

    market_value = current_shares * current_price
    unrealized_gain_amount = market_value - total_cost
    unrealized_gain_perc = unrealized_gain_amount / total_cost

    return unrealized_gain_amount, unrealized_gain_perc

def sum_realized_gains_per_currency(positions_df: pd.DataFrame) -> dict:
    """
    Calculates the total realized gain for each currency in a DataFrame.

    Args:
        positions_df (pd.DataFrame): A DataFrame containing closed position data
                                      with 'currency' and 'gross_pl_amount' columns.

    Returns:
        dict: A dictionary where keys are currencies and values are the total realized gain for that currency.
    """
    if positions_df.empty:
        return {}

    # Group by currency and sum the gross_pl_amount
    gains_per_currency = positions_df.groupby('currency')['gross_pl_amount'].sum()
    
    # Convert the result to a dictionary
    return gains_per_currency.to_dict()

# def calculate_realized_gain(total_cost: float, total_gross_profit: float) -> tuple:
