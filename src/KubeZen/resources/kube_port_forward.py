#!/usr/bin/env python3
import subprocess
import json
import re
import sys
import os
import tempfile
import atexit
from typing import List, Tuple, Optional
import libtmux
from .kube_base import KubeBase

class PortForwardManager:
    """Manages port forwarding for Kubernetes resources (pods, services, etc.)"""
    
    def __init__(self, base: KubeBase):
        self.base = base
        self._server = None
        atexit.register(self.cleanup)

    def cleanup(self):
        """Clean up tmux sessions started by this manager when the application exits."""
        try:
            if self._server:
                cleaned_sessions = False
                for session in list(self._server.sessions): # Iterate over a copy if modifying
                    if session.name and session.name.startswith('pf-'):
                        try:
                            session.kill_session()
                            print(f"Cleaned up port forward session: {session.name}")
                            cleaned_sessions = True
                        except libtmux.exc.LibTmuxException as e:
                            # This might happen if the session was already killed or is otherwise inaccessible
                            print(f"Note: Error killing session {session.name} during cleanup: {e}", file=sys.stderr)
                        except Exception as e:
                            # Catch any other unexpected errors during individual session kill
                            print(f"Unexpected error killing session {session.name} during cleanup: {e}", file=sys.stderr)
                
                # Optionally, if no other sessions are managed by this server instance
                # and the server was started by this app (more complex to determine),
                # you might consider killing the server. For now, just killing pf- sessions is safest.
                # self._server = None # The libtmux Server object itself doesn't need to be explicitly None'd unless re-creating
                if cleaned_sessions:
                    print("Port forward cleanup complete.")
        except libtmux.exc.LibTmuxException as e:
            # This could happen if the server was killed externally or is unavailable
            print(f"Note: Error accessing tmux server during cleanup: {e}", file=sys.stderr)
        except Exception as e:
            # Catch any other unexpected errors during the cleanup process
            print(f"Unexpected error during port forward cleanup: {e}", file=sys.stderr)

    def ensure_server(self):
        """Ensure we have a server instance, creating one if needed."""
        if not self._server:
            try:
                self._server = libtmux.Server()
            except libtmux.exc.LibTmuxException as e:
                print(f"Error connecting to tmux server: {e}", file=sys.stderr)
                return False
        return True

    def get_ports(self, resource_type: str, resource_name: str, namespace: str) -> List[Tuple[str, str, int]]:
        """Get available ports for a resource using KubectlClient.
        
        Args:
            resource_type: Type of resource (pod, service, etc.)
            resource_name: Name of the resource
            namespace: Kubernetes namespace
            
        Returns:
            List of tuples containing (container_name_or_service_indicator, port_name_with_protocol, port_number)
        """
        data = self.base.kubectl_client.get_resource_spec(resource_type, resource_name, namespace)

        if not data:
            # KubectlClient.get_resource_spec already prints errors to sys.stderr
            # print(f"Could not retrieve spec for {resource_type} {resource_name}", file=sys.stderr)
            return []

        ports = []
        if resource_type == "pod":
            containers = data.get('spec', {}).get('containers', [])
            for container in containers:
                container_name = container.get('name', 'unnamed-container') # Provide default if name is missing
                for port_info in container.get('ports', []):
                    name = port_info.get('name', 'unnamed-port') # Default for port name
                    protocol = port_info.get('protocol', 'TCP')
                    container_port = port_info.get('containerPort')
                    if container_port:
                        ports.append((container_name, f"{name} ({protocol})", container_port))
        elif resource_type == "service":
            # For services, the "container_name" field is less relevant, use a placeholder or service name
            service_identifier = f"service-{resource_name}" 
            for port_info in data.get('spec', {}).get('ports', []):
                name = port_info.get('name', 'unnamed-svc-port') # Default for service port name
                protocol = port_info.get('protocol', 'TCP')
                service_port = port_info.get('port')
                if service_port:
                    ports.append((service_identifier, f"{name} ({protocol})", service_port))
        # Add other resource types like deployment, statefulset if needed, 
        # but they would typically be handled by first getting their pods.

        return ports

    def port_forward(self, resource_type: str, resource_name: str, namespace: str, selected_pod=None, from_management=False):
        """Start port forwarding for a resource.
        
        Args:
            resource_type: Type of resource (pod, service, etc.)
            resource_name: Name of the resource
            namespace: Kubernetes namespace
            selected_pod: Optional pod name if this is being called from pod selection
            from_management: Whether this is being called from the management menu
        """
        print(f"Port forwarding for {resource_type} {resource_name} in namespace {namespace}")
        
        # Get available ports
        ports = self.get_ports(resource_type, resource_name, namespace)
        if not ports:
            print("No valid ports found in resource definition.")
            # Always wait for input here so the user sees the message
            input("\nPress Enter to continue...")
            return

        # Create port options for fzf
        port_options = [f"{container} - {name}: {port}" for container, name, port in ports]

        print("Select port to forward:")
        port_result = self.base.run_fzf(
            port_options,
            f"Port Forward ({resource_name})",
            extra_header="Select port to forward (Esc to cancel)",
            extra_bindings=["--bind", "enter:accept"], # Ensure enter is an accept key
            include_common_elements=False
        )

        if port_result is None or (isinstance(port_result, tuple) and port_result[0] == "esc"):
            print("Port forward cancelled.")
            if not from_management:
                input("\nPress Enter to continue...")
            return

        selected_key, selected_port = port_result if isinstance(port_result, tuple) else ("enter", port_result)
        if selected_key != "enter":
            print(f"Unexpected key pressed: {selected_key}")
            if not from_management:
                input("\nPress Enter to continue...")
            return

        # Extract port number from selection
        port_match = re.search(r': (\d+)$', selected_port)
        if not port_match:
            print("Could not parse port number from selection.")
            if not from_management:
                input("\nPress Enter to continue...")
            return

        remote_port = port_match.group(1)

        # Get local port from user
        while True:
            try:
                local_port = input(f"Enter local port to forward to (default: {remote_port}): ").strip()
                if not local_port:
                    local_port = remote_port
                local_port = int(local_port)
                if local_port < 1 or local_port > 65535:
                    print("Port must be between 1 and 65535")
                    continue
                break
            except ValueError:
                print("Please enter a valid port number")
                continue
            except KeyboardInterrupt:
                return

        # Create a unique session name for this port forward
        session_name = f"pf-{resource_type}-{resource_name}-{local_port}-{remote_port}".lower().replace(' ', '-')
        window_name = f"{resource_name}:{local_port}->{remote_port}"

        try:
            # Ensure we have a server instance
            if not self.ensure_server():
                print("Failed to connect to tmux server.")
                if not from_management:
                    input("\nPress Enter to continue...")
                return

            # Check if session already exists
            existing_session = self._server.find_where({"session_name": session_name})
            if existing_session:
                print(f"Port forward {window_name} is already running.")
                if not from_management:
                    input("\nPress Enter to continue...")
                return

            # Create new session for port forward
            session = self._server.new_session(
                session_name=session_name,
                window_name=window_name,
                start_directory=None,
                attach=False,
                window_command=f"kubectl port-forward {resource_type}/{resource_name} {local_port}:{remote_port} -n {namespace}"
            )

            # Set session options
            session.set_option('status', 'on')
            session.set_option('status-interval', 1)
            session.set_option('status-left-length', 100)
            session.set_option('status-right-length', 100)
            session.set_option('status-style', 'fg=black,bg=green')
            session.set_option('mouse', 'on')

            # Set status bar
            session.set_option('status-left', f'#[fg=green]#H #[fg=black]• #[fg=blue,bold]🔌 #[fg=yellow]Port Forward: {window_name}#[default]')
            session.set_option('status-right', '#[fg=green]#(cut -d " " -f 1 /proc/loadavg)#[default] #[fg=blue]%H:%M#[default]')

            print(f"\nPort forward started in background session: {session_name}")
            print(f"Forwarding local port {local_port} to {resource_type} port {remote_port}")
            print("\nTo manage port forwards:")
            print("- Press Alt+P in the main menu to view and manage port forwards")
            if not from_management:
                input("\nPress Enter to continue...")

        except libtmux.exc.LibTmuxException as e:
            print(f"Error creating port forward session: {e}", file=sys.stderr)
            if not from_management:
                input("\nPress Enter to continue...")

    def manage_port_forwards(self, selected_resource=None):
        """Manage port forwards.
        
        Args:
            selected_resource: Optional tuple of (resource_type, resource_name) if this is being called from resource selection
        """
        try:
            # Ensure we have a server instance
            if not self.ensure_server():
                print("Failed to connect to tmux server.")
                input("\nPress Enter to continue...")
                return

            # Get all port forward sessions
            pf_sessions = [s for s in self._server.sessions if s.session_name.startswith('pf-')]
            
            # Create list of port forwards for fzf
            pf_list = []
            if pf_sessions:
                for session in pf_sessions:
                    window = session.windows[0]
                    pf_list.append(f"{window.window_name} (Session: {session.session_name})")
            
            # Add option to start new port forward
            pf_list.append("+ Start New Port Forward")

            # Let user select port forward to manage
            result = self.base.run_fzf(
                pf_list,
                "Port Forward Management",
                extra_header="Alt-K: Kill Selected | Alt-A: Kill All | Enter: View Details | Esc: Back",
                extra_bindings=[
                    "--bind", "enter:accept", # View Details
                    "--bind", "alt-k:accept",  # Kill selected
                    "--bind", "alt-a:accept",  # Kill all
                ],
                include_common_elements=False
            )

            if result is None:
                return

            if isinstance(result, tuple):
                key, selected = result

                if key == "esc":
                    return
                elif key == "alt-a":
                    self._server.kill_server()
                    self._server = None
                    print("All port forwards have been stopped.")
                    input("\nPress Enter to continue...")
                    return
                elif key == "alt-k":
                    session_name = selected.split("(Session: ")[1].rstrip(")")
                    session = self._server.find_where({"session_name": session_name})
                    if session:
                        session.kill_session()
                        print(f"Port forward {selected.split(' (Session:')[0]} has been stopped.")
                        input("\nPress Enter to continue...")
                        return self.manage_port_forwards(selected_resource)
                elif key == "enter":
                    if selected == "+ Start New Port Forward":
                        if selected_resource:
                            resource_type, resource_name = selected_resource
                            self.port_forward(resource_type, resource_name, self.base.current_namespace, from_management=True)
                            return 
                        else:
                            print("\nTo start a new port forward from this general management screen, first select a resource (pod/service) and use Alt+P.")
                            print("This option is primarily for when Alt+P is used on a specific resource.")
                            input("\nPress Enter to continue...")
                            return self.manage_port_forwards(selected_resource)
                    else:
                        # Show details of selected port forward
                        session_name = selected.split("(Session: ")[1].rstrip(")")
                        session = self._server.find_where({"session_name": session_name})
                        if session:
                            script_path = None # Initialize script_path
                            try:
                                # Create a new window in the session to show the output
                                window = session.new_window(
                                    window_name="Port Forward Output",
                                    start_directory=None
                                )
                                
                                # Get the original port-forward window
                                pf_window = session.windows[0]
                                
                                # Set up a script to continuously show output and handle Ctrl+C
                                watch_script = f'''#!/bin/bash
trap 'tmux detach-client -s {session.session_name}' INT TERM
echo "Port Forward Output (Press Ctrl+C to return to menu):"
while true; do
    clear
    echo "Port Forward Output (Press Ctrl+C to return to menu):"
    tmux capture-pane -p -t {pf_window.panes[0].id}
    sleep 1
done
'''
                                # Create a temporary script file
                                with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
                                    f.write(watch_script)
                                    script_path = f.name # Assign script_path here
                                os.chmod(script_path, 0o755)
                                
                                # Run the watch script
                                window.cmd('send-keys', f"{script_path}", 'C-m')
                                
                                # Set window options
                                window.set_window_option('status', 'on')
                                window.set_window_option('status-interval', 1)
                                window.set_window_option('status-left-length', 100)
                                window.set_window_option('status-right-length', 100)
                                window.set_window_option('status-style', 'fg=black,bg=green')
                                window.set_window_option('mouse', 'on')
                                
                                # Set status bar
                                window.set_window_option('status-left', f'#[fg=green]#H #[fg=black]• #[fg=blue,bold]🔌 #[fg=yellow]Port Forward Output#[default]')
                                window.set_window_option('status-right', '#[fg=green]#(cut -d " " -f 1 /proc/loadavg)#[default] #[fg=blue]%H:%M#[default] #[fg=yellow]🚪 Ctrl+C to return#[default]')
                                
                                window.select_window()
                                session.attach_session()
                                     
                                print("\nPort forward output is being shown in a new window.")
                                print("Press Ctrl+C in the new window to return to the menu.")
                                
                            except libtmux.exc.LibTmuxException as e:
                                print(f"Error showing port forward output: {e}", file=sys.stderr)
                                input("\nPress Enter to continue...")
                            finally:
                                if 'window' in locals() and window.id:
                                    try:
                                        if session.find_where({"window_id": window.id}):
                                            window.kill_window()
                                    except libtmux.exc.LibTmuxException as e:
                                        print(f"Note: Error killing port forward output window: {e}", file=sys.stderr)
                                        pass
                                if script_path and os.path.exists(script_path):
                                    try:
                                        os.unlink(script_path)
                                    except OSError as e:
                                        print(f"Error unlinking temp script {script_path}: {e}", file=sys.stderr)
                                
                                return self.manage_port_forwards(selected_resource)
                                
        except libtmux.exc.LibTmuxException as e:
            print(f"Error managing port forwards: {e}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return self.manage_port_forwards(selected_resource) 