from __future__ import annotations
import logging
import os
import shlex
import sys
from pathlib import Path
from typing import Optional

import click
from libtmux import Server
import yaml

from .config import AppConfig

log = logging.getLogger(__name__)


def _launch_logic(  # pylint: disable=R1260
    ctx: click.Context,
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

    click.echo(f"Launching KubeZen TUI in tmux session '{config.session_name}'...")

    # --- Get paths from our centralized config ---
    socket_path = config.paths.tmux_socket_path
    tmux_config = config.paths.resources.get("tmux-config")

    # Define the log file path in /tmp
    log_file_path = Path("/tmp") / "kubezen.log"
    if log_file_path.exists():
        try:
            log_file_path.unlink()
        except OSError as e:
            # Log an error if we can't delete the old log file, but continue
            logging.warning(f"Could not remove old log file: {e}")


    python_executable = sys.executable

    if getattr(sys, "frozen", False):
        app_command = shlex.join([str(python_executable), "--tui"])
    else:
        run_script_path = os.path.join(config.paths.base_path, "run_kubezen.py")
        app_command = shlex.join([str(python_executable), run_script_path, "--tui"])
    crasher_script_path = shlex.quote(str(config.paths.base_path / "bin/crasher.sh"))
    window_command = f"{app_command}; if [ $? -ne 0 ]; then {crasher_script_path}; fi"

    session_env = os.environ.copy()

    session_env["KUBEZEN_LOG_FILE"] = str(log_file_path)
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
        with Server(
            socket_path=socket_path,
            config_file=str(tmux_config) if tmux_config else None,
        ) as server:
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

def validate_kubeconfig(ctx, param, value):
    if value:
        path = Path(value).expanduser()
        if not path.exists():
            raise click.BadParameter(f"Kubeconfig file not found: {path}")
        if not path.is_file():
            raise click.BadParameter(f"Kubeconfig path is not a file: {path}")
    return value

def validate_context(ctx, param, value):
    if not value:
        return value

    kubeconfig_path = ctx.params.get("kubeconfig") or os.environ.get("KUBECONFIG")
    if not kubeconfig_path:
        kubeconfig_path = os.path.expanduser("~/.kube/config")

    kubeconfig_path = os.path.expanduser(kubeconfig_path)
    if not os.path.exists(kubeconfig_path):
        raise click.BadParameter(f"Kubeconfig file not found: {kubeconfig_path}")

    try:
        with open(kubeconfig_path, "r") as f:
            config = yaml.safe_load(f)
        available_contexts = [c["name"] for c in config.get("contexts", [])]
    except Exception as e:
        raise click.BadParameter(f"Failed to read kubeconfig: {e}")

    if value not in available_contexts:
        raise click.BadParameter(
            f"Context '{value}' not found in kubeconfig '{kubeconfig_path}'. "
            f"Available: {', '.join(available_contexts)}"
        )

    return value

@click.group(invoke_without_command=True)
@click.option(
    "--kubeconfig",
    envvar="KUBECONFIG",
    callback=validate_kubeconfig,
    help="Path to the kubeconfig file.",
    is_eager=True,
)
@click.option(
    "--context",
    envvar="KUBE_CONTEXT",
    callback=validate_context,
    help="The name of the kubeconfig context to use.",
)
@click.option(
    "--debug", is_flag=True, help="Enable asyncio debug mode and visual indicator."
)
@click.pass_context
def main(
    ctx: click.Context,  # pylint: disable=W0613
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
            kubeconfig=kubeconfig,
            context=context,
            debug=debug,
        )

if __name__ == "__main__":
    main()
