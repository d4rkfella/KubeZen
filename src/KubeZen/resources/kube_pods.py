#!/usr/bin/env python3
import subprocess
import json
import re
import sys
import os
from typing import List, Tuple, Optional
from .kube_base import KubeBase
from .kube_port_forward import PortForwardManager
from .kube_logs import LogManager
import libtmux
import time
import tempfile
import atexit

class PodManager(KubeBase):
    resource_type = "pods"
    resource_name = "Pod"

    def __init__(self):
        super().__init__()
        self.port_forward_manager = PortForwardManager(self)
        self.log_manager = LogManager(self)

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-c:accept", "header_text": "Alt-C: Exec"},
            {"fzf_bind_action": "alt-p:accept", "header_text": "Alt-P: Port Forward"},
            {"fzf_bind_action": "alt-l:accept", "header_text": "Alt-L: Logs"},
        ]

    def _get_resource_actions(self):
        return {
            "alt-c": self._exec_into_pod,
            "alt-p": self._port_forward,
            "alt-l": self._show_logs,
        }

    def _exec_into_pod(self, pod_name: str, namespace: str):
        container_names = self.kubectl_client.get_pod_container_names(pod_name, namespace)
        if not container_names:
            return

        selected_container_name = None
        if len(container_names) > 1:
            container_result = self.run_fzf(
                container_names,
                f"Exec Into Pod ({pod_name})",
                extra_header="Select container (Esc to cancel)",
                extra_bindings=["--bind", "enter:accept"], # Ensure 'enter' is an accept action
                include_common_elements=False
            )

            if container_result is None or (isinstance(container_result, tuple) and container_result[0] == "esc"):
                print("Exec cancelled.")
                return
            selected_container_name = container_result[1] if isinstance(container_result, tuple) else container_result
        elif len(container_names) == 1:
            selected_container_name = container_names[0]
        else: 
            print(f"No containers found in pod '{pod_name}'. Cannot exec.")
            input("\nPress Enter to continue...")
            return

        print(f"Executing into {selected_container_name} in pod {pod_name}...")
        print("Type 'exit' to return to the menu")

        try:
            self._try_shells(pod_name, selected_container_name, namespace)
        except KeyboardInterrupt:
            print("Exec session ended.")
            input("\nPress Enter to continue...")

    def _port_forward(self, pod_name: str):
        # Delegate to PortForwardManager
        self.port_forward_manager.manage_port_forwards(selected_resource=("pod", pod_name))

    def _show_logs(self, pod_name: str):
        # Delegate to LogManager
        self.log_manager.show_logs("pod", pod_name, self.current_namespace)

    def _try_shells(self, pod_name, container, namespace):
        shells = ["bash", "sh", "ash"]
        for shell in shells:
            print(f"Trying shell '{shell}' in pod '{pod_name}', container '{container}'...")
            result = subprocess.run(
                ["kubectl", "exec", pod_name, "-n", namespace, "-c", container, "--", shell, "-c", "echo Shell OK"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                subprocess.run(
                    ["kubectl", "exec", "-it", pod_name, "-n", namespace, "-c", container, "--", shell]
                )
                return
        print("No suitable shell found in the container.")

    def select_pods_by_label(self, label_selector: str, title: str = "Pods"):
        """Select and handle actions for pods matching a label selector using KubectlClient and self.navigate."""
        print(f"Fetching pods with selector '{label_selector}' in namespace '{self.current_namespace}'...")
        pod_specs = self.kubectl_client.get_pods_by_selector(self.current_namespace, label_selector)

        if not pod_specs:
            print(f"No pods found matching selector '{label_selector}' in namespace '{self.current_namespace}'.")
            input("\nPress Enter to continue...")
            return

        display_pods = []
        self._pod_display_to_name_map = {} # Temporary map for the current navigation session

        for pod_spec in pod_specs:
            pod_name = pod_spec.get('metadata', {}).get('name', 'unknown-pod')
            pod_status = pod_spec.get('status', {}).get('phase', 'Unknown')
            display_name = f"{pod_name} ({pod_status})"
            display_pods.append(display_name)
            self._pod_display_to_name_map[display_name] = pod_name
        
        self.navigate(resources=display_pods, title=title)

        if hasattr(self, '_pod_display_to_name_map'):
            del self._pod_display_to_name_map

    def _handle_action(self, key: str, selected_resource_display_name: str, namespace: Optional[str] = None):
        """Handles actions selected from fzf, resolving display name to actual pod name."""
        actual_pod_name = selected_resource_display_name 
        if hasattr(self, '_pod_display_to_name_map') and selected_resource_display_name in self._pod_display_to_name_map:
            actual_pod_name = self._pod_display_to_name_map[selected_resource_display_name]
        
        super()._handle_action(key, actual_pod_name, namespace) 