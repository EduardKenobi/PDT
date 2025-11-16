import inquirer
import subprocess
import sys
import os

from config import EXIT_CODE_RETURN_TO_MENU, CHOICE_EXIT, CHOICE_RUN_ANALYZER, CHOICE_RUN_PARSER, CHOICE_RUN_REPORTER, CHOICE_RUN_TAXER, CHOICE_RUN_UPDATER

def run_script(command, module=False):
    """Runs a script and returns the completed process object."""
    try:
        if module:
            return subprocess.run([sys.executable, "-m", command])
        else:
            return subprocess.run([sys.executable, command])
    except FileNotFoundError:
        print(f"Error: Script not found.")
        return None

def main():
    """Main function to display the interactive menu."""
    
    # Check if the new dependency has been installed
    try:
        import inquirer
    except ImportError:
        print("The 'inquirer' library is not installed.")
        print("Please install the project dependencies by running:")
        print("pip install -r requirements.txt")
        return

    menu_choices = {
        CHOICE_RUN_PARSER: lambda: run_script("run_parser.py"),
        CHOICE_RUN_UPDATER: lambda: run_script("update_market_data.py"),
        CHOICE_RUN_ANALYZER: lambda: run_script("app.stock_analyzer", module=True),
        CHOICE_RUN_REPORTER: lambda: run_script("run_reporter.py"),
        CHOICE_RUN_TAXER: lambda: run_script("app.taxes.tax", module=True),
        CHOICE_EXIT: lambda: print("Exiting application.")
    }

    while True:
        questions = [
            inquirer.List(
                'action',
                message="Select an action to perform",
                choices=list(menu_choices.keys()),
                carousel=True
            ),
        ]
        
        try:
            answers = inquirer.prompt(questions)
            if not answers:
                # User pressed Ctrl+C
                print("Exiting application.")
                break

            action = answers['action']
            
            # Clear console before running the action for a cleaner output
            os.system('cls' if os.name == 'nt' else 'clear')
            
            print(f"--- {action} ---")

            if action == CHOICE_EXIT:
                menu_choices[action]()
                break

            result = menu_choices[action]()
            print(f"--- {action} Finished ---")

            if result and hasattr(result, 'returncode') and result.returncode == EXIT_CODE_RETURN_TO_MENU:
                # Special exit code from script, return to menu immediately
                continue

            input("\nPress Enter to return to the menu...")
            # Clear console again before showing the menu
            os.system('cls' if os.name == 'nt' else 'clear')

        except KeyboardInterrupt:
            print("\nExiting application.")
            break

if __name__ == "__main__":
    main()
