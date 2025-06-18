"""Logging utilities."""

import logging
import time
from contextlib import contextmanager
from typing import Generator, Any

log = logging.getLogger(__name__)


@contextmanager
def log_batch_timing(app: Any, log_changes: bool = True) -> Generator[None, None, None]:
    """Context manager to log batch update timing.

    Args:
        app: The application instance
        log_changes: Whether to log the batch update timing
    """
    start_time = time.time()
    try:
        yield
    finally:
        if log_changes:
            elapsed = time.time() - start_time
            log.debug("Batch update after %.3f seconds", elapsed)
