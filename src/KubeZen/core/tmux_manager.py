from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional, ClassVar
import subprocess

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
        self.server: Optional[libtmux.Server] = libtmux.Server(socket_path=os.environ.get("KUBEZEN_SOCKET_PATH"))
        self.session: Optional[libtmux.Session] = self.server.find_where({"session_name": session_name})

    async def launch_command_in_new_window(
        self,
        command: str,
        window_name: str,
        attach: bool = False,
        remain_on_exit: bool = False,
        key_bindings: Optional[dict[str, str]] = None,
    ) -> None:
        """
        Launches a command in a new tmux window.
        Returns a tuple of the window and pane object.
        """
        log.info("Launching command in new window '%s': %s", window_name, command)
        window = self.session.new_window(
            window_name=window_name,
            attach=attach,
            window_shell=command,
        )
        if key_bindings:
            await self.set_key_bindings(window.attached_pane.id, key_bindings)

    async def launch_command_and_capture_output(
        self, command: str,
        window_name: str,
        attach: bool = False,
    ) -> str:
        unique_channel = f"kubezen_wait_{os.urandom(4).hex()}"
        command_in_pane = f"{command}; tmux wait-for -S {unique_channel}"

        window = self.session.new_window(window_name=window_name, attach=attach)
        window.set_window_option('remain-on-exit', 'on')
        pane = window.attached_pane
        pane.send_keys(command_in_pane, enter=True)

        wait_command = f"tmux wait-for {unique_channel}"
        process = await asyncio.create_subprocess_shell(wait_command)
        await asyncio.wait_for(process.wait())

        output_lines = await asyncio.to_thread(pane.capture_pane)

        clean_output = [
            line for line in output_lines
            if not line.strip().startswith("tmux wait-for")
            and not line.strip().startswith(command)
            and "Pane is dead" not in line
        ]
        log.info("Cleaned output: %s", clean_output)
        await asyncio.to_thread(window.kill_window)
        return "\n".join(clean_output).strip()

    async def set_key_bindings(
        self, pane_id: str, key_bindings: dict[str, str]
    ) -> None:
        """Binds keys to commands for a specific pane using a conditional if-shell."""
        for key, command in key_bindings.items():
            try:
                command = f'run-shell "{command} {pane_id}"'

                log.info(
                    "Binding key '%s' to conditional command for pane %s", key, pane_id
                )
                await asyncio.to_thread(
                    self.server.cmd,
                    "bind-key",
                    "-n",
                    key,
                    command,
                )
            except Exception:
                log.error(
                    "Failed to bind key '%s' for pane %s", key, pane_id, exc_info=True
                )

    async def unbind_key(self, key: str) -> None:
        """Unbinds a key from the global (no-prefix) key table."""
        if not self.server:
            log.error("Cannot unbind key: Tmux server not initialized.")
            return
        try:
            log.info("Unbinding key '%s'", key)
            await asyncio.to_thread(self.server.cmd, "unbind-key", "-n", key)
        except Exception:
            # This is not critical, so log a warning.
            log.warning("Could not unbind key '%s'", key, exc_info=True)

    async def find_window(self, window_name: str) -> Optional[libtmux.Window]:
        """Finds a window by its name."""
        return self.session.find_where({"window_name": window_name})
