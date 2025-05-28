#!/usr/bin/env python3
import subprocess
import json
import sys
import os
from typing import List, Optional, Tuple, Dict, Union

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        if relative_path == "bin/kubectl":
             return "kubectl" 
        
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class KubectlClient:

    def _run_kubectl_command(self, command: List[str], expect_json: bool = False) -> Tuple[Optional[Union[dict, List[dict], str]], Optional[str]]:
        try:
            
            executable_path = command[0]
            if executable_path == "kubectl":
                actual_kubectl_path = get_resource_path("bin/kubectl")
                modified_command = [actual_kubectl_path] + command[1:]
            else:
                modified_command = command 
            
            process = subprocess.run(modified_command, capture_output=True, text=True, check=False)
            
            if process.returncode != 0:
                error_message = process.stderr.strip()
                if not error_message:
                    error_message = process.stdout.strip()
                if "namespaces \"kube-system\" not found" in error_message and "--all-namespaces" in command:
                    return "Error: Could not list resources across all namespaces. Try selecting a specific namespace.", None
                return None, error_message

            stdout = process.stdout.strip()
            if not stdout:
                return [], None if expect_json else (None, None)


            if expect_json:
                try:
                    return json.loads(stdout), None
                except json.JSONDecodeError as e:
                    return None, f"Error decoding JSON from kubectl: {e}\nRaw output: {stdout}"
            return stdout, None
            
        except FileNotFoundError:
            return None, "Error: kubectl command not found. Please ensure it's installed and in your PATH."
        except Exception as e:
            return None, f"An unexpected error occurred while running kubectl: {str(e)}"

    def get_resources(self, resource_type: str, namespace: Optional[str] = None, labels: Optional[Dict[str, str]] = None) -> Optional[List[str]]:
        command = ["kubectl", "get", resource_type, "-o", "name"]
        if namespace:
            command.extend(["-n", namespace])
        if labels:
            label_selector = ",".join([f"{k}={v}" for k, v in labels.items()])
            command.extend(["-l", label_selector])
        
        output, error = self._run_kubectl_command(command)
        if error:
            print(error, file=sys.stderr)
            return None
        
        if output is None or not isinstance(output, str): 
            return []
        
        processed_list = [name.split('/')[-1] for name in output.splitlines() if name.strip()]
        return processed_list

    def get_resource_spec(self, resource_type: str, resource_name: str, namespace: Optional[str] = None) -> Optional[dict]:
        command = ["kubectl", "get", resource_type, resource_name, "-o", "json"]
        if namespace:
            command.extend(["-n", namespace])
        
        data, error = self._run_kubectl_command(command, expect_json=True)
        if error:
            print(error, file=sys.stderr)
            return None
        if not isinstance(data, dict):
            return None
        return data

    def delete_resource(self, resource_type: str, resource_name: str, namespace: Optional[str] = None) -> Tuple[bool, str]:
        command = ["kubectl", "delete", resource_type, resource_name]
        if namespace:
            command.extend(["-n", namespace])
        
        _, error = self._run_kubectl_command(command)
        if error:
            return False, f"Failed to delete {resource_type} '{resource_name}': {error}"
        return True, f"{resource_type.capitalize()} '{resource_name}' deleted successfully."

    def get_pods_by_selector(self, namespace: str, label_selector: str) -> List[dict]:
        command = ["kubectl", "get", "pods", "-n", namespace, "-l", label_selector, "-o", "json"]
        data, error = self._run_kubectl_command(command, expect_json=True)
        if error:
            print(error, file=sys.stderr)
            return []
        if data and isinstance(data, dict) and 'items' in data:
            return data['items']
        return []
        
    def get_pod_container_names(self, pod_name: str, namespace: str) -> Optional[List[str]]:
        pod_spec = self.get_resource_spec("pod", pod_name, namespace)
        if not pod_spec:
            return None
        
        container_names = []
        for container in pod_spec.get('spec', {}).get('containers', []):
            container_names.append(container.get('name', 'unnamed-container'))
        if not container_names:
            print(f"No containers found in pod '{pod_name}' in namespace '{namespace}'.", file=sys.stderr)
            return None
        return container_names

    def get_workload_selector_labels(self, workload_kind: str, workload_name: str, namespace: str) -> Optional[Dict[str, str]]:
        """Get selector labels for a workload (deployment, statefulset, daemonset)."""
        data = self.get_resource_spec(workload_kind, workload_name, namespace)
        if not data:
            return None
        
        try:
            return data['spec']['selector']['matchLabels']
        except (KeyError, TypeError) as e:
            print(f"Error parsing selector labels for {workload_kind} '{workload_name}': {e}", file=sys.stderr)
            return None

    def rollout_restart_workload(self, workload_kind: str, workload_name: str, namespace: str) -> Tuple[bool, str]:
        command = ["kubectl", "rollout", "restart", f"{workload_kind}/{workload_name}", "-n", namespace]
        _, error = self._run_kubectl_command(command)
        if error:
            return False, f"Failed to restart {workload_kind} '{workload_name}': {error}"
        return True, f"{workload_kind.capitalize()} '{workload_name}' is being restarted."

    def get_workload_rollout_history(self, workload_kind: str, workload_name: str, namespace: str) -> Tuple[Optional[List[str]], Optional[str]]:
        command = ["kubectl", "rollout", "history", f"{workload_kind}/{workload_name}", "-n", namespace]
        output, error = self._run_kubectl_command(command)
        if error:
            return None, error
        return output.splitlines() if isinstance(output, str) else None, None

    def rollout_undo_workload(self, workload_kind: str, workload_name: str, namespace: str, to_revision: Optional[int] = None) -> Tuple[bool, str]:
        command = ["kubectl", "rollout", "undo", f"{workload_kind}/{workload_name}", "-n", namespace]
        if to_revision:
            command.extend(["--to-revision", str(to_revision)])
        
        _, error = self._run_kubectl_command(command)
        if error:
            return False, f"Failed to undo rollout for {workload_kind} '{workload_name}': {error}"
        return True, f"Rollout undo for {workload_kind.capitalize()} '{workload_name}' initiated."

    def get_workload_rollout_status(self, workload_kind: str, workload_name: str, namespace: str, watch: bool = True) -> Tuple[bool, str]:
        command = ["kubectl", "rollout", "status", f"{workload_kind}/{workload_name}", "-n", namespace]
        if watch:
            command.append("--watch=true")
        
        output, error = self._run_kubectl_command(command)
        if error:
            return False, f"Error getting rollout status for {workload_kind} '{workload_name}': {error}"
        return True, output if isinstance(output, str) else "Status check complete."


    def get_deployment_replicas(self, deployment_name: str, namespace: str) -> Optional[int]:
        data = self.get_resource_spec("deployment", deployment_name, namespace)
        if data:
            return data.get('spec', {}).get('replicas')
        return None

    def scale_deployment(self, deployment_name: str, namespace: str, replicas: int) -> Tuple[bool, str]:
        command = ["kubectl", "scale", "deployment", deployment_name, "-n", namespace, f"--replicas={replicas}"]
        _, error = self._run_kubectl_command(command)
        if error:
            return False, f"Failed to scale deployment '{deployment_name}': {error}"
        return True, f"Deployment '{deployment_name}' scaled to {replicas} replicas."

    def get_statefulset_replicas(self, statefulset_name: str, namespace: str) -> Optional[int]:
        data = self.get_resource_spec("statefulset", statefulset_name, namespace)
        if data:
            return data.get('spec', {}).get('replicas')
        return None

    def scale_statefulset(self, statefulset_name: str, namespace: str, replicas: int) -> Tuple[bool, str]:
        command = ["kubectl", "scale", "statefulset", statefulset_name, "-n", namespace, f"--replicas={replicas}"]
        _, error = self._run_kubectl_command(command)
        if error:
            return False, f"Failed to scale statefulset '{statefulset_name}': {error}"
        return True, f"StatefulSet '{statefulset_name}' scaled to {replicas} replicas."

    def get_command_template(self, action: str, resource_type: str, name: Optional[str] = None, namespace: Optional[str] = None, extra_args: Optional[List[str]] = None, output_format: Optional[str] = None) -> str:
        """Constructs a kubectl command string template.
        Placeholders like {{1}} for fzf should be passed within name/namespace arguments.
        """
        kubectl_path = get_resource_path("bin/kubectl")
        cmd_parts = [kubectl_path, action, resource_type]
        if name:
            cmd_parts.append(name)
        if namespace:
            cmd_parts.extend(["-n", namespace])
        if output_format:
            cmd_parts.extend(["-o", output_format])
        if extra_args:
            cmd_parts.extend(extra_args)
        
        return " ".join(cmd_parts)

    def wait_for_resource_ready(self, resource_type_and_name: str, namespace: str, timeout_seconds: int = 60) -> Tuple[bool, str]:
        """Wait for a resource to reach the Ready condition."""
        cmd = [
            "kubectl", "wait", f"--for=condition=Ready",
            resource_type_and_name,
            "-n", namespace,
            f"--timeout={timeout_seconds}s"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return True, f"Resource '{resource_type_and_name}' is ready in namespace '{namespace}'.\n{result.stdout.strip()}"
        except subprocess.CalledProcessError as e:
            error_message = e.stderr.strip() if e.stderr else ""
            stdout_message = e.stdout.strip() if e.stdout else ""
            full_message = f"Error waiting for '{resource_type_and_name}' to be ready (timeout or other error):\nSTDOUT: {stdout_message}\nSTDERR: {error_message}"
            return False, full_message.strip()
        except KeyboardInterrupt:
            return False, f"Wait for '{resource_type_and_name}' interrupted by user." 