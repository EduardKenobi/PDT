import yaml
from config import CASH_FLOW_CATEGORIZATION_FILE

def float_representer(dumper, value):
    """
    Represent a float as a YAML float, always with a decimal point.
    Args:
        dumper: The YAML dumper.
        value (float): The float value to represent.
    Returns:
        The YAML scalar representation of the float.
    """

    text = f'{value:.10f}'.rstrip('0').rstrip('.')
    return dumper.represent_scalar('tag:yaml.org,2002:float', text)

# Add the representer to the yaml dumper
yaml.add_representer(float, float_representer)

def save_data_to_yaml(data, filepath):
    """
    Save the given data to a YAML file.
    Args:
        data (dict): The data to save.
        filepath (str): The path to the YAML file.
    """

    try:
        # Write the merged data to a YAML file
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        print(f"Successfully saved data to {filepath}")
    except IOError as e:
        print(f"Error writing data to {filepath}: {e}")

def save_categorizations(data):
    """
    Saves the cash flow categorizations to the specified YAML file.
    """
    save_data_to_yaml(data, CASH_FLOW_CATEGORIZATION_FILE)