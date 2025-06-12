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
    cast,
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
        self._cleanup_callbacks: Dict[str, list[Callable[[], Coroutine[Any, Any, None]]]] = {}
        self._window_monitor_task: Optional[asyncio.Task] = None
        self._WINDOW_MONITOR_INTERVAL = 2  # seconds

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
        self._window_monitor_task = asyncio.create_task(self.monitor_closed_windows())
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

        if self._window_monitor_task:
            self.logger.info("Cancelling window monitor task.")
            self._window_monitor_task.cancel()
            try:
                await self._window_monitor_task
            except asyncio.CancelledError:
                pass  # Expected cancellation

        # Create a copy of the set to iterate over, as kill_window_by_id modifies the original set.
        window_ids_to_kill = list(self.kubezen_window_ids)

        # Use asyncio.gather to kill windows concurrently for speed.
        kill_tasks = [self.kill_window_by_id(window_id) for window_id in window_ids_to_kill]
        results = await asyncio.gather(*kill_tasks, return_exceptions=True)

        for window_id, result in zip(window_ids_to_kill, results):
            if isinstance(result, Exception):
                self.logger.error(f"Error during shutdown of window ID '{window_id}': {result}")

        self.logger.info("UI shutdown sequence completed.")

    async def monitor_closed_windows(self) -> None:
        """
        Runs in the background, periodically checking for closed windows and
        executing any registered cleanup callbacks.
        """
        self.logger.info("Starting window monitor task.")
        while True:
            try:
                # Check for closed windows
                closed_window_ids = []
                # Iterate over a copy as the set will be modified
                for window_id in list(self.kubezen_window_ids):
                    if not self._does_window_exist(window_id):
                        self.logger.info(f"Detected closed window: {window_id}")
                        closed_window_ids.append(window_id)

                # Run cleanup callbacks for closed windows
                for window_id in closed_window_ids:
                    if window_id in self._cleanup_callbacks:
                        self.logger.info(
                            f"Running {len(self._cleanup_callbacks[window_id])} cleanup callbacks for window {window_id}."
                        )
                        callbacks = self._cleanup_callbacks.pop(window_id)
                        await asyncio.gather(
                            *(cb() for cb in callbacks), return_exceptions=True
                        )

                    # Remove from the main tracked set
                    self.kubezen_window_ids.discard(window_id)

                await asyncio.sleep(self._WINDOW_MONITOR_INTERVAL)
            except asyncio.CancelledError:
                self.logger.info("Window monitor task cancelled.")
                break
            except Exception as e:
                self.logger.error(f"Error in window monitor task: {e}", exc_info=True)
                # Avoid tight loop on unexpected errors
                await asyncio.sleep(5)

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
        set_remain_on_exit: bool = False,
        wait_for_completion: bool = False,
    ) -> Optional[Dict[str, str]]:
        """Creates a new tmux window and runs a command in it."""
        if not self.session:
            raise TmuxEnvironmentError("Cannot launch command: session not initialized.")

        self.logger.debug(
            f"Launching command in new window '{window_name}'. Attach: {attach}, Remain-on-exit: {set_remain_on_exit}"
        )

        try:
            # Using window_shell is more robust for commands that should own the pane.
            # It ensures the window closes when the command exits (if remain-on-exit is off).
            new_window = await asyncio.to_thread(
                self.session.new_window,
                window_name=window_name,
                attach=attach,
                window_shell=command_str,
            )

            if set_remain_on_exit:
                await asyncio.to_thread(new_window.set_window_option, "remain-on-exit", "on")

            pane = await self._get_pane_with_retry(new_window, window_name)
            if not pane:
                raise TmuxOperationError(f"Could not find attached pane for new window '{window_name}'.")

            self.kubezen_window_ids.add(new_window.id)
            self.logger.debug(
                f"Successfully launched command in window '{new_window.name}' (ID: {new_window.id}, Pane: {pane.id})."
            )

            if wait_for_completion:
                await self.wait_for_window_to_close(new_window.id)

            return {"window_id": new_window.id, "pane_id": pane.id}
        except Exception as e:
            self.logger.error(f"Error in launch_command_in_new_window: {e}", exc_info=True)
            raise

    async def _get_pane_with_retry(
        self, window: "libtmux.Window", window_name: str, retries=5, delay=0.1
    ) -> Optional["libtmux.Pane"]:
        """Retry mechanism to find the pane, making it more robust."""
        for _ in range(retries):
            pane = await asyncio.to_thread(getattr, window, 'attached_pane', None)
            if pane:
                return cast(libtmux.Pane, pane)
            await asyncio.sleep(delay)
        return None

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
        This is a simple, fire-and-forget pager.
        """
        full_command = f"{command_to_page} | {pager_command}"
        try:
            # Use launch_command_in_new_window, which should handle window creation
            # and closing gracefully. set_remain_on_exit=False is the default and correct.
            result = await self.launch_command_in_new_window(
                command_str=full_command,
                window_name=task_name,
                attach=attach,
            )
            return result is not None
        except Exception as e:
            await self.show_toast(f"Error opening pager: {e}", bg_color="red", duration=8)
            return False

    @tmux_error_handler()
    async def display_logs_in_pager(
        self,
        pager_command: str,
        task_name: str,
        attach: bool = True,
        key_bindings: Optional[Dict[str, str]] = None,
        on_close_callbacks: Optional[list[Callable[[], Coroutine[Any, Any, None]]]] = None,
    ) -> bool:
        """
        Displays logs from a file in a new tmux window with a pager.
        This is a specialized method that handles key bindings for interactivity.
        """
        if not self.session:
            self.logger.error("Cannot display logs in pager: Tmux session not initialized.")
            return False

        window_name = task_name[:30]  # Truncate for tmux status bar

        # Launch the pager command in a new window but don't wait for completion here.
        window_info = await self.launch_command_in_new_window(
            command_str=pager_command,
            window_name=window_name,
            task_name=task_name,
            attach=attach,
            set_remain_on_exit=False,  # Let the window close when pager exits
            wait_for_completion=False, # We will wait manually below
        )

        if not window_info or "pane_id" not in window_info or "window_id" not in window_info:
            self.logger.error("Failed to create a new window for the pager.")
            return False

        pane_id = window_info["pane_id"]
        window_id = window_info["window_id"]

        # Apply custom key bindings to the new pane if they exist.
        if key_bindings:
            # IMPORTANT: Replace placeholder for the pane_id in the commands
            final_bindings = {
                key: cmd.replace("%TMUX_PANE%", pane_id)
                for key, cmd in key_bindings.items()
            }
            await self.set_window_key_bindings(pane_id, final_bindings)

        if on_close_callbacks:
            self.logger.debug(
                f"Registering {len(on_close_callbacks)} on_close callbacks for window {window_id}"
            )
            self._cleanup_callbacks[window_id] = on_close_callbacks
        
        return True

    @tmux_error_handler()
    async def unbind_keys(self, keys: list[str]) -> None:
        """Unbinds a list of keys from the global (no-prefix) key table."""
        if not self.session:
            self.logger.error("Cannot unbind keys: Tmux session not initialized.")
            return

        for key in keys:
            try:
                self.logger.info(f"Unbinding key '{key}'")
                await asyncio.to_thread(self.server.cmd, "unbind-key", "-n", key)
            except Exception as e:
                # This is not critical, so we log a warning instead of an error.
                self.logger.warning(f"Could not unbind key '{key}': {e}", exc_info=False)

    @tmux_error_handler()
    async def set_window_key_bindings(
        self, pane_id: str, key_bindings: Dict[str, str]
    ) -> None:
        """
        Binds keys to commands. The binding is conditional: it only fires if the
        active pane matches the one it was created for. Otherwise, the keypress
        is passed through to the application (e.g., Vim).
        """
        if not self.session:
            self.logger.error("Cannot set key bindings: Tmux session not initialized.")
            return

        self.logger.debug(f"Setting conditional key bindings for pane {pane_id}: {key_bindings}")

        for key, command in key_bindings.items():
            try:
                # The command will only run if the active pane is the one we are targeting.
                # If not, the key press is ignored by this binding and handled by the application.
                condition = f'[ "#{{pane_id}}" = "{pane_id}" ]'
                if_command = f'run-shell "{command}"'
                
                self.logger.info(f"Binding key '{key}' to conditional command for pane {pane_id}")

                await asyncio.to_thread(
                    self.server.cmd,
                    "bind-key",
                    "-n",       # -n: no prefix key required
                    key,
                    "if-shell",
                    condition,
                    if_command,
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to bind key '{key}' for pane {pane_id}: {e}",
                    exc_info=True,
                )
        self.logger.debug(f"Finished setting key bindings for pane {pane_id}.")

    @tmux_error_handler()
    async def launch_editor(self, file_path: str, task_name: str = "KubeZen Editor") -> bool:
        """
        Launches the user's editor in a new, attached window to edit a file.
        It prioritizes using vim with the custom config if available.
        """
        if not self.server:
            self.logger.error("Cannot launch editor: Tmux server not initialized.")
            return False

        # Prioritize using vim with our custom config if available
        if self.config.vim_path and self.config.vim_config_path:
            command_str = (
                f"{shlex.quote(str(self.config.vim_path))} "
                f"-u {shlex.quote(str(self.config.vim_config_path))} "
                f"{shlex.quote(file_path)}"
            )
        else:
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

    @tmux_error_handler()
    async def display_text_in_new_window(
        self,
        text: str,
        window_name: str,
        pager_command: str = "less -R",
        attach: bool = True,
    ) -> bool:
        """Displays a string of text in a new window with a pager."""
        try:
            # Create a temporary file to hold the text
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, encoding="utf-8", suffix=".txt"
            ) as tmp_file:
                tmp_file.write(text)
                tmp_file_path = tmp_file.name

            # The command to run in the new window is the pager opening the file.
            # We add a trap to ensure the temp file is cleaned up when the shell exits.
            command_to_run = (
                f"trap 'rm -f {shlex.quote(tmp_file_path)}' EXIT; "
                f"{pager_command} {shlex.quote(tmp_file_path)}"
            )

            await self.launch_command_in_new_window(
                command_str=command_to_run,
                window_name=window_name,
                attach=attach,
                set_remain_on_exit=False,  # Window should close when less exits
            )
            return True
        except Exception as e:
            self.logger.error(f"Error in display_text_in_new_window: {e}", exc_info=True)
            return False
