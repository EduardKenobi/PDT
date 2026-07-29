from ..Config import Config
from ..Logger import Logger
from ..Ticker

class Project:
    """
    Main Project class that orchestrates all data and future modules.
    This serves as the central hub (the 'proj' object).
    """
    def __init__(self):
        # 1. Initialize Logger first so other modules can use it
        self.logger = Logger(self)
        
        # 2. Initialize the Config class which loads all data
        self.config = Config(self)
        
        self.logger.info("Project initialized with Config and Logger.")

        self.ticker
        
        # In the future, you can initialize other classes here:
        # self.stock_metrics = StockMetrics(self)
        # self.portfolio_processor = PortfolioProcessor(self)
        
    def refresh_data(self):
        """Reloads data from the JSON file."""
        self.config = Config()
        self.logger.info("Project data refreshed.")
