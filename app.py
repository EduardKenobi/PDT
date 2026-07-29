from app.Project import Project

def main():
    """
    Main entry point for the Tracker project using the new OOP architecture.
    """
    # 1. Initialize the project (the 'proj' object)
    # This automatically sets up the Logger and loads all Config data.
    proj = Project()
    
    proj.logger.info("Tracker Application Started")

    # Accessing data through the centralized project object
    portfolio_value = proj.config.portfolio_summary.get('portfolio_value', 0)
    currency = proj.config.portfolio_summary.get('primary_currency', 'EUR')
    
    proj.logger.info(f"Loaded {len(proj.config.tickers)} tickers.")
    proj.logger.info(f"Total Portfolio Value: {portfolio_value:,.2f} {currency}")

    # --- Application Logic Starts Here ---
    # In the future, you will add your menu or processing logic here.
    # example: 
    # from app.interface.menu import MainMenu
    # menu = MainMenu(proj)
    # menu.show()
    
    proj.logger.info("Application session finished.")

if __name__ == "__main__":
    main()
