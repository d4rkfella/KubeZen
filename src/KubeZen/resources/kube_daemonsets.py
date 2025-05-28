#!/usr/bin/env python3
import subprocess
from typing import List, Tuple, Optional
from .kube_base import KubeBase # Adjusted import
import sys
import json
# Assuming PodManager and LogManager are in the same directory or PYTHONPATH is set
from .kube_pods import PodManager # Adjusted import
from .kube_logs import LogManager # Adjusted import

class DaemonSetManager(KubeBase):
    resource_type = "daemonsets"
    # resource_name = "DaemonSet" # KubeBase can derive this
    _workload_kind = "daemonset"

    def __init__(self):
        super().__init__()
        self.pod_manager = PodManager()
        self.log_manager = LogManager(self)

    def _get_resource_fzf_elements(self) -> List[dict]:
        return [
            {"fzf_bind_action": "alt-p:accept", "header_text": "Alt-P: View Pods"}, # Assuming you want view pods for daemonsets too
            {"fzf_bind_action": "alt-r:accept", "header_text": "Alt-R: Rolling Restart"},
            {"fzf_bind_action": "alt-h:accept", "header_text": "Alt-H: Rollout History"},
            {"fzf_bind_action": "alt-u:accept", "header_text": "Alt-U: Undo Rollout"},
            {"fzf_bind_action": "alt-t:accept", "header_text": "Alt-T: Rollout Status"},
        ]

    def _get_resource_actions(self):
        return {
            "enter": self._view_daemonset_pods,
            "alt-p": self._view_daemonset_pods, # Mapping alt-p to view pods
            "alt-r": self._rolling_restart_daemonset,
            "alt-h": self._rollout_history,
            "alt-u": self._undo_rollout,
            "alt-t": self._rollout_status
        }

    # select_resource override is removed, KubeBase.navigate is used.

    def _view_daemonset_pods(self, daemonset_name: str):
        print(f"Fetching pods for {self._workload_kind} '{daemonset_name}'...")
        selector_labels = self.kubectl_client.get_workload_selector_labels(self._workload_kind, daemonset_name, self.current_namespace)
        
        if not selector_labels:
            print(f"Could not get selector labels for {self._workload_kind} '{daemonset_name}'.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return

        label_selector_str = ",".join(f"{k}={v}" for k, v in selector_labels.items())
        
        original_pod_manager_ns = self.pod_manager.current_namespace
        self.pod_manager.current_namespace = self.current_namespace
        try:
            self.pod_manager.select_pods_by_label(label_selector_str, f"Pods for {self.resource_name}: {daemonset_name}")
        finally:
            self.pod_manager.current_namespace = original_pod_manager_ns 

    def _rolling_restart_daemonset(self, daemonset_name: str):
        print(f"Attempting to restart {self._workload_kind} '{daemonset_name}'...")
        success, message = self.kubectl_client.rollout_restart_workload(self._workload_kind, daemonset_name, self.current_namespace)
        print(message)
        input("\nPress Enter to continue...")

    def _rollout_history(self, daemonset_name: str):
        print(f"Fetching rollout history for {self._workload_kind} '{daemonset_name}'...")
        history_lines, error_message = self.kubectl_client.get_workload_rollout_history(self._workload_kind, daemonset_name, self.current_namespace)
        if error_message:
            print(error_message, file=sys.stderr)
        elif history_lines:
            subprocess.run(["clear"]) 
            print("\n".join(history_lines))
        else:
            subprocess.run(["clear"])
            print("No rollout history found.")
        input("\nPress Enter to continue...")

    def _undo_rollout(self, daemonset_name: str):
        print(f"Fetching rollout history for {self._workload_kind} '{daemonset_name}' to select revision for undo...")
        history_lines, error_message = self.kubectl_client.get_workload_rollout_history(self._workload_kind, daemonset_name, self.current_namespace)

        if error_message:
            print(error_message, file=sys.stderr)
            input("\nPress Enter to continue...")
            return
        if not history_lines or len(history_lines) <=1:
            print(f"No usable rollout history found for {self._workload_kind} '{daemonset_name}'. Cannot undo.")
            input("\nPress Enter to continue...")
            return

        revisions_for_fzf = []
        for line in history_lines[1:]:
            parts = line.split()
            if parts and parts[0].isdigit():
                revisions_for_fzf.append(line.strip())
        
        if not revisions_for_fzf:
            print(f"Could not parse revisions from history for {self._workload_kind} '{daemonset_name}'.")
            input("\nPress Enter to continue...")
            return

        fzf_items = ["<Previous Revision (Automatic)>"] + revisions_for_fzf
        
        result = self.run_fzf(
            fzf_items,
            f"Undo Rollout for {self._workload_kind} '{daemonset_name}'",
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
            
            print(f"Executing undo rollout for {self._workload_kind} '{daemonset_name}" + (f" to revision {to_revision_val}" if to_revision_val else " to previous") + "...")
            success, message = self.kubectl_client.rollout_undo_workload(self._workload_kind, daemonset_name, self.current_namespace, to_revision=to_revision_val)
            print(message)
        else:
            print(f"Unexpected action '{key_pressed}' during revision selection.")
        
        input("\nPress Enter to continue...")

    def _rollout_status(self, daemonset_name: str):
        print(f"Checking rollout status for {self._workload_kind} '{daemonset_name}' (Ctrl+C to stop watching)...")
        success, message = self.kubectl_client.get_workload_rollout_status(self._workload_kind, daemonset_name, self.current_namespace)
        print(message) 
        input("\nPress Enter to continue...") 