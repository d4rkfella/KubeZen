from __future__ import annotations
import os
import shlex
import sys
from pathlib import Path
from typing import Optional

import click
from libtmux import Server
from libtmux.exc import TmuxCommandNotFound
import yaml

from KubeZen.config import AppConfig
from KubeZen.app import main as run_app


def _launch_logic(
    kubeconfig: Optional[str],
    context: Optional[str],
    debug: bool,
    log_level: str,
) -> None:
    """The core logic for launching the KubeZen TUI inside a tmux session."""
    click.echo("Launching KubeZen TUI in tmux session...")

    config = AppConfig.get_instance()

    socket_path = config.paths.tmux_socket_path
    tmux_config = config.paths.resources.get("tmux-config")
    log_file_path = Path("/tmp") / "kubezen.log"
    if log_file_path.exists():
        try:
            log_file_path.unlink()
        except OSError:
            pass  # Ignore errors

    if getattr(sys, "frozen", False):
        app_command = shlex.join([sys.executable, "tui"])
    else:
        app_command = "kubezen tui"

    window_command = (
        f"{app_command}; "
        "exit_code=$?; "
        "if [ $exit_code -ne 0 ]; then "
        'echo; echo "--- KubeZen has crashed (exit code: $exit_code) ---"; '
        "read -p 'Press Enter to close this pane...'; "
        "fi"
    )

    session_env = os.environ.copy()
    session_env["KUBEZEN_LOG_FILE"] = str(log_file_path)
    if kubeconfig:
        session_env["KUBECONFIG"] = kubeconfig
    if context:
        session_env["KUBE_CONTEXT"] = context
    if log_level:
        session_env["LOG_LEVEL"] = log_level
    if log_level == "DEBUG":
        session_env["PYTHONASYNCIODEBUG"] = "1"

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
            click.echo("Session ended.")
    except TmuxCommandNotFound:
        click.secho("ERROR: Application binary for tmux not found.", fg="red", err=True)
        sys.exit(1)
    finally:
        click.echo("Cleaning up...")
        config.cleanup()


def validate_kubeconfig(ctx, param, value):
    if value:
        path = Path(value).expanduser()
        if not path.is_file():
            click.secho(
                f"ERROR: Kubeconfig path is not a file: {path}", fg="red", err=True
            )
            sys.exit(1)
    return value


def validate_context(ctx, param, value):
    if not value:
        return value
    kubeconfig_path = ctx.params.get("kubeconfig") or os.environ.get("KUBECONFIG")
    if not kubeconfig_path:
        kubeconfig_path = Path.home() / ".kube" / "config"
    config_path = Path(kubeconfig_path).expanduser()
    if not config_path.exists():
        raise click.BadParameter(f"Kubeconfig file not found: {config_path}")
    try:
        config_data = yaml.safe_load(config_path.read_text())
        contexts = [c["name"] for c in config_data.get("contexts", [])]
        if value not in contexts:
            raise click.BadParameter(
                f"Context '{value}' not found. Available: {', '.join(contexts)}"
            )
    except Exception as e:
        raise click.BadParameter(f"Failed to read kubeconfig: {e}")
    return value


@click.group(
    invoke_without_command=True,
    context_settings=dict(help_option_names=["-h", "--help"]),
)
@click.option(
    "--kubeconfig",
    envvar="KUBECONFIG",
    callback=validate_kubeconfig,
    help="Path to the kubeconfig file.",
)
@click.option(
    "--context",
    envvar="KUBE_CONTEXT",
    callback=validate_context,
    help="The name of the kubeconfig context to use.",
)
@click.option("--debug", is_flag=True, help="Enable debug mode.")
@click.option(
    "--log_level",
    envvar="LOG_LEVEL",
)
@click.pass_context
def main(
    ctx: click.Context,
    kubeconfig: Optional[str],
    context: Optional[str],
    debug: bool,
    log_level: str,
) -> None:
    """A TUI for Kubernetes management.

    This command acts as a launcher. By default (with no sub-command),
    it sets up a tmux session and launches the TUI inside it.
    """
    if ctx.invoked_subcommand is None:
        _launch_logic(
            kubeconfig=kubeconfig,
            context=context,
            debug=debug,
            log_level=log_level,
        )


@main.command(hidden=True)
def tui() -> None:
    """Run the KubeZen TUI application directly.

    This is intended to be run inside the tmux session created by the main launcher.
    """
    import asyncio

    asyncio.run(run_app())


if __name__ == "__main__":
    main()
