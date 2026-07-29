import logging

class AlignedFormatter(logging.Formatter):
    """
    Formatter that matches user's specific layout:
    [Timestamp] [Context]    LEVEL    Message
    """
    def __init__(self, fmt=None, datefmt=None, context_width=30):
        super().__init__(fmt, datefmt)
        self.context_width = context_width

    def format(self, record):
        # 1. Format timestamp
        asctime = self.formatTime(record, self.datefmt)
        
        # 2. Get Context (Class.Method)
        class_name = getattr(record, 'class_name', "Global")
        method_name = record.funcName
        
        # Special handling: if class is Global and method starts with _load (standalone loaders)
        if class_name == "Global" and method_name.startswith('_load'):
             context = f"Config.{method_name}"
        else:
             context = f"{class_name}.{method_name}"
             
        # 3. Handle IDs (Error/Warning)
        log_id = getattr(record, 'log_id', None)
        id_str = f"[{log_id}] " if log_id else ""
        
        # 4. Construct the parts
        timestamp_part = f"[{asctime}]"
        context_part = f"[{context}]"
        level_part = f"{record.levelname:<8}"
        
        # 5. Build the aligned string
        # [Timestamp] [Context (padded)]    LEVEL    Message
        return f"{timestamp_part} {context_part:<{self.context_width}} {level_part} {id_str}{record.getMessage()}"
