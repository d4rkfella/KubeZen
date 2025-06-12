from __future__ import annotations
import os
import time
import libtmux
import libtmux.common
import asyncio
import tempfile
import shlex
from functools import wraps
from typing import (
    TYPE_CHECKING,
    Optional,
    Any,
    Callable,
    Dict,
    TypeVar,
    Coroutine,
    Set,
    Union,
)

from KubeZen.core.service_base import ServiceBase
from KubeZen.core.exceptions import (
    TmuxEnvironmentError,
    TmuxOperationError,
    UserInputFailedError,
)

if TYPE_CHECKING:
    from KubeZen.core.app_services import AppServices
    from KubeZen.config import AppConfig

T = TypeVar("T")
AsyncFunc = Callable[..., Coroutine[Any, Any, T]]


def tmux_error_handler(
    show_toast: bool = True,
) -> Callable[[AsyncFunc[T]], AsyncFunc[T]]:
    """
    Decorator for robust error handling in TmuxUIManager methods.
    Logs errors and optionally shows a toast to the user.
    """

    def decorator(func: AsyncFunc[T]) -> AsyncFunc[T]:
        @wraps(func)
        async def wrapper(self: "TmuxUIManager", *args: Any, **kwargs: Any) -> T:
            try:
                return await func(self, *args, **kwargs)
            except Exception as e:
                self.logger.error(f"TmuxUIManager error in {func.__name__}: {e}", exc_info=True)
                if show_toast:
                    await self.show_toast(
                        f"Tmux error: {e}", bg_color="red", fg_color="white", duration=7
                    )
                raise

        return wrapper

    return decorator


class TmuxUIManager(ServiceBase):
    """
    Manages tmux sessions, windows, and panes for KubeZen.
    Tracks all KubeZen-created window IDs for robust cleanup.

    Features:
    - Async, robust, and testable tmux command execution
    - Consistent error handling and user feedback
    - Configurable behaviors (pager, remain-on-exit, window naming, etc.)
    - Reliable resource cleanup
    - User-friendly focus and error messages
    """

    DEFAULT_INPUT_WINDOW_NAME: str = "KubeZenInput"
    DEFAULT_INPUT_PANE_POLLING_TIMEOUT: float = 60.0  # seconds
    DEFAULT_INPUT_PANE_POLLING_INTERVAL: float = 0.1  # seconds

    def __init__(
        self,
        app_services: AppServices,
        main_window_name: str,
        session_name: str,
    ) -> None:
        super().__init__(app_services)
        assert (
            self.app_services.config is not None
        ), "TmuxUIManager requires a non-None AppConfig from AppServices"
        self.config: AppConfig = self.app_services.config
        self.session_name = session_name
        self.main_window_name = main_window_name

        # Only socket_path needs to come from environment as it's used for libtmux connection
        self.socket_path = os.environ.get("KUBEZEN_SOCKET_PATH")
        if not self.socket_path:
            err_msg = (
                "KUBEZEN_SOCKET_PATH environment variable not set. TmuxUIManager cannot connect."
            )
            self.logger.critical(f"{err_msg}")
            raise TmuxEnvironmentError(err_msg)

        self.server: Optional[libtmux.Server] = None
        self.session: Optional[libtmux.Session] = None
        self.main_window: Optional[libtmux.Window] = None

        # For dedicated input pane
        self.input_window_name: str = getattr(
            self.config, "tmux_input_window_name", self.DEFAULT_INPUT_WINDOW_NAME
        )
        self.input_window_id: Optional[str] = None
        self.input_pane_id: Optional[str] = None
        self.input_pane: Optional[libtmux.Pane] = None
        self._input_pane_polling_timeout: float = getattr(
            self.config,
            "tmux_input_polling_timeout",
            self.DEFAULT_INPUT_PANE_POLLING_TIMEOUT,
        )
        self._input_pane_polling_interval: float = getattr(
            self.config,
            "tmux_input_polling_interval",
            self.DEFAULT_INPUT_PANE_POLLING_INTERVAL,
        )

        self.logger.debug(
            f"TmuxUIManager fully configured. Input window: '{self.input_window_name}'"
        )

        self.kubezen_window_ids: Set[str] = set()  # Track all KubeZen-created window IDs

    @tmux_error_handler()
    async def initialize_environment(self) -> bool:
        self.logger.debug("Initializing tmux environment...")
        self.server = await asyncio.to_thread(libtmux.Server, socket_path=self.socket_path)
        await asyncio.to_thread(self.server.list_sessions)
        self.session = self.server.find_where({"session_name": self.session_name})
        if not self.session:
            raise TmuxEnvironmentError(f"Session '{self.session_name}' not found.")
        self.session_id = self.session.id
        self.main_window = self.session.find_where({"window_name": self.main_window_name})
        if not self.main_window and self.session.windows:
            self.main_window = self.session.windows[0]
        if not self.main_window:
            raise TmuxEnvironmentError("Main window not found.")
        try:
            await asyncio.to_thread(self.session.set_option, "mouse", "on")
        except libtmux.exc.TmuxCommandNotFound:
            pass
        self.logger.debug(
            f"Successfully initialized tmux environment. Session: '{self.session.name}', Main Window: '{self.main_window.name}'"
        )
        return True

    def _find_pane_by_id(self, pane_id: str) -> Optional[libtmux.Pane]:
        """Finds a pane by its ID across all windows in the current session."""
        if not self.session:
            self.logger.error("Cannot find pane: Tmux session not initialized.")
            return None
        try:
            for window in self.session.windows:
                for pane in window.panes:
                    if pane.id == pane_id:
                        return pane
        except Exception as e:
            self.logger.error(f"Error finding pane by ID '{pane_id}': {e}")
        return None

    def _does_window_exist(self, window_id: Optional[str]) -> bool:
        if not self.session or not window_id:
            return False
        try:
            return bool(self.session.find_where({"window_id": window_id}))
        except Exception as e:
            self.logger.error(f"Error checking if window ID '{window_id}' exists: {e}")
            return False

    @tmux_error_handler()
    async def kill_window_by_id(self, window_id: Optional[str]) -> bool:
        """Kills a tmux window by its ID and removes it from the tracked set."""
        self.logger.info(f"kill_window_by_id called for window_id={window_id}")
        if not self.session or not window_id:
            self.logger.warning(
                f"Cannot kill window: session not initialized or window_id not provided ('{window_id}')."
            )
            return False
        try:
            target_window = self.session.find_where({"window_id": window_id})
            if target_window:
                self.logger.debug(
                    f"Attempting to kill window ID '{window_id}' (Name: '{target_window.name}')."
                )
                await asyncio.to_thread(target_window.kill_window)
                self.kubezen_window_ids.discard(window_id)  # Remove from tracked set
                self.logger.info(f"Successfully killed window ID '{window_id}'.")
                return True
            else:
                self.logger.debug(
                    f"Window ID '{window_id}' not found. Assuming it already closed."
                )
                return True  # Treat as success if window is already gone
        except Exception as e:
            self.logger.error(f"Error killing window ID '{window_id}': {e}")
            return False

    @tmux_error_handler()
    async def shutdown_ui(self) -> None:
        """Kills all tracked tmux windows created by this KubeZen session."""
        self.logger.info(
            f"Shutting down UI: killing all {len(self.kubezen_window_ids)} tracked windows."
        )

        # Create a copy of the set to iterate over, as kill_window_by_id modifies the original set.
        window_ids_to_kill = list(self.kubezen_window_ids)

        # Use asyncio.gather to kill windows concurrently for speed.
        kill_tasks = [self.kill_window_by_id(window_id) for window_id in window_ids_to_kill]
        results = await asyncio.gather(*kill_tasks, return_exceptions=True)

        for window_id, result in zip(window_ids_to_kill, results):
            if isinstance(result, Exception):
                self.logger.error(f"Error during shutdown of window ID '{window_id}': {result}")

        self.logger.info("UI shutdown sequence completed.")

    def _get_or_create_input_pane(self) -> Optional[libtmux.Pane]:
        """Finds or creates a dedicated tmux pane for user input."""
        if not self.session:
            self.logger.error(
                "[InputPane] Cannot get or create input pane: Tmux session not initialized."
            )
            raise TmuxOperationError("Cannot operate without a tmux session.")

        self.logger.debug("Getting or creating input pane.")

        input_pane: Optional[libtmux.Pane] = None
        input_window: Optional[libtmux.Window] = None

        if self.input_pane_id and self._find_pane_by_id(self.input_pane_id):
            input_pane = self._find_pane_by_id(self.input_pane_id)
            if input_pane:
                input_window = self.session.find_where({"window_id": input_pane.window_id})
                if input_window:
                    self.logger.debug(
                        f"[InputPane] Found existing live input pane {self.input_pane_id} in window {input_window.name}."
                    )
                else:
                    self.logger.warning(
                        f"[InputPane] Found live input pane {self.input_pane_id} but its window {input_pane.window_id} is missing. Will recreate."
                    )
                    input_pane = None
            else:
                self.logger.warning(
                    f"[InputPane] Pane {self.input_pane_id} was reported alive but find_pane_by_id failed. Will recreate."
                )

        if not input_pane:
            self.logger.debug(
                f"[InputPane] No known live input pane. Searching for window named '{self.input_window_name}'."
            )
            input_window = self.session.find_where({"window_name": self.input_window_name})
            if input_window:
                self.logger.debug(
                    f"[InputPane] Found existing window '{self.input_window_name}' (ID: {input_window.id})."
                )
                if input_window.panes:
                    input_pane = input_window.panes[0]
                    self.input_window_id = input_window.id
                    if input_pane:
                        self.input_pane_id = input_pane.id
                    if input_window.id:
                        self.kubezen_window_ids.add(input_window.id)  # Track the input window
                    self.logger.debug(
                        f"[InputPane] Using pane {self.input_pane_id} in existing window."
                    )
                else:
                    self.logger.error(
                        f"[InputPane] Window '{self.input_window_name}' found but has no panes. Killing and recreating."
                    )
                    try:
                        if input_window:
                            input_window.kill_window()
                    except Exception:
                        pass
                    input_window = None
                    input_pane = None
            else:
                self.logger.debug(
                    f"[InputPane] Window '{self.input_window_name}' not found. Creating it."
                )
                try:
                    input_window = self.session.new_window(
                        window_name=self.input_window_name, attach=False
                    )
                    if input_window and input_window.id:
                        self.kubezen_window_ids.add(input_window.id)
                        self.input_window_id = input_window.id
                        if input_window.panes:
                            input_pane = input_window.panes[0]
                            if input_pane and input_pane.id:
                                self.input_pane_id = input_pane.id
                        self.logger.info(
                            f"[InputPane] Created new input window (ID: {self.input_window_id}) and pane (ID: {self.input_pane_id})."
                        )
                    else:
                        raise TmuxOperationError("Failed to create new window or get its ID.")
                except Exception as e:
                    self.logger.error(f"[InputPane] Failed to create input window/pane: {e}")
                    raise TmuxOperationError(f"Failed to create input window/pane: {e}") from e

        if not input_pane:
            self.logger.critical(
                "[InputPane] CRITICAL: Failed to get or create an input pane after all attempts."
            )
            raise TmuxOperationError("Failed to get or create an input pane.")

        self.input_pane = input_pane
        return self.input_pane

    @tmux_error_handler()
    async def execute_command_in_input_pane(
        self,
        command_str: str,
        result_file_path: str,
        task_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Executes a command in the dedicated input pane and waits for it to complete.
        The command is expected to write its result to the specified result file.
        """
        self.logger.debug(
            f"[ExecInput] Executing command in input pane. Task: {task_name or 'Untitled'}"
        )

        pane = await asyncio.to_thread(self._get_or_create_input_pane)
        if not pane:
            raise TmuxEnvironmentError("Could not get or create an input pane.")

        # Select the window and pane to bring it to the user's attention
        await asyncio.to_thread(pane.window.select_window)
        await asyncio.to_thread(pane.select_pane)

        # The command needs to be executed in the shell running in the pane.
        # We also clear the pane before running the command for a clean slate.
        full_command = f"clear && {command_str}"
        await asyncio.to_thread(pane.send_keys, full_command, enter=True, suppress_history=False)
        self.logger.debug(f"[ExecInput] Sent command to pane {pane.id}: {full_command}")

        # Poll for the existence of the result file to know when the command is done.
        self.logger.debug(f"[ExecInput] Polling for result file: {result_file_path}")
        start_time = time.monotonic()
        while time.monotonic() - start_time < self._input_pane_polling_timeout:
            if os.path.exists(result_file_path):
                self.logger.debug(
                    f"[ExecInput] Result file found after {time.monotonic() - start_time:.2f}s."
                )
                try:
                    with open(result_file_path, "r") as f:
                        result = f.read()

                    # Kill the input window
                    if pane and pane.window_id:
                        self.logger.debug(f"[ExecInput] Killing input window: {pane.window_id}")
                        await self.kill_window_by_id(pane.window_id)
                        self.input_window_id = None  # Clear cached IDs
                        self.input_pane_id = None

                    return result
                except Exception as e:
                    self.logger.error(
                        f"[ExecInput] Error reading or cleaning up result file: {e}",
                        exc_info=True,
                    )
                    raise UserInputFailedError(f"Failed to process result from input command: {e}")
                finally:
                    # Ensure the result file is cleaned up even if window operations fail
                    if os.path.exists(result_file_path):
                        os.remove(result_file_path)

            await asyncio.sleep(self._input_pane_polling_interval)

        # Before raising timeout, try to clean up the input window
        if pane and pane.window_id:
            await self.kill_window_by_id(pane.window_id)
            self.input_window_id = None
            self.input_pane_id = None

        self.logger.error(f"[ExecInput] Timeout waiting for result file '{result_file_path}'.")
        raise UserInputFailedError(
            f"Timeout waiting for user input on task '{task_name or 'Untitled'}'."
        )

    @tmux_error_handler(show_toast=False)
    async def launch_command_in_new_window(
        self,
        command_str: Union[str, list[str]],
        window_name: str = "KubeZen Task Window",
        task_name: Optional[str] = None,
        attach: bool = True,
        set_remain_on_exit: bool = True,
        wait_for_completion: bool = False,
    ) -> Optional[Dict[str, str]]:
        if not self.session:
            raise TmuxOperationError("Tmux session not initialized.")

        final_command = shlex.join(command_str) if isinstance(command_str, list) else command_str
        stderr_file = tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8')
        
        # The command is wrapped to ensure stderr is captured and it runs in a proper shell environment
        command_to_run = f"{{ {final_command}; }} 2> {stderr_file.name}"
        
        new_window = None
        try:
            # Create window with remain-on-exit ON to prevent race condition
            new_window = await asyncio.to_thread(
                self.session.new_window,
                window_name=window_name,
                attach=attach,
                window_shell=command_to_run,
            )
            
            # Check for instant failure by reading the stderr file
            stderr_file.close()
            with open(stderr_file.name, "r") as f:
                error_output = f.read().strip()

            if error_output:
                # If there's an immediate error, raise an exception.
                raise TmuxOperationError(f"{error_output}")
            
            # If we are here, a window was created without immediate error.
            if new_window.id:
                self.kubezen_window_ids.add(new_window.id)
            
            # Retry mechanism to find the pane, making it more robust.
            pane = None
            for _ in range(5): # Retry up to 5 times (1 second total)
                pane = await asyncio.to_thread(getattr, new_window, 'attached_pane', None)
                if pane:
                    break
                await asyncio.sleep(0.2)

            if not pane:
                raise TmuxOperationError(f"Could not find attached pane for new window '{window_name}'.")

            if not set_remain_on_exit:
                await asyncio.to_thread(new_window.set_window_option, "remain-on-exit", "off")

            if wait_for_completion:
                # Wait for the pane to disappear as a signal of completion
                while await asyncio.to_thread(pane.pane_exists):
                    await asyncio.sleep(0.2)
            
            if new_window.id and pane and pane.id:
                return {"window_id": new_window.id, "pane_id": pane.id}
            
            raise TmuxOperationError("Failed to get window or pane ID after creation.")

        except Exception as e:
            self.logger.error(f"Error in launch_command_in_new_window: {e}", exc_info=True)
            if new_window: # If window was created but something else failed, kill it
                await self.kill_window_by_id(new_window.id)
            # Re-raise the original exception to be handled by the decorator
            raise
        finally:
            # Ensure the temp file is always cleaned up
            os.remove(stderr_file.name)

    @tmux_error_handler()
    async def display_text_in_new_window(
        self,
        text: str,
        window_name: str,
        pager_command: str = "less -R",
        attach: bool = True,
    ) -> bool:
        """
        Displays text in a new window with a pager and waits for it to close.
        Returns True on success, False on failure.
        """
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as tmp:
            tmp.write(text)
            tmp_path = tmp.name

        # The command to execute in the new window
        command_str = f"{pager_command} {shlex.quote(tmp_path)}"
        # The command to run after the main command exits (for cleanup)
        cleanup_command = f"rm {shlex.quote(tmp_path)}"

        # We combine them so cleanup always runs. The `trap` ensures cleanup even on Ctrl+C in the pager.
        full_shell_command = f"trap '{cleanup_command}' EXIT; {command_str}"

        return await self.display_command_in_pager(
            command_to_page=full_shell_command,
            pager_command="",  # The pager is already in the command
            task_name=window_name,
            attach=attach,
        )

    @tmux_error_handler()
    async def wait_for_window_to_close(self, window_id: str, timeout: float = 3600.0) -> bool:
        """Polls until a given window ID no longer exists."""
        self.logger.debug(f"Polling for window {window_id} to close.")
        start_time = time.monotonic()

        while time.monotonic() - start_time < timeout:
            if not await asyncio.to_thread(self._does_window_exist, window_id):
                self.logger.info(
                    f"Window {window_id} closed after {time.monotonic() - start_time:.2f}s."
                )
                return True
            await asyncio.sleep(0.5)

        self.logger.warning(f"Timeout waiting for window {window_id} to close.")
        await self.kill_window_by_id(window_id)
        return False

    @tmux_error_handler()
    async def display_command_in_pager(
        self,
        command_to_page: str,
        pager_command: str = "less -R",
        task_name: str = "KubeZen Pager",
        attach: bool = True,
    ) -> bool:
        """
        Displays the output of a command in a new window, piped through a pager.
        """
        # If a pager command is provided, pipe the command_to_page into it.
        # Otherwise, assume command_to_page is a self-contained command.
        if pager_command:
            full_command = f"{command_to_page} | {pager_command}"
        else:
            full_command = command_to_page

        try:
            result = await self.launch_command_in_new_window(
                command_str=full_command,
                window_name=task_name,
                attach=attach,
                set_remain_on_exit=True,  # This is critical to prevent race conditions.
            )
            return result is not None
        except Exception as e:
            await self.show_toast(f"Error opening pager: {e}", bg_color="red", duration=8)
            return False

    @tmux_error_handler()
    async def launch_editor(self, file_path: str, task_name: str = "KubeZen Editor") -> bool:
        """
        Launches the user's editor in a new, attached window to edit a file.
        Waits for the editor process to complete using a polling mechanism.
        Returns True if the editor exits successfully, False otherwise.
        """
        if not self.server:
            self.logger.error("Cannot launch editor: Tmux server not initialized.")
            return False

        editor = os.environ.get("EDITOR", "vi")
        command_str = f"{editor} {shlex.quote(file_path)}"
        self.logger.info(f"Launching editor: {command_str}")

        try:
            window_info = await self.launch_command_in_new_window(
                command_str=command_str,
                window_name=task_name,
                attach=True,
                set_remain_on_exit=True,
            )

            if not window_info or not window_info.get("window_id"):
                self.logger.error("Failed to create editor window.")
                return False

            return await self.wait_for_window_to_close(window_info["window_id"])

        except Exception as e:
            self.logger.error(f"Failed to launch editor: {e}", exc_info=True)
            await self.show_toast(f"Error launching editor: {e}", bg_color="red", fg_color="white")
            return False

    async def show_toast(
        self,
        message: str,
        duration: int = 5,
        fg_color: str = "white",
        bg_color: str = "green",
    ) -> None:
        """
        Displays a short, non-blocking notification in the tmux status line.
        """
        if (
            not self.main_window
            or not hasattr(self.main_window, "active_pane")
            or not self.main_window.active_pane
        ):
            self.logger.error("Cannot show toast: Main window or active pane not available.")
            return

        style_parts = []
        if fg_color:
            style_parts.append(f"fg={fg_color}")
        if bg_color:
            style_parts.append(f"bg={bg_color}")

        style_str = ",".join(style_parts)

        formatted_message = f"#[{style_str}]{message}#[default]" if style_str else message
        self.logger.info(f"[Toast] {message}")

        try:
            active_pane = self.main_window.active_pane
            await asyncio.to_thread(
                active_pane.cmd,
                "display-message",
                "-d",
                str(duration * 1000),
                formatted_message,
            )
            self.logger.debug(f"Toast displayed via pane {active_pane.id}.")
        except Exception as e:
            if "no active pane" in str(e):
                self.logger.warning(
                    "Could not show toast, no active pane found. This can happen during shutdown."
                )
            else:
                self.logger.error(f"Failed to display toast: {e}", exc_info=True)
