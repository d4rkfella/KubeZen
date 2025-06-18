from __future__ import annotations
import logging
import os
import shlex
import sys
import time
from typing import Optional

import click
import libtmux

from .config import AppConfig

# Set up logging for the main entry point
log = logging.getLogger(__name__)


def _launch_logic(  # pylint: disable=R1260
    ctx: click.Context,
    session_name: Optional[str],
    kubeconfig: Optional[str],
    context: Optional[str],
    debug: bool,
) -> None:
    """The core logic for launching the KubeZen TUI."""
    # Use a basic logger for the launch script itself
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(levelname)s - %(message)s"
    )

    try:
        config = AppConfig.get_instance()
    except Exception as e:
        logging.basicConfig(
            level=logging.INFO, stream=sys.stderr, format="%(levelname)s - %(message)s"
        )
        logging.error("Failed to initialize configuration: %s", e, exc_info=True)
        click.echo(f"Error: Failed to initialize configuration. {e}", err=True)
        sys.exit(1)

    # Allow session name override from the command line
    if session_name:
        config.session_name = session_name

    click.echo(f"Launching KubeZen TUI in tmux session '{config.session_name}'...")

    # --- Get paths from our centralized config ---
    tmux_config_path = config.paths.tmux_config_path
    socket_path = config.paths.tmux_socket_path

    python_executable = sys.executable

    log_file_path = config.paths.base_path / "kubezen.log"
    if log_file_path.exists():
        log_file_path.unlink()

    if getattr(sys, "frozen", False):
        app_command = shlex.join([str(python_executable), "--tui"])
    else:
        run_script_path = os.path.join(config.paths.base_path, "run_kubezen.py")
        app_command = shlex.join([str(python_executable), run_script_path, "--tui"])
    crasher_script_path = shlex.quote(str(config.paths.base_path / "bin/crasher.sh"))
    window_command = f"{app_command}; if [ $? -ne 0 ]; then {crasher_script_path}; fi"

    session_env = os.environ.copy()
    session_env["KUBEZEN_LOG_FILE"] = str(log_file_path)
    session_env["KUBEZEN_SOCKET_PATH"] = str(socket_path)
    session_env["KUBEZEN_TEMP_DIR"] = str(config.paths.temp_dir)

    if kubeconfig:
        session_env["KUBECONFIG"] = kubeconfig
    if context:
        session_env["KUBE_CONTEXT"] = context

    # Enable debug mode if the flag is set.
    if debug:
        # This makes asyncio much more verbose about un-awaited coroutines.
        session_env["PYTHONASYNCIODEBUG"] = "1"
        # This signals the TUI to add a visual indicator.
        session_env["KUBEZEN_DEBUG"] = "1"

    try:
        server = libtmux.Server(
            socket_path=str(socket_path),
            config_file=str(tmux_config_path) if tmux_config_path else None,
        )

        existing_session = server.find_where({"session_name": config.session_name})
        if existing_session:
            click.echo(f"Found and killing existing session: {config.session_name}")
            existing_session.kill_session()
            time.sleep(0.2)

        click.echo("Creating new tmux session...")
        session = server.new_session(
            session_name=config.session_name,
            attach=False,
            window_name="KubeZen",
            window_command=window_command,
            environment=session_env,
        )

        click.echo(f"Tmux session '{session.name}' created. Attaching...")
        session.attach_session()
        click.echo("Session detached or ended.")

    except Exception as e:
        logging.error("Failed to launch KubeZen TUI in tmux: %s", e, exc_info=True)
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        config.cleanup()


@click.group(invoke_without_command=True)
@click.option("--session-name", default=None, help="The name of the tmux session.")
@click.option("--kubeconfig", envvar="KUBECONFIG", help="Path to the kubeconfig file.")
@click.option(
    "--context",
    envvar="KUBE_CONTEXT",
    help="The name of the kubeconfig context to use.",
)
@click.option(
    "--debug", is_flag=True, help="Enable asyncio debug mode and visual indicator."
)
@click.pass_context
def main(
    ctx: click.Context,  # pylint: disable=W0613
    session_name: Optional[str],
    kubeconfig: Optional[str],
    context: Optional[str],
    debug: bool,
) -> None:
    """A TUI for Kubernetes management. Launches the TUI by default."""
    # If no subcommand is invoked, run the launch logic
    if ctx.invoked_subcommand is None:
        # pylint: disable=no-value-for-parameter
        _launch_logic(
            ctx=ctx,
            session_name=session_name,
            kubeconfig=kubeconfig,
            context=context,
            debug=debug,
        )


if __name__ == "__main__":
    main()
