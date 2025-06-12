from __future__ import annotations
from typing import List, Optional
from pathlib import Path
import tempfile
import os
import logging
import uuid

from KubeZen.config import AppConfig


def format_fzf_display_item(
    code: str, text: str, icon: Optional[str] = None, view_session_id: Optional[str] = None
) -> str:
    """
    Formats an item for FZF display, ensuring a code part and a text part, separated by '|'.
    The code part will have '|', '\t', '\n', '\r' replaced by spaces and then stripped.
    The text part will have '\n', '\r' replaced by spaces.
    The original BaseUIView._format_fzf_item also replaced '|' in the text part with a space;
    this behavior is maintained here for the display text.
    Optionally prepends an icon to the text part.
    Optionally inserts a view_session_id between the code and text parts.
    """
    # Clean code: replace problematic characters for the 'code' part.
    # It must not contain '|' before being joined with the text part.
    cleaned_code = (
        str(code).replace("|", " ").replace("\t", " ").replace("\n", " ").replace("\r", "").strip()
    )

    # Clean text for display: remove newlines/carriage returns.
    # Replace '|' with ' ' in the text part to match original BaseUIView behavior.
    cleaned_text_for_display = (
        str(text).replace("\n", " ").replace("\r", "").replace("|", " ").strip()
    )

    display_prefix = f"{icon} " if icon else ""

    # Ensure no leading/trailing whitespace on the final text part that might affect FZF parsing or display.
    final_text_part = f"{display_prefix}{cleaned_text_for_display}".strip()

    if view_session_id:
        return f"{cleaned_code}|{view_session_id}|{final_text_part}"
    else:
        return f"{cleaned_code}|{final_text_part}"


class ViewFileManager:
    """Manages file operations for views."""

    def __init__(self) -> None:
        self._temp_files: List[str] = []
        self._data_file_path: Optional[Path] = None
        # Use the session temp directory from AppConfig
        self._temp_dir = AppConfig().session_temp_dir
        logging.info(f"ViewFileManager initialized with temp directory: {self._temp_dir}")

    def _get_or_create_data_file_path(self) -> Path:
        """Get or create a stable file path for view data."""
        if self._data_file_path is None:
            temp_dir_path = Path(self._temp_dir)
            self._data_file_path = temp_dir_path / f"kubezen_view_data_{uuid.uuid4()}.dat"
            self._temp_files.append(str(self._data_file_path))
            logging.info(f"Created new data file path: {self._data_file_path}")
        else:
            logging.debug(f"Using existing data file path: {self._data_file_path}")
        return self._data_file_path

    def write_items(self, items: List[str]) -> Optional[str]:
        """Write items to a file and return the path."""
        final_data_path = self._get_or_create_data_file_path()
        logging.info(f"Writing {len(items)} items to {final_data_path}")

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                dir=Path(self._temp_dir),
                prefix="kubezen_tmp_",
                suffix=".tmp",
                encoding="utf-8",
            ) as tmp_file:
                tmp_file_path = Path(tmp_file.name)
                logging.info(f"Created temporary file: {tmp_file_path}")
                for item in items:
                    tmp_file.write(item + "\n")

            os.rename(tmp_file_path, final_data_path)
            logging.info(f"Renamed {tmp_file_path} to {final_data_path}. Item count: {len(items)}")
            return str(final_data_path)
        except Exception as e:
            logging.error(f"Error writing FZF items to temp file: {e}", exc_info=True)
            if "tmp_file_path" in locals() and tmp_file_path.exists():
                try:
                    os.remove(tmp_file_path)
                    logging.info(f"Cleaned up temporary file after error: {tmp_file_path}")
                except OSError as e:
                    logging.error(f"Failed to clean up temporary file {tmp_file_path}: {e}")
            return None

    def cleanup(self) -> None:
        """Clean up temporary files."""
        if not self._temp_files:
            logging.debug("No temporary files to clean up.")
            return
        logging.info(f"Cleaning up {len(self._temp_files)} temporary files: {self._temp_files}")
        for temp_file in self._temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    logging.info(f"Deleted temporary file: {temp_file}")
                else:
                    logging.debug(f"Temporary file already deleted: {temp_file}")
            except OSError as e:
                logging.warning(f"Error deleting temp file {temp_file}: {e}")
        self._temp_files.clear()
        self._data_file_path = None


class FZFItemFormatter:
    """Handles FZF item formatting."""

    def __init__(self, view_session_id: str):
        self._view_session_id = view_session_id

    def format_item(self, action_code: str, display_name: str, icon: Optional[str] = None) -> str:
        """Format an item for FZF display."""
        return format_fzf_display_item(
            code=action_code,
            text=display_name,
            icon=icon,
            view_session_id=self._view_session_id,
        )

    def format_go_back_item(self) -> str:
        """Format the 'go back' item."""
        return self.format_item("go_back", "Go Back", icon="🔙")
