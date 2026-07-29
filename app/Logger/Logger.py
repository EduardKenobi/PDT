import logging
import os
import inspect
from datetime import datetime
from config import LOG_DIR
from ._AlignedFormatter import AlignedFormatter

class Logger:
    """
    Custom Logger class that wraps Python's built-in logging module.
    This class sets up a logger with both file and console handlers, using a custom formatter for aligned output.
    The log file is named with the current date and stored in the specified LOG_DIR.

    Usage:
        logger = Logger(proj)
        logger.info("This is an info message.")
        logger.error("This is an error message.")
    
    Examples of log output:
    [2024-06-01 12:00:00] [Project]                     INFO: This is an info message.
    [2024-06-01 12:01:00] [Config._load_market_data]    ERROR: This is an error message.

    """
    _current_log_file = None

    def __init__(self, proj=None, name="Tracker"):
        self.proj = proj
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        if not self.logger.hasHandlers():
            self._setup_handlers()

    def _setup_handlers(self):
        # 1. Formatter (Imported from standalone file)
        # Using context_width=35 for better alignment of longer class.method names
        formatter = AlignedFormatter(datefmt='%Y-%m-%d %H:%M:%S', context_width=35)

        # 2. Setup the file path once
        if Logger._current_log_file is None:
            if not os.path.exists(LOG_DIR):
                os.makedirs(LOG_DIR)
            Logger._current_log_file = os.path.join(LOG_DIR, f"tracker_{datetime.now().strftime('%Y%m%d')}.log")

        # 3. File Handler (INFO and above)
        file_handler = logging.FileHandler(Logger._current_log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)

        # 4. Console Handler (INFO and above by default)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)

        # Add handlers to logger
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _get_caller_context(self):
        """Automatically detects the class name of the caller."""
        stack = inspect.stack()
        # stack[0] is this method
        # stack[1] is debug/info/warning/error method
        # stack[2] is the actual user code
        if len(stack) > 2:
            frame = stack[2][0]
            # Try to get 'self' from the caller's local variables
            instance = frame.f_locals.get('self', None)
            if instance:
                return instance.__class__.__name__
        return "Global"

    def debug(self, msg):
        extra = {'class_name': self._get_caller_context()}
        self.logger.debug(msg, extra=extra)

    def info(self, msg):
        extra = {'class_name': self._get_caller_context()}
        self.logger.info(msg, extra=extra)

    def warning(self, msg, warning_id=None):
        extra = {'class_name': self._get_caller_context(), 'log_id': warning_id}
        self.logger.warning(msg, extra=extra)

    def error(self, msg, error_id=None):
        extra = {'class_name': self._get_caller_context(), 'log_id': error_id}
        self.logger.error(msg, extra=extra)

    def set_level(self, level):
        self.logger.setLevel(level)
        for handler in self.logger.handlers:
            handler.setLevel(level)
