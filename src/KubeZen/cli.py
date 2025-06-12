import os
import sys
import signal
import tracemalloc
from typing import cast, Optional
from types import FrameType
import libtmux
import click
import datetime
import traceback

from KubeZen.config import AppConfig

# Add src directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
src_dir = os.path.join(project_root, "src")
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

print("[cli.py INFO] Script started", file=sys.stderr)


def cleanup_old_logs(app_config: AppConfig) -> None:
    """Deletes old log files, keeping only the most recent N."""
    try:
        log_dir = app_config.permanent_log_dir
        retention_count = app_config.log_retention_count

        if not log_dir.is_dir():
            return

        log_files = [
            f
            for f in log_dir.iterdir()
            if f.is_file() and f.name.startswith("core_ui_runner_") and f.name.endswith(".log")
        ]

        if len(log_files) <= retention_count:
            return

        # Sort files by modification time, oldest first
        log_files.sort(key=lambda f: f.stat().st_mtime)

        # Determine how many files to delete
        files_to_delete = log_files[:-retention_count]

        deleted_count = 0
        for log_file in files_to_delete:
            try:
                log_file.unlink()
                deleted_count += 1
            except OSError as e:
                print(
                    f"CLI WARNING: Could not delete old log file: {log_file}. Error: {e}",
                    file=sys.stderr,
                )

        if deleted_count > 0:
            print(
                f"CLI INFO: Log Rotation: Cleaned up {deleted_count} old log file(s).",
                file=sys.stderr,
            )

    except Exception as e:
        print(
            f"CLI ERROR: An unexpected error occurred during log cleanup: {e}",
            file=sys.stderr,
        )


def signal_handler(signum: int, frame: Optional[FrameType]) -> None:
    """Handle termination signals."""
    print(f"\nReceived signal {signum}. Cleaning up...", file=sys.stderr)
    sys.exit(0)


@click.command()
@click.option(
    "--enable-tracemalloc",
    is_flag=True,
    hidden=True,
    help="Enable tracemalloc for memory debugging.",
)
def cli(enable_tracemalloc: bool) -> None:
    """Main entry point for the KubeZen CLI."""
    if enable_tracemalloc:
        tracemalloc.start()
        print("[cli.py INFO] tracemalloc enabled.", file=sys.stderr)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app_config_instance = None

    try:
        # --- Stage 1: Initialize AppConfig ---
        app_config_instance = AppConfig()
        print(f"CLI INFO: KubeZen CLI (PID: {os.getpid()}) starting...", file=sys.stderr)

        # --- Perform log cleanup ---
        cleanup_old_logs(app_config_instance)

        # --- Stage 2: Set up environment variables ---
        try:
            # Export the config to a file for the subprocess
            config_export_path = app_config_instance.export_to_file()
            os.environ["KUBEZEN_CONFIG_FILE"] = str(config_export_path)
            os.environ["KUBEZEN_SOCKET_PATH"] = str(app_config_instance.tmux_socket_path)
            os.environ["KUBEZEN_SESSION_NAME"] = app_config_instance.kubezen_session_name
            os.environ["KUBEZEN_MAIN_WINDOW_NAME"] = (
                app_config_instance.kubezen_initial_window_name
            )
            os.environ["KUBEZEN_SESSION_TEMP_DIR"] = str(app_config_instance.session_temp_dir)
        except KeyError as e:
            print(
                f"CLI CRITICAL: Failed to set required environment variable {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        # --- Stage 3: Launch CoreUI in tmux session ---
        print("CLI INFO: Launching KubeZen CoreUI in tmux session...", file=sys.stderr)

        # Get tmux configuration
        kubezen_tmux_config = str(app_config_instance.kubezen_tmux_config_path)
        print(f"CLI INFO: Using KubeZen tmux config: {kubezen_tmux_config}", file=sys.stderr)

        # Set up the core_ui_runner command
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_filename = f"core_ui_runner_{timestamp}_{os.getpid()}.log"
        core_ui_runner_log_file = app_config_instance.permanent_log_dir / log_filename

        print(
            f"CLI INFO: Core UI runner output will be logged to: {core_ui_runner_log_file}",
            file=sys.stderr,
        )

        window_command = (
            f"'{sys.executable}' -m KubeZen.core_ui_runner >'{core_ui_runner_log_file}' 2>&1"
        )

        try:
            print("CLI INFO: Initializing tmux server...", file=sys.stderr)
            with libtmux.Server(
                socket_path=app_config_instance.tmux_socket_path,
                config_file=kubezen_tmux_config,
            ) as server:
                print(
                    f"CLI INFO: Tmux server initialized with socket: {app_config_instance.tmux_socket_path}",
                    file=sys.stderr,
                )

                # Create new session with core_ui_runner
                print("CLI INFO: Creating new tmux session...", file=sys.stderr)
                with server.new_session(
                    session_name=app_config_instance.kubezen_session_name,
                    attach=False,
                    window_name=app_config_instance.kubezen_initial_window_name,
                    window_command=window_command,
                    environment=cast(dict[str, str], os.environ),
                ) as session:
                    print(
                        f"CLI INFO: Tmux session '{session.name}' created successfully",
                        file=sys.stderr,
                    )

                    # Attach to the session
                    print(f"CLI INFO: Attaching to session '{session.name}'...", file=sys.stderr)
                    try:
                        session.attach()
                        print("CLI INFO: Session detached or ended", file=sys.stderr)
                    except libtmux.exc.LibTmuxException as e:
                        if "no server running" in str(e):
                            print(
                                "CLI INFO: Tmux session ended and server shut down cleanly.",
                                file=sys.stderr,
                            )
                        else:
                            print(f"CLI ERROR: Error during tmux session: {e}", file=sys.stderr)
                            raise

        except libtmux.exc.LibTmuxException as e:
            print(f"CLI ERROR: Tmux error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"CLI ERROR: Failed to launch CoreUI in tmux: {e}", file=sys.stderr)
            sys.exit(1)

        print("CLI INFO: KubeZen CoreUI process completed successfully.", file=sys.stderr)

    except Exception as e:
        print(f"CLI CRITICAL: Critical error in KubeZen CLI: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
    finally:
        # --- Guaranteed Cleanup ---
        if app_config_instance:
            try:
                # The cleanup method itself checks for debug mode
                app_config_instance.cleanup_temp_dirs()
                if app_config_instance.debug_mode:
                    print(
                        "CLI INFO: Cleanup skipped (debug mode). Temporary files preserved.",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "CLI INFO: Temporary directory cleaned up successfully.",
                        file=sys.stderr,
                    )
            except Exception as e:
                print(f"CLI ERROR: Error during temp directory cleanup: {e}", file=sys.stderr)
