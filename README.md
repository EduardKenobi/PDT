# Portfolio Tracker & Analyzer

## Description

This project is a comprehensive, menu-driven command-line tool for tracking and analyzing a stock portfolio. It parses transaction data from broker exports, fetches the latest market data, calculates a wide range of performance metrics, and provides detailed tax analysis.

## Features

- **Interactive Menu:** A user-friendly, interactive command-line interface for running all major functions of the application.
- **Broker Parsing:** Automatically parses transaction, dividend, and cash operation data from XTB Excel files.
- **Automatic Ticker Mapping:** Intelligently converts broker-specific ticker symbols (e.g., `TSLA.US`) to the corresponding Yahoo Finance format (e.g., `TSLA`) with a persistent cache.
- **Market Data Fetching:** Downloads and caches the latest stock prices and currency exchange rates required for analysis.
- **Portfolio Analysis:** Calculates key metrics for the entire portfolio and individual tickers, including:
  - Realized and Unrealized Profit/Loss
  - Cost Basis (Total and Per-Currency)
  - Market Value
  - Annualized Returns
- **Dividend Metrics:** In-depth dividend analysis including:
  - PADI (Projected Annual Dividend Income)
  - Dividend Yield and Yield on Cost
  - TTM, 3Y, 5Y, and 10Y Dividend Growth (CAGR)
  - 5-Year Average Dividend Yield
  - Upcoming dividend calendar.
- **Tax Analysis (Czech Republic):**
  - **Capital Gains:** Performs gross analysis for income limit checks and net analysis for the final tax base, applying the statutory time test.
  - **Dividends:** Calculates Czech tax liability on foreign dividends, accounting for double-taxation treaties and tax credits.
- **Data Output:** Generates detailed JSON files for analysis results and market data.

## Project Structure

```
/
├── app/                # Contains the main analysis logic
│   ├── stock_analyzer.py # Main portfolio analysis script
│   └── taxes/            # Tax calculation logic
├── config.py           # Main project configuration (e.g., primary currency, XTB mappings)
├── data/               # For all input and output data files (.xlsx, .json, .yaml)
├── parser/             # Scripts for parsing input files
│   └── brokers/        # Broker-specific parsers
│       └── xtb.py      # XTB broker parser and related modules
├── utils/              # Shared utility functions (e.g., data loaders, API fetchers)
├── main.py             # The main entry point for the interactive application
├── run_parser.py       # Script to run the data parser
├── run_reporter.py     # Script to generate and print console reports
├── update_market_data.py # Script to fetch latest market prices and exchange rates
└── requirements.txt    # Project dependencies
```

## Setup and Installation

1.  **Clone the repository:**
    ```sh
    git clone <repository-url>
    cd Tracker
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```sh
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    The `inquirer` library is crucial for the interactive menu.
    ```sh
    pip install -r requirements.txt
    ```

## Configuration

Before running the application, configure the following:

1.  **`config.py`**:
    -   Set the `PRIMARY_CURRENCY` for all final calculations (e.g., 'EUR', 'USD').
    -   Update the `ACCOUNTS` list to point to your broker's Excel export files located in the `data/` directory.
    -   **XTB-Specific Mappings:** If needed, review and update `XTB_MARKET_MAP` for new market codes and `XTB_SPECIAL_TICKER_MAP` for specific commodity/index tickers if the automatic mapping fails.

2.  **`app/taxes/tax_config.py`**:
    -   Review and update tax rates and income limits if they change.

## Usage

The entire application is run through a single, interactive main menu.

1.  **Start the Application:**
    From the project's root directory, run:
    ```sh
    python main.py
    ```

2.  **Follow the Menu Workflow:**
    The menu will guide you through the process. The recommended workflow is to run the steps in order:

    -   **`Run Parser`**: This processes your raw broker Excel files into a standardized format. It performs automatic ticker mapping and saves the results.
    -   **`Run Updater`**: This fetches the latest stock prices and currency exchange rates from the internet and saves them.
    -   **`Run Analyzer`**: This performs all the core calculations based on the parsed data and fresh market data.
    -   **`Run Reporter`**: This opens a sub-menu where you can view detailed reports, including a portfolio summary, a dividend calendar, and deep dives into individual stocks.
    -   **`Run Taxer`**: This generates and displays the specific tax analysis reports.

## Output

-   **Console:** The `run_reporter.py` and `app.taxes.tax` scripts display interactive menus and print formatted summary tables directly to the console.
-   **`data/stock_analysis_output.json`**: A detailed JSON file containing all raw and calculated data for your portfolio.
-   **`data/market_data.json`**: Contains the most recently fetched stock prices and currency exchange rates.
-   **`data/*.yaml`**: Intermediate YAML files generated by the parser.
-   **`data/xtb_ticker_cache.json`**: An automatically generated cache storing the mappings from XTB ticker symbols to Yahoo Finance symbols.