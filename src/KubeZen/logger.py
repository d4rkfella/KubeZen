import logging
import sys
from typing import Optional
from typing_extensions import TypeAlias

from KubeZen.config import app_config

# Type alias for Logger to make it available for import
Logger: TypeAlias = logging.Logger


def setup_logging(process_name: Optional[str] = None) -> logging.Logger:
    """
    Configures and returns the main application logger.
    All logs are directed to the standard error stream (stderr).
    """
    # Get the root logger for the application
    logger = logging.getLogger("KubeZen")

    # Prevent logs from propagating to the root logger if it has other handlers
    logger.propagate = False

    # Clear any existing handlers to prevent duplicate logging
    if logger.hasHandlers():
        logger.handlers.clear()

    # Set the logging level from the application configuration
    log_level_str = app_config.log_level.upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    logger.setLevel(log_level)

    # Create a formatter that includes timestamp, logger name, level, and message
    formatter = logging.Formatter(
        "%(asctime)s - [%(name)s] - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Stderr Handler ---
    # Always write logs to the standard error stream.
    # For cli.py, this will be the user's terminal.
    # For core_ui_runner.py, this will be captured by shell redirection.
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_message = (
        f"--- KubeZen {process_name} Logging Initialized ---"
        if process_name
        else "--- KubeZen Logging Initialized ---"
    )
    logger.info(log_message)
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Returns a logger instance. If name is provided, it's a child of the main
    'KubeZen' logger. Otherwise, it's the main logger itself.
    """
    if name:
        return logging.getLogger(f"KubeZen.{name}")
    return logging.getLogger("KubeZen")
