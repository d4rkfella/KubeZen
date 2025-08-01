from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional, ClassVar

import libtmux
from libtmux.exc import TmuxCommandNotFound, TmuxObjectDoesNotExist

log = logging.getLogger(__name__)


class TmuxManager:
    """A wrapper around libtmux for managing tmux sessions, windows, and panes."""

    # --- Singleton Pattern ---
    _instance: ClassVar[TmuxManager | None] = None

    @classmethod
    def get_instance(cls, session_name: str) -> TmuxManager:
        """Returns the singleton instance of the TmuxManager."""
        if cls._instance is None:
            cls._instance = TmuxManager(session_name)
            log.info("TmuxManager singleton initialized.")
        return cls._instance

    def __init__(self, session_name: str) -> None:
        self.server: libtmux.Server = libtmux.Server(
            socket_path=os.environ.get("KUBEZEN_SOCKET_PATH")
        )
        self.session: Optional[libtmux.Session] = self.server.find_where(
            {"session_name": session_name}
        )

    async def launch_command_in_new_window(
        self,
        command: str,
        window_name: str,
        env_vars: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Launches a command in a new tmux window.
        Returns a tuple of the window and pane object.
        """
        try:
            assert self.session is not None, "Tmux session is None"
            if window := self.session.find_where({"window_name": window_name}):
                window.select_window()
                return

            window = self.session.new_window(
                window_name=window_name,
                attach=True,
                window_shell=command,
            )
            assert window.attached_pane is not None
            pane_id = window.attached_pane.id
            if env_vars:
                for var, val in env_vars.items():
                    await asyncio.to_thread(
                        self.server.cmd,
                        "set-option",
                        "-p",
                        "-t",
                        pane_id,
                        f"@{var.lower()}",
                        val,
                    )
        except (TmuxCommandNotFound, TmuxObjectDoesNotExist) as e:
            log.error(f"Failed to launch command in tmux window '{window_name}': {e}")
            raise
