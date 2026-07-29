from typing import Optional
from ..Dividends.py import Dividends

class Ticker:
    """
    Represents a single stock ticker.
    Encapsulates all attributes and delegates calculations to domain-specific classes.
    """
    def __init__(self, symbol: str, proj):
        self.symbol = symbol
        self.proj = proj
        
        # Initialize domain processor
        self.dividend_processor = Dividends(proj)
        
        # Raw attributes (initially loaded from data, eventually from DB)
        self.name: Optional[str] = None
        self.sector: Optional[str] = None
        
    @property
    def dividend_frequency(self) -> str:
        """Evaluated by the Dividend logic."""
        return self.dividend_processor.evaluate_dividend_frequency(self.symbol)
        
    @property
    def forward_dividend(self) -> float:
        """Evaluated by the Dividend logic."""
        val = self.dividend_processor.evaluate_fw_dividend(self.symbol)
        return val if val is not None else 0.0
