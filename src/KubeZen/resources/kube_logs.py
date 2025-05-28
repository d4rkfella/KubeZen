#!/usr/bin/env python3
import subprocess
import json
import re
import sys
import os
import tempfile
from typing import List, Tuple, Optional, Dict
import libtmux
from .kube_base import KubeBase # Adjusted import
import shutil # Added for shutil.which

class LogManager:
    """Manages logs for Kubernetes resources (pods, deployments, statefulsets, etc.)"""
    
    def __init__(self, base: KubeBase):
        self.base = base

    def get_containers(self, resource_type: str, resource_name: str, namespace: str) -> List[str]:
        """Get available containers for a resource using KubectlClient."""
        container_names = set()

        if resource_type == "pod":
            pod_spec = self.base.kubectl_client.get_resource_spec("pod", resource_name, namespace)
            if pod_spec:
                for container in pod_spec.get('spec', {}).get('containers', []):
                    container_names.add(container.get('name', 'unnamed-container'))
        else:
            # For other types like deployment, statefulset, daemonset
            resource_spec = self.base.kubectl_client.get_resource_spec(resource_type, resource_name, namespace)
            if resource_spec:
                selector = resource_spec.get('spec', {}).get('selector', {}).get('matchLabels')
                if selector:
                    label_selector_str = ",".join(f"{k}={v}" for k, v in selector.items())
                    pods = self.base.kubectl_client.get_pods_by_selector(namespace, label_selector_str)
                    for pod_spec in pods:
                        for container in pod_spec.get('spec', {}).get('containers', []):
                            container_names.add(container.get('name', 'unnamed-container'))
                else:
                    print(f"No selector found for {resource_type} {resource_name}", file=sys.stderr)
            else:
                print(f"Could not retrieve spec for {resource_type} {resource_name}", file=sys.stderr)
        
        if not container_names:
            print(f"No containers found for {resource_type} {resource_name} in {namespace}", file=sys.stderr)
        return list(container_names)

    def show_logs(self, resource_type: str, resource_name: str, namespace: str):
        """Show logs for a resource."""
        print(f"Showing logs for {resource_type} {resource_name} in namespace {namespace}")
        # get_containers will now print errors to stderr if any occur
        containers = self.get_containers(resource_type, resource_name, namespace)
        if not containers:
            # No need to print "No containers found" here as get_containers already does to stderr
            input("\nPress Enter to continue...")
            return

        if len(containers) == 1:
            selected_container = containers[0]
        else:
            print("Select container to show logs for:")
            container_options = ["<All Containers>"] + containers
            container_result = self.base.run_fzf(
                container_options,
                f"{resource_type.title()} Logs ({resource_name})",
                extra_header="Select container (Esc to cancel)",
                extra_bindings=["--bind", "enter:accept"],
                include_common_elements=False
            )

            if container_result is None or (isinstance(container_result, tuple) and container_result[0] == "esc"):
                print("Logs cancelled.")
                input("\nPress Enter to continue...")
                return

            selected_key, selected_container = container_result if isinstance(container_result, tuple) else ("enter", container_result)
            if selected_key != "enter":
                print(f"Unexpected key pressed: {selected_key}")
                input("\nPress Enter to continue...")
                return

        follow, previous, tail, timestamps, since = self.get_log_options()

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.log')
        temp_file.close()

        base_logs_cmd = f"kubectl logs {resource_name} -n {namespace}"
        if selected_container != "<All Containers>":
            base_logs_cmd += f" -c {selected_container}"
        if previous:
            base_logs_cmd += " -p"
        if follow:
            base_logs_cmd += " -f"
        if tail is not None:
            base_logs_cmd += f" --tail {tail}"
        if timestamps:
            base_logs_cmd += " --timestamps"
        if since:
            base_logs_cmd += f" --since={since}"

        title = f"Logs: {resource_name}{f' - {selected_container}' if selected_container != '<All Containers>' else ''}{ ' (previous)' if previous else ''}"

        try:
            with libtmux.Server() as server:
                session_name = f"logs-{resource_name.lower().replace(' ', '-')}"
                window_command = ""
                less_flags = "-j.5 -R -N"

                try:
                    if not follow:
                        with open(temp_file.name, 'w') as f:
                            result = subprocess.run(
                                base_logs_cmd.split(),
                                stdout=f,
                                stderr=subprocess.PIPE,
                                text=True,
                                check=True
                            )
                except subprocess.CalledProcessError as e:
                    error_msg = e.stderr if e.stderr else str(e)
                    if "previous terminated container" in error_msg:
                        print("No previous container logs found. The container has not been restarted.")
                    else:
                        print(f"Error getting logs: {error_msg}", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return

                if follow:
                    less_flags += " +F"
                    try:
                        temp_file_handle = open(temp_file.name, 'a')
                        follow_process = subprocess.Popen(
                            base_logs_cmd.split(),
                            stdout=temp_file_handle,
                            stderr=subprocess.PIPE
                        )
                        if follow_process.poll() is not None:
                            raise subprocess.CalledProcessError(follow_process.returncode, base_logs_cmd)
                    except subprocess.CalledProcessError as e:
                        print(f"Error starting log follow process: {e.stderr.strip() if e.stderr else str(e)}", file=sys.stderr)
                        input("\nPress Enter to continue...")
                        return

                window_command = f"less {less_flags} {temp_file.name}"

                session = server.new_session(
                    session_name=session_name,
                    window_name=title,
                    start_directory=None,
                    attach=False,
                    window_command=window_command
                )

                session.set_option('status', 'on')
                session.set_option('status-interval', 1)
                session.set_option('status-left-length', 100)
                session.set_option('status-right-length', 100)
                session.set_option('status-style', 'fg=black,bg=green')
                session.set_option('mouse', 'on')
                session.set_option('history-limit', 100000)

                pane = session.windows[0].panes[0]
                target_pane_id = pane.id

                # Determine path to fzf-tmux robustly
                fzf_tmux_cmd_path = "fzf-tmux" # Default
                if hasattr(sys, '_MEIPASS'):
                    # PyInstaller bundle
                    bundled_fzf_tmux = os.path.join(sys._MEIPASS, 'bin', 'fzf-tmux')
                    if os.path.exists(bundled_fzf_tmux):
                        fzf_tmux_cmd_path = bundled_fzf_tmux
                    else:
                        print(f"WARNING: Bundled fzf-tmux not found at {bundled_fzf_tmux}", file=sys.stderr)
                else:
                    # Development mode, try to find in PATH
                    path_fzf_tmux = shutil.which('fzf-tmux')
                    if path_fzf_tmux:
                        fzf_tmux_cmd_path = path_fzf_tmux
                    else:
                        print("WARNING: fzf-tmux not found in PATH. Using 'fzf-tmux' directly, hoping it's available.", file=sys.stderr)
                
                # Use the determined fzf_tmux_cmd_path
                fzf_run_script = (
                    f'SELECTED_LINE=$('
                    f'nl -ba -w1 {temp_file.name} | "{fzf_tmux_cmd_path}" -p 80% '
                    f'--preview "echo {{}}" --preview-window=up:1 '
                    f'--bind "enter:accept" '
                    f'); '
                    f'if [ -n "$SELECTED_LINE" ]; then '
                    f"  LINE_NO=$(echo \\\"$SELECTED_LINE\\\" | awk \'{{sub(/^[ \\t]+/, \\\"\\\"); print $1}}\'); "
                    f'  tmux display-message "Extracted LINE_NO: [$LINE_NO]"; '
                    f"  tmux send-keys -l -t {target_pane_id} \\\"$LINE_NO\\\"; "
                    f"  tmux send-keys -t {target_pane_id} g Enter; "
                    f'else '
                    f'  tmux display-message "fzf cancelled or no selection"; '
                    f'fi'
                )
                server.cmd('bind-key', '-n', 'F2', 'run-shell', fzf_run_script)

                session.set_option('status-left', '#[fg=green]#H #[fg=black]• #[fg=blue,bold]🔍 #[fg=yellow]Press F2 for fuzzy search#[default]')
                session.set_option('status-right', '#[fg=green]#(cut -d " " -f 1 /proc/loadavg)#[default] #[fg=blue]%H:%M#[default] #[fg=yellow]🚪 q(quit)#[default]')

                session.attach_session()

                print(f"\nLogs are being shown in a new window.")
                print("\nSearch and Navigation:")
                print("- Press F2 for fuzzy search (searches entire log file)")
                print("- Regular search: / (forward) or ? (backward)")
                print("- Next match: n (forward) or N (backward)")
                if follow:
                    print("\nFollowing logs:")
                    print("- Press Ctrl+C to stop following and navigate freely")
                    print("- Press Shift+F to resume following")
                    print("- To go to a specific line while following:")
                    print("  1. Press Ctrl+C to stop following")
                    print("  2. Press F2 for fuzzy search or type line number")
                    print("  3. Press Shift+F to resume following")
                print("\nExit:")
                print("- Press 'q' to quit and return to menu")
                input("\nPress Enter to continue...")

        finally:
            if follow and 'follow_process' in locals():
                follow_process.terminate()
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)

    def get_log_options(self) -> Tuple[bool, bool, Optional[int], bool, Optional[str]]:
        """Get log viewing options from user.
        
        Returns:
            Tuple of (follow, previous, tail, timestamps, since)
            - follow: Whether to follow logs
            - previous: Whether to show previous container logs
            - tail: Number of lines to show (None for all)
            - timestamps: Whether to show timestamps
            - since: Show logs since a specific time
        """
        while True:
            try:
                follow = input("Follow logs? (y/n, default: n): ").strip().lower()
                if not follow:
                    follow = "n"
                if follow not in ["y", "n"]:
                    print("Please enter 'y' or 'n'")
                    continue
                follow = follow == "y"
                break
            except KeyboardInterrupt:
                return False, False, None, False, None

        while True:
            try:
                previous = input("Show logs from previous container instance? (y/n, default: n) [Only available if container was restarted]: ").strip().lower()
                if not previous:
                    previous = "n"
                if previous not in ["y", "n"]:
                    print("Please enter 'y' or 'n'")
                    continue
                previous = previous == "y"
                break
            except KeyboardInterrupt:
                return False, False, None, False, None

        tail = None
        while True:
            try:
                tail_input = input("Number of lines to show (default: all): ").strip()
                if not tail_input:
                    break
                tail = int(tail_input)
                if tail < 1:
                    print("Number of lines must be positive")
                    continue
                break
            except ValueError:
                print("Please enter a valid number")
                continue
            except KeyboardInterrupt:
                return False, False, None, False, None

        while True:
            try:
                timestamps = input("Show timestamps? (y/n, default: n): ").strip().lower()
                if not timestamps:
                    timestamps = "n"
                if timestamps not in ["y", "n"]:
                    print("Please enter 'y' or 'n'")
                    continue
                timestamps = timestamps == "y"
                break
            except KeyboardInterrupt:
                return False, False, None, False, None

        while True:
            try:
                since = input("Show logs since (e.g., 1h, 30m, 1d) or leave empty for all: ").strip()
                if not since:
                    break
                if not re.match(r'^\d+[smhd]$', since):
                    print("Please enter a valid time format (e.g., 1h, 30m, 1d)")
                    continue
                break
            except KeyboardInterrupt:
                return False, False, None, False, None

        return follow, previous, tail, timestamps, since 