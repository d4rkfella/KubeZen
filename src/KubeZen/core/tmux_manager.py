from __future__ import annotations
import asyncio
import logging
import os
from typing import Optional

import libtmux
from libtmux.exc import TmuxCommandNotFound

log = logging.getLogger(__name__)


class TmuxManager:
    """A wrapper around libtmux for managing tmux sessions, windows, and panes."""

    def __init__(self) -> None:
        self.server: Optional[libtmux.Server] = None
        self.session: Optional[libtmux.Session] = None
        self.socket_path = os.environ.get("TMUX")

    async def connect(self) -> None:
        """Connects to the tmux server and finds the current session."""
        log.debug("Connecting to tmux server...")
        if not self.socket_path:
            log.error("TMUX environment variable not set. Are you in a tmux session?")
            raise ConnectionError(
                "TMUX environment variable not set. Are you in a tmux session?"
            )

        # The socket path is in the format /tmp/tmux-1000/default,12345,0 - we need the path part
        socket_path = self.socket_path.split(",")[0]
        log.debug("Using tmux socket path: %s", socket_path)

        try:
            self.server = await asyncio.to_thread(
                libtmux.Server, socket_path=socket_path
            )
            log.debug("Connected to tmux server: %s", self.server)

            tty = os.ttyname(0)
            log.debug("Current TTY: %s", tty)
            current_pane = await asyncio.to_thread(
                self.server.find_where, {"pane_tty": tty}
            )
            log.debug("Found current pane: %s", current_pane)

            if current_pane:
                session_id = getattr(current_pane, "session_id", None)
                if session_id:
                    log.debug("Found session ID '%s' from pane.", session_id)
                    self.session = await asyncio.to_thread(
                        self.server.find_where, {"session_id": session_id}
                    )
                else:
                    log.warning(
                        "Could not determine session ID from pane, falling back."
                    )
                    if self.server.sessions:
                        self.session = self.server.sessions[0]
            else:
                log.warning("Could not find current pane by TTY, falling back.")
                if self.server.sessions:
                    self.session = self.server.sessions[0]

            if self.session:
                log.info("Successfully connected to tmux session: %s", self.session.name)
            else:
                log.error("Failed to find any tmux session.")
                raise ConnectionError("Could not find the current tmux session.")
        except TmuxCommandNotFound as exc:
            log.critical("tmux command not found. Is tmux installed and in your PATH?")
            raise ConnectionError(
                "tmux command not found. Please ensure tmux is installed."
            ) from exc
        except Exception:
            log.exception("An unexpected error occurred while connecting to tmux.")
            raise

    async def launch_command_in_new_window(
        self,
        command: str,
        window_name: str,
        attach: bool = False,
        remain_on_exit: bool = False,
    ) -> Optional[libtmux.Window]:
        """Launches a command in a new tmux window.
        By default, the window will close when the command exits.
        """
        if not self.session:
            log.error("Cannot launch command: no tmux session available.")
            return None

        log.info("Launching command in new window '%s': %s", window_name, command)
        try:
            window = await asyncio.to_thread(
                self.session.new_window,
                window_name=window_name,
                attach=attach,
                window_shell=command,  # This runs the command as the pane's shell
            )

            if not remain_on_exit:
                log.debug("Setting remain-on-exit=off for window '%s'", window_name)
                await asyncio.to_thread(
                    window.set_window_option, "remain-on-exit", "off"
                )
            else:
                log.debug("Setting remain-on-exit=on for window '%s'", window_name)
                await asyncio.to_thread(
                    window.set_window_option, "remain-on-exit", "on"
                )

            # The pane is created with the command, so no need to send keys.

            await asyncio.sleep(0.1)  # Give tmux time for the command to start
            log.debug("Window '%s' (ID: %s) created successfully.", window_name, window.id)
            return window
        except Exception:
            log.exception("Failed to launch command in new window '%s'.", window_name)
            return None

    async def launch_command_and_capture_output(
        self, command: str, window_name: str, attach: bool = False
    ) -> str:
        """Launch a command, wait for it, and capture the output from its pane."""
        if not self.session:
            log.error("Cannot capture output: no tmux session available.")
            return ""

        signal_name = f"{window_name}_done"
        full_command = f"{command}; tmux wait-for -S {signal_name}"

        log.debug("Launching command for output capture in window '%s'.", window_name)
        window = await self.launch_command_in_new_window(
            command=full_command,
            window_name=window_name,
            attach=attach,
            remain_on_exit=True,  # Must remain to capture output
        )
        if not window:
            log.error("Failed to create window '%s' for output capture.", window_name)
            return ""

        # Wait for the command to signal completion
        wait_command = f"tmux wait-for {signal_name}"
        log.debug("Waiting for signal '%s' to capture output...", signal_name)
        process = await asyncio.create_subprocess_shell(wait_command)
        try:
            await process.wait()
            log.debug("Signal '%s' received. Capturing output.", signal_name)

            # Capture the output from the pane, including history
            pane = window.attached_pane
            if pane is None:
                log.error(
                    "Could not find pane for window %s to capture output.", window_name
                )
                return ""

            # Capture the last 20 lines from the history buffer.
            # This is more robust than just the visible pane, which might have been cleared.
            output_lines = await asyncio.to_thread(pane.capture_pane, start=-20)
            output = "\n".join(output_lines)
            log.info("Command in '%s' done. Captured output:\n%s", window_name, output)

            return output
        except asyncio.CancelledError:
            log.warning("Output capture for '%s' was cancelled.", window_name)
            process.terminate()
            await process.wait()
            raise
        except Exception:
            log.exception(
                "An error occurred during output capture for '%s'.", window_name
            )
            return ""
        finally:
            # Clean up the window
            log.debug("Killing window '%s' after capturing output.", window_name)
            try:
                await asyncio.to_thread(window.kill_window)
            except Exception:
                log.exception(
                    "Failed to kill window '%s'. It may already be closed.", window_name
                )

    async def set_key_bindings(
        self, pane_id: str, key_bindings: dict[str, str]
    ) -> None:
        """Binds keys to commands for a specific pane using a conditional if-shell."""
        if not self.server:
            log.error("Cannot set key bindings: Tmux server not initialized.")
            return

        for key, command in key_bindings.items():
            try:
                # This command only runs if the active pane is the one we are targeting.
                condition = f'[ "#{{pane_id}}" = "{pane_id}" ]'
                if_command = f'run-shell "{command}"'

                log.info(
                    "Binding key '%s' to conditional command for pane %s", key, pane_id
                )
                await asyncio.to_thread(
                    self.server.cmd,
                    "bind-key",
                    "-n",  # -n: no prefix key required
                    key,
                    "if-shell",
                    condition,
                    if_command,
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
        if not self.session:
            return None
        try:
            return self.session.find_where({"window_name": window_name})
        except Exception as e:
            log.error("Failed to find tmux window '%s': %s", window_name, e)
            return None

    async def attach_session(self) -> None:
        """Attaches to the current tmux session."""
        if not self.session:
            log.error("Cannot attach to session: no tmux session available.")
            return

        log.info("Attaching to tmux session...")
        try:
            await asyncio.to_thread(self.session.attach)
            log.info("Successfully attached to tmux session.")
        except Exception:
            log.exception("Failed to attach to tmux session.")
            raise
