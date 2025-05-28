#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from .kube_base import KubeBase # Adjusted import
import sys
import json

from .kube_pods import PodManager # Adjusted import
from .kube_logs import LogManager # Adjusted import

class StatefulSetManager(KubeBase):
    resource_type = "statefulsets"
    _workload_kind = "statefulset"

    def __init__(self):
        super().__init__()
        self.pod_manager = PodManager()
        self.log_manager = LogManager(self)

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-p:accept", "header_text": "Alt-P: View Pods"}, # Assuming view pods for statefulsets
            {"fzf_bind_action": "alt-r:accept", "header_text": "Alt-R: Rolling Restart"},
            {"fzf_bind_action": "alt-h:accept", "header_text": "Alt-H: Rollout History"},
            {"fzf_bind_action": "alt-u:accept", "header_text": "Alt-U: Undo Rollout"},
            {"fzf_bind_action": "alt-t:accept", "header_text": "Alt-T: Rollout Status"},
            {"fzf_bind_action": "alt-s:accept", "header_text": "Alt-S: Scale"},
        ]

    def _get_resource_actions(self):
        return {
            "enter": self._view_statefulset_pods,
            "alt-p": self._view_statefulset_pods, # Mapping alt-p to view pods
            "alt-r": self._rolling_restart_statefulset,
            "alt-h": self._rollout_history,
            "alt-u": self._undo_rollout,
            "alt-t": self._rollout_status,
            "alt-s": self._scale_statefulset
        }

    def _view_statefulset_pods(self, statefulset_name: str):
        print(f"Fetching pods for {self._workload_kind} '{statefulset_name}'...")
        selector_labels = self.kubectl_client.get_workload_selector_labels(self._workload_kind, statefulset_name, self.current_namespace)
        
        if not selector_labels:
            print(f"Could not get selector labels for {self._workload_kind} '{statefulset_name}'.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return

        label_selector_str = ",".join(f"{k}={v}" for k, v in selector_labels.items())
        
        original_pod_manager_ns = self.pod_manager.current_namespace
        self.pod_manager.current_namespace = self.current_namespace
        try:
            self.pod_manager.select_pods_by_label(label_selector_str, f"Pods for {self.resource_name}: {statefulset_name}")
        finally:
            self.pod_manager.current_namespace = original_pod_manager_ns 

    def _rolling_restart_statefulset(self, statefulset_name: str):
        print(f"Attempting to restart {self._workload_kind} '{statefulset_name}'...")
        success, message = self.kubectl_client.rollout_restart_workload(self._workload_kind, statefulset_name, self.current_namespace)
        print(message)
        input("\nPress Enter to continue...")

    def _rollout_history(self, statefulset_name: str):
        print(f"Fetching rollout history for {self._workload_kind} '{statefulset_name}'...")
        history_lines, error_message = self.kubectl_client.get_workload_rollout_history(self._workload_kind, statefulset_name, self.current_namespace)
        if error_message:
            print(error_message, file=sys.stderr)
        elif history_lines:
            subprocess.run(["clear"]) 
            print("\n".join(history_lines))
        else:
            subprocess.run(["clear"])
            print("No rollout history found.")
        input("\nPress Enter to continue...")

    def _undo_rollout(self, statefulset_name: str):
        print(f"Fetching rollout history for {self._workload_kind} '{statefulset_name}' to select revision for undo...")
        history_lines, error_message = self.kubectl_client.get_workload_rollout_history(self._workload_kind, statefulset_name, self.current_namespace)

        if error_message:
            print(error_message, file=sys.stderr)
            input("\nPress Enter to continue...")
            return
        if not history_lines or len(history_lines) <=1:
            print(f"No usable rollout history found for {self._workload_kind} '{statefulset_name}'. Cannot undo.")
            input("\nPress Enter to continue...")
            return

        revisions_for_fzf = []
        for line in history_lines[1:]:
            parts = line.split()
            if parts and parts[0].isdigit():
                revisions_for_fzf.append(line.strip())
        
        if not revisions_for_fzf:
            print(f"Could not parse revisions from history for {self._workload_kind} '{statefulset_name}'.")
            input("\nPress Enter to continue...")
            return

        fzf_items = ["<Previous Revision (Automatic)>"] + revisions_for_fzf
        
        result = self.run_fzf(
            fzf_items,
            f"Undo Rollout for {self._workload_kind} '{statefulset_name}'",
            extra_header="Select revision to undo to (Esc to cancel)",
            extra_bindings=["--bind", "enter:accept"],
            include_common_elements=False
        )

        if result is None or (isinstance(result, tuple) and result[0] == "esc"): 
            print("Undo rollout cancelled.")
            input("\nPress Enter to continue...")
            return
        
        key_pressed, selected_line = result if isinstance(result, tuple) else ("enter", result)

        if key_pressed == "esc":
            print("Undo rollout cancelled.")
            input("\nPress Enter to continue...")
            return
        
        if key_pressed == "enter":
            to_revision_val = None
            if selected_line != "<Previous Revision (Automatic)>":
                try:
                    revision_number_str = selected_line.split(None, 1)[0]
                    if revision_number_str.isdigit():
                        to_revision_val = int(revision_number_str)
                    else:
                        raise ValueError("Revision number not found at start of line")
                except (ValueError, IndexError):
                    print(f"Error parsing revision number from: '{selected_line}'.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return
            
            print(f"Executing undo rollout for {self._workload_kind} '{statefulset_name}" + (f" to revision {to_revision_val}" if to_revision_val else " to previous") + "...")
            success, message = self.kubectl_client.rollout_undo_workload(self._workload_kind, statefulset_name, self.current_namespace, to_revision=to_revision_val)
            print(message)
        else:
            print(f"Unexpected action '{key_pressed}' during revision selection.")
        
        input("\nPress Enter to continue...")

    def _rollout_status(self, statefulset_name: str):
        print(f"Checking rollout status for {self._workload_kind} '{statefulset_name}' (Ctrl+C to stop watching)...")
        success, message = self.kubectl_client.get_workload_rollout_status(self._workload_kind, statefulset_name, self.current_namespace)
        print(message) 
        input("\nPress Enter to continue...")

    def _scale_statefulset(self, statefulset_name: str):
        print(f"Scaling {self._workload_kind} '{statefulset_name}'...")
        current_replicas = self.kubectl_client.get_statefulset_replicas(statefulset_name, self.current_namespace)
        
        if current_replicas is not None:
            print(f"Current replicas: {current_replicas}")
        else:
            print("Could not determine current replicas.")

        while True:
            try:
                replicas_input = input("Enter desired number of replicas (integer): ").strip()
                if not replicas_input:
                    print("Scale operation cancelled.")
                    input("\nPress Enter to continue...")
                    return
                desired_replicas = int(replicas_input)
                if desired_replicas < 0:
                    print("Number of replicas cannot be negative.")
                    continue
                break
            except ValueError:
                print("Invalid input. Please enter an integer.")
            except KeyboardInterrupt:
                print("\nScale operation cancelled by user.")
                input("\nPress Enter to continue...")
                return
        
        success, message = self.kubectl_client.scale_statefulset(statefulset_name, self.current_namespace, desired_replicas)
        print(message)
        input("\nPress Enter to continue...") 