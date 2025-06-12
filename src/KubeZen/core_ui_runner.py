import sys
import os
import asyncio
import traceback
import logging


_core_ui_runner_file_path = os.path.abspath(__file__)
_src_directory_path = os.path.dirname(os.path.dirname(_core_ui_runner_file_path))

if _src_directory_path not in sys.path:
    sys.path.insert(0, _src_directory_path)
# --- End of sys.path modification ---

# KubeZen project imports
from KubeZen.config import AppConfig, BinaryNotFoundError  # noqa: E402
from KubeZen.logger import setup_logging  # noqa: E402
from KubeZen.core.app_services import AppServices  # noqa: E402
from KubeZen.core.app_controller import AppController  # noqa: E402
from KubeZen.core.fzf_ui_manager import FzfUIManager  # noqa: E402
from KubeZen.core.kubernetes_client import KubernetesClient  # noqa: E402
from KubeZen.core.tmux_ui_manager import TmuxUIManager  # noqa: E402
from KubeZen.core.kubernetes_watch_manager import KubernetesWatchManager  # noqa: E402
from KubeZen.core.user_input_manager import UserInputManager  # noqa: E402
from KubeZen.core.exceptions import TmuxEnvironmentError  # noqa: E402
from KubeZen.core.event_bus import EventBus  # noqa: E402
from KubeZen.core.ui_event_handler import UiEventHandler  # noqa: E402
from KubeZen.ui.navigation_coordinator import NavigationCoordinator  # noqa: E402
from KubeZen.ui.view_setup import create_and_populate_view_registry  # noqa: E402
from KubeZen.core.error_handler import handle_uncaught_exception  # noqa: E402

print("[core_ui_runner] Script execution started.", file=sys.stderr)


async def main() -> None:
    app_controller_instance = None
    app_services_instance = None
    app_config = AppConfig()

    # Initialize logger using the new setup function
    logger = setup_logging(process_name="CoreUI")

    try:
        # --- Stage 2: Initialize AppServices ---
        app_services_instance = AppServices(config=app_config, logger=logger)
        assert logger is not None  # Assure mypy that logger exists after the check above
        logger.info(f"KubeZen Core UI Runner (PID: {os.getpid()}) starting...")
        logger.info("AppServices initialized.")

        # --- Stage 3: Initialize EventBus ---
        event_bus = EventBus(logger=logger)
        app_services_instance.event_bus = event_bus
        logger.info("EventBus initialized.")

        # --- Stage 4: Initialize Core Services (in dependency order) ---
        try:
            # These environment variables are critical for tmux operation
            main_window_name = os.environ["KUBEZEN_MAIN_WINDOW_NAME"]
            session_name = os.environ["KUBEZEN_SESSION_NAME"]
        except KeyError as e:
            logger.error(f"Critical error: Required environment variable {e} not set")
            sys.exit(1)

        tmux_ui_manager = TmuxUIManager(
            app_services=app_services_instance,
            main_window_name=main_window_name,
            session_name=session_name,
        )
        await tmux_ui_manager.initialize_environment()
        app_services_instance.tmux_ui_manager = tmux_ui_manager
        logger.info("TmuxUIManager initialized.")

        # Initialize the view registry and report any errors
        view_registry, view_errors = create_and_populate_view_registry()
        if view_errors:
            for error in view_errors:
                await tmux_ui_manager.show_toast(
                    message=f"View Load Error: {error}",
                    duration=10,
                    bg_color="red",
                    fg_color="white",
                )

        fzf_ui_manager = FzfUIManager(app_services=app_services_instance)
        await fzf_ui_manager.start_services()  # Start FZF's own services (e.g., HTTP server)
        app_services_instance.fzf_ui_manager = fzf_ui_manager
        logger.info("FzfUIManager initialized.")

        user_input_manager = UserInputManager(
            app_services=app_services_instance,
        )
        app_services_instance.user_input_manager = user_input_manager
        logger.info("UserInputManager initialized.")

        kubernetes_client = await KubernetesClient.create(app_services=app_services_instance)
        app_services_instance.kubernetes_client = kubernetes_client
        logger.info("KubernetesClient initialized.")

        kubernetes_watch_manager = KubernetesWatchManager(app_services=app_services_instance)
        app_services_instance.kubernetes_watch_manager = kubernetes_watch_manager
        logger.info("KubernetesWatchManager initialized.")

        # Initialize the navigation coordinator with the view registry
        navigation_coordinator = NavigationCoordinator(
            app_services=app_services_instance,
            view_registry=view_registry,
        )
        app_services_instance.navigation_coordinator = navigation_coordinator
        logger.info("NavigationCoordinator initialized.")

        # --- Stage 5: Initialize Event Handlers ---
        ui_event_handler = UiEventHandler(app_services=app_services_instance)
        ui_event_handler.subscribe_to_events()
        app_services_instance.ui_event_handler = ui_event_handler
        await ui_event_handler.start()
        logger.info("UiEventHandler initialized.")

        # --- Stage 6: Create the AppController ---
        app_controller_instance = AppController(
            config=app_config, app_services=app_services_instance
        )
        logger.info("AppController initialized.")

        # --- Stage 7: Run the main application loop ---
        while True:
            try:
                await app_controller_instance.run_main_loop()
                # If the loop exits cleanly, we can break.
                logger.info("AppController main loop finished cleanly. Shutting down.")
                break
            except Exception as e:
                logger.error("An uncaught exception occurred in the main loop.", exc_info=True)
                if app_services_instance and app_services_instance.tmux_ui_manager:
                    await handle_uncaught_exception(e, app_services_instance.tmux_ui_manager)
                # After displaying the error, the loop will continue, allowing the app to recover.
                # We add a small sleep to prevent rapid-fire error loops.
                await asyncio.sleep(1)

    except BinaryNotFoundError as e:
        log_msg = f"Binary Not Found: {str(e)}"
        if logger:
            logger.error(log_msg, exc_info=True)
        else:
            print(f"KubeZen CoreUI ERROR: {log_msg}", file=sys.stderr)
        sys.exit(1)
    except TmuxEnvironmentError as e_tmux:
        log_msg = f"Tmux Environment Error: {e_tmux}"
        if logger:
            logger.error(log_msg, exc_info=True)
        else:
            print(f"KubeZen CoreUI ERROR: {log_msg}", file=sys.stderr)
        sys.exit(1)
    except EnvironmentError as e_env:
        log_msg = f"Environment Error: {e_env}"
        if logger:
            logger.error(log_msg, exc_info=True)
        else:
            print(f"KubeZen CoreUI ERROR: {log_msg}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e_rt:
        log_msg = f"Runtime Error during application setup: {e_rt}"
        if logger:
            logger.error(log_msg, exc_info=True)
        else:
            print(f"KubeZen CoreUI ERROR: {log_msg}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        log_msg = f"A critical error occurred in core_ui_runner: {e}"
        # --- Create Crash Dump ---
        try:
            from pathlib import Path
            import datetime

            crash_dir = Path.home() / ".kubezen" / "crashes"
            crash_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            crash_file_path = crash_dir / f"kubezen_crash_{timestamp}.log"

            with open(crash_file_path, "w") as f:
                f.write(f"KubeZen Critical Error at {timestamp}\n")
                f.write("=" * 80 + "\n")
                f.write(f"Error: {e}\n\n")
                f.write("Traceback:\n")
                traceback.print_exc(file=f)

            # Also print a message to stderr pointing to the crash file
            crash_message = f"CRITICAL ERROR: KubeZen has crashed. A crash report has been saved to: {crash_file_path}"
            print(crash_message, file=sys.stderr)
            if logger:
                logger.critical(crash_message)

        except Exception as dump_exc:
            # If we can't even write the dump file, just print to stderr
            print(f"FATAL: Could not write crash dump. Original error: {e}", file=sys.stderr)
            print(f"FATAL: Crash dump failed with: {dump_exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

        if logger:
            logger.error(log_msg, exc_info=True)
        else:
            print(log_msg, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    finally:
        if logger:
            logger.info("CoreUI: main() is exiting.")
        if app_controller_instance:
            try:
                await app_controller_instance.shutdown()
                if logger:
                    logger.info("CoreUI: AppController shutdown complete.")
            except Exception as e:
                if logger:
                    logger.error(
                        f"CoreUI: Error during AppController shutdown: {e}",
                        exc_info=True,
                    )
        logging.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("KubeZen CoreUI: Received KeyboardInterrupt. Exiting.", file=sys.stderr)
    except Exception as e:
        print(f"KubeZen CoreUI: A critical error occurred in main: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
