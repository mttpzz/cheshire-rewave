import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from logging.handlers import RotatingFileHandler


# --- ENV VARIABLES -------------------------------------------------------------------------------------------------------------
LOG_FOLDER = os.getenv('LOG_FOLDER')


# --- LOGGER --------------------------------------------------------------------------------------------------------------------
def get_plugin_logger(plugin_name: str) -> logging.Logger:
    """Crea un logger dedicato per ogni plugin."""

    # cat logs dir
    log_dir = LOG_FOLDER
    plugin_dir = os.path.join(log_dir, plugin_name)
    os.makedirs(plugin_dir, exist_ok=True)

    logger = logging.getLogger(f"Logger_{plugin_name}")
    
    # no duplicated handlers
    if not logger.handlers:
        logger.setLevel(logging.INFO)

        # formatting the logger with italian time
        formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
        formatter.formatTime = lambda record, datefmt=None: datetime.fromtimestamp(
            record.created, tz=ZoneInfo("Europe/Rome")
            ).strftime(datefmt or "%Y-%m-%d %H:%M:%S %Z")

        # logger filename and path
        log_file_path = os.path.join(plugin_dir, f"{plugin_name}.log")
        
        # file handler (rotating: max 10MB, 5 backup)
        file_handler = RotatingFileHandler(
            filename=log_file_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # console Handler (optional)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)   # only WARNINGS and ERRORS in console
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
