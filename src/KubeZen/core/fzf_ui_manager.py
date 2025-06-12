from __future__ import annotations
import time
from typing import List, Dict, Any, Optional, cast, TYPE_CHECKING
import shlex
import socket
import asyncio
import aiohttp
from aiohttp import web

from KubeZen.core.exceptions import (
    FzfLaunchError,
)
from KubeZen.core.service_base import ServiceBase
from KubeZen.core.events import (
    Event,
    FzfRefreshRequestEvent,
    FzfSelectionEvent,
    UnhandledEvent,
    FzfQueryChangeEvent,
    FzfClearQueryEvent,
    FzfExitRequestEvent,
)
from KubeZen.core.app_services import AppServices

if TYPE_CHECKING:
    from KubeZen.config import AppConfig
    from KubeZen.core.tmux_ui_manager import TmuxUIManager
    from KubeZen.core.event_bus import EventBus


FZF_COLORS = {
    "fg": "#d0d0d0",
    "bg": "#1b1b1b",
    "hl": "#00afff",
    "fg+": "#ffffff",
    "bg+": "#005f87",
    "hl+": "#00afff",
    "info": "#87ffaf",
    "prompt": "#ff5f00",
    "pointer": "#af00ff",
}


class FzfUIManager(ServiceBase):
    """Manages the fzf UI process and communication (via HTTP API)."""

    def __init__(
        self,
        app_services: AppServices,
    ):
        super().__init__(app_services=app_services)
        assert (
            self.app_services.config is not None
        ), "AppConfig not initialized in AppServices for FzfUIManager"
        self.config: AppConfig = self.app_services.config

        assert (
            self.app_services.tmux_ui_manager is not None
        ), "TmuxUIManager not initialized in AppServices for FzfUIManager"
        self.tmux_ui_manager: TmuxUIManager = self.app_services.tmux_ui_manager

        assert (
            self.app_services.event_bus is not None
        ), "EventBus not initialized in AppServices for FzfUIManager"
        self.event_bus: EventBus = self.app_services.event_bus

        self.fzf_server_url: Optional[str] = None
        self.fzf_pane_id: Optional[str] = None  # For the main FZF tmux pane
        self.fzf_window_id: Optional[str] = None  # For the main FZF tmux window
        self._fzf_launch_attempted: bool = False
        self.fzf_client_session: Optional[aiohttp.ClientSession] = None

        # --- New HTTP Event Server ---
        self.event_server: Optional[web.Application] = None
        self.event_server_runner: Optional[web.AppRunner] = None
        self.event_server_site: Optional[web.TCPSite] = None
        self.event_server_port: Optional[int] = None
        # --- End New HTTP Event Server ---

    def _strip_quotes(self, value: str) -> str:
        """Removes leading/trailing single or double quotes from a string."""
        if (value.startswith("'") and value.endswith("'")) or (
            value.startswith('"') and value.endswith('"')
        ):
            return value[1:-1]
        return value

    def _get_fzf_style_options(self) -> List[str]:
        """Returns a list of basic styling options for FZF."""
        style = [
            "--history-size=1000",
            "--layout=reverse",
            "--border=rounded",
            "--margin=1,2",
            "--height=100%",
            "--ansi",
        ]
        # Apply FZF_COLORS for basic theming if not using a more complex theme system.
        # This provides a consistent default look if AppConfig doesn't specify other theme mechanisms.
        for k, v in FZF_COLORS.items():  # FZF_COLORS is a predefined dict
            style += ["--color", f"{k}:{v}"]

        # Add other general style options from config if needed
        # Example: if self.app_services.config.fzf_custom_style_option:
        # style.append(self.app_services.config.fzf_custom_style_option)
        return style

    def generate_core_fzf_bindings(self) -> str:
        """
        Generates the core essential key bindings for FZF to communicate with the app.
        """
        return ",".join(
            [
                f"enter:{self.build_fzf_event_http_action_command_str('enter')}",
                f"ctrl-r:{self.build_fzf_event_http_action_command_str('refresh')}",
                f"ctrl-c:{self.build_fzf_event_http_action_command_str('exit-request')}+abort",
                "ctrl-l:clear-screen",
                f"change:{self.build_fzf_event_http_action_command_str('change-query', fzf_event_raw_line_data_placeholder='{q}')}",
                f"ctrl-u:{self.build_fzf_event_http_action_command_str('clear-query', fzf_event_raw_line_data_placeholder='placeholder')}",
            ]
        )

    def build_fzf_event_http_action_command_str(
        self,
        event_key_literal: str,
        fzf_event_raw_line_data_placeholder: str = "{..}",
    ) -> str:
        """
        Builds the shell command string for an fzf action that sends an event
        to the internal HTTP server.
        """
        if self.event_server_port is None:
            self.logger.error("Cannot build event action command: Event server port not set.")
            # Return a command that does nothing but log, to avoid crashing fzf
            return "execute(echo 'KubeZen: Event server not ready' >&2)"

        # Use the provided placeholder (e.g., {..} or {q})
        # The data is sent as the raw request body.
        # No more shlex.quote on the placeholder
        return (
            f"execute-silent(curl -s -X POST "
            f"--data-binary {fzf_event_raw_line_data_placeholder} "
            f"http://localhost:{self.event_server_port}/{event_key_literal})"
        )

    async def start_fzf(
        self,
    ) -> bool:
        self.logger.debug(
            f"[DIAGNOSTIC] start_fzf called. _fzf_launch_attempted={self._fzf_launch_attempted}, fzf_window_id={self.fzf_window_id}, fzf_pane_id={self.fzf_pane_id}"
        )
        # Defensive reset: if FZF is not running, always allow launch
        if not self.fzf_window_id or not self.fzf_pane_id:
            self.logger.debug(
                "[DIAGNOSTIC] FZF window_id or pane_id not set. Resetting _fzf_launch_attempted to False."
            )
            self._fzf_launch_attempted = False
        self.logger.info("Attempting to launch FZF process with HTTP server...")

        assert self.app_services.navigation_coordinator is not None
        initial_fzf_actions = await self.app_services.navigation_coordinator.start()
        if not initial_fzf_actions:
            self.logger.error(
                "No initial FZF actions from NavigationCoordinator. Cannot start FZF."
            )
            return False

        prompt_from_initial_actions: Optional[str] = None
        header_from_initial_actions: Optional[str] = None
        initial_item_provider_command: Optional[str] = None

        if initial_fzf_actions:
            self.logger.debug(
                f"Processing initial_fzf_actions for prompt/header/initial_command extraction: {initial_fzf_actions}"
            )
            temp_actions_for_api = []
            for action_str in initial_fzf_actions:
                if action_str.startswith("change-prompt("):
                    content = action_str[len("change-prompt("): -1]
                    prompt_from_initial_actions = self._strip_quotes(content)
                elif action_str.startswith("change-header("):
                    content = action_str[len("change-header("): -1]
                    header_from_initial_actions = self._strip_quotes(content)
                elif action_str.startswith("reload(") and action_str.endswith(")"):
                    extracted_command_str = action_str[len("reload("): -1]
                    initial_item_provider_command = self._strip_quotes(extracted_command_str)
                else:
                    temp_actions_for_api.append(action_str)
            initial_fzf_actions = temp_actions_for_api

        cmd_line_prompt_val = (
            prompt_from_initial_actions if prompt_from_initial_actions is not None else "KubeZen>"
        )
        cmd_line_header_val = (
            header_from_initial_actions if header_from_initial_actions is not None else ""
        )

        # First, check if a previously launched FZF instance is still responsive.
        if self.fzf_server_url and await self.is_running():
            self.logger.info("FZF listen port active. Attempting to reconfigure existing FZF.")
            actions_to_send = ["clear-query", "first"]
            if cmd_line_prompt_val:
                actions_to_send.append(f"change-prompt({cmd_line_prompt_val})")
            if cmd_line_header_val:
                actions_to_send.append(f"change-header({cmd_line_header_val})")
            if initial_fzf_actions:
                actions_to_send.extend(initial_fzf_actions)

            # If reconfiguring, and there was an initial_item_provider_command, use it for reload.
            if initial_item_provider_command:
                self.logger.info(
                    f"Reconfiguring with reload command: {initial_item_provider_command}"
                )
                actions_to_send.append(f"reload({initial_item_provider_command})")

            if await self.send_actions(actions_to_send):
                self.logger.info("Successfully reconfigured existing FZF instance.")
            return True

        # If not running, proceed to launch a new instance.
        if not (self.config and self.config.fzf_path):
            self.logger.error("FZF path is not configured.")
            return False

        # --- Corrected FZF Command Construction ---
        fzf_base_command_parts = [str(self.config.fzf_path)]
        fzf_base_command_parts.extend(self._get_fzf_style_options())

        # Add prompt and header
        fzf_base_command_parts.extend(["--prompt", cmd_line_prompt_val])
        if cmd_line_header_val:
            fzf_base_command_parts.extend(["--header", cmd_line_header_val])

        # Add listen port for the API
        listen_port = self._find_free_port()
        fzf_base_command_parts.extend(["--listen", str(listen_port)])
        self.fzf_server_url = f"http://localhost:{listen_port}"

        # Add delimiter and data processing options
        fzf_base_command_parts.extend(["--delimiter", "|", "--with-nth", "-1"])

        # Add bindings
        fzf_base_command_parts.extend(["--bind", self.generate_core_fzf_bindings()])

        # Quote all parts of the fzf command for safety
        quoted_fzf_command = " ".join(shlex.quote(part) for part in fzf_base_command_parts)

        # --- Final Shell Command Assembly ---
        if self.config:
            exports = [
                f"export FZF_API_KEY={self.config.fzf_api_key}",
                f"export KUBEZEN_SESSION_DIR={self.config.get_temp_dir_path()}",
                "export FZF_DEFAULT_COMMAND=''",
            ]
        else:
            exports = []

        exports_str = "; ".join(exports) + "; " if exports else ""

        if initial_item_provider_command:
            # Pipe the output of the item provider script into fzf
            full_command_str = (
                f"{exports_str}{initial_item_provider_command} | {quoted_fzf_command}"
            )
        else:
            # If no item provider, pipe an empty string to start fzf without items
            full_command_str = f"{exports_str}echo '' | {quoted_fzf_command}"

        self.logger.debug(f"Final shell command for new FZF window: {full_command_str}")

        try:
            tmux_ui = self.tmux_ui_manager
            launch_result = await tmux_ui.launch_command_in_new_window(
                command_str=full_command_str,
                window_name="KubeZen-FZF",
                task_name="KubeZen FZF Launcher",
                attach=True,
                set_remain_on_exit=False,
            )

            if not launch_result or "window_id" not in launch_result:
                self.logger.error(f"Failed to launch FZF in new window. Result: {launch_result}")
                return False

            self.fzf_window_id = launch_result.get("window_id")
            self.fzf_pane_id = launch_result.get("pane_id")

            self.logger.info(
                f"FZF launched. Window ID: {self.fzf_window_id}, Pane ID: {self.fzf_pane_id}, Server URL: {self.fzf_server_url}"
            )
            return True

        except FzfLaunchError as fle:
            self.logger.error(f"FzfLaunchError: {fle}")
            await self.stop()
            raise
        except Exception as e:
            self.logger.error(f"Exception during FZF launch: {e}", exc_info=True)
            await self.stop()  # Ensure cleanup on any launch exception
            return False

    async def send_actions(self, actions: List[str]) -> bool:
        """Sends a list of actions to the FZF API."""
        if not actions:
            return True

        concatenated_actions = "+".join(actions)
        self.logger.debug(
            f"TIMING: Preparing to send actions at {time.perf_counter():.4f}. Actions: {actions!r}"
        )
        # self.logger.debug(
        #     f"Sending actions to FZF (concatenated for form-urlencoded): {concatenated_actions}"
        # ) # Original log, commented for now to reduce noise if new one is better

        start_time = time.perf_counter()
        response = await self._make_fzf_api_request("POST", "", payload_str=concatenated_actions)
        end_time = time.perf_counter()
        duration_ms = (end_time - start_time) * 1000
        self.logger.debug(
            f"TIMING: FZF API call for actions completed in {duration_ms:.2f} ms. Response: {response is not None}"
        )
        return response is not None and response.get("status") == "success"

    async def _ensure_client_session(self) -> aiohttp.ClientSession:
        """Ensures the aiohttp client session is ready."""
        if self.fzf_client_session and not self.fzf_client_session.closed:
            return self.fzf_client_session

        self.logger.debug("Creating new aiohttp.ClientSession or replacing closed one.")
        session_headers = {
            "Content-Type": "application/json",
            "X-API-Key": self.config.fzf_api_key,
        }
        self.fzf_client_session = aiohttp.ClientSession(headers=session_headers)
        return self.fzf_client_session

    async def _make_fzf_api_request(
        self, method: str, endpoint_suffix: str, payload_str: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Makes an API request to the running FZF process."""
        request_start_time = time.monotonic()
        url = f"{self.fzf_server_url}/{endpoint_suffix}"
        self.logger.debug(f"Making FZF API request to {url}")

        try:
            session = await self._ensure_client_session()
            headers = {}
            if self.config.fzf_api_key:
                headers["X-API-Key"] = self.config.fzf_api_key

            async with session.request(
                method,
                url,
                data=payload_str,
                headers=headers,
                timeout=self.config.fzf_api_timeout_seconds,
                ssl=False,  # Explicitly disable SSL for this request
            ) as response:
                response_text = await response.text()
                if response.status == 200:
                    self.logger.info(
                        f"FZF_API_RESPONSE: Status={response.status}, Headers={response.headers}, RawContent='{response_text}' at {time.perf_counter():.4f}"
                    )
                    # Attempt to parse as JSON, but it's okay if it fails
                    try:
                        json_data = await response.json()
                        if isinstance(json_data, dict):
                            return json_data
                        return {"raw_content": response_text}
                    except aiohttp.ContentTypeError:
                        return {"raw_content": response_text}
                else:
                    self.logger.error(
                        f"FZF API request to {url} failed with status {response.status}: {response_text}"
                    )
        except asyncio.TimeoutError:
            self.logger.error(
                f"FZF API request to {url} timed out after {self.config.fzf_api_timeout_seconds}s."
            )
        except aiohttp.ClientConnectorError as e:
            self.logger.error(
                f"FZF API connection error ({method} {endpoint_suffix}): {e}. FZF might be down."
            )
            return None
        except Exception as e:
            self.logger.error(
                f"Unexpected error in FZF API request ({method} {endpoint_suffix}): {e}",
                exc_info=True,
            )
            return None
        finally:
            duration_ms = (time.monotonic() - request_start_time) * 1000
            self.logger.debug(
                f"TIMING: FZF API call for actions completed in {duration_ms:.2f} ms. Response: False"
            )

        return None

    async def is_running(self, retries: int = 3, delay: float = 0.2) -> bool:
        """
        Checks if the FZF server is responsive by pinging its root endpoint.
        Includes a retry mechanism to handle startup delays.
        """
        if not self.fzf_server_url:
            return False

        for attempt in range(retries):
            try:
                # REUSE the main session, do not create a new one
                session = await self._ensure_client_session()
                async with session.get(self.fzf_server_url, timeout=1.0) as response:
                    # No need to check response.status == 200, any successful connection is enough
                    if response.status < 500:  # Any non-server-error response is good
                        return True
            except (aiohttp.ClientError, asyncio.TimeoutError):
                self.logger.debug(
                    f"FZF health check failed on attempt {attempt + 1}/{retries}. Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)

        self.logger.warning(
            f"FZF server at {self.fzf_server_url} is not responsive after {retries} attempts."
        )
        return False

    async def _handle_fzf_event(self, request: web.Request) -> web.Response:
        """
        Handles incoming HTTP requests from FZF actions.
        """
        try:
            event_key = request.path.lstrip("/")
            raw_data = await request.text()

            self.logger.debug(
                f"HTTP Event Server received event. Key: '{event_key}', Data: '{raw_data}'"
            )

            event_data = {
                "event_key": event_key,
                "fzf_event_raw_line_data": raw_data,
                "timestamp": time.time(),
            }

            # Additional parsing for events that contain structured data
            if "|" in raw_data:
                parts = raw_data.split("|", 2)
                event_data["action_code"] = parts[0]
                event_data["view_session_id"] = parts[1] if len(parts) > 1 else None
                event_data["selected_text_display"] = parts[2] if len(parts) > 2 else ""
            else:
                # For simple events like 'change-query', the raw_data is the whole action_code
                event_data["action_code"] = raw_data

            event = self._create_event_from_data(event_data)
            if event and self.event_bus:
                await self.event_bus.publish(event)
            return web.Response(status=200)
        except Exception as e:
            self.logger.error(f"Error handling FZF event: {e}")
            return web.Response(status=500)

    def _create_event_from_data(self, event_data: Dict[str, Any]) -> Optional[Event]:
        """Creates an Event object from FZF event data."""
        event_key = event_data.get("event_key")

        if event_key == "enter":
            return FzfSelectionEvent(event_data)
        elif event_key == "refresh":
            return FzfRefreshRequestEvent(event_data)
        elif event_key == "change-query":
            return FzfQueryChangeEvent(event_data)
        elif event_key == "clear-query":
            return FzfClearQueryEvent(event_data)
        elif event_key == "exit-request":
            return FzfExitRequestEvent(event_data)
        elif event_key == "esc":
            return UnhandledEvent(event_data)  # Let UiEventHandler map this to ToParentSignal

        self.logger.warning(f"Unhandled event key: '{event_key}'. Creating UnhandledEvent.")
        return UnhandledEvent(event_data)

    async def start_services(self) -> bool:
        """
        Starts the necessary services for the FzfUIManager, primarily the
        internal HTTP event server.
        """
        self.logger.debug("Starting FZF UI Manager services...")
        try:
            # Start the internal HTTP server for receiving fzf events
            self.event_server = web.Application()
            self.event_server.add_routes(
                [
                    web.post("/{event_key}", self._handle_fzf_event),
                ]
            )
            self.event_server_runner = web.AppRunner(self.event_server)
            await self.event_server_runner.setup()

            # Find a free port
            sock = socket.socket()
            sock.bind(("localhost", 0))
            self.event_server_port = sock.getsockname()[1]
            sock.close()

            self.event_server_site = web.TCPSite(
                self.event_server_runner, "localhost", self.event_server_port
            )
            await self.event_server_site.start()
            self.logger.info(
                f"FZF Event Server started on http://localhost:{self.event_server_port}"
            )

            return True
        except Exception as e:
            self.logger.error(
                f"Failed to start event server on port {self.event_server_port}: {e}",
                exc_info=True,
            )
            return False

    async def stop(self) -> None:
        """Gracefully stops all managed services."""
        self.logger.info("Stopping FZF UI Manager services...")
        # First, terminate the fzf process and client session
        if self.fzf_client_session and not self.fzf_client_session.closed:
            await self.fzf_client_session.close()
            self.fzf_client_session = None
            self.logger.info("FZF client session closed.")

        self.fzf_server_url = None

        # Then, shut down the event server
        if self.event_server_runner:
            await self.event_server_runner.cleanup()
            self.logger.info("FZF event server shut down.")

    def _find_free_port(self) -> int:
        """Finds a free TCP port to use for the servers."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return cast(int, s.getsockname()[1])
