def get_parser_functions(broker_name: str) -> dict:
    """
    Factory function to retrieve parsing functions for a given broker.

    This function acts as a registry for all broker-specific parsers.
    Based on the broker_name, it imports the correct module and returns
    a dictionary of its public parsing functions.

    Args:
        broker_name (str): The name of the broker (e.g., 'xtb').

    Returns:
        dict: A dictionary containing the parsing functions for that broker.
    
    Raises:
        ValueError: If no parser is found for the given broker_name.
    """
    if broker_name.lower() == 'xtb':
        from .brokers import xtb
        return {
            "get_transactions": xtb.get_transactions_from_excel_files,
            "get_cash_operations": xtb.get_cash_operations_from_excel_files,
        }
    # To add a new broker, add an 'elif' block here:
    # elif broker_name.lower() == 'degiro':
    #     from .brokers import degiro
    #     return {
    #         "get_transactions": degiro.get_transactions,
    #         "get_cash_operations": degiro.get_cash_operations,
    #     }
    else:
        raise ValueError(f"No parser found for broker: '{broker_name}'")
