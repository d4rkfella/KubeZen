from __future__ import annotations
import traceback
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from KubeZen.core.tmux_ui_manager import TmuxUIManager


async def handle_uncaught_exception(exc: Exception, tmux_ui_manager: TmuxUIManager) -> None:
    """
    Displays a formatted traceback for an uncaught exception in a new tmux window.
    """
    # Format the traceback into a string
    tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    error_report = "".join(tb_lines)

    # Create a user-friendly error message
    header = "--- Uncaught Exception Report ---"
    footer = "--- Press 'q' to close this window and return to the application. ---"
    full_message = f"{header}\\n\\n{error_report}\\n{footer}"

    # Use the tmux manager to display the error in a pager
    await tmux_ui_manager.display_text_in_new_window(
        text=full_message, window_name="KubeZen Error Report"
    )
